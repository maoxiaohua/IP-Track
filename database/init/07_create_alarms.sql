-- Migration: Create alarms table for unified alert system
-- Date: 2026-02-20
-- Description: Centralized alarm/alert system for tracking failures across all modules

-- Create ENUM types for alarm fields
DO $$ BEGIN
    CREATE TYPE alarm_severity AS ENUM ('critical', 'error', 'warning', 'info');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE alarm_status AS ENUM ('active', 'acknowledged', 'resolved', 'auto_resolved');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE alarm_source_type AS ENUM ('collection', 'switch', 'batch', 'system');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Create alarms table
CREATE TABLE IF NOT EXISTS alarms (
    id SERIAL PRIMARY KEY,

    -- Severity and status
    severity alarm_severity NOT NULL,
    status alarm_status NOT NULL DEFAULT 'active',

    -- Core information
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,

    -- Source tracking
    source_type alarm_source_type NOT NULL,
    source_id INTEGER,
    source_name VARCHAR(200),

    -- De-duplication
    fingerprint VARCHAR(64) NOT NULL,

    -- Occurrence tracking
    occurrence_count INTEGER NOT NULL DEFAULT 1,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_occurrence_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    acknowledged_by VARCHAR(100),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(100)
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_alarms_severity ON alarms(severity);
CREATE INDEX IF NOT EXISTS idx_alarms_status ON alarms(status);
CREATE INDEX IF NOT EXISTS idx_alarms_source_type ON alarms(source_type);
CREATE INDEX IF NOT EXISTS idx_alarms_fingerprint ON alarms(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alarms_created_at ON alarms(created_at);

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_alarms_fingerprint_status ON alarms(fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_alarms_severity_status ON alarms(severity, status);
CREATE INDEX IF NOT EXISTS idx_alarms_source ON alarms(source_type, source_id);

-- Add comments for documentation
COMMENT ON TABLE alarms IS 'Centralized alarm/alert system for tracking failures across all modules';
COMMENT ON COLUMN alarms.severity IS 'Severity level: critical (red), error (orange), warning (yellow), info (blue)';
COMMENT ON COLUMN alarms.status IS 'Current status: active, acknowledged, resolved, auto_resolved';
COMMENT ON COLUMN alarms.title IS 'Short description of the alarm (max 200 chars)';
COMMENT ON COLUMN alarms.message IS 'Detailed error message';
COMMENT ON COLUMN alarms.details IS 'Structured error details in JSON format';
COMMENT ON COLUMN alarms.source_type IS 'Type of source: collection, switch, batch, system';
COMMENT ON COLUMN alarms.source_id IS 'ID of the source object (switch ID, batch ID, etc.)';
COMMENT ON COLUMN alarms.source_name IS 'Cached name of source for display';
COMMENT ON COLUMN alarms.fingerprint IS 'MD5 hash for de-duplication (source_type + source_id + title + severity)';
COMMENT ON COLUMN alarms.occurrence_count IS 'Number of times this alarm has occurred';
COMMENT ON COLUMN alarms.created_at IS 'Timestamp when alarm was first created';
COMMENT ON COLUMN alarms.last_occurrence_at IS 'Timestamp of most recent occurrence';
COMMENT ON COLUMN alarms.acknowledged_at IS 'Timestamp when alarm was acknowledged';
COMMENT ON COLUMN alarms.acknowledged_by IS 'User who acknowledged the alarm';
COMMENT ON COLUMN alarms.resolved_at IS 'Timestamp when alarm was resolved';
COMMENT ON COLUMN alarms.resolved_by IS 'User who resolved the alarm (or "system" for auto-resolution)';
