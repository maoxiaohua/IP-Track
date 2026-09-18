from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, update
from typing import List, Optional
from api.deps import get_db
from schemas.snmp import (
    SNMPProfileCreate,
    SNMPProfileUpdate,
    SNMPProfileResponse,
    SNMPProfileListResponse,
    SNMPProfileAdoptRequest,
    SNMPTestRequest,
    SNMPTestResponse
)
from models.ipam import SNMPProfile, IPSubnet
from models.switch import Switch
from core.security import encrypt_password, decrypt_password
from services.snmp_service import (
    snmp_service,
    normalize_snmp_config,
    normalize_protocol_key,
    apply_profile_display_fields,
)
from utils.logger import logger

router = APIRouter(prefix="/snmp-profiles", tags=["snmp-profiles"])


async def _usage_counts(
    db: AsyncSession,
    profile_ids: List[int],
) -> dict:
    """
    一次性统计这批模板各自被多少个子网、多少台交换机引用。

    两条聚合查询查完整批，而不是每个模板两条查询 —— 模板列表是会被前端反复拉的
    页面，N+1 在这里会直接变成几十次往返。
    """
    if not profile_ids:
        return {}

    subnet_rows = await db.execute(
        select(IPSubnet.snmp_profile_id, func.count(IPSubnet.id))
        .where(IPSubnet.snmp_profile_id.in_(profile_ids))
        .group_by(IPSubnet.snmp_profile_id)
    )
    switch_rows = await db.execute(
        select(Switch.snmp_profile_id, func.count(Switch.id))
        .where(Switch.snmp_profile_id.in_(profile_ids))
        .group_by(Switch.snmp_profile_id)
    )

    counts = {
        pid: {'subnet_count': 0, 'switch_count': 0} for pid in profile_ids
    }
    for pid, n in subnet_rows.all():
        counts.setdefault(pid, {'subnet_count': 0, 'switch_count': 0})['subnet_count'] = n
    for pid, n in switch_rows.all():
        counts.setdefault(pid, {'subnet_count': 0, 'switch_count': 0})['switch_count'] = n
    return counts


async def _resync_referencing_switches(db: AsyncSession, profile: SNMPProfile) -> int:
    """
    模板被改动后，把展示字段重新回填到每一台引用它的交换机行上，返回回填台数。

    凭据本身不用动 —— 引用模板的交换机在采集/测试时是直接从模板解析凭据的
    （build_switch_snmp_config），改模板口令天然立刻生效。真正会过期的是交换机行上
    那几列**展示用**的副本（snmp_version / snmp_username / snmp_auth_protocol …）：
    不回填的话，SNMP 配置页的「用户名」列会一直显示模板改之前的旧值，用户改了模板
    却看到列表没变，只能怀疑是自己没保存成功。

    必须在 setattr 那一轮之后调用：apply_profile_display_fields 读的是内存里的
    profile 对象，会话又是 autoflush=False，靠查询是刷不出来的，只能靠调用时序。
    """
    switches = (await db.execute(
        select(Switch).where(Switch.snmp_profile_id == profile.id)
    )).scalars().all()

    for switch in switches:
        apply_profile_display_fields(switch, profile)

    return len(switches)


async def _profile_response(db: AsyncSession, profile: SNMPProfile) -> SNMPProfileResponse:
    """把模板 ORM 对象转成响应体，并带上引用计数。"""
    counts = await _usage_counts(db, [profile.id])
    c = counts.get(profile.id, {'subnet_count': 0, 'switch_count': 0})
    return SNMPProfileResponse(
        **{k: v for k, v in profile.__dict__.items() if not k.startswith('_')},
        subnet_count=c['subnet_count'],
        switch_count=c['switch_count'],
    )


