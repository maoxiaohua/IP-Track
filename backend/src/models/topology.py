"""
自动网络拓扑模型

四张表按「事实 → 派生」分层：
- SwitchInterface / LldpNeighbor 是采集到的原始事实，只记录不推断；
- TopologyLink 是推导结果，每轮采集后重建；
- TopologyUnknownNode 是未纳管对端的合并身份，避免图上出现大量重复未知节点。
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, BigInteger,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.sql import func
from core.database import Base


class SwitchInterface(Base):
    """交换机接口清单（IF-MIB / CLI 采集）"""

    __tablename__ = 'switch_interfaces'

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(
        Integer, ForeignKey('switches.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    if_index = Column(Integer, nullable=False)
    if_name = Column(String(128))
    if_descr = Column(String(255))
    if_alias = Column(String(255))
    if_type = Column(Integer)
    admin_status = Column(String(16))
    oper_status = Column(String(16))
    speed_mbps = Column(BigInteger)
    phys_address = Column(String(32))
    # 归一化后的聚合口键（ae0 / po1 / Bundle-Ether10 ...），用于展示层折叠 LAG
    lag_key = Column(String(128))

    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    collected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('switch_id', 'if_index', name='uq_switch_interfaces_switch_if'),
        Index('idx_switch_interfaces_switch', 'switch_id'),
    )

    def __repr__(self):
        return f"<SwitchInterface switch={self.switch_id} if={self.if_name or self.if_index}>"


class LldpNeighbor(Base):
    """原始邻居事实（LLDP 或 CDP），一条 = 本端某接口看到的一个远端邻居"""

    __tablename__ = 'lldp_neighbors'

    id = Column(Integer, primary_key=True, index=True)
    switch_id = Column(
        Integer, ForeignKey('switches.id', ondelete='CASCADE'),
        nullable=False, index=True
    )
    protocol = Column(String(8), nullable=False)  # 'lldp' | 'cdp'

    local_if_index = Column(Integer)
    local_port_id = Column(String(255))
    local_port_desc = Column(String(255))

    remote_chassis_id = Column(String(255))
    remote_chassis_id_subtype = Column(String(32))
    remote_port_id = Column(String(255))
    remote_port_id_subtype = Column(String(32))
    remote_port_desc = Column(String(255))
    remote_sys_name = Column(String(255))
    remote_sys_desc = Column(Text)
    remote_mgmt_addr = Column(String(64))
    remote_mgmt_addr_type = Column(String(16))

    ttl = Column(Integer)
    capability = Column(String(255))
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    collected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            'switch_id', 'protocol', 'local_if_index',
            'remote_chassis_id', 'remote_port_id',
            name='uq_lldp_neighbors_fact'
        ),
        Index('idx_lldp_neighbors_switch', 'switch_id'),
        Index('idx_lldp_neighbors_sysname', 'remote_sys_name'),
    )

    def __repr__(self):
        return (
            f"<LldpNeighbor switch={self.switch_id} {self.protocol} "
            f"local={self.local_if_index} remote={self.remote_sys_name or self.remote_chassis_id}>"
        )


class TopologyLink(Base):
    """派生链路。a/b 端点中未知对端 switch_id 为 NULL。"""

    __tablename__ = 'topology_links'

    id = Column(Integer, primary_key=True, index=True)
    # 端点规范排序后的唯一键，保证 A→B 与 B→A 落到同一行
    link_key = Column(String(512), nullable=False, unique=True)

    a_switch_id = Column(Integer, ForeignKey('switches.id', ondelete='CASCADE'), index=True)
    a_if_index = Column(Integer)
    a_port_name = Column(String(128))
    a_sys_name = Column(String(255))
    a_mgmt_ip = Column(String(64))

    b_switch_id = Column(Integer, ForeignKey('switches.id', ondelete='CASCADE'), index=True)
    b_if_index = Column(Integer)
    b_port_name = Column(String(128))
    b_sys_name = Column(String(255))
    b_mgmt_ip = Column(String(64))

    status = Column(String(16), nullable=False, default='unresolved', index=True)
    confidence = Column(Integer, nullable=False, default=0)
    evidence = Column(String(32))
    is_lag = Column(Boolean, nullable=False, default=False)
    conflict_reason = Column(Text)

    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    collected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_topology_links_a', 'a_switch_id'),
        Index('idx_topology_links_b', 'b_switch_id'),
        Index('idx_topology_links_status', 'status'),
    )

    def __repr__(self):
        return f"<TopologyLink {self.status} {self.a_sys_name} <-> {self.b_sys_name}>"


class TopologyUnknownNode(Base):
    """未纳管对端的合并身份（管理IP > chassis MAC > sysName）"""

    __tablename__ = 'topology_unknown_nodes'

    id = Column(Integer, primary_key=True, index=True)
    node_key = Column(String(512), nullable=False, unique=True)
    display_name = Column(String(255))
    mgmt_ip = Column(String(64))
    chassis_id = Column(String(255))
    sys_name = Column(String(255))
    vendor_hint = Column(String(100))
    # switch / router / wlan-ap / phone / host / hub / unknown，用于过滤非网络设备
    device_class = Column(String(20))
    seen_count = Column(Integer, nullable=False, default=1)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<TopologyUnknownNode {self.node_key}>"
