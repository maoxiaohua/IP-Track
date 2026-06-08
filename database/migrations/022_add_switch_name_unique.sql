-- Migration: Add unique constraint on switch name
-- Version: 022
-- Date: 2026-06-02
-- Description: Prevents duplicate switch names at the database level.
--   Part of Layer 2 duplicate switch detection (IP + Name check).

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_switches_name'
          AND conrelid = 'switches'::regclass
    ) THEN
        ALTER TABLE switches
        ADD CONSTRAINT uq_switches_name UNIQUE (name);
    END IF;
END $$;
