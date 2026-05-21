-- Migration: Add BMC Cold Reset Support
-- Version: 017
-- Date: 2026-05-15
-- Description: Creates bmc_servers and bmc_reset_history tables for IPMI-based
--              BMC cold reset functionality, along with supporting system settings
--              for global credentials and scheduling.

-- Create bmc_servers table
CREATE TABLE IF NOT EXISTS bmc_servers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    host VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    password_encrypted TEXT,
    use_global_credentials BOOLEAN DEFAULT TRUE NOT NULL,
    enabled BOOLEAN DEFAULT TRUE NOT NULL,
    notes TEXT,
    last_reset_at TIMESTAMP WITH TIME ZONE,
    last_reset_result VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bmc_servers_enabled ON bmc_servers(enabled);
CREATE INDEX IF NOT EXISTS idx_bmc_servers_host ON bmc_servers(host);

-- Use the existing trigger if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
        CREATE TRIGGER update_bmc_servers_updated_at
            BEFORE UPDATE ON bmc_servers
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- Create bmc_reset_history table
CREATE TABLE IF NOT EXISTS bmc_reset_history (
    id SERIAL PRIMARY KEY,
    bmc_server_id INTEGER NOT NULL REFERENCES bmc_servers(id) ON DELETE CASCADE,
    server_name VARCHAR(200) NOT NULL,
    server_host VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_category VARCHAR(50),
    error_message TEXT,
    attempts_made INTEGER DEFAULT 1,
    duration_ms INTEGER,
    ipmi_command TEXT,
    triggered_by VARCHAR(50) DEFAULT 'manual',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bmc_history_server ON bmc_reset_history(bmc_server_id);
CREATE INDEX IF NOT EXISTS idx_bmc_history_status ON bmc_reset_history(status);
CREATE INDEX IF NOT EXISTS idx_bmc_history_created ON bmc_reset_history(created_at);
CREATE INDEX IF NOT EXISTS idx_bmc_history_category ON bmc_reset_history(error_category);

-- Insert BMC system settings for global IPMI credentials and schedule config
INSERT INTO system_settings (key, value, data_type, description, is_configurable, is_sensitive)
VALUES
    ('bmc_global_username', '', 'string', 'Default IPMI username for BMC cold reset', true, false),
    ('bmc_global_password', '', 'string', 'Default IPMI password for BMC cold reset (encrypted)', true, true),
    ('bmc_monthly_reset_enabled', 'false', 'boolean', 'Enable monthly automatic BMC cold reset', true, false),
    ('bmc_monthly_reset_day', '1', 'integer', 'Day of month for automatic BMC cold reset (1-28)', true, false),
    ('bmc_monthly_reset_hour', '2', 'integer', 'Hour of day for automatic BMC cold reset (0-23)', true, false),
    ('bmc_reset_timeout_seconds', '30', 'integer', 'Timeout in seconds for each ipmitool invocation', true, false)
ON CONFLICT (key) DO NOTHING;
