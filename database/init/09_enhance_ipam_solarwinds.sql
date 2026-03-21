-- Migration: Enhance IPAM for SolarWinds-style features
-- Adds hostname_source, DNS, SNMP, and enhanced tracking fields

-- Step 1: Create SNMP Profiles table
CREATE TABLE IF NOT EXISTS snmp_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    version VARCHAR(10) DEFAULT 'v3' NOT NULL CHECK (version IN ('v2c', 'v3')),

    -- SNMPv3 Authentication
    username VARCHAR(100),
    auth_protocol VARCHAR(20) CHECK (auth_protocol IN ('MD5', 'SHA', 'SHA-224', 'SHA-256', 'SHA-384', 'SHA-512')),
    auth_password_encrypted TEXT,

    -- SNMPv3 Privacy
    priv_protocol VARCHAR(20) CHECK (priv_protocol IN ('DES', 'AES', 'AES-192', 'AES-256')),
    priv_password_encrypted TEXT,

    -- SNMPv2c Community
    community_encrypted TEXT,

    -- Common settings
    port INTEGER DEFAULT 161 NOT NULL,
    timeout INTEGER DEFAULT 5 NOT NULL,
    retries INTEGER DEFAULT 3 NOT NULL,

    -- Metadata
    description TEXT,
    enabled BOOLEAN DEFAULT true NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Step 2: Add new columns to ip_subnets
ALTER TABLE ip_subnets
    ADD COLUMN IF NOT EXISTS snmp_profile_id INTEGER REFERENCES snmp_profiles(id) ON DELETE SET NULL;

-- Step 3: Add new columns to ip_addresses
ALTER TABLE ip_addresses
    ADD COLUMN IF NOT EXISTS hostname_source VARCHAR(20) CHECK (hostname_source IN ('DNS', 'SNMP', 'MANUAL', 'ARP')) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS dns_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS system_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS contact VARCHAR(255),
    ADD COLUMN IF NOT EXISTS location VARCHAR(255),
    ADD COLUMN IF NOT EXISTS machine_type VARCHAR(100),
    ADD COLUMN IF NOT EXISTS last_boot_time TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS vendor VARCHAR(100);

-- Step 4: Create indexes for new columns
CREATE INDEX IF NOT EXISTS idx_ip_addresses_hostname_source ON ip_addresses(hostname_source);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_dns_name ON ip_addresses(dns_name);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_system_name ON ip_addresses(system_name);
CREATE INDEX IF NOT EXISTS idx_ip_subnets_snmp_profile ON ip_subnets(snmp_profile_id);

-- Step 5: Update trigger for snmp_profiles
CREATE TRIGGER update_snmp_profiles_updated_at BEFORE UPDATE ON snmp_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Step 6: Add comments for documentation
COMMENT ON TABLE snmp_profiles IS 'SNMP profiles for device identification and monitoring';
COMMENT ON COLUMN ip_addresses.hostname_source IS 'Source of hostname: DNS (reverse lookup), SNMP (sysName), MANUAL (user input), ARP (from switch)';
COMMENT ON COLUMN ip_addresses.dns_name IS 'DNS reverse lookup result (PTR record)';
COMMENT ON COLUMN ip_addresses.system_name IS 'SNMP sysName (OID 1.3.6.1.2.1.1.5.0)';
COMMENT ON COLUMN ip_addresses.last_seen_at IS 'Last successful ping/response timestamp (used for "Last Response" calculation)';

COMMIT;
