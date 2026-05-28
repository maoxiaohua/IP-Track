-- Migration: Create missing core tables
-- Date: 2026-05-27
-- Description: Creates 5 tables that were defined in SQLAlchemy models
--   but had no CREATE TABLE in any SQL script:
--   port_analysis, arp_table, ip_location, mac_table, switch_successful_commands

-- ============================================
-- 1. Port Analysis Results
-- ============================================
CREATE TABLE IF NOT EXISTS port_analysis (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    port_name VARCHAR(50) NOT NULL,

    -- Analysis results
    mac_count INTEGER DEFAULT 0 NOT NULL,
    unique_vlans INTEGER DEFAULT 0 NOT NULL,
    port_type VARCHAR(20) NOT NULL,
    confidence_score FLOAT DEFAULT 0.0 NOT NULL,

    -- Port naming hints
    is_trunk_by_name INTEGER DEFAULT 0 NOT NULL,
    is_access_by_name INTEGER DEFAULT 0 NOT NULL,

    -- Manual lookup policy overrides
    lookup_policy_override VARCHAR(20),
    lookup_policy_note TEXT,
    lookup_policy_updated_at TIMESTAMP WITH TIME ZONE,

    -- Timestamps
    analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for port_analysis
CREATE UNIQUE INDEX IF NOT EXISTS idx_port_switch_port ON port_analysis(switch_id, port_name);
CREATE INDEX IF NOT EXISTS idx_port_type ON port_analysis(port_type);
CREATE INDEX IF NOT EXISTS idx_port_lookup_policy_override ON port_analysis(lookup_policy_override);

-- ============================================
-- 2. ARP Table Records
-- ============================================
CREATE TABLE IF NOT EXISTS arp_table (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    ip_address INET NOT NULL,
    mac_address MACADDR NOT NULL,
    vlan_id INTEGER,
    interface VARCHAR(50),
    age_seconds INTEGER,

    -- Timestamps
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for arp_table
CREATE INDEX IF NOT EXISTS idx_arp_ip_mac ON arp_table(ip_address, mac_address);
CREATE INDEX IF NOT EXISTS idx_arp_switch_ip ON arp_table(switch_id, ip_address);
CREATE INDEX IF NOT EXISTS idx_arp_collected ON arp_table(collected_at);

-- ============================================
-- 3. IP Location Mappings
-- ============================================
CREATE TABLE IF NOT EXISTS ip_location (
    id SERIAL PRIMARY KEY,
    ip_address INET NOT NULL,
    mac_address MACADDR NOT NULL,

    -- Location information
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    port_name VARCHAR(50) NOT NULL,
    vlan_id INTEGER,

    -- Analysis metadata
    confidence_score FLOAT DEFAULT 0.0 NOT NULL,
    detection_method VARCHAR(50) NOT NULL,
    port_mac_count INTEGER,
    appears_on_switches INTEGER DEFAULT 1 NOT NULL,

    -- Timestamps
    first_detected TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_confirmed TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_arp_seen TIMESTAMP WITH TIME ZONE,
    last_mac_seen TIMESTAMP WITH TIME ZONE
);

-- Indexes for ip_location
CREATE UNIQUE INDEX IF NOT EXISTS idx_ip_location_ip ON ip_location(ip_address);
CREATE INDEX IF NOT EXISTS idx_location_switch_port ON ip_location(switch_id, port_name);
CREATE INDEX IF NOT EXISTS idx_location_mac ON ip_location(mac_address);
CREATE INDEX IF NOT EXISTS idx_location_confidence ON ip_location(confidence_score);

-- ============================================
-- 4. MAC Address Table
-- ============================================
CREATE TABLE IF NOT EXISTS mac_table (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    mac_address MACADDR NOT NULL,
    port_name VARCHAR(50) NOT NULL,
    vlan_id INTEGER,
    is_dynamic INTEGER DEFAULT 1 NOT NULL,

    -- Timestamps
    collected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for mac_table
CREATE INDEX IF NOT EXISTS idx_mac_switch_port ON mac_table(switch_id, port_name);
CREATE INDEX IF NOT EXISTS idx_mac_address_switch ON mac_table(mac_address, switch_id);
CREATE INDEX IF NOT EXISTS idx_mac_collected ON mac_table(collected_at);

-- ============================================
-- 5. Switch Successful Command Cache
-- ============================================
CREATE TABLE IF NOT EXISTS switch_successful_commands (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    command_type VARCHAR(20) NOT NULL,
    successful_command TEXT NOT NULL,
    parser_type VARCHAR(50),
    success_count INTEGER DEFAULT 1,
    last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cmd_switch_type ON switch_successful_commands(switch_id, command_type);
