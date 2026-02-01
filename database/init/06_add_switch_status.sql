-- Migration: Add status fields to switches table
-- Date: 2026-02-01
-- Description: Add ping status tracking fields

-- Add new columns for ping status
ALTER TABLE switches
ADD COLUMN IF NOT EXISTS is_reachable BOOLEAN DEFAULT NULL,
ADD COLUMN IF NOT EXISTS last_check_at TIMESTAMP DEFAULT NULL,
ADD COLUMN IF NOT EXISTS response_time_ms FLOAT DEFAULT NULL;

-- Create index for faster status queries
CREATE INDEX IF NOT EXISTS idx_switches_is_reachable ON switches(is_reachable);
CREATE INDEX IF NOT EXISTS idx_switches_last_check_at ON switches(last_check_at);

-- Add comment
COMMENT ON COLUMN switches.is_reachable IS 'Whether the switch is reachable via ICMP ping';
COMMENT ON COLUMN switches.last_check_at IS 'Timestamp of last ping check';
COMMENT ON COLUMN switches.response_time_ms IS 'Ping response time in milliseconds';
