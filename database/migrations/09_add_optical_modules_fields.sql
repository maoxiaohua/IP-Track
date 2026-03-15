-- Add missing fields to optical_modules table for search functionality

-- Add switch_name for easier querying without joins
ALTER TABLE optical_modules
ADD COLUMN IF NOT EXISTS switch_name VARCHAR(255);

-- Add switch_ip for easier querying without joins
ALTER TABLE optical_modules
ADD COLUMN IF NOT EXISTS switch_ip INET;

-- Add part_number as requested
ALTER TABLE optical_modules
ADD COLUMN IF NOT EXISTS part_number VARCHAR(100);

-- Create indexes for search functionality
CREATE INDEX IF NOT EXISTS idx_optical_modules_switch_name ON optical_modules(switch_name);
CREATE INDEX IF NOT EXISTS idx_optical_modules_switch_ip ON optical_modules(switch_ip);
CREATE INDEX IF NOT EXISTS idx_optical_modules_model ON optical_modules(model);

-- Add comments
COMMENT ON COLUMN optical_modules.switch_name IS 'Switch name (denormalized for search performance)';
COMMENT ON COLUMN optical_modules.switch_ip IS 'Switch IP address (denormalized for search performance)';
COMMENT ON COLUMN optical_modules.part_number IS 'Manufacturer part number';
