-- Prevent scheduled IP scans from wiping previously discovered identity fields
-- when the current runtime cannot resolve hostname/DNS/SNMP data.

CREATE OR REPLACE FUNCTION preserve_ip_identity_on_empty_scan()
RETURNS TRIGGER AS $$
BEGIN
    -- Only apply this safeguard for scan-driven updates that advance last_scan_at.
    IF NEW.last_scan_at IS DISTINCT FROM OLD.last_scan_at THEN
        IF COALESCE(BTRIM(NEW.hostname), '') = '' AND COALESCE(BTRIM(OLD.hostname), '') <> '' THEN
            NEW.hostname := OLD.hostname;
        END IF;

        IF COALESCE(BTRIM(NEW.hostname_source), '') = '' AND COALESCE(BTRIM(OLD.hostname_source), '') <> '' THEN
            NEW.hostname_source := OLD.hostname_source;
        END IF;

        IF COALESCE(BTRIM(NEW.dns_name), '') = '' AND COALESCE(BTRIM(OLD.dns_name), '') <> '' THEN
            NEW.dns_name := OLD.dns_name;
        END IF;

        IF COALESCE(BTRIM(NEW.system_name), '') = '' AND COALESCE(BTRIM(OLD.system_name), '') <> '' THEN
            NEW.system_name := OLD.system_name;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS preserve_ip_identity_on_empty_scan ON ip_addresses;

CREATE TRIGGER preserve_ip_identity_on_empty_scan
BEFORE UPDATE ON ip_addresses
FOR EACH ROW
EXECUTE FUNCTION preserve_ip_identity_on_empty_scan();