@router.post("", response_model=SNMPProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_snmp_profile(
    profile: SNMPProfileCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new SNMP profile

    Creates a new SNMP profile with encrypted credentials.
    Supports both SNMPv2c (community string) and SNMPv3 (username/password).
    """
    try:
        # Check if profile name already exists
        result = await db.execute(
            select(SNMPProfile).where(SNMPProfile.name == profile.name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SNMP profile with name '{profile.name}' already exists"
            )

        # Validate version
        if profile.version not in ['v2c', 'v3']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Version must be 'v2c' or 'v3'"
            )

        # Validate required fields based on version
        if profile.version == 'v3':
            if not profile.username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username is required for SNMPv3"
                )
            if not profile.auth_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Auth password is required for SNMPv3"
                )
        elif profile.version == 'v2c':
            if not profile.community:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Community string is required for SNMPv2c"
                )

        # Create new profile with encrypted credentials
        new_profile = SNMPProfile(
            name=profile.name,
            version=profile.version,
            username=profile.username,
            auth_protocol=profile.auth_protocol,
            auth_password_encrypted=encrypt_password(profile.auth_password) if profile.auth_password else None,
            priv_protocol=profile.priv_protocol,
            priv_password_encrypted=encrypt_password(profile.priv_password) if profile.priv_password else None,
            community_encrypted=encrypt_password(profile.community) if profile.community else None,
            port=profile.port,
            timeout=profile.timeout,
            retries=profile.retries,
            description=profile.description,
            enabled=profile.enabled
        )

        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)

        logger.info(f"Created SNMP profile: {new_profile.name} (ID: {new_profile.id})")

        return await _profile_response(db, new_profile)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating SNMP profile: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create SNMP profile: {str(e)}"
        )


@router.get("", response_model=SNMPProfileListResponse)
async def list_snmp_profiles(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    enabled_only: bool = Query(False, description="Show only enabled profiles"),
    db: AsyncSession = Depends(get_db)
):
    """
    List all SNMP profiles

    Returns a paginated list of SNMP profiles with subnet counts.
    """
    try:
        # Build query
        query = select(SNMPProfile)
        if enabled_only:
            query = query.where(SNMPProfile.enabled == True)

        # Get total count
        count_result = await db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar() or 0

        # Get paginated results
        query = query.order_by(SNMPProfile.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        profiles = result.scalars().all()

        # 引用计数整批查一次，避免每个模板各查两条
        counts = await _usage_counts(db, [p.id for p in profiles])

        profile_responses = []
        for profile in profiles:
            c = counts.get(profile.id, {'subnet_count': 0, 'switch_count': 0})
            profile_responses.append(
                SNMPProfileResponse(
                    **{k: v for k, v in profile.__dict__.items() if not k.startswith('_')},
                    subnet_count=c['subnet_count'],
                    switch_count=c['switch_count'],
                )
            )

        return SNMPProfileListResponse(
            items=profile_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        logger.error(f"Error listing SNMP profiles: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list SNMP profiles"
        )


@router.get("/{profile_id}", response_model=SNMPProfileResponse)
async def get_snmp_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get a specific SNMP profile by ID"""
    result = await db.execute(
        select(SNMPProfile).where(SNMPProfile.id == profile_id)
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SNMP profile {profile_id} not found"
        )

    return await _profile_response(db, profile)


@router.put("/{profile_id}", response_model=SNMPProfileResponse)
async def update_snmp_profile(
    profile_id: int,
    profile_update: SNMPProfileUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    Update an SNMP profile

    Updates profile settings. Passwords are re-encrypted if provided.
    """
    try:
        # Get existing profile
        result = await db.execute(
            select(SNMPProfile).where(SNMPProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SNMP profile {profile_id} not found"
            )

        # Check if new name conflicts with another profile
        if profile_update.name and profile_update.name != profile.name:
            result = await db.execute(
                select(SNMPProfile).where(
                    SNMPProfile.name == profile_update.name,
                    SNMPProfile.id != profile_id
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"SNMP profile with name '{profile_update.name}' already exists"
                )

        # Update fields
        update_data = profile_update.model_dump(exclude_unset=True)

        # Handle password encryption
        if 'auth_password' in update_data and update_data['auth_password']:
            update_data['auth_password_encrypted'] = encrypt_password(update_data.pop('auth_password'))

        if 'priv_password' in update_data and update_data['priv_password']:
            update_data['priv_password_encrypted'] = encrypt_password(update_data.pop('priv_password'))

        if 'community' in update_data and update_data['community']:
            update_data['community_encrypted'] = encrypt_password(update_data.pop('community'))

        # Apply updates
        for key, value in update_data.items():
            setattr(profile, key, value)

        # 模板改了，引用它的交换机行上那几列展示副本得跟着刷新，
        # 否则配置页会一直显示改之前的用户名/协议。凭据不受影响（本来就实时取自模板）。
        resynced = await _resync_referencing_switches(db, profile)

        await db.commit()
        await db.refresh(profile)

        logger.info(
            f"Updated SNMP profile: {profile.name} (ID: {profile.id})"
            + (f"，已同步 {resynced} 台引用它的交换机" if resynced else "")
        )

        return await _profile_response(db, profile)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating SNMP profile: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update SNMP profile: {str(e)}"
        )


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snmp_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an SNMP profile

    Cannot delete if the profile is being used by any subnets.
    """
    try:
        # Check if profile exists
        result = await db.execute(
            select(SNMPProfile).where(SNMPProfile.id == profile_id)
        )
        profile = result.scalar_one_or_none()

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SNMP profile {profile_id} not found"
            )

        # Check if profile is being used
        counts = await _usage_counts(db, [profile_id])
        c = counts.get(profile_id, {'subnet_count': 0, 'switch_count': 0})
        subnet_count, switch_count = c['subnet_count'], c['switch_count']

        if subnet_count > 0 or switch_count > 0:
            # 交换机这一路必须一并挡住。外键是 ON DELETE SET NULL，放行不会报错，
            # 但引用它的交换机会静默退回用本机自己那份凭据 —— 而那份凭据在绑定模板
            # 时已经被清空了。结果是这些设备变成「未配置凭据」，采集直接跳过，
            # 界面上只是一片空白，看不出是删了个模板导致的。
            parts = []
            if subnet_count:
                parts.append(f"{subnet_count} 个子网")
            if switch_count:
                parts.append(f"{switch_count} 台交换机")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"无法删除：该模板正被 {'、'.join(parts)} 引用。"
                    f"请先解除引用，或改用「停用」而不是删除。"
                ),
            )

        # Delete profile
        await db.delete(profile)
        await db.commit()

        logger.info(f"Deleted SNMP profile: {profile.name} (ID: {profile_id})")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting SNMP profile: {str(e)}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete SNMP profile"
        )


