-- Migration: Add verification columns to bmc_servers
-- Version: 019
-- Date: 2026-05-15
-- Description: Add verified and verify_error columns for connectivity check on creation.

ALTER TABLE bmc_servers
    ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verify_error VARCHAR(200);
