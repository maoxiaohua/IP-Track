-- Create optical_modules table to store SFP/QSFP transceiver information
CREATE TABLE IF NOT EXISTS optical_modules (
    id SERIAL PRIMARY KEY,
    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    port_name VARCHAR(50) NOT NULL,
    module_type VARCHAR(20),  -- SFP, SFP+, QSFP, QSFP+, QSFP28, etc.
    model VARCHAR(100),
    serial_number VARCHAR(100),
    vendor VARCHAR(100),
    speed_gbps INTEGER,  -- Speed in Gbps (1, 10, 40, 100, etc.)

    collected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT optical_modules_switch_port UNIQUE (switch_id, port_name)
);

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_optical_modules_switch ON optical_modules(switch_id);
CREATE INDEX IF NOT EXISTS idx_optical_modules_port ON optical_modules(port_name);
CREATE INDEX IF NOT EXISTS idx_optical_modules_collected ON optical_modules(collected_at);
CREATE INDEX IF NOT EXISTS idx_optical_modules_serial ON optical_modules(serial_number);
CREATE INDEX IF NOT EXISTS idx_optical_modules_vendor ON optical_modules(vendor);

-- Add comments
COMMENT ON TABLE optical_modules IS 'Optical transceiver (SFP/QSFP) information collected from switches via SNMP';
COMMENT ON COLUMN optical_modules.module_type IS 'Type of optical module: SFP, SFP+, QSFP, QSFP+, QSFP28';
COMMENT ON COLUMN optical_modules.speed_gbps IS 'Port speed in Gbps';
