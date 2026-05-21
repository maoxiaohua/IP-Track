-- Migration: Add credential profiles for BMC multi-credential support
-- Version: 020
-- Date: 2026-05-15
-- Description: Add bmc_credential_profiles table and credential_profile_id foreign key to bmc_servers.

CREATE TABLE IF NOT EXISTS bmc_credential_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    username VARCHAR(100) NOT NULL,
    password_encrypted TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE bmc_servers
    ADD COLUMN IF NOT EXISTS credential_profile_id INTEGER
        REFERENCES bmc_credential_profiles(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_bmc_servers_credential_profile_id
    ON bmc_servers(credential_profile_id);
