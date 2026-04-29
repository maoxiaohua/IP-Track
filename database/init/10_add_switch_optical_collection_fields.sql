-- Add switch-level optical collection tracking fields so optical inventory can
-- preserve historical rows and still expose current vs historical state.

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS last_optical_collection_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS last_optical_success_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS last_optical_collection_status VARCHAR(50);

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS last_optical_collection_message TEXT;

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS last_optical_modules_count INTEGER;

CREATE INDEX IF NOT EXISTS idx_switches_last_optical_collection_at
ON switches(last_optical_collection_at);

CREATE INDEX IF NOT EXISTS idx_switches_last_optical_success_at
ON switches(last_optical_success_at);

WITH optical_agg AS (
    SELECT
        switch_id,
        MAX(last_seen) AS last_seen_at,
        COUNT(*) AS module_count
    FROM optical_modules
    GROUP BY switch_id
)
UPDATE switches s
SET
    last_optical_collection_at = COALESCE(s.last_optical_collection_at, optical_agg.last_seen_at),
    last_optical_success_at = COALESCE(s.last_optical_success_at, optical_agg.last_seen_at),
    last_optical_collection_status = COALESCE(s.last_optical_collection_status, 'success'),
    last_optical_collection_message = COALESCE(
        s.last_optical_collection_message,
        'Backfilled from existing optical inventory snapshot'
    ),
    last_optical_modules_count = COALESCE(s.last_optical_modules_count, optical_agg.module_count)
FROM optical_agg
WHERE s.id = optical_agg.switch_id;
