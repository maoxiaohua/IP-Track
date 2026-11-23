"""
交换机配置备份 API（挂在 collector 服务）

- 只读原则：本模块的备份动作只执行 show/display 类只读命令，绝不下发写配置命令；
- 总览/历史接口不返回配置正文，正文单独按记录 id 拉取，避免列表被大文本拖垮；
- 写操作（立即备份、修改设置）对访客由 ReadOnlyGuestMiddleware 统一 401。
"""

import difflib
import io
import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from models.config_backup import ConfigBackup, ConfigBlob
from models.switch import Switch
from schemas.config_backup import BackupGlobalSettingsUpdate, BackupSwitchSettingsUpdate
from services.config_backup_service import (
    INTERVAL_SETTING_KEY,
    RETENTION_SETTING_KEY,
    VENDOR_PRESETS,
    backup_switch_config,
    get_global_interval_minutes,
    get_retention_versions,
    resolve_backup_target,
)
from services.settings_service import SettingsService

router = APIRouter(prefix="/config-backups", tags=["config-backups"])

MAX_PAGE_SIZE = 200
# 一次性打包的交换机数量上限，避免超大请求拖垮服务
MAX_BATCH_SWITCHES = 500
# 超大配置的 diff 文本会拖垮浏览器，超出部分截断并提示
MAX_DIFF_CHARS = 500_000

VALID_STATUSES = {'never', 'running', 'success', 'failed', 'unsupported', 'skipped'}


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _backup_brief(row: ConfigBackup) -> Dict[str, Any]:
    return {
        'id': row.id,
        'switch_id': row.switch_id,
        'status': row.status,
        'trigger_source': row.trigger_source,
        'sha256': row.sha256,
        'size_bytes': row.size_bytes,
        'device_type': row.device_type,
        'command': row.command,
        'message': row.message,
        'started_at': _iso(row.started_at),
        'finished_at': _iso(row.finished_at),
        'duration_ms': row.duration_ms,
    }


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', (text or '').strip())
    return cleaned.strip('._') or 'switch'


@router.get("")
async def list_overview(
    status: Optional[str] = Query(None, description="按最新状态筛选：never/success/failed/running/unsupported/skipped"),
    db: AsyncSession = Depends(get_db),
):
    """每台交换机的备份总览：最新状态、上次成功、版本数、有效间隔。"""
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"不支持的 status：{status}")

    global_interval = await get_global_interval_minutes(db)

    switches = (await db.execute(select(Switch).order_by(Switch.name))).scalars().all()

    # PostgreSQL DISTINCT ON：每台交换机只取最新一条记录
    latest_rows = (await db.execute(
        select(ConfigBackup)
        .order_by(ConfigBackup.switch_id, ConfigBackup.started_at.desc())
        .distinct(ConfigBackup.switch_id)
    )).scalars().all()
    latest_map = {row.switch_id: row for row in latest_rows}

    success_rows = (await db.execute(
        select(ConfigBackup)
        .where(ConfigBackup.status == 'success')
        .order_by(ConfigBackup.switch_id, ConfigBackup.started_at.desc())
        .distinct(ConfigBackup.switch_id)
    )).scalars().all()
    success_map = {row.switch_id: row for row in success_rows}

    count_rows = (await db.execute(
        select(ConfigBackup.switch_id, func.count(func.distinct(ConfigBackup.sha256)))
        .where(ConfigBackup.status == 'success', ConfigBackup.sha256.isnot(None))
        .group_by(ConfigBackup.switch_id)
    )).all()
    version_map = {switch_id: int(count or 0) for switch_id, count in count_rows}

    items: List[Dict[str, Any]] = []
    for sw in switches:
        latest = latest_map.get(sw.id)
        last_success = success_map.get(sw.id)
        _, command, reason = resolve_backup_target(sw)
        item = {
            'switch_id': sw.id,
            'name': sw.name,
            'ip_address': str(sw.ip_address) if sw.ip_address else None,
            'vendor': sw.vendor,
            'model': sw.model,
            'location': sw.location,
            'enabled': bool(sw.enabled),
            'cli_enabled': bool(sw.cli_enabled),
            'backup_enabled': bool(sw.backup_enabled),
            'backup_interval_minutes': sw.backup_interval_minutes,
            'backup_device_type': sw.backup_device_type,
            'backup_config_command': sw.backup_config_command,
            # 网络不可达：计划备份已暂停，恢复可达后自动继续
            'backup_unreachable': bool(getattr(sw, 'backup_unreachable', False)),
            'interval_minutes': sw.backup_interval_minutes or global_interval,
            'supported': bool(command),
            'unsupported_reason': reason or None,
            'status': latest.status if latest else 'never',
            'message': latest.message if latest else None,
            'trigger_source': latest.trigger_source if latest else None,
            'last_backup_at': _iso(latest.started_at) if latest else None,
            'last_duration_ms': latest.duration_ms if latest else None,
            'last_success_at': _iso(last_success.started_at) if last_success else None,
            'last_success_id': last_success.id if last_success else None,
            'last_success_size': last_success.size_bytes if last_success else None,
            'last_sha256': last_success.sha256 if last_success else None,
            'version_count': version_map.get(sw.id, 0),
        }
        if status and item['status'] != status:
            continue
        items.append(item)

    return {
        'items': items,
        'total': len(items),
        'global_interval_minutes': global_interval,
    }


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    """全局默认间隔、保留版本数，以及各厂商内置的驱动/命令（供前端提示）。"""
    return {
        'interval_minutes': await get_global_interval_minutes(db),
        'retention_versions': await get_retention_versions(db),
        'vendor_presets': {
            vendor: {'device_type': device_type, 'command': command}
            for vendor, (device_type, command) in VENDOR_PRESETS.items()
        },
    }


