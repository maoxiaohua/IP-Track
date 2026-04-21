-- Migration: Add switch_name column to query_history table
-- Date: 2026-04-13
-- Description: Add denormalized switch_name field to query_history for better display in Recent Queries

-- Add switch_name column
ALTER TABLE query_history
ADD COLUMN IF NOT EXISTS switch_name VARCHAR(255);

-- Create index on switch_name for faster filtering
CREATE INDEX IF NOT EXISTS idx_query_history_switch_name ON query_history(switch_name);

-- Update existing records with switch names from switches table
UPDATE query_history qh
SET switch_name = s.name
FROM switches s
WHERE qh.switch_id = s.id
  AND qh.switch_name IS NULL;

-- Add comment
COMMENT ON COLUMN query_history.switch_name IS 'Denormalized switch name for display purposes';
