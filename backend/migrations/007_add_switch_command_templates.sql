-- Create switch_command_templates table
CREATE TABLE IF NOT EXISTS switch_command_templates (
    id SERIAL PRIMARY KEY,
    vendor VARCHAR(50) NOT NULL,
    model_pattern VARCHAR(100) NOT NULL,
    name_pattern VARCHAR(100),
    device_type VARCHAR(50) NOT NULL,
    arp_command TEXT,
    arp_parser_type VARCHAR(50),
    arp_enabled BOOLEAN DEFAULT TRUE,
    mac_command TEXT,
    mac_parser_type VARCHAR(50),
    mac_enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 100,
    description TEXT,
    is_builtin BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_switch_cmd_templates_vendor ON switch_command_templates(vendor);

-- Insert built-in templates
INSERT INTO switch_command_templates
(vendor, model_pattern, name_pattern, device_type, arp_command, arp_parser_type, arp_enabled, mac_command, mac_parser_type, mac_enabled, priority, description, is_builtin, enabled)
VALUES
-- Nokia 7220
('alcatel', '7220', NULL, 'nokia_srl', 'show arpnd arp-entries', 'nokia_7220', TRUE, 'show network-instance bridge-table mac-table all', 'nokia_7220', TRUE, 200, 'Nokia/Alcatel 7220 SR Linux switches', TRUE, TRUE),

-- Dell OS10
('dell', 'os10', NULL, 'dell_os10', NULL, NULL, FALSE, 'show mac-address-table', 'dell_os10', TRUE, 150, 'Dell OS10 switches (MAC only, ARP via SNMP)', TRUE, TRUE),

-- Cisco IOS
('cisco', 'ios', NULL, 'cisco_ios', NULL, NULL, FALSE, 'show mac address-table', 'cisco_ios', TRUE, 150, 'Cisco IOS switches (MAC only, ARP via SNMP)', TRUE, TRUE);

COMMENT ON TABLE switch_command_templates IS 'Command templates for collecting ARP and MAC tables from different switch vendors/models';
