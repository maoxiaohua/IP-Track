-- Migration: Update switches table fields
-- Date: 2026-02-15
-- Description: Remove role/priority fields, add CLI and collection tracking fields

-- Add new fields for CLI authentication and data collection
ALTER TABLE switches
    ADD COLUMN IF NOT EXISTS cli_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS auto_collect_arp BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS auto_collect_mac BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_arp_collection_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_mac_collection_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_collection_status VARCHAR(50),
    ADD COLUMN IF NOT EXISTS last_collection_message TEXT;

-- Remove role and priority fields (drop indexes first)
DROP INDEX IF EXISTS ix_switches_priority;
ALTER TABLE switches
    DROP COLUMN IF EXISTS role CASCADE,
    DROP COLUMN IF EXISTS priority CASCADE;

-- Update existing switches to enable CLI if they have SSH credentials
UPDATE switches
SET cli_enabled = TRUE
WHERE username IS NOT NULL AND password_encrypted IS NOT NULL;

COMMENT ON COLUMN switches.cli_enabled IS 'Enable CLI/SSH authentication for this switch';
COMMENT ON COLUMN switches.auto_collect_arp IS 'Automatically collect ARP table from this switch';
COMMENT ON COLUMN switches.auto_collect_mac IS 'Automatically collect MAC table from this switch';
COMMENT ON COLUMN switches.last_arp_collection_at IS 'Timestamp of last ARP table collection';
COMMENT ON COLUMN switches.last_mac_collection_at IS 'Timestamp of last MAC table collection';
COMMENT ON COLUMN switches.last_collection_status IS 'Status of last collection: success, failed, partial';
COMMENT ON COLUMN switches.last_collection_message IS 'Detailed message from last collection attempt';
