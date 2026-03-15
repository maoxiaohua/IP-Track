"""
Database Schema Update Script for SNMP Features

This script directly uses SQLAlchemy to add SNMP columns to the switches table
and create new SNMP-related tables.

Usage:
    cd /opt/IP-Track/backend
    source /opt/IP-Track/venv/bin/activate
    python update_database.py
"""

import asyncio
import sys
import os

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, OperationalError
from core.database import engine
from utils.logger import logger


async def update_database():
    """Update database schema for SNMP features"""

    logger.info("Starting database schema update for SNMP features...")

    async with engine.begin() as conn:

        # ====================================================================
        # Step 1: Add SNMP columns to switches table
        # ====================================================================

        logger.info("Step 1: Adding SNMP columns to switches table...")

        snmp_columns = [
            ("snmp_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ("snmp_version", "VARCHAR(10) NOT NULL DEFAULT '3'"),
            ("snmp_username", "VARCHAR(100)"),
            ("snmp_auth_protocol", "VARCHAR(20)"),
            ("snmp_auth_password_encrypted", "TEXT"),
            ("snmp_priv_protocol", "VARCHAR(20)"),
            ("snmp_priv_password_encrypted", "TEXT"),
            ("snmp_port", "INTEGER NOT NULL DEFAULT 161"),
        ]

        for column_name, column_type in snmp_columns:
            try:
                await conn.execute(text(f"""
                    ALTER TABLE switches
                    ADD COLUMN IF NOT EXISTS {column_name} {column_type}
                """))
                logger.info(f"  ✅ Added column: {column_name}")
            except (ProgrammingError, OperationalError) as e:
                if "already exists" in str(e).lower():
                    logger.info(f"  ℹ️  Column already exists: {column_name}")
                else:
                    raise

        # Create index
        try:
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_switches_snmp_enabled
                ON switches(snmp_enabled)
            """))
            logger.info("  ✅ Created index: idx_switches_snmp_enabled")
        except Exception as e:
            logger.warning(f"  ⚠️  Index creation skipped: {e}")

        # ====================================================================
        # Step 2: Create ARP table
        # ====================================================================

        logger.info("Step 2: Creating arp_table...")

        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS arp_table (
                    id SERIAL PRIMARY KEY,
                    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
                    ip_address INET NOT NULL,
                    mac_address MACADDR NOT NULL,
                    vlan_id INTEGER,
                    interface VARCHAR(50),
                    age_seconds INTEGER,
                    collected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """))
            logger.info("  ✅ Created table: arp_table")
        except Exception as e:
            logger.info(f"  ℹ️  Table already exists: arp_table")

        # Create indexes for arp_table
        arp_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_arp_switch_id ON arp_table(switch_id)",
            "CREATE INDEX IF NOT EXISTS idx_arp_ip_address ON arp_table(ip_address)",
            "CREATE INDEX IF NOT EXISTS idx_arp_mac_address ON arp_table(mac_address)",
            "CREATE INDEX IF NOT EXISTS idx_arp_last_seen ON arp_table(last_seen)",
            "CREATE INDEX IF NOT EXISTS idx_arp_switch_ip ON arp_table(switch_id, ip_address)",
        ]

        for index_sql in arp_indexes:
            try:
                await conn.execute(text(index_sql))
            except Exception:
                pass

        logger.info("  ✅ Created indexes for arp_table")

        # ====================================================================
        # Step 3: Create MAC table
        # ====================================================================

        logger.info("Step 3: Creating mac_table...")

        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS mac_table (
                    id SERIAL PRIMARY KEY,
                    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
                    mac_address MACADDR NOT NULL,
                    port_name VARCHAR(50) NOT NULL,
                    vlan_id INTEGER,
                    is_dynamic INTEGER NOT NULL DEFAULT 1,
                    collected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """))
            logger.info("  ✅ Created table: mac_table")
        except Exception as e:
            logger.info(f"  ℹ️  Table already exists: mac_table")

        # Create indexes for mac_table
        mac_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_mac_switch_id ON mac_table(switch_id)",
            "CREATE INDEX IF NOT EXISTS idx_mac_address ON mac_table(mac_address)",
            "CREATE INDEX IF NOT EXISTS idx_mac_last_seen ON mac_table(last_seen)",
            "CREATE INDEX IF NOT EXISTS idx_mac_switch_port ON mac_table(switch_id, port_name)",
        ]

        for index_sql in mac_indexes:
            try:
                await conn.execute(text(index_sql))
            except Exception:
                pass

        logger.info("  ✅ Created indexes for mac_table")

        # ====================================================================
        # Step 4: Create port_analysis table
        # ====================================================================

        logger.info("Step 4: Creating port_analysis table...")

        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS port_analysis (
                    id SERIAL PRIMARY KEY,
                    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
                    port_name VARCHAR(50) NOT NULL,
                    mac_count INTEGER NOT NULL DEFAULT 0,
                    unique_vlans INTEGER NOT NULL DEFAULT 0,
                    port_type VARCHAR(20) NOT NULL,
                    confidence_score FLOAT NOT NULL DEFAULT 0.0,
                    is_trunk_by_name INTEGER NOT NULL DEFAULT 0,
                    is_access_by_name INTEGER NOT NULL DEFAULT 0,
                    analyzed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    UNIQUE(switch_id, port_name)
                )
            """))
            logger.info("  ✅ Created table: port_analysis")
        except Exception as e:
            logger.info(f"  ℹ️  Table already exists: port_analysis")

        # Create indexes
        port_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_port_switch_id ON port_analysis(switch_id)",
            "CREATE INDEX IF NOT EXISTS idx_port_type ON port_analysis(port_type)",
            "CREATE INDEX IF NOT EXISTS idx_port_confidence ON port_analysis(confidence_score)",
            "CREATE INDEX IF NOT EXISTS idx_port_analyzed_at ON port_analysis(analyzed_at)",
        ]

        for index_sql in port_indexes:
            try:
                await conn.execute(text(index_sql))
            except Exception:
                pass

        logger.info("  ✅ Created indexes for port_analysis")

        # ====================================================================
        # Step 5: Create ip_location table
        # ====================================================================

        logger.info("Step 5: Creating ip_location table...")

        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ip_location (
                    id SERIAL PRIMARY KEY,
                    ip_address INET NOT NULL UNIQUE,
                    mac_address MACADDR NOT NULL,
                    switch_id INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
                    port_name VARCHAR(50) NOT NULL,
                    vlan_id INTEGER,
                    confidence_score FLOAT NOT NULL DEFAULT 0.0,
                    detection_method VARCHAR(50) NOT NULL,
                    port_mac_count INTEGER,
                    appears_on_switches INTEGER NOT NULL DEFAULT 1,
                    first_detected TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_confirmed TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    last_arp_seen TIMESTAMP WITH TIME ZONE,
                    last_mac_seen TIMESTAMP WITH TIME ZONE
                )
            """))
            logger.info("  ✅ Created table: ip_location")
        except Exception as e:
            logger.info(f"  ℹ️  Table already exists: ip_location")

        # Create indexes
        location_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_location_ip ON ip_location(ip_address)",
            "CREATE INDEX IF NOT EXISTS idx_location_mac ON ip_location(mac_address)",
            "CREATE INDEX IF NOT EXISTS idx_location_switch_id ON ip_location(switch_id)",
            "CREATE INDEX IF NOT EXISTS idx_location_confidence ON ip_location(confidence_score)",
            "CREATE INDEX IF NOT EXISTS idx_location_last_confirmed ON ip_location(last_confirmed)",
            "CREATE INDEX IF NOT EXISTS idx_location_switch_port ON ip_location(switch_id, port_name)",
        ]

        for index_sql in location_indexes:
            try:
                await conn.execute(text(index_sql))
            except Exception:
                pass

        logger.info("  ✅ Created indexes for ip_location")

    logger.info("")
    logger.info("=" * 70)
    logger.info("✅ Database schema update completed successfully!")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Created tables:")
    logger.info("  - arp_table (IP-MAC mappings)")
    logger.info("  - mac_table (MAC-Port mappings)")
    logger.info("  - port_analysis (Port type analysis)")
    logger.info("  - ip_location (IP location results)")
    logger.info("")
    logger.info("Updated switches table with SNMP columns")
    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Restart backend: sudo systemctl restart ip-track-backend")
    logger.info("  2. Access SNMP config: http://your-server/snmp-config")
    logger.info("")


if __name__ == "__main__":
    try:
        asyncio.run(update_database())
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Database update failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
