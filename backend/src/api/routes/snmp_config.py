"""
SNMP Configuration API Routes

Provides endpoints to:
1. Configure SNMP credentials for switches
2. Test SNMP connectivity
3. Batch configure SNMP for multiple switches
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd, next_cmd,
)

from core.database import get_db
from core.security import encrypt_password, decrypt_password
from api.deps import load_snmp_profile_or_400
from models.switch import Switch
from services.snmp_service import (
    snmp_service,
    apply_profile_display_fields,
    build_snmp_auth,
    build_switch_snmp_config,
    describe_snmp_error,
    switch_has_snmp_credentials,
)
from utils.logger import logger

router = APIRouter(prefix="/snmp", tags=["snmp"])


# ==================== Pydantic Models ====================

class SNMPConfigRequest(BaseModel):
    """SNMP configuration request model"""
    snmp_enabled: bool = True
    snmp_version: str = Field(default="3", pattern="^(2c|3)$")

    # 引用的 SNMP 凭据模板。非空时本请求里的逐台凭据字段**一律忽略**，凭据整体以
    # 模板为准；显式传 null 表示解绑，改回用本机自带的那份。
    # 声明在 snmp_username 之前：pydantic v1 的 validator 只能看到**前面**已声明的
    # 字段，下面的校验器要读它才能决定跳不跳过。
    snmp_profile_id: Optional[int] = Field(default=None, ge=1)

    # SNMPv3 fields
    snmp_username: Optional[str] = None
    # 协议名放宽到带连字符的写法（SHA-256 / AES-192 等）：snmp_profiles 表里存的就是
    # 这种带连字符的形式，而这里原先只认 SHA256/AES192。同一个概念两套写法，
    # 一旦哪边没归一化就会静默降级成 SHA/AES128 —— 症状是设备侧回 WrongDigest，
    # 和「口令配错」长得一模一样，极难排查。现在两处都收，并在构造凭据时统一归一化。
    snmp_auth_protocol: Optional[str] = Field(default="SHA", pattern="^(MD5|SHA|SHA1|SHA-?224|SHA-?256|SHA-?384|SHA-?512)$")
    snmp_auth_password: Optional[str] = None
    snmp_priv_protocol: Optional[str] = Field(default="AES128", pattern="^(DES|AES|AES-?128|AES-?192|AES-?256)$")
    snmp_priv_password: Optional[str] = None
    snmp_port: int = Field(default=161, ge=1, le=65535)

    # SNMPv2c fields
    snmp_community: Optional[str] = None  # For v2c

    @validator('snmp_username')
    def validate_username(cls, v, values):
        # 引用了模板就跳过逐台校验：凭据在模板上，这里本来就该是空的
        if values.get('snmp_profile_id'):
            return v
        if values.get('snmp_version') == '3' and values.get('snmp_enabled') and not v:
            raise ValueError('snmp_username is required for SNMPv3')
        return v

    @validator('snmp_auth_password')
    def validate_auth_password(cls, v, values):
        if values.get('snmp_profile_id'):
            return v
        if values.get('snmp_version') == '3' and values.get('snmp_enabled'):
            if not v or len(v) < 8:
                raise ValueError('snmp_auth_password must be at least 8 characters for SNMPv3')
        return v

    @validator('snmp_priv_password')
    def validate_priv_password(cls, v, values):
        if values.get('snmp_profile_id'):
            return v
        if values.get('snmp_version') == '3' and values.get('snmp_enabled'):
            if v and len(v) < 8:
                raise ValueError('snmp_priv_password must be at least 8 characters for SNMPv3')
        return v

    @validator('snmp_community')
    def validate_community(cls, v, values):
        if values.get('snmp_profile_id'):
            return v
        if values.get('snmp_version') == '2c' and values.get('snmp_enabled') and not v:
            raise ValueError('snmp_community is required for SNMPv2c')
        return v


class SNMPTestRequest(BaseModel):
    """SNMP connection test request"""
    target_ip: str
    snmp_version: str = Field(default="3", pattern="^(2c|3)$")
    snmp_username: Optional[str] = None
    snmp_auth_protocol: Optional[str] = "SHA"
    snmp_auth_password: Optional[str] = None
    snmp_priv_protocol: Optional[str] = "AES128"
    snmp_priv_password: Optional[str] = None
    snmp_port: int = 161
    snmp_community: Optional[str] = None


class SNMPBatchConfigRequest(BaseModel):
    """Batch SNMP configuration for multiple switches"""
    switch_ids: List[int]
    snmp_config: SNMPConfigRequest


class SNMPConfigResponse(BaseModel):
    """SNMP configuration response"""
    switch_id: int
    switch_name: str
    switch_ip: str
    snmp_enabled: bool
    snmp_version: str
    snmp_username: Optional[str]
    snmp_auth_protocol: Optional[str]
    snmp_priv_protocol: Optional[str]
    snmp_port: int
    has_credentials: bool  # Whether credentials are configured
    # 凭据来源：非空表示这台交换机的凭据取自该模板，上面的 username/协议/端口
    # 都是模板上的**生效值**（回填给界面显示），本机存的那份已被忽略。
    snmp_profile_id: Optional[int] = None
    snmp_profile_name: Optional[str] = None


# ==================== API Endpoints ====================

@router.get("/config/{switch_id}", response_model=SNMPConfigResponse)
async def get_snmp_config(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Get SNMP configuration for a switch

    Note: Passwords are not returned for security reasons
    """
    result = await db.execute(
        select(Switch).where(Switch.id == switch_id)
    )
    switch = result.scalar_one_or_none()

    if not switch:
        raise HTTPException(status_code=404, detail=f"Switch {switch_id} not found")

    # 展示值一律走统一解析：引用了模板就以模板上的版本/端口/用户名/协议为准，
    # 否则用本机那份。直接读 switch.snmp_username 之类会让引用模板的交换机在
    # 这个页面上显示成空白/旧的残留值，而实际生效的完全是另一套。
    effective = build_switch_snmp_config(switch)

    return SNMPConfigResponse(
        switch_id=switch.id,
        switch_name=switch.name,
        switch_ip=str(switch.ip_address),
        snmp_enabled=switch.snmp_enabled or False,
        snmp_version=effective['snmp_version'] or "3",
        snmp_username=effective['snmp_username'],
        snmp_auth_protocol=effective['snmp_auth_protocol'],
        snmp_priv_protocol=effective['snmp_priv_protocol'],
        snmp_port=effective['snmp_port'] or 161,
        # 不能写 bool(switch.snmp_auth_password_encrypted)：引用模板的交换机这一列
        # 是空的，那样所有引用模板的交换机都会显示「未配置凭据」。
        has_credentials=switch_has_snmp_credentials(switch),
        snmp_profile_id=switch.snmp_profile_id,
        snmp_profile_name=switch.snmp_profile_name,
    )


