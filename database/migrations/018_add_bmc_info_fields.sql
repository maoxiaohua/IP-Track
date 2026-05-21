-- Migration: Add BMC info columns to bmc_servers
-- Version: 018
-- Date: 2026-05-15
-- Description: Add serial_number, bmc_firmware_version, and bmc_info_updated_at
--   to bmc_servers table for IPMI FRU and MC info queries.

ALTER TABLE bmc_servers
    ADD COLUMN IF NOT EXISTS serial_number VARCHAR(200),
    ADD COLUMN IF NOT EXISTS bmc_firmware_version VARCHAR(100),
    ADD COLUMN IF NOT EXISTS bmc_info_updated_at TIMESTAMP WITH TIME ZONE;
