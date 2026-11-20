-- 031: 自动网络拓扑（LLDP / CDP / 互联接口）
-- 全部语句幂等：迁移中途失败会整文件重跑。

-- 1) 任务队列新增 topology 类型（008 建的是 PG enum；ORM 侧是 String(20)）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_type_enum') THEN
        ALTER TYPE job_type_enum ADD VALUE IF NOT EXISTS 'topology';
    END IF;
END
$$;

-- 2) 交换机身份与拓扑采集状态
ALTER TABLE switches ADD COLUMN IF NOT EXISTS sys_name VARCHAR(255);
ALTER TABLE switches ADD COLUMN IF NOT EXISTS chassis_id VARCHAR(255);
ALTER TABLE switches ADD COLUMN IF NOT EXISTS bridge_mac VARCHAR(32);
ALTER TABLE switches ADD COLUMN IF NOT EXISTS auto_collect_topology BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS topology_collection_method VARCHAR(20);
ALTER TABLE switches ADD COLUMN IF NOT EXISTS last_topology_collection_at TIMESTAMPTZ;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS last_topology_success_at TIMESTAMPTZ;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS last_topology_collection_status VARCHAR(20);
ALTER TABLE switches ADD COLUMN IF NOT EXISTS last_topology_collection_message TEXT;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS last_topology_neighbors_count INTEGER;

-- 3) CLI 命令模板新增拓扑相关命令（与 arp/mac 同构）
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS lldp_command TEXT;
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS lldp_parser_type VARCHAR(50);
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS lldp_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS cdp_command TEXT;
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS cdp_parser_type VARCHAR(50);
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS cdp_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS interfaces_command TEXT;
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS interfaces_parser_type VARCHAR(50);
ALTER TABLE switch_command_templates ADD COLUMN IF NOT EXISTS interfaces_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- 4) 接口清单（IF-MIB / CLI show interfaces）
CREATE TABLE IF NOT EXISTS switch_interfaces (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    if_index INTEGER NOT NULL,
    if_name VARCHAR(128),
    if_descr VARCHAR(255),
    if_alias VARCHAR(255),
    if_type INTEGER,
    admin_status VARCHAR(16),
    oper_status VARCHAR(16),
    speed_mbps BIGINT,
    phys_address VARCHAR(32),
    lag_key VARCHAR(128),
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_switch_interfaces_switch_if UNIQUE (switch_id, if_index)
);
CREATE INDEX IF NOT EXISTS idx_switch_interfaces_switch ON switch_interfaces(switch_id);

-- 5) 原始 LLDP / CDP 邻居事实（只记录，不推断）
CREATE TABLE IF NOT EXISTS lldp_neighbors (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    protocol VARCHAR(8) NOT NULL,
    local_if_index INTEGER,
    local_port_id VARCHAR(255),
    local_port_desc VARCHAR(255),
    remote_chassis_id VARCHAR(255),
    remote_chassis_id_subtype VARCHAR(32),
    remote_port_id VARCHAR(255),
    remote_port_id_subtype VARCHAR(32),
    remote_port_desc VARCHAR(255),
    remote_sys_name VARCHAR(255),
    remote_sys_desc TEXT,
    remote_mgmt_addr VARCHAR(64),
    remote_mgmt_addr_type VARCHAR(16),
    ttl INTEGER,
    capability VARCHAR(255),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lldp_neighbors_fact UNIQUE (
        switch_id, protocol, local_if_index, remote_chassis_id, remote_port_id
    )
);
CREATE INDEX IF NOT EXISTS idx_lldp_neighbors_switch ON lldp_neighbors(switch_id);
CREATE INDEX IF NOT EXISTS idx_lldp_neighbors_sysname ON lldp_neighbors(remote_sys_name);

-- 6) 派生链路（每轮采集后重建）
CREATE TABLE IF NOT EXISTS topology_links (
    id SERIAL PRIMARY KEY,
    link_key VARCHAR(512) NOT NULL UNIQUE,
    a_switch_id INTEGER REFERENCES switches(id) ON DELETE CASCADE,
    a_if_index INTEGER,
    a_port_name VARCHAR(128),
    a_sys_name VARCHAR(255),
    a_mgmt_ip VARCHAR(64),
    b_switch_id INTEGER REFERENCES switches(id) ON DELETE CASCADE,
    b_if_index INTEGER,
    b_port_name VARCHAR(128),
    b_sys_name VARCHAR(255),
    b_mgmt_ip VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'unresolved',
    confidence INTEGER NOT NULL DEFAULT 0,
    evidence VARCHAR(32),
    is_lag BOOLEAN NOT NULL DEFAULT FALSE,
    conflict_reason TEXT,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_topology_links_a ON topology_links(a_switch_id);
CREATE INDEX IF NOT EXISTS idx_topology_links_b ON topology_links(b_switch_id);
CREATE INDEX IF NOT EXISTS idx_topology_links_status ON topology_links(status);

-- 7) 未纳管节点（多次出现合并为同一节点）
CREATE TABLE IF NOT EXISTS topology_unknown_nodes (
    id SERIAL PRIMARY KEY,
    node_key VARCHAR(512) NOT NULL UNIQUE,
    display_name VARCHAR(255),
    mgmt_ip VARCHAR(64),
    chassis_id VARCHAR(255),
    sys_name VARCHAR(255),
    vendor_hint VARCHAR(100),
    seen_count INTEGER NOT NULL DEFAULT 1,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
