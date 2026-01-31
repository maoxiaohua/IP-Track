-- Migration script to add IPAM (IP Address Management) tables
-- Run this to add IPAM functionality to existing database

-- Create IP subnets table
CREATE TABLE IF NOT EXISTS ip_subnets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    network INET NOT NULL UNIQUE,
    description TEXT,
    vlan_id INTEGER CHECK (vlan_id >= 1 AND vlan_id <= 4094),
    gateway INET,
    dns_servers VARCHAR(200),
    enabled BOOLEAN DEFAULT true NOT NULL,
    auto_scan BOOLEAN DEFAULT true NOT NULL,
    scan_interval INTEGER DEFAULT 3600 NOT NULL CHECK (scan_interval >= 300 AND scan_interval <= 86400),
    last_scan_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create IP addresses table
CREATE TABLE IF NOT EXISTS ip_addresses (
    id SERIAL PRIMARY KEY,
    subnet_id INTEGER NOT NULL REFERENCES ip_subnets(id) ON DELETE CASCADE,
    ip_address INET NOT NULL UNIQUE,
    status VARCHAR(20) DEFAULT 'available' NOT NULL CHECK (status IN ('available', 'used', 'reserved', 'offline')),

    -- Basic information
    hostname VARCHAR(255),
    mac_address MACADDR,
    description TEXT,

    -- Network information
    is_reachable BOOLEAN DEFAULT false NOT NULL,
    response_time INTEGER,

    -- Operating system information
    os_type VARCHAR(50),
    os_name VARCHAR(100),
    os_version VARCHAR(100),
    os_vendor VARCHAR(100),

    -- Switch association
    switch_id INTEGER REFERENCES switches(id) ON DELETE SET NULL,
    switch_port VARCHAR(50),
    vlan_id INTEGER,

    -- Scan information
    last_seen_at TIMESTAMP WITH TIME ZONE,
    last_scan_at TIMESTAMP WITH TIME ZONE,
    scan_count INTEGER DEFAULT 0 NOT NULL,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create IP scan history table
CREATE TABLE IF NOT EXISTS ip_scan_history (
    id SERIAL PRIMARY KEY,
    ip_address_id INTEGER NOT NULL REFERENCES ip_addresses(id) ON DELETE CASCADE,

    -- Scan results
    is_reachable BOOLEAN NOT NULL,
    response_time INTEGER,
    hostname VARCHAR(255),
    mac_address MACADDR,
    os_type VARCHAR(50),
    os_name VARCHAR(100),

    -- Change detection
    status_changed BOOLEAN DEFAULT false NOT NULL,
    hostname_changed BOOLEAN DEFAULT false NOT NULL,
    os_changed BOOLEAN DEFAULT false NOT NULL,

    scanned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_ip_subnets_network ON ip_subnets(network);
CREATE INDEX IF NOT EXISTS idx_ip_subnets_enabled ON ip_subnets(enabled);

CREATE INDEX IF NOT EXISTS idx_ip_addresses_subnet ON ip_addresses(subnet_id);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_ip ON ip_addresses(ip_address);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_status ON ip_addresses(status);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_mac ON ip_addresses(mac_address);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_switch ON ip_addresses(switch_id);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_reachable ON ip_addresses(is_reachable);

CREATE INDEX IF NOT EXISTS idx_ip_scan_history_ip ON ip_scan_history(ip_address_id);
CREATE INDEX IF NOT EXISTS idx_ip_scan_history_scanned_at ON ip_scan_history(scanned_at);

-- Create trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_ip_subnets_updated_at BEFORE UPDATE ON ip_subnets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_ip_addresses_updated_at BEFORE UPDATE ON ip_addresses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;
