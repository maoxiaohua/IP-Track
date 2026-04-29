-- Expand IPAM hostname_source allowed values to support new discovery sources.
-- Required for NetBIOS-based Windows hostname discovery and switch inventory fallback.

ALTER TABLE ip_addresses
DROP CONSTRAINT IF EXISTS ip_addresses_hostname_source_check;

ALTER TABLE ip_addresses
ADD CONSTRAINT ip_addresses_hostname_source_check
CHECK (
    hostname_source IS NULL OR
    hostname_source IN ('SNMP', 'DNS', 'NETBIOS', 'ARP', 'SWITCH', 'MANUAL')
);
