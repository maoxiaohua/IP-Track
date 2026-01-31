-- IP Track System Database Initialization Script
-- PostgreSQL 16+

-- Create tables for IP tracking system

-- Switches table
CREATE TABLE IF NOT EXISTS switches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    ip_address INET NOT NULL UNIQUE,
    vendor VARCHAR(50) NOT NULL CHECK (vendor IN ('cisco', 'dell', 'alcatel')),
    model VARCHAR(100),
    role VARCHAR(20) DEFAULT 'access' NOT NULL CHECK (role IN ('core', 'aggregation', 'access')),
    priority INTEGER DEFAULT 50 NOT NULL CHECK (priority >= 1 AND priority <= 100),
    ssh_port INTEGER DEFAULT 22 NOT NULL CHECK (ssh_port > 0 AND ssh_port <= 65535),
    username VARCHAR(100) NOT NULL,
    password_encrypted TEXT NOT NULL,
    enable_password_encrypted TEXT,
    enabled BOOLEAN DEFAULT true NOT NULL,
    connection_timeout INTEGER DEFAULT 30 NOT NULL CHECK (connection_timeout >= 5 AND connection_timeout <= 300),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create indexes for switches
CREATE INDEX IF NOT EXISTS idx_switches_ip ON switches(ip_address);
CREATE INDEX IF NOT EXISTS idx_switches_enabled ON switches(enabled);
CREATE INDEX IF NOT EXISTS idx_switches_priority ON switches(priority);
CREATE INDEX IF NOT EXISTS idx_switches_role ON switches(role);

-- Query history table
CREATE TABLE IF NOT EXISTS query_history (
    id SERIAL PRIMARY KEY,
    target_ip INET NOT NULL,
    found_mac MACADDR,
    switch_id INTEGER REFERENCES switches(id) ON DELETE SET NULL,
    port_name VARCHAR(50),
    vlan_id INTEGER,
    query_status VARCHAR(20) NOT NULL CHECK (query_status IN ('success', 'not_found', 'error')),
    error_message TEXT,
    query_time_ms INTEGER,
    queried_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create indexes for query_history
CREATE INDEX IF NOT EXISTS idx_query_history_target_ip ON query_history(target_ip);
CREATE INDEX IF NOT EXISTS idx_query_history_queried_at ON query_history(queried_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_history_mac ON query_history(found_mac);
CREATE INDEX IF NOT EXISTS idx_query_history_status ON query_history(query_status);

-- MAC address cache table
CREATE TABLE IF NOT EXISTS mac_address_cache (
    id SERIAL PRIMARY KEY,
    mac_address MACADDR NOT NULL,
    ip_address INET,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    port_name VARCHAR(50) NOT NULL,
    vlan_id INTEGER,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    CONSTRAINT uq_mac_switch_port UNIQUE (mac_address, switch_id, port_name)
);

-- Create indexes for mac_address_cache
CREATE INDEX IF NOT EXISTS idx_mac_cache_mac ON mac_address_cache(mac_address);
CREATE INDEX IF NOT EXISTS idx_mac_cache_ip ON mac_address_cache(ip_address);
CREATE INDEX IF NOT EXISTS idx_mac_cache_last_seen ON mac_address_cache(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_mac_cache_switch ON mac_address_cache(switch_id);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for switches table
DROP TRIGGER IF EXISTS update_switches_updated_at ON switches;
CREATE TRIGGER update_switches_updated_at
    BEFORE UPDATE ON switches
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert sample data (optional - comment out for production)
-- INSERT INTO switches (name, ip_address, vendor, model, username, password_encrypted, enabled)
-- VALUES
--     ('Core-Switch-01', '192.168.1.1', 'cisco', 'Catalyst 3850', 'admin', 'encrypted_password_here', true),
--     ('Access-Switch-02', '192.168.1.2', 'dell', 'N3048', 'admin', 'encrypted_password_here', true);

-- Grant permissions (adjust as needed for your setup)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO iptrack;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO iptrack;
