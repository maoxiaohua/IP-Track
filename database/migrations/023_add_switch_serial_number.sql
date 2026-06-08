-- Migration: Add serial_number column to switches
-- Version: 023
-- Date: 2026-06-02
-- Description: Stores the chassis serial number collected via SNMP ENTITY-MIB.
--   Used for Layer 3 duplicate switch detection (serial number matching).

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS serial_number VARCHAR(200);
