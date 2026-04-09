-- Migration: Add System Settings table for dynamic configuration
-- Version: 010
-- Date: 2026-03-27
-- Description: Creates system_settings table for database-backed configuration

-- Create system_settings table
CREATE TABLE IF NOT EXISTS system_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) NOT NULL UNIQUE,
    value TEXT NOT NULL,
    data_type VARCHAR(20) NOT NULL DEFAULT 'string'
        CHECK (data_type IN ('string', 'integer', 'float', 'boolean', 'json')),
    description TEXT,
    is_configurable BOOLEAN DEFAULT true NOT NULL,
    is_sensitive BOOLEAN DEFAULT false NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Create index for key lookups
CREATE INDEX IF NOT EXISTS idx_system_settings_key ON system_settings(key);
CREATE INDEX IF NOT EXISTS idx_system_settings_configurable ON system_settings(is_configurable);

-- Create trigger for updated_at column (use existing function)
DROP TRIGGER IF EXISTS update_system_settings_updated_at ON system_settings;
CREATE TRIGGER update_system_settings_updated_at
    BEFORE UPDATE ON system_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert initial IP Lookup settings
INSERT INTO system_settings (key, value, data_type, description, is_configurable, is_sensitive)
VALUES
    ('ip_lookup_cache_hours', '24', 'integer',
     'IP Lookup cache mode query window in hours (1-168)', true, false),
    ('ip_lookup_cache_hours_min', '1', 'integer',
     'Minimum allowed cache hours (constraint)', false, false),
    ('ip_lookup_cache_hours_max', '168', 'integer',
     'Maximum allowed cache hours - 7 days (constraint)', false, false)
ON CONFLICT (key) DO NOTHING;