def _decrypt_or_none(value: Optional[str]) -> Optional[str]:
    """解密一个凭据字段；解不开就返回 None（当成「对不上」处理，不是抛异常）。"""
    if not value:
        return None
    try:
        return decrypt_password(value)
    except Exception:
        return None


def _credential_mismatch(switch_config: dict, target_config: dict) -> Optional[str]:
    """
    比较交换机的生效凭据与模板凭据，一致返回 None，不一致返回原因。

    口令是**在进程内解密后逐字节比**的，Fernet 每次加密结果都不同，密文永远比不了。
    比较结果只用于「要不要挂到模板上」，明文不出这个函数、不进日志、不进响应。
    """
    if not switch_config.get('snmp_auth_password_encrypted'):
        return 'no_credentials'

    if (switch_config.get('snmp_username') or '') != (target_config.get('snmp_username') or ''):
        return 'different_username'

    if (normalize_protocol_key(switch_config.get('snmp_auth_protocol'))
            != normalize_protocol_key(target_config.get('snmp_auth_protocol'))):
        return 'different_auth_protocol'

    if (normalize_protocol_key(switch_config.get('snmp_priv_protocol'))
            != normalize_protocol_key(target_config.get('snmp_priv_protocol'))):
        return 'different_priv_protocol'

    if (_decrypt_or_none(switch_config.get('snmp_auth_password_encrypted'))
            != _decrypt_or_none(target_config.get('snmp_auth_password_encrypted'))):
        return 'different_auth_password'

    # 协议名一致但一边有 priv 口令、一边没有，仍是不同的凭据
    switch_has_priv = bool(switch_config.get('snmp_priv_password_encrypted'))
    target_has_priv = bool(target_config.get('snmp_priv_password_encrypted'))
    if switch_has_priv != target_has_priv:
        return 'different_priv_password'
    if switch_has_priv and (
        _decrypt_or_none(switch_config.get('snmp_priv_password_encrypted'))
        != _decrypt_or_none(target_config.get('snmp_priv_password_encrypted'))
    ):
        return 'different_priv_password'

    return None


