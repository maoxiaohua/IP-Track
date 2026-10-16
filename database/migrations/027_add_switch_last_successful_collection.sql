-- Migration: Add last_successful_collection_at column to switches
-- Version: 027
-- Date: 2026-08-26
-- Description: Tracks the last time a switch's ARP/MAC collection *succeeded*.
--   Unlike last_arp_collection_at / last_mac_collection_at (which get set even on
--   failed attempts), this field only advances on a successful collection, so it
--   reflects the true last time we actually got data from the device. This is what
--   the UI uses to judge how long a device has really been away (ping-unreachable),
--   rather than when it was last merely *attempted*.

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS last_successful_collection_at TIMESTAMPTZ;
