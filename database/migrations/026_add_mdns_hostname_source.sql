-- Migration 026: Add MDNS to hostname_source CHECK constraint
-- Adds support for mDNS-based hostname discovery (Linux/Mac hosts via UDP 5353)

DO $$
BEGIN
    -- Only add if the constraint still exists (it might have been dropped in a future migration)
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'ip_addresses'::regclass
          AND conname = 'ip_addresses_hostname_source_check'
    ) THEN
        ALTER TABLE ip_addresses
        DROP CONSTRAINT ip_addresses_hostname_source_check;

        ALTER TABLE ip_addresses
        ADD CONSTRAINT ip_addresses_hostname_source_check
        CHECK (
            hostname_source IS NULL
            OR hostname_source::text IN (
                'SNMP', 'DNS', 'NETBIOS', 'MDNS', 'ARP', 'SWITCH', 'MANUAL'
            )
        );
    END IF;
END;
$$;