@router.post("/{profile_id}/adopt")
async def adopt_switches_into_profile(
    profile_id: int,
    request: SNMPProfileAdoptRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    把**已经用着同一份凭据**的历史交换机改成引用这个模板。

    迁移 028 故意不回填任何一行：把 239 台一次性挂到某个模板上，等于在没有逐一核对
    的情况下改掉全网的凭据来源，一旦哪台本来用的是另一套口令，表现是「采集静默全
    空」而没有任何报错。这个接口是那条回填语句的替代品 —— 只认真正对得上的设备：

      * 版本、用户名、认证协议、加密协议、两个口令全部逐项比对
      * 任何一项对不上就不动它，并在报告里给出**原因分类**
      * 默认 dry_run=true，只报不改

    对得上的那些挂过去是安全的：凭据一模一样，行为不变，只是从此改口令只需改模板一处。
    """
    result = await db.execute(select(SNMPProfile).where(SNMPProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SNMP profile {profile_id} not found",
        )

    target_config = normalize_snmp_config(profile)

    query = select(Switch).where(Switch.snmp_profile_id.is_(None))
    if request.switch_ids:
        query = query.where(Switch.id.in_(request.switch_ids))
    switches = (await db.execute(query)).scalars().all()

    matched = []
    skipped = {}
    for switch in switches:
        switch_config = normalize_snmp_config(switch)

        if switch_config['snmp_version'] != target_config['snmp_version']:
            reason = 'different_version'
        else:
            reason = _credential_mismatch(switch_config, target_config)

        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue

        matched.append(switch)

    if not request.dry_run:
        for switch in matched:
            # 赋给关系属性而不是外键列：snmp_profile 是 lazy='selectin' 预加载的，
            # 只改 snmp_profile_id 那一列，会话里缓存的关系还是旧的。
            switch.snmp_profile = profile
            # 挂上模板后本机那份副本必须清掉，否则改模板口令时这些设备仍在用旧副本，
            # 表现是「模板改了但采集还是用老口令」，且看不出来。
            switch.snmp_auth_password_encrypted = None
            switch.snmp_priv_password_encrypted = None
            switch.snmp_community = None
        await db.commit()

        logger.info(
            f"Adopted {len(matched)} switch(es) into SNMP profile "
            f"{profile.name} (id={profile.id})"
        )

    return {
        'profile_id': profile.id,
        'profile_name': profile.name,
        'dry_run': request.dry_run,
        'examined': len(switches),
        'matched_count': len(matched),
        'skipped_count': sum(skipped.values()),
        'matched': [
            {'id': s.id, 'name': s.name, 'ip_address': str(s.ip_address)}
            for s in matched
        ],
        # 只给分类计数，不给具体是哪台配了另一套口令 —— 这份响应会进浏览器和日志，
        # 「哪几台凭据跟模板不一样」本身就是敏感信息。
        'skipped_by_reason': skipped,
    }


@router.post("/test", response_model=SNMPTestResponse)
async def test_snmp_connection(
    test_request: SNMPTestRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Test SNMP connection to a device

    Can use an existing profile or provide credentials directly.
    """
    try:
        snmp_profile = None

        if test_request.profile_id:
            # Use existing profile
            result = await db.execute(
                select(SNMPProfile).where(SNMPProfile.id == test_request.profile_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"SNMP profile {test_request.profile_id} not found"
                )

            snmp_profile = {
                'username': profile.username,
                'auth_protocol': profile.auth_protocol,
                'auth_password_encrypted': profile.auth_password_encrypted,
                'priv_protocol': profile.priv_protocol,
                'priv_password_encrypted': profile.priv_password_encrypted,
                'port': profile.port,
                'timeout': profile.timeout
            }
        else:
            # Use provided credentials
            if not test_request.username or not test_request.auth_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username and auth_password are required for SNMP test"
                )

            snmp_profile = {
                'username': test_request.username,
                'auth_protocol': test_request.auth_protocol or 'SHA',
                'auth_password_encrypted': encrypt_password(test_request.auth_password),
                'priv_protocol': test_request.priv_protocol or 'AES',
                'priv_password_encrypted': encrypt_password(test_request.priv_password) if test_request.priv_password else None,
                'port': test_request.port,
                'timeout': test_request.timeout
            }

        # Test SNMP connection
        result = await snmp_service.get_device_identification(
            test_request.target_ip,
            snmp_profile
        )

        if result:
            return SNMPTestResponse(
                success=True,
                message=f"Successfully connected to {test_request.target_ip}",
                data=result
            )
        else:
            return SNMPTestResponse(
                success=False,
                message=f"Failed to get SNMP data from {test_request.target_ip}",
                error="No data returned from device"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing SNMP connection: {str(e)}")
        return SNMPTestResponse(
            success=False,
            message="SNMP test failed",
            error=str(e)
        )
