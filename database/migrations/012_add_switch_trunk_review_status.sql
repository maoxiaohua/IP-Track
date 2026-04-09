-- Migration: Add switch-level manual trunk review status
-- Description: Lets operators mark each switch after manually confirming true trunk ports.

ALTER TABLE switches
    ADD COLUMN IF NOT EXISTS trunk_review_completed BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE switches
    ADD COLUMN IF NOT EXISTS trunk_review_completed_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE switches
    ADD COLUMN IF NOT EXISTS trunk_review_note TEXT;

CREATE INDEX IF NOT EXISTS idx_switches_trunk_review_completed
    ON switches(trunk_review_completed);
