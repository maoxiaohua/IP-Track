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

-- Update existing switches based on vendor/model (optional, adjust as needed)
-- Core switches typically have higher-end models
UPDATE switches SET role = 'core', priority = 10
WHERE model LIKE '%Catalyst 6%' OR model LIKE '%Nexus%' OR model LIKE '%Core%';

-- Aggregation switches
UPDATE switches SET role = 'aggregation', priority = 30
WHERE model LIKE '%Catalyst 4%' OR model LIKE '%Catalyst 3850%' OR model LIKE '%Aggregation%';

-- Access switches (default)
UPDATE switches SET role = 'access', priority = 50
WHERE role = 'access';

COMMIT;
