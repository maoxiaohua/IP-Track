-- Migration: Add manual lookup policy overrides to port_analysis
-- Version: 011
-- Date: 2026-03-31
-- Description: Allows operators to manually include/exclude ports from IP lookup matching

ALTER TABLE IF EXISTS port_analysis
    ADD COLUMN IF NOT EXISTS lookup_policy_override VARCHAR(20);

ALTER TABLE IF EXISTS port_analysis
    ADD COLUMN IF NOT EXISTS lookup_policy_note TEXT;

ALTER TABLE IF EXISTS port_analysis
    ADD COLUMN IF NOT EXISTS lookup_policy_updated_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_port_analysis_lookup_policy_override
    ON port_analysis(lookup_policy_override);
