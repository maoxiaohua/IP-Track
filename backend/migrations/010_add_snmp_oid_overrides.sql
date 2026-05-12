-- 010: Vendor-specific SNMP OID overrides for ARP/MAC table collection
-- Follows same pattern as switch_command_templates

CREATE TABLE IF NOT EXISTS snmp_oid_overrides (
    id SERIAL PRIMARY KEY,
    vendor VARCHAR(50) NOT NULL,
    model_pattern VARCHAR(100),
    oid_role VARCHAR(30) NOT NULL,
    oid_value VARCHAR(255) NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 100,
    enabled BOOLEAN DEFAULT TRUE NOT NULL,
    is_builtin BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_snmp_oid_overrides_vendor
    ON snmp_oid_overrides(vendor);

CREATE INDEX IF NOT EXISTS idx_snmp_oid_overrides_role
    ON snmp_oid_overrides(oid_role);

CREATE UNIQUE INDEX IF NOT EXISTS idx_snmp_oid_unique_override
    ON snmp_oid_overrides(vendor, COALESCE(model_pattern, ''), oid_role);

-- Seed: Nokia SR OS (TiMetra) OIDs for Alcatel/Nokia switches
-- Enterprise OID: 1.3.6.1.4.1.6527 (Nokia TiMetra)
-- These apply to all alcatel models (NULL model_pattern = match-all)

-- ARP table (tmnxVrtrIfArpTable)
INSERT INTO snmp_oid_overrides
(vendor, model_pattern, oid_role, oid_value, priority, description, is_builtin, enabled)
VALUES
('alcatel', NULL, 'arp_ip',  '1.3.6.1.4.1.6527.3.1.2.3.1.1.4', 100,
 'Nokia SR OS tmnxVrtrIfArpIPAddr', TRUE, TRUE),
('alcatel', NULL, 'arp_mac', '1.3.6.1.4.1.6527.3.1.2.3.1.1.5', 100,
 'Nokia SR OS tmnxVrtrIfArpMacAddr', TRUE, TRUE);

-- MAC FDB table (tmnxFdbTable)
INSERT INTO snmp_oid_overrides
(vendor, model_pattern, oid_role, oid_value, priority, description, is_builtin, enabled)
VALUES
('alcatel', NULL, 'mac_address', '1.3.6.1.4.1.6527.3.1.2.4.3.1.1', 100,
 'Nokia SR OS tmnxFdbMacAddress', TRUE, TRUE),
('alcatel', NULL, 'mac_port',    '1.3.6.1.4.1.6527.3.1.2.4.3.1.3', 100,
 'Nokia SR OS tmnxFdbPort', TRUE, TRUE),
('alcatel', NULL, 'mac_vlan',    '1.3.6.1.4.1.6527.3.1.2.4.3.1.4', 100,
 'Nokia SR OS tmnxFdbVlan', TRUE, TRUE);
