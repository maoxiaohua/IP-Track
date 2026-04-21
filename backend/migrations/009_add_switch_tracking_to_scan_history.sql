-- Migration: Add switch tracking to IP scan history
-- Date: 2026-04-14
-- Description: Add switch_id, switch_port, and change tracking for network location history

-- Add switch tracking columns
ALTER TABLE ip_scan_history
ADD COLUMN IF NOT EXISTS switch_id INTEGER,
ADD COLUMN IF NOT EXISTS switch_port VARCHAR(50),
ADD COLUMN IF NOT EXISTS vlan_id INTEGER;

-- Add change detection columns
ALTER TABLE ip_scan_history
ADD COLUMN IF NOT EXISTS mac_changed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS switch_changed BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS port_changed BOOLEAN DEFAULT FALSE;

-- Add foreign key constraint
ALTER TABLE ip_scan_history
ADD CONSTRAINT fk_ip_scan_history_switch
FOREIGN KEY (switch_id) REFERENCES switches(id) ON DELETE SET NULL;

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_ip_scan_history_switch_id ON ip_scan_history(switch_id);
CREATE INDEX IF NOT EXISTS idx_ip_scan_history_mac_changed ON ip_scan_history(mac_changed) WHERE mac_changed = TRUE;
CREATE INDEX IF NOT EXISTS idx_ip_scan_history_switch_changed ON ip_scan_history(switch_changed) WHERE switch_changed = TRUE;

-- Add comments
COMMENT ON COLUMN ip_scan_history.switch_id IS 'Switch where the IP was found (for tracking moves)';
COMMENT ON COLUMN ip_scan_history.switch_port IS 'Port where the IP was found (for tracking moves)';
COMMENT ON COLUMN ip_scan_history.mac_changed IS 'Whether MAC address changed since last scan';
COMMENT ON COLUMN ip_scan_history.switch_changed IS 'Whether switch changed since last scan (device moved)';
COMMENT ON COLUMN ip_scan_history.port_changed IS 'Whether port changed since last scan (device moved)';
