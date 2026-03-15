#!/bin/bash
# Migration script for existing IP-Track v1.x deployments

echo "=== IP-Track v1.x to v2.x Migration ==="

# Backup current environment
if [ -f backend/.env ]; then
    echo "Backing up existing configuration..."
    cp backend/.env backend/.env.v1.backup

    # Extract important values
    OLD_ENCRYPTION_KEY=$(grep "^ENCRYPTION_KEY=" backend/.env | cut -d= -f2)
    OLD_DB_PASSWORD=$(echo "$(grep "^DATABASE_URL=" backend/.env)" | grep -oP '://[^:]+:\K[^@]+')

    echo "Found existing credentials"
fi

# Create new .env from template
if [ ! -f .env.example ]; then
    echo "❌ Error: .env.example not found"
    exit 1
fi

cp .env.example .env

# Migrate credentials
if [ -n "$OLD_ENCRYPTION_KEY" ]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/GENERATE_ME_WITH_FERNET_KEY_GENERATOR/$OLD_ENCRYPTION_KEY/" .env
    else
        sed -i "s/GENERATE_ME_WITH_FERNET_KEY_GENERATOR/$OLD_ENCRYPTION_KEY/" .env
    fi
    echo "✅ Migrated encryption key"
fi

if [ -n "$OLD_DB_PASSWORD" ]; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/CHANGE_ME_TO_SECURE_PASSWORD/$OLD_DB_PASSWORD/" .env
    else
        sed -i "s/CHANGE_ME_TO_SECURE_PASSWORD/$OLD_DB_PASSWORD/" .env
    fi
    echo "✅ Migrated database password"
fi

echo ""
echo "=== Migration Complete ==="
echo "1. Review .env and adjust settings (especially COLLECTION_INTERVAL_MINUTES, COLLECTION_WORKERS)"
echo "2. Restart: docker-compose down && docker-compose up -d"
echo "3. Verify: Check switch list, run IP lookup, check collection jobs"
