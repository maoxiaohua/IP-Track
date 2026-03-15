-- Migration: Collection System Redesign
-- Adds capability detection, job queue, and performance tracking

BEGIN;

-- Create ENUM types for collection jobs
CREATE TYPE job_type_enum AS ENUM ('mac', 'arp', 'optical', 'all');
CREATE TYPE job_status_enum AS ENUM ('pending', 'running', 'success', 'failed', 'timeout', 'cancelled');

-- Add collection method preferences to switches table
ALTER TABLE switches ADD COLUMN IF NOT EXISTS mac_collection_method VARCHAR(10) DEFAULT 'auto';
ALTER TABLE switches ADD COLUMN IF NOT EXISTS arp_collection_method VARCHAR(10) DEFAULT 'auto';
ALTER TABLE switches ADD COLUMN IF NOT EXISTS optical_collection_method VARCHAR(10) DEFAULT 'auto';

ALTER TABLE switches ADD COLUMN IF NOT EXISTS mac_method_override BOOLEAN DEFAULT FALSE;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS arp_method_override BOOLEAN DEFAULT FALSE;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS optical_method_override BOOLEAN DEFAULT FALSE;

ALTER TABLE switches ADD COLUMN IF NOT EXISTS mac_collection_success_count INTEGER DEFAULT 0;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS arp_collection_success_count INTEGER DEFAULT 0;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS optical_collection_success_count INTEGER DEFAULT 0;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS mac_collection_fail_count INTEGER DEFAULT 0;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS arp_collection_fail_count INTEGER DEFAULT 0;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS optical_collection_fail_count INTEGER DEFAULT 0;

-- Create collection_jobs table
CREATE TABLE IF NOT EXISTS collection_jobs (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    job_type job_type_enum NOT NULL,
    status job_status_enum NOT NULL DEFAULT 'pending',
    worker_id VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds FLOAT,
    collection_method VARCHAR(10),  -- 'snmp' or 'cli'
    entries_collected INTEGER DEFAULT 0,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    snmp_duration_seconds FLOAT,
    cli_duration_seconds FLOAT,
    batch_id VARCHAR(50),
    priority INTEGER DEFAULT 0
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_jobs_switch ON collection_jobs(switch_id);
CREATE INDEX IF NOT EXISTS idx_jobs_type ON collection_jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON collection_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON collection_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_switch_type ON collection_jobs(switch_id, job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_batch ON collection_jobs(batch_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON collection_jobs(created_at);

-- Partial index for pending jobs (most frequently queried)
CREATE INDEX IF NOT EXISTS idx_jobs_pending ON collection_jobs(status, priority DESC, created_at ASC)
WHERE status = 'pending';

-- Add comments
COMMENT ON TABLE collection_jobs IS 'Persistent job queue for MAC/ARP/Optical module collection';
COMMENT ON COLUMN switches.mac_collection_method IS 'Preferred collection method: snmp, cli, auto, manual';
COMMENT ON COLUMN switches.mac_method_override IS 'True if admin manually set collection method';

COMMIT;
