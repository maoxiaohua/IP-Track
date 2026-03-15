#!/bin/bash
set -e

echo "=== IP-Track Initial Configuration ==="

# Check if .env exists
if [ -f .env ]; then
    echo "⚠️  .env already exists. Skipping."
else
    echo "Creating .env from template..."
    cp .env.example .env

    # Generate encryption key
    echo "Generating encryption key..."
    KEY=$(python3 scripts/generate_key.py | grep "^ENCRYPTION_KEY=" | cut -d= -f2)

    # Update .env with generated key
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/GENERATE_ME_WITH_FERNET_KEY_GENERATOR/$KEY/" .env
    else
        # Linux
        sed -i "s/GENERATE_ME_WITH_FERNET_KEY_GENERATOR/$KEY/" .env
    fi

    # Generate random database password
    DB_PASS=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/CHANGE_ME_TO_SECURE_PASSWORD/$DB_PASS/" .env
    else
        # Linux
        sed -i "s/CHANGE_ME_TO_SECURE_PASSWORD/$DB_PASS/" .env
    fi

    echo "✅ .env created with generated credentials"
fi

echo ""
echo "=== Setup Complete ==="
echo "1. Review .env and customize if needed"
echo "2. Start services: docker-compose up -d"
echo "3. Access frontend: http://localhost:8001"
echo "4. Access API docs: http://localhost:8101/api/docs"
