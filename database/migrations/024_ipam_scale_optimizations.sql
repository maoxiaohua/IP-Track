-- Migration 024: IPAM Scale Optimizations for 1000+ subnets
-- Adds BRIN index, partial change index, and autovacuum tuning for ip_scan_history

-- BRIN index for efficient time-range queries on scanned_at
-- BRIN is ideal for append-only time-series data: stores min/max per block range,
-- occupying only kilobytes even for millions of rows.
CREATE INDEX IF NOT EXISTS idx_ip_scan_history_scanned_at_brin
    ON ip_scan_history USING BRIN (scanned_at)
    WITH (pages_per_range = 32);

-- Partial index for changed-only queries (used by IP_SCAN_HISTORY_RECORD_ALL=false mode)
-- Covers only rows where at least one change flag is true, enabling efficient
-- change-detection queries without scanning the full table.
CREATE INDEX IF NOT EXISTS idx_ip_scan_history_changed
    ON ip_scan_history (scanned_at)
    WHERE (status_changed OR hostname_changed OR os_changed OR mac_changed OR switch_changed OR port_changed);

-- Autovacuum tuning for high-write tables
-- ip_scan_history: trigger autovacuum at 5% dead rows (down from default 20%)
-- with higher I/O budget to keep up with concurrent scan write rates
ALTER TABLE ip_scan_history SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_cost_limit = 1000
);

-- ip_addresses: trigger autovacuum at 2% dead rows (254K rows at 1000 subnets)
-- to prevent dead tuple accumulation from last_scan_at/scan_count updates
ALTER TABLE ip_addresses SET (
    autovacuum_vacuum_scale_factor = 0.02
);