@router.put("/settings")
async def update_settings(
    payload: BackupGlobalSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """修改全局默认间隔与保留版本数。"""
    await SettingsService.set_setting(
        db, INTERVAL_SETTING_KEY, payload.interval_minutes, 'integer',
        '交换机配置备份全局默认间隔（分钟），单台可覆盖',
    )
    await SettingsService.set_setting(
        db, RETENTION_SETTING_KEY, payload.retention_versions, 'integer',
        '每台交换机保留的配置版本数（按内容去重后）',
    )
    await db.commit()
    return {
        'interval_minutes': await get_global_interval_minutes(db),
        'retention_versions': await get_retention_versions(db),
    }


@router.post("/{switch_id}/run")
async def run_backup_now(switch_id: int, db: AsyncSession = Depends(get_db)):
    """立即对单台交换机执行一次只读备份（同步返回结果）。"""
    switch = await db.get(Switch, switch_id)
    if not switch:
        raise HTTPException(status_code=404, detail="交换机不存在")
    if not switch.enabled:
        raise HTTPException(status_code=400, detail="交换机已停用，无法备份")
    result = await backup_switch_config(db, switch, 'manual')
    return result


@router.get("/{switch_id}/history")
async def backup_history(
    switch_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    status: Optional[str] = Query(None, description="按状态筛选：running/success/failed/unsupported"),
    db: AsyncSession = Depends(get_db),
):
    """版本历史（含失败记录），按时间倒序分页。"""
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"不支持的 status：{status}")
    switch = await db.get(Switch, switch_id)
    if not switch:
        raise HTTPException(status_code=404, detail="交换机不存在")

    filters = [ConfigBackup.switch_id == switch_id]
    if status:
        filters.append(ConfigBackup.status == status)

    total = (await db.execute(
        select(func.count(ConfigBackup.id)).where(*filters)
    )).scalar() or 0

    rows = (await db.execute(
        select(ConfigBackup)
        .where(*filters)
        .order_by(ConfigBackup.started_at.desc(), ConfigBackup.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    return {
        'items': [_backup_brief(row) for row in rows],
        'total': int(total),
        'page': page,
        'page_size': page_size,
    }


async def _get_backup_content(db: AsyncSession, backup_id: int):
    row = await db.get(ConfigBackup, backup_id)
    if not row:
        raise HTTPException(status_code=404, detail="备份记录不存在")
    if not row.sha256:
        raise HTTPException(status_code=404, detail="该记录没有配置内容（备份未成功）")
    blob = await db.get(ConfigBlob, row.sha256)
    if not blob:
        raise HTTPException(status_code=404, detail="配置内容已丢失")
    return row, blob


@router.get("/versions/{backup_id}/content")
async def get_version_content(backup_id: int, db: AsyncSession = Depends(get_db)):
    """打开某次成功备份的配置正文。"""
    row, blob = await _get_backup_content(db, backup_id)
    data = _backup_brief(row)
    data['content'] = blob.content
    return data


@router.get("/versions/{backup_id}/download")
async def download_version(backup_id: int, db: AsyncSession = Depends(get_db)):
    """下载配置文件，文件名 <hostname>-<时间>.cfg。"""
    row, blob = await _get_backup_content(db, backup_id)
    switch = await db.get(Switch, row.switch_id)
    host = switch.name if switch else f'switch_{row.switch_id}'
    stamp = row.started_at.strftime('%Y%m%d-%H%M%S') if row.started_at else 'config'
    filename = f'{_safe_filename(host)}-{stamp}.cfg'
    headers = {
        'Content-Disposition': (
            f"attachment; filename=\"{filename}\"; "
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return Response(
        content=blob.content.encode('utf-8'),
        media_type='text/plain; charset=utf-8',
        headers=headers,
    )


@router.get("/batch-download")
async def batch_download(
    # 用 Optional 自行校验：本版本 FastAPI 对缺失的必填 List 参数会序列化报错成 500
    switch_ids: Optional[List[int]] = Query(None, description="要打包的交换机 id，可重复传参"),
    db: AsyncSession = Depends(get_db),
):
    """把多台交换机各自最新的成功备份打包成一个 ZIP（只读，不触发备份）。"""
    unique_ids = list(dict.fromkeys(switch_ids or []))
    if not unique_ids:
        raise HTTPException(status_code=422, detail="请至少选择一台交换机")
    if len(unique_ids) > MAX_BATCH_SWITCHES:
        raise HTTPException(
            status_code=422,
            detail=f"一次最多打包 {MAX_BATCH_SWITCHES} 台交换机",
        )

    switches = (
        await db.execute(select(Switch).where(Switch.id.in_(unique_ids)))
    ).scalars().all()
    switch_names = {s.id: s.name for s in switches}

    # 每台交换机各自最近一条成功记录
    rows = (
        await db.execute(
            select(ConfigBackup)
            .where(
                ConfigBackup.switch_id.in_(unique_ids),
                ConfigBackup.status == 'success',
                ConfigBackup.sha256.isnot(None),
            )
            .order_by(ConfigBackup.switch_id, ConfigBackup.started_at.desc())
        )
    ).scalars().all()
    latest: Dict[int, ConfigBackup] = {}
    for row in rows:
        latest.setdefault(row.switch_id, row)

    sha_list = list({row.sha256 for row in latest.values() if row.sha256})
    blobs = {}
    if sha_list:
        blob_rows = (
            await db.execute(select(ConfigBlob).where(ConfigBlob.sha256.in_(sha_list)))
        ).scalars().all()
        blobs = {b.sha256: b for b in blob_rows}

    buffer = io.BytesIO()
    used_names: set = set()
    included = 0
    skipped: List[str] = []
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for switch_id in unique_ids:
            row = latest.get(switch_id)
            blob = blobs.get(row.sha256) if row and row.sha256 else None
            if not row or not blob:
                skipped.append(switch_names.get(switch_id) or f'switch_{switch_id}')
                continue
            host = switch_names.get(switch_id) or f'switch_{switch_id}'
            stamp = row.started_at.strftime('%Y%m%d-%H%M%S') if row.started_at else 'config'
            base = f'{_safe_filename(host)}-{stamp}.cfg'
            name = base
            seq = 2
            while name in used_names:
                name = f'{base[:-4]}({seq}).cfg'
                seq += 1
            used_names.add(name)
            archive.writestr(name, blob.content.encode('utf-8'))
            included += 1

    if not included:
        raise HTTPException(
            status_code=404,
            detail='所选交换机都没有可下载的成功备份',
        )

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    filename = f'config-backups-{stamp}.zip'
    headers = {
        'Content-Disposition': (
            f"attachment; filename=\"{filename}\"; "
            f"filename*=UTF-8''{quote(filename)}"
        ),
        'X-Batch-Included': str(included),
        'X-Batch-Skipped': str(len(skipped)),
        # 交换机名可能是中文，响应头只能是 ASCII，用 URL 编码传给前端解码；
        # 只回传前 100 个，避免超长响应头。
        'X-Batch-Skipped-Names': ','.join(quote(name, safe='') for name in skipped[:100]),
    }
    return Response(
        content=buffer.getvalue(),
        media_type='application/zip',
        headers=headers,
    )


@router.get("/diff")
async def diff_versions(
    from_id: int = Query(..., description="旧版本记录 id"),
    to_id: int = Query(..., description="新版本记录 id"),
    db: AsyncSession = Depends(get_db),
):
    """对比两次备份的配置差异（服务端 unified diff）。"""
    from_row, from_blob = await _get_backup_content(db, from_id)
    to_row, to_blob = await _get_backup_content(db, to_id)

    diff_text = '\n'.join(difflib.unified_diff(
        from_blob.content.splitlines(),
        to_blob.content.splitlines(),
        fromfile=f'#{from_id} {_iso(from_row.started_at) or ""}',
        tofile=f'#{to_id} {_iso(to_row.started_at) or ""}',
        lineterm='',
    ))
    truncated = False
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS]
        truncated = True
    return {
        'from': _backup_brief(from_row),
        'to': _backup_brief(to_row),
        'diff': diff_text,
        'truncated': truncated,
    }


@router.put("/{switch_id}/settings")
async def update_switch_settings(
    switch_id: int,
    payload: BackupSwitchSettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """修改单台交换机的备份设置；显式 null 表示清除覆盖，回到全局/预设。"""
    switch = await db.get(Switch, switch_id)
    if not switch:
        raise HTTPException(status_code=404, detail="交换机不存在")

    data = payload.model_dump(exclude_unset=True)
    if 'backup_enabled' in data:
        if data['backup_enabled'] is None:
            raise HTTPException(status_code=422, detail="backup_enabled 不能为 null")
        switch.backup_enabled = bool(data['backup_enabled'])
    for field in ('backup_interval_minutes', 'backup_device_type', 'backup_config_command'):
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip() or None
            setattr(switch, field, value)

    await db.commit()

    device_type, command, reason = resolve_backup_target(switch)
    return {
        'switch_id': switch.id,
        'backup_enabled': bool(switch.backup_enabled),
        'backup_interval_minutes': switch.backup_interval_minutes,
        'backup_device_type': switch.backup_device_type,
        'backup_config_command': switch.backup_config_command,
        'resolved_device_type': device_type,
        'resolved_command': command,
        'unsupported_reason': reason or None,
    }
