-- 025: Add IPAM enrichment tracking
-- Separates enrichment (hostname/DNS/SNMP) from quick ping scan
-- Allows independent scheduling of enrichment as a background task

ALTER TABLE ip_subnets
    ADD COLUMN last_enrichment_at TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN ip_subnets.last_enrichment_at IS 'Last time hostname/DNS/SNMP enrichment completed for this subnet';
