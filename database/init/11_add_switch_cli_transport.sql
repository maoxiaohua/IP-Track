-- Add CLI transport selection so new installs can use SSH or Telnet globally.

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS cli_transport VARCHAR(10) NOT NULL DEFAULT 'ssh';

UPDATE switches
SET cli_transport = 'ssh'
WHERE cli_transport IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'check_switches_cli_transport'
    ) THEN
        ALTER TABLE switches
        ADD CONSTRAINT check_switches_cli_transport
        CHECK (cli_transport IN ('ssh', 'telnet'));
    END IF;
END $$;

COMMENT ON COLUMN switches.cli_transport IS 'CLI transport protocol used for switch access: ssh or telnet';
