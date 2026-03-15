-- Migration script to add role and priority fields to switches table
-- Run this if you already have an existing database

-- Add role column
ALTER TABLE switches ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'access' NOT NULL;
ALTER TABLE switches ADD CONSTRAINT check_role CHECK (role IN ('core', 'aggregation', 'access'));

-- Add priority column
ALTER TABLE switches ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 50 NOT NULL;
ALTER TABLE switches ADD CONSTRAINT check_priority CHECK (priority >= 1 AND priority <= 100);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_switches_priority ON switches(priority);
CREATE INDEX IF NOT EXISTS idx_switches_role ON switches(role);

COMMIT;
