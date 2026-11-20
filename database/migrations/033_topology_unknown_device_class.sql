-- 未纳管节点的设备类别：switch / router / wlan-ap / phone / host / unknown
-- 来自 LLDP capability 位与系统描述的启发式判断，仅用于拓扑图过滤，不影响建链。
ALTER TABLE topology_unknown_nodes
    ADD COLUMN IF NOT EXISTS device_class VARCHAR(20);
