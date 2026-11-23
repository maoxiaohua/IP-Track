"""
Automatic Network Topology API (LLDP / CDP derived)

- 原始事实（neighbors / interfaces）与派生结果（links）分开暴露，便于核对；
- 所有 GET 由 ReadOnlyGuestMiddleware 放行给访客，写操作要求登录；
- 本文件不触发采集以外的副作用，POST /collect 只是入队。
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from core.config import settings
from models.collection_job import JobType
from models.switch import Switch
from models.topology import LldpNeighbor, SwitchInterface, TopologyLink, TopologyUnknownNode
from schemas.topology import TopologyCollectRequest
from services.collection_worker import worker_pool
from services.topology_service import derive_links

router = APIRouter(prefix="/topology", tags=["topology"])

# 超过该链路数说明前端一次画不下，降级为截断 + 提示（请求 /graph?focus_switch_id= 聚焦）
GRAPH_MAX_LINKS = 800
# /links 表格单页上限
MAX_PAGE_SIZE = 500


def _switch_id_of(row: TopologyLink, side: str) -> Optional[int]:
    return getattr(row, f'{side}_switch_id')


def _unknown_node_id(row: TopologyLink, side: str) -> str:
    """链路里的未知端只存了 mgmt_ip / sys_name，用与 topology_service 相同的键前缀重建。"""
    # link_key 里带着对端派生时用的合并键（un:ip:/un:mac:/un:chassis:/un:name:），
    # 与 topology_unknown_nodes.node_key 完全一致，优先用它，避免同一设备因某个
    # 链路行缺字段而分裂成两个节点、或丢掉 device_class。
    for part in (row.link_key or '').split('|'):
        if part.startswith('un:') and len(part) > 3:
            return part[3:]
    ip = getattr(row, f'{side}_mgmt_ip')
    if ip:
        return f'ip:{ip}'
    name = (getattr(row, f'{side}_sys_name') or '').strip().lower()
    if name:
        return f'name:{name[:200]}'
    return f'link:{row.link_key}:{side}'


def _endpoint_node_id(row: TopologyLink, side: str) -> str:
    switch_id = _switch_id_of(row, side)
    if switch_id is not None:
        return f'sw:{switch_id}'
    return _unknown_node_id(row, side)


def _switch_node(switch: Switch, degree: int) -> Dict:
    return {
        'id': f'sw:{switch.id}',
        'kind': 'switch',
        'switch_id': switch.id,
        'label': switch.name,
        'sys_name': switch.sys_name,
        'mgmt_ip': str(switch.ip_address) if switch.ip_address else None,
        'vendor': switch.vendor,
        'enabled': bool(switch.enabled),
        'auto_collect_topology': bool(switch.auto_collect_topology),
        'collection_status': switch.last_topology_collection_status,
        'last_collection_at': (
            switch.last_topology_collection_at.isoformat()
            if switch.last_topology_collection_at else None
        ),
        'neighbors_count': switch.last_topology_neighbors_count,
        'degree': degree,
    }


def _link_payload(row: TopologyLink) -> Dict:
    return {
        'link_key': row.link_key,
        'source': _endpoint_node_id(row, 'a'),
        'target': _endpoint_node_id(row, 'b'),
        'status': row.status,
        'confidence': row.confidence,
        'evidence': row.evidence,
        'is_lag': bool(row.is_lag),
        'conflict_reason': row.conflict_reason,
        'a_switch_id': row.a_switch_id,
        'a_if_index': row.a_if_index,
        'a_port_name': row.a_port_name,
        'a_sys_name': row.a_sys_name,
        'a_mgmt_ip': row.a_mgmt_ip,
        'b_switch_id': row.b_switch_id,
        'b_if_index': row.b_if_index,
        'b_port_name': row.b_port_name,
        'b_sys_name': row.b_sys_name,
        'b_mgmt_ip': row.b_mgmt_ip,
        'first_seen': row.first_seen.isoformat() if row.first_seen else None,
        'last_seen': row.last_seen.isoformat() if row.last_seen else None,
    }


def _coverage(switches: List[Switch], link_counts: Dict[str, int], unknown_nodes: int) -> Dict:
    by_status: Dict[str, int] = {}
    for switch in switches:
        key = switch.last_topology_collection_status or 'not_collected'
        by_status[key] = by_status.get(key, 0) + 1
    return {
        'switches_total': len(switches),
        'switches_enabled': sum(1 for s in switches if s.enabled),
        'auto_collect': sum(1 for s in switches if s.auto_collect_topology),
        'collected': sum(1 for s in switches if s.last_topology_collection_at is not None),
        'not_collected': by_status.get('not_collected', 0),
        'success': by_status.get('success', 0),
        'partial': by_status.get('partial', 0),
        'unsupported': by_status.get('unsupported', 0),
        'failed': by_status.get('failed', 0),
        'links': link_counts,
        'unknown_nodes': unknown_nodes,
    }


async def _link_counts(db: AsyncSession) -> Dict[str, int]:
    rows = await db.execute(
        select(TopologyLink.status, func.count()).group_by(TopologyLink.status)
    )
    counts = {status: count for status, count in rows.all()}
    counts['total'] = sum(counts.values())
    return counts


@router.get("/status")
async def topology_status(db: AsyncSession = Depends(get_db)):
    """覆盖统计：让用户看到「没采到」而不是被画成孤立节点。"""
    switches = list((await db.execute(select(Switch))).scalars().all())
    unknown_nodes = await db.scalar(select(func.count()).select_from(TopologyUnknownNode))
    return _coverage(switches, await _link_counts(db), int(unknown_nodes or 0))


@router.get("/graph")
async def topology_graph(
    focus_switch_id: Optional[int] = None,
    depth: int = Query(1, ge=1, le=3),
    switch_status: Optional[str] = Query(None, max_length=20),
    db: AsyncSession = Depends(get_db),
):
    """
    拓扑图数据。全量超过 GRAPH_MAX_LINKS 时截断并置 truncated=True（请用 focus 聚焦）。

    switch_status 按交换机的 last_topology_collection_status 过滤图上的交换机：
    只保留该状态的交换机，以及它们之间的链路（对端未纳管的未知节点保留）。
    coverage 仍返回全量统计，不受过滤影响。
    """
    all_switches = list((await db.execute(select(Switch))).scalars().all())
    switches = all_switches
    rows = list(
        (await db.execute(
            select(TopologyLink).order_by(TopologyLink.confidence.desc(), TopologyLink.id.asc())
        )).scalars().all()
    )
    truncated = False

    if switch_status:
        switches = [s for s in switches if s.last_topology_collection_status == switch_status]
        visible = {s.id for s in switches}
        rows = [
            row for row in rows
            if (row.a_switch_id is None or row.a_switch_id in visible)
            and (row.b_switch_id is None or row.b_switch_id in visible)
        ]

    if focus_switch_id is not None:
        focus_id = f'sw:{focus_switch_id}'
        allowed = {focus_id}
        for _ in range(depth):
            for row in rows:
                source, target = _endpoint_node_id(row, 'a'), _endpoint_node_id(row, 'b')
                if source in allowed:
                    allowed.add(target)
                elif target in allowed:
                    allowed.add(source)
        rows = [r for r in rows if _endpoint_node_id(r, 'a') in allowed and _endpoint_node_id(r, 'b') in allowed]
    elif len(rows) > GRAPH_MAX_LINKS:
        rows = rows[:GRAPH_MAX_LINKS]
        truncated = True

    degree: Dict[str, int] = {}
    for row in rows:
        source, target = _endpoint_node_id(row, 'a'), _endpoint_node_id(row, 'b')
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1

    switches_by_id = {s.id: s for s in switches}
    unknown_rows = {
        node.node_key: node
        for node in (await db.execute(select(TopologyUnknownNode))).scalars().all()
    }
    # 未知节点在库里可能按 mac:/chassis: 建档（邻居没上报管理地址），而链路行只存了
    # mgmt_ip/sys_name，重建出来的键是 name:xxx。用 sys_name 兜底回查，
    # 否则 device_class/label 全部丢失，「只显示网络设备」的过滤就失效。
    unknown_by_name: Dict[str, TopologyUnknownNode] = {}
    for node in unknown_rows.values():
        name = (node.sys_name or '').strip().lower()
        if name:
            unknown_by_name.setdefault(name[:200], node)

    nodes: Dict[str, Dict] = {}
    for node_id in degree:
        if node_id.startswith('sw:'):
            switch = switches_by_id.get(int(node_id[3:]))
            if switch is not None:
                nodes[node_id] = _switch_node(switch, degree[node_id])
            continue
        node = unknown_rows.get(node_id)
        if node is None and node_id.startswith('name:'):
            node = unknown_by_name.get(node_id[5:])
        nodes[node_id] = {
            'id': node_id,
            'kind': 'unknown',
            'node_key': node_id if node is not None else None,
            'label': (node.display_name if node and node.display_name else node_id),
            'sys_name': node.sys_name if node else None,
            'mgmt_ip': node.mgmt_ip if node else None,
            'chassis_id': node.chassis_id if node else None,
            'vendor_hint': node.vendor_hint if node else None,
            'device_class': node.device_class if node else None,
            'seen_count': node.seen_count if node else None,
            'degree': degree[node_id],
        }

    if focus_switch_id is not None:
        focus_node = f'sw:{focus_switch_id}'
        if focus_node not in nodes:
            switch = switches_by_id.get(focus_switch_id)
            if switch is None:
                raise HTTPException(status_code=404, detail=f"Switch {focus_switch_id} not found")
            nodes[focus_node] = _switch_node(switch, 0)

    if not truncated:
        # 未参与链路的交换机（LLDP 未开启 / 未采集）也要出现在图上，如实展示为孤立节点。
        for switch in switches:
            node_id = f'sw:{switch.id}'
            if node_id not in nodes and switch.enabled:
                nodes[node_id] = _switch_node(switch, 0)

    return {
        'nodes': list(nodes.values()),
        'links': [_link_payload(row) for row in rows],
        'coverage': _coverage(all_switches, await _link_counts(db), len(unknown_rows)),
        'truncated': truncated,
    }


@router.get("/links")
async def list_links(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
):
    conditions = []
    if status:
        conditions.append(TopologyLink.status == status)
    if q:
        needle = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        if needle:
            pattern = f"%{needle}%"
            conditions.append(or_(
                TopologyLink.a_sys_name.ilike(pattern, escape='\\'),
                TopologyLink.b_sys_name.ilike(pattern, escape='\\'),
                TopologyLink.a_port_name.ilike(pattern, escape='\\'),
                TopologyLink.b_port_name.ilike(pattern, escape='\\'),
                TopologyLink.a_mgmt_ip.ilike(pattern, escape='\\'),
                TopologyLink.b_mgmt_ip.ilike(pattern, escape='\\'),
            ))

    total = int(await db.scalar(
        select(func.count()).select_from(TopologyLink).where(*conditions)
    ) or 0)
    rows = (await db.execute(
        select(TopologyLink)
        .where(*conditions)
        .order_by(TopologyLink.confidence.desc(), TopologyLink.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'items': [_link_payload(row) for row in rows],
    }


@router.get("/neighbors")
async def list_neighbors(
    switch_id: Optional[int] = None,
    protocol: Optional[str] = Query(None, pattern='^(lldp|cdp)$'),
    limit: int = Query(1000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    query = select(LldpNeighbor)
    if switch_id is not None:
        query = query.where(LldpNeighbor.switch_id == switch_id)
    if protocol:
        query = query.where(LldpNeighbor.protocol == protocol)
    rows = (await db.execute(
        query.order_by(LldpNeighbor.switch_id.asc(), LldpNeighbor.local_if_index.asc()).limit(limit)
    )).scalars().all()
    return [
        {
            'id': row.id,
            'switch_id': row.switch_id,
            'protocol': row.protocol,
            'local_if_index': row.local_if_index,
            'local_port_id': row.local_port_id,
            'local_port_desc': row.local_port_desc,
            'remote_chassis_id': row.remote_chassis_id,
            'remote_port_id': row.remote_port_id,
            'remote_port_desc': row.remote_port_desc,
            'remote_sys_name': row.remote_sys_name,
            'remote_sys_desc': row.remote_sys_desc,
            'remote_mgmt_addr': row.remote_mgmt_addr,
            'capability': row.capability,
            'last_seen': row.last_seen.isoformat() if row.last_seen else None,
        }
        for row in rows
    ]


@router.get("/interfaces")
async def list_interfaces(
    switch_id: Optional[int] = None,
    limit: int = Query(2000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    query = select(SwitchInterface)
    if switch_id is not None:
        query = query.where(SwitchInterface.switch_id == switch_id)
    rows = (await db.execute(
        query.order_by(
            SwitchInterface.switch_id.asc(),
            SwitchInterface.if_name.asc().nullslast(),
            SwitchInterface.if_index.asc(),
        ).limit(limit)
    )).scalars().all()
    return [
        {
            'switch_id': row.switch_id,
            'if_index': row.if_index,
            'if_name': row.if_name,
            'if_descr': row.if_descr,
            'if_alias': row.if_alias,
            'if_type': row.if_type,
            'admin_status': row.admin_status,
            'oper_status': row.oper_status,
            'speed_mbps': row.speed_mbps,
            'phys_address': row.phys_address,
            'lag_key': row.lag_key,
            'last_change_ticks': row.last_change_ticks,
            'last_change_at': row.last_change_at.isoformat() if row.last_change_at else None,
            'last_seen': row.last_seen.isoformat() if row.last_seen else None,
        }
        for row in rows
    ]


@router.get("/unknown-nodes")
async def list_unknown_nodes(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(TopologyUnknownNode).order_by(
            TopologyUnknownNode.seen_count.desc(), TopologyUnknownNode.id.asc()
        )
    )).scalars().all()
    return [
        {
            'node_key': row.node_key,
            'display_name': row.display_name,
            'mgmt_ip': row.mgmt_ip,
            'chassis_id': row.chassis_id,
            'sys_name': row.sys_name,
            'vendor_hint': row.vendor_hint,
            'device_class': row.device_class,
            'seen_count': row.seen_count,
            'first_seen': row.first_seen.isoformat() if row.first_seen else None,
            'last_seen': row.last_seen.isoformat() if row.last_seen else None,
        }
        for row in rows
    ]


@router.post("/collect")
async def trigger_collection(
    body: Optional[TopologyCollectRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """把拓扑采集加入任务队列（真正的采集由 worker 执行）。"""
    if not settings.FEATURE_TOPOLOGY:
        raise HTTPException(status_code=400, detail="Topology feature is disabled")

    query = select(Switch)
    switch_ids = body.switch_ids if body else None
    if switch_ids:
        found = set((await db.execute(
            select(Switch.id).where(Switch.id.in_(switch_ids))
        )).scalars().all())
        missing = sorted(set(switch_ids) - found)
        if missing:
            raise HTTPException(status_code=400, detail=f"Switches not found: {missing}")
        query = query.where(Switch.id.in_(switch_ids))
    else:
        # 手动「采集拓扑」的预期是「所有在线交换机重新采集」；
        # auto_collect_topology 只控制定时采集，不限制手动触发。
        # 只排除已确认离线的设备，避免它们白占 worker。
        query = query.where(Switch.is_reachable.is_(True))

    switches = [s for s in (await db.execute(query)).scalars().all() if s.enabled]
    if not switches:
        return {'queued': 0, 'switches': 0, 'message': 'no eligible switches'}

    queued = await worker_pool.create_jobs(db, switches, JobType.TOPOLOGY)
    return {
        'queued': queued,
        'switches': len(switches),
        'skipped': len(switches) - queued,
    }


@router.post("/derive")
async def trigger_derive(db: AsyncSession = Depends(get_db)):
    """不重新采集，仅用现有事实重算链路（运维排查 / 采集后手动刷新）。"""
    if not settings.FEATURE_TOPOLOGY:
        raise HTTPException(status_code=400, detail="Topology feature is disabled")
    result = await derive_links(db)
    await db.commit()
    return result