@router.put("/config/{switch_id}")
async def update_snmp_config(
    switch_id: int,
    config: SNMPConfigRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Update SNMP configuration for a switch

    This endpoint encrypts and stores SNMP credentials securely.
    """
    # Get switch
    result = await db.execute(
        select(Switch).where(Switch.id == switch_id)
    )
    switch = result.scalar_one_or_none()

    if not switch:
        raise HTTPException(status_code=404, detail=f"Switch {switch_id} not found")

    # 引用 / 解绑 SNMP 凭据模板。**必须放在下面那些逐台写口令的代码之前** ——
    # 绑定了模板就绝不能再往交换机行写一份口令副本，否则「同一份凭据抄 239 份」
    # 又回来了，而且模板和副本之后会各自变，排查时完全看不出以哪个为准。
    bound_profile = None
    if config.snmp_profile_id is not None:
        bound_profile = await load_snmp_profile_or_400(db, config.snmp_profile_id)
        # 赋给关系属性而不是外键列：关系是预加载过的，直接改 FK 列 SQLAlchemy 不认。
        switch.snmp_profile = bound_profile
        # snmp_enabled 是「这台设备到底用不用 SNMP」的开关，属于调用方的决定，
        # 不由模板覆盖；其余传输参数/用户名一律回填成模板上的生效值。
        switch.snmp_enabled = config.snmp_enabled
        apply_profile_display_fields(switch, bound_profile)
        # 本机残留的凭据副本一并清掉：留着只会在解绑后被当成有效凭据用起来，
        # 而它十有八九已经过期了。
        switch.snmp_auth_password_encrypted = None
        switch.snmp_priv_password_encrypted = None
        switch.snmp_community = None

        await db.commit()
        await db.refresh(switch)

        logger.info(
            f"Bound switch {switch.name} ({switch.ip_address}) to SNMP profile "
            f"{bound_profile.name} (id={bound_profile.id})"
        )
        return {
            "success": True,
            "message": f"交换机 {switch.name} 的 SNMP 凭据已改为引用模板「{bound_profile.name}」",
            "switch_id": switch.id,
            "snmp_profile_id": bound_profile.id,
            "snmp_profile_name": bound_profile.name,
        }

    if 'snmp_profile_id' in config.model_fields_set and config.snmp_profile_id is None:
        # 显式传 null = 解绑模板，改回用本机自带凭据。
        # 这里**不清空**本机凭据列：解绑之后它们就是唯一可用的凭据了，
        # 清掉等于把设备直接变成「未配置凭据」。要连凭据一起清，
        # 走 DELETE /snmp/config/{switch_id}。
        switch.snmp_profile = None

    # Update SNMP configuration
    switch.snmp_enabled = config.snmp_enabled
    switch.snmp_version = config.snmp_version
    switch.snmp_port = config.snmp_port

    if config.snmp_version == "3":
        # SNMPv3 configuration
        switch.snmp_username = config.snmp_username
        switch.snmp_auth_protocol = config.snmp_auth_protocol

        # Encrypt passwords
        if config.snmp_auth_password:
            switch.snmp_auth_password_encrypted = encrypt_password(config.snmp_auth_password)
        if config.snmp_priv_password:
            switch.snmp_priv_protocol = config.snmp_priv_protocol or "AES128"
            switch.snmp_priv_password_encrypted = encrypt_password(config.snmp_priv_password)
        else:
            switch.snmp_priv_protocol = None
            switch.snmp_priv_password_encrypted = None

        switch.snmp_community = None

    elif config.snmp_version == "2c":
        # SNMPv2c configuration
        switch.snmp_username = None
        switch.snmp_auth_protocol = None
        switch.snmp_priv_protocol = None
        switch.snmp_priv_password_encrypted = None
        if config.snmp_community:
            # Store community string in auth_password field (encrypted)
            switch.snmp_auth_password_encrypted = encrypt_password(config.snmp_community)

    await db.commit()
    await db.refresh(switch)

    logger.info(f"Updated SNMP config for switch {switch.name} ({switch.ip_address})")

    return {
        "success": True,
        "message": f"SNMP configuration updated for switch {switch.name}",
        "switch_id": switch.id
    }


@router.post("/config/batch")
async def batch_update_snmp_config(
    batch_config: SNMPBatchConfigRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Batch update SNMP configuration for multiple switches

    Useful when you have the same SNMP credentials for multiple switches.
    """
    if not batch_config.switch_ids:
        raise HTTPException(status_code=400, detail="No switch IDs provided")

    # Get all switches
    result = await db.execute(
        select(Switch).where(Switch.id.in_(batch_config.switch_ids))
    )
    switches = result.scalars().all()

    if not switches:
        raise HTTPException(status_code=404, detail="No switches found with provided IDs")

    updated_count = 0
    config = batch_config.snmp_config

    # 批量绑定模板：整批一次性校验，避免循环里逐台抛 400 只改了一半。
    bound_profile = None
    if config.snmp_profile_id is not None:
        bound_profile = await load_snmp_profile_or_400(db, config.snmp_profile_id)

    for switch in switches:
        if bound_profile is not None:
            # 模板为准：本批请求里逐台填的 SNMP 字段全部丢弃（校验器也已跳过），
            # 只回填模板上的展示字段，且不落任何口令副本。
            switch.snmp_profile = bound_profile
            switch.snmp_enabled = config.snmp_enabled
            apply_profile_display_fields(switch, bound_profile)
            switch.snmp_auth_password_encrypted = None
            switch.snmp_priv_password_encrypted = None
            switch.snmp_community = None
            updated_count += 1
            continue

        if 'snmp_profile_id' in config.model_fields_set and config.snmp_profile_id is None:
            # 显式传 null = 整批解绑，改回各自的凭据（凭据列保留，见单台接口的说明）
            switch.snmp_profile = None

        # Update SNMP configuration
        switch.snmp_enabled = config.snmp_enabled
        switch.snmp_version = config.snmp_version
        switch.snmp_port = config.snmp_port

        if config.snmp_version == "3":
            switch.snmp_username = config.snmp_username
            switch.snmp_auth_protocol = config.snmp_auth_protocol

            if config.snmp_auth_password:
                switch.snmp_auth_password_encrypted = encrypt_password(config.snmp_auth_password)
            if config.snmp_priv_password:
                switch.snmp_priv_protocol = config.snmp_priv_protocol or "AES128"
                switch.snmp_priv_password_encrypted = encrypt_password(config.snmp_priv_password)
            else:
                switch.snmp_priv_protocol = None
                switch.snmp_priv_password_encrypted = None

            switch.snmp_community = None

        elif config.snmp_version == "2c":
            switch.snmp_username = None
            switch.snmp_auth_protocol = None
            switch.snmp_priv_protocol = None
            switch.snmp_priv_password_encrypted = None
            if config.snmp_community:
                switch.snmp_auth_password_encrypted = encrypt_password(config.snmp_community)

        updated_count += 1

    await db.commit()

    logger.info(f"Batch updated SNMP config for {updated_count} switches")

    return {
        "success": True,
        "message": f"SNMP configuration updated for {updated_count} switches",
        "updated_count": updated_count,
        "switch_ids": [s.id for s in switches]
    }


@router.post("/test")
async def test_snmp_connection(
    test_config: SNMPTestRequest
):
    """
    Test SNMP connectivity to a switch

    This endpoint attempts to connect to the switch and retrieve basic system information.
    Returns success/failure and any error messages.
    """
    try:
        # 认证凭据统一走 services.snmp_service.build_snmp_auth，
        # 与连接测试、后台采集保持完全一致的构造逻辑（含协议名大小写归一化与 v1/v2c 分支）。
        from services.snmp_service import build_snmp_auth, describe_snmp_error

        if test_config.snmp_version == "3":
            # Test SNMPv3
            if not test_config.snmp_username or not test_config.snmp_auth_password:
                raise HTTPException(
                    status_code=400,
                    detail="SNMPv3 requires username and auth_password"
                )

            auth_data = build_snmp_auth(
                username=test_config.snmp_username,
                auth_protocol=test_config.snmp_auth_protocol,
                auth_password=test_config.snmp_auth_password,
                priv_protocol=test_config.snmp_priv_protocol,
                priv_password=test_config.snmp_priv_password,
                snmp_version="3",
            )

            # Create transport target (pysnmp 7.x requires .create())
            transport = await UdpTransportTarget.create(
                (test_config.target_ip, test_config.snmp_port),
                timeout=5,
                retries=1
            )

            # Try to get system description using asyncio API
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                SnmpEngine(),
                auth_data,
                transport,
                ContextData(),
                ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))  # sysDescr
            )

            if errorIndication:
                logger.warning(
                    f"SNMPv3 test failed for {test_config.target_ip}: {errorIndication}"
                )
                return {
                    "success": False,
                    # message 给人看（中文可操作），raw_error 保留 pysnmp 原文供排障
                    "message": describe_snmp_error(errorIndication),
                    "error_type": "connection_error",
                    "raw_error": str(errorIndication),
                }
            elif errorStatus:
                logger.warning(
                    f"SNMPv3 test error status for {test_config.target_ip}: "
                    f"{errorStatus.prettyPrint()}"
                )
                return {
                    "success": False,
                    "message": f"设备返回 SNMP 错误：{errorStatus.prettyPrint()}",
                    "error_type": "snmp_error",
                    "raw_error": errorStatus.prettyPrint(),
                }
            else:
                sys_descr = str(varBinds[0][1])
                return {
                    "success": True,
                    "message": "SNMP connection successful",
                    "system_description": sys_descr[:200],  # Limit length
                    "target_ip": test_config.target_ip,
                    "snmp_version": test_config.snmp_version
                }

        elif test_config.snmp_version == "2c":
            # Test SNMPv2c
            if not test_config.snmp_community:
                raise HTTPException(
                    status_code=400,
                    detail="SNMPv2c requires community string"
                )

            # Create transport target (pysnmp 7.x requires .create())
            transport = await UdpTransportTarget.create(
                (test_config.target_ip, test_config.snmp_port),
                timeout=5,
                retries=1
            )

            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                SnmpEngine(),
                # v2c 团体字同样经 build_snmp_auth 构造，保持与其它入口一致
                build_snmp_auth(
                    username=None,
                    auth_protocol=None,
                    auth_password=test_config.snmp_community,
                    snmp_version="2c",
                ),
                transport,
                ContextData(),
                ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))
            )

            if errorIndication:
                logger.warning(
                    f"SNMPv2c test failed for {test_config.target_ip}: {errorIndication}"
                )
                return {
                    "success": False,
                    "message": describe_snmp_error(errorIndication),
                    "error_type": "connection_error",
                    "raw_error": str(errorIndication),
                }
            elif errorStatus:
                logger.warning(
                    f"SNMPv2c test error status for {test_config.target_ip}: "
                    f"{errorStatus.prettyPrint()}"
                )
                return {
                    "success": False,
                    "message": f"设备返回 SNMP 错误：{errorStatus.prettyPrint()}",
                    "error_type": "snmp_error",
                    "raw_error": errorStatus.prettyPrint(),
                }
            else:
                sys_descr = str(varBinds[0][1])
                return {
                    "success": True,
                    "message": "SNMP connection successful",
                    "system_description": sys_descr[:200],
                    "target_ip": test_config.target_ip,
                    "snmp_version": test_config.snmp_version
                }

    except Exception as e:
        logger.error(f"SNMP test failed for {test_config.target_ip}: {str(e)}")
        return {
            "success": False,
            "message": f"SNMP test failed: {str(e)}",
            "error_type": "exception"
        }


@router.post("/test/{switch_id}")
async def test_saved_snmp_config(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    用**库里已保存**的凭据测一台交换机的 SNMP 连通性。

    为什么需要这个接口：`POST /snmp/test` 要求把口令明文传进来，而引用模板的交换机
    口令只存在模板上、接口从不返回，界面上根本拿不到。结果是这类交换机要么没法测，
    要么只能让人拿模板口令手工再敲一遍 —— 敲错了就变成「设备明明好的却测不通」。
    这里在服务端按统一解析路径取凭据，和后台采集用的是同一份，测出来的就是真实情况。
    """
    result = await db.execute(select(Switch).where(Switch.id == switch_id))
    switch = result.scalar_one_or_none()
    if not switch:
        raise HTTPException(status_code=404, detail=f"Switch {switch_id} not found")

    switch_ip = str(switch.ip_address)

    if not switch_has_snmp_credentials(switch):
        return {
            "success": False,
            "message": "这台交换机没有可用的 SNMP 凭据（未启用 SNMP，或凭据为空）",
            "error_type": "no_credentials",
            "credential_source": switch.snmp_profile_name or "switch",
        }

    try:
        snmp_config = build_switch_snmp_config(switch)

        auth_password = (
            decrypt_password(snmp_config['snmp_auth_password_encrypted'])
            if snmp_config['snmp_auth_password_encrypted'] else None
        )
        priv_password = (
            decrypt_password(snmp_config['snmp_priv_password_encrypted'])
            if snmp_config['snmp_priv_password_encrypted'] else None
        )

        auth_data = build_snmp_auth(
            username=snmp_config['snmp_username'],
            auth_protocol=snmp_config['snmp_auth_protocol'],
            auth_password=auth_password,
            priv_protocol=snmp_config['snmp_priv_protocol'],
            priv_password=priv_password,
            snmp_version=snmp_config['snmp_version'],
        )

        transport = await UdpTransportTarget.create(
            (switch_ip, snmp_config['snmp_port'] or 161),
            timeout=5,
            retries=1,
        )

        errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
            SnmpEngine(),
            auth_data,
            transport,
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0')),  # sysDescr
        )

        if errorIndication:
            logger.warning(f"SNMP test failed for switch {switch.name} ({switch_ip}): {errorIndication}")
            return {
                "success": False,
                "message": describe_snmp_error(errorIndication),
                "error_type": "connection_error",
                "raw_error": str(errorIndication),
                "credential_source": switch.snmp_profile_name or "switch",
            }
        if errorStatus:
            logger.warning(
                f"SNMP test error status for switch {switch.name} ({switch_ip}): "
                f"{errorStatus.prettyPrint()}"
            )
            return {
                "success": False,
                "message": f"设备返回 SNMP 错误：{errorStatus.prettyPrint()}",
                "error_type": "snmp_error",
                "raw_error": errorStatus.prettyPrint(),
                "credential_source": switch.snmp_profile_name or "switch",
            }

        return {
            "success": True,
            "message": "SNMP connection successful",
            "system_description": str(varBinds[0][1])[:200],
            "target_ip": switch_ip,
            "snmp_version": snmp_config['snmp_version'],
            # 告诉排障的人这份凭据是从模板来的还是本机自带的：改了交换机上的口令
            # 却毫无变化时，能立刻看出「以模板为准」而不是以为缓存没刷新。
            "credential_source": switch.snmp_profile_name or "switch",
        }

    except Exception as e:
        logger.error(f"SNMP test failed for switch {switch.name} ({switch_ip}): {str(e)}")
        return {
            "success": False,
            "message": f"SNMP test failed: {str(e)}",
            "error_type": "exception",
            "credential_source": switch.snmp_profile_name or "switch",
        }


@router.get("/switches/configured")
async def list_snmp_configured_switches(
    db: AsyncSession = Depends(get_db)
):
    """
    List all switches with SNMP configuration status
    """
    result = await db.execute(
        select(Switch).order_by(Switch.name.asc(), Switch.id.asc())
    )
    switches = result.scalars().all()

    rows = []
    for s in switches:
        # 版本/用户名取**实际生效**的那份：引用模板时以模板为准，直接读交换机行
        # 会显示成回填前的残留值。解析一次复用，别在一个列表接口里解析两遍。
        effective = build_switch_snmp_config(s)
        rows.append({
            "id": s.id,
            "name": s.name,
            "ip_address": str(s.ip_address),
            "vendor": s.vendor,
            "role": "",
            "snmp_enabled": s.snmp_enabled or False,
            "snmp_version": effective['snmp_version'],
            "snmp_username": effective['snmp_username'],
            # 引用模板的交换机自己那两列是空的，判定必须走统一入口，
            # 否则它们会被整批显示成「未配置凭据」。
            "has_credentials": switch_has_snmp_credentials(s),
            "snmp_profile_id": s.snmp_profile_id,
            "snmp_profile_name": s.snmp_profile_name,
            "enabled": s.enabled,
        })

    return {
        "total": len(switches),
        "switches": rows,
    }


@router.delete("/config/{switch_id}")
async def delete_snmp_config(
    switch_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    Remove SNMP configuration from a switch
    """
    result = await db.execute(
        select(Switch).where(Switch.id == switch_id)
    )
    switch = result.scalar_one_or_none()

    if not switch:
        raise HTTPException(status_code=404, detail=f"Switch {switch_id} not found")

    # Clear SNMP configuration
    switch.snmp_enabled = False
    switch.snmp_username = None
    switch.snmp_auth_protocol = None
    switch.snmp_auth_password_encrypted = None
    switch.snmp_priv_protocol = None
    switch.snmp_priv_password_encrypted = None
    # 解除模板引用：这个接口的语义是「把这台交换机的 SNMP 配置整个清掉」，
    # 留着一个模板引用会让界面显示「凭据来源：模板X」同时又显示「未配置」，自相矛盾。
    # 要保留绑定只是临时停用 SNMP，应该用 PUT /snmp/config/{id} 传 snmp_enabled=false。
    # 赋给关系属性而不是外键列：关系是预加载过的，直接改 FK 列 SQLAlchemy 不认。
    switch.snmp_profile = None

    await db.commit()

    logger.info(f"Removed SNMP config from switch {switch.name}")

    return {
        "success": True,
        "message": f"SNMP configuration removed from switch {switch.name}"
    }
