#!/bin/bash

# IP Track System - Setup Script
# This script helps you set up the IP Track System quickly

set -e

echo "=========================================="
echo "IP Track System - Setup Script"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check for docker-compose or docker compose
DOCKER_COMPOSE_CMD=""
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
else
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo "   Using: $DOCKER_COMPOSE_CMD"
echo ""

# Create the root .env (the file docker compose actually reads) with real secrets
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cp .env.example .env

    ENCRYPTION_KEY=$(python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
    DATABASE_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(24))")
    REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(24))")

    python3 - "$ENCRYPTION_KEY" "$DATABASE_PASSWORD" "$REDIS_PASSWORD" <<'PY'
import pathlib, re, sys
key, db_pw, redis_pw = sys.argv[1:4]
p = pathlib.Path('.env')
text = p.read_text()
for name, value in (('ENCRYPTION_KEY', key), ('DATABASE_PASSWORD', db_pw), ('REDIS_PASSWORD', redis_pw)):
    text = re.sub(rf'(?m)^{name}=.*$', f'{name}={value}', text)
if 'REDIS_BIND=' not in text:
    text = re.sub(r'(?m)^REDIS_PASSWORD=', 'REDIS_BIND=127.0.0.1\nREDIS_PASSWORD=', text, count=1)
p.write_text(text)
PY

    echo "✅ Created .env with generated ENCRYPTION_KEY / DATABASE_PASSWORD / REDIS_PASSWORD"
else
    echo "ℹ️  .env already exists, skipping..."
    if ! grep -q '^REDIS_BIND=' .env; then
        echo "REDIS_BIND=127.0.0.1" >> .env
    fi
    if grep -q '^REDIS_PASSWORD=$' .env; then
        REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_hex(24))")
        sed -i.bak "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$REDIS_PASSWORD|" .env && rm -f .env.bak
        echo "⚠️  REDIS_PASSWORD was empty - generated one and updated .env"
    fi
fi

# Read DB credentials without sourcing .env (some values contain spaces)
DB_USER=$(grep -m1 '^DATABASE_USER=' .env | cut -d= -f2-)
DB_NAME=$(grep -m1 '^DATABASE_NAME=' .env | cut -d= -f2-)
DB_USER=${DB_USER:-iptrack}
DB_NAME=${DB_NAME:-iptrack}

echo ""
echo "=========================================="
echo "Starting database services..."
echo "=========================================="
echo ""

$DOCKER_COMPOSE_CMD up -d postgres redis

echo "⏳ Waiting for PostgreSQL..."
for i in {1..30}; do
    if $DOCKER_COMPOSE_CMD exec -T postgres pg_isready -U "$DB_USER" > /dev/null 2>&1; then
        echo "✅ PostgreSQL is ready"
        break
    fi
    sleep 2
done

# Apply pending migrations before the backends start. schema_migrations tracks
# what has run, so later migrations are never skipped again.
echo "🗄️  Checking database migrations..."
HAS_VERSION_TABLE=$($DOCKER_COMPOSE_CMD exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.schema_migrations')" 2>/dev/null | tr -d '[:space:]')

if [ -z "$HAS_VERSION_TABLE" ]; then
    $DOCKER_COMPOSE_CMD exec -T postgres psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -c \
        "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" > /dev/null

    # Legacy install (already has users) was fully migrated by the old script.
    HAS_USERS=$($DOCKER_COMPOSE_CMD exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.users')" 2>/dev/null | tr -d '[:space:]')
    if [ -n "$HAS_USERS" ]; then
        for sql in $(ls database/migrations/*.sql | sort); do
            name=$(basename "$sql")
            $DOCKER_COMPOSE_CMD exec -T postgres psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -c \
                "INSERT INTO schema_migrations(filename) VALUES ('$name') ON CONFLICT DO NOTHING;" > /dev/null
        done
        echo "ℹ️  Existing database: marked previous migrations as applied"
    fi
fi

for sql in $(ls database/migrations/*.sql | sort); do
    name=$(basename "$sql")
    applied=$($DOCKER_COMPOSE_CMD exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT 1 FROM schema_migrations WHERE filename='$name'" | tr -d '[:space:]')
    [ -n "$applied" ] && continue
    echo "   ▶ $name"
    if ! $DOCKER_COMPOSE_CMD exec -T postgres psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" < "$sql" > /dev/null; then
        echo "❌ Migration failed: $sql"
        exit 1
    fi
    $DOCKER_COMPOSE_CMD exec -T postgres psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" -c \
        "INSERT INTO schema_migrations(filename) VALUES ('$name') ON CONFLICT DO NOTHING;" > /dev/null
done
echo "✅ Migrations up to date"

echo ""
echo "=========================================="
echo "Starting Docker containers..."
echo "=========================================="
echo ""

# Start the remaining services
$DOCKER_COMPOSE_CMD up -d

echo ""
echo "=========================================="
echo "Waiting for services to be ready..."
echo "=========================================="
echo ""

# Wait for backend services to be ready
echo "⏳ Waiting for backend services..."
for i in {1..30}; do
    if curl --noproxy '*' -s http://localhost:8101/health > /dev/null 2>&1 \
        && curl --noproxy '*' -s http://localhost:8102/health > /dev/null 2>&1 \
        && curl --noproxy '*' -s http://localhost:8103/health > /dev/null 2>&1; then
        echo "✅ Backend services are ready"
        break
    fi
    sleep 2
done

# Wait for frontend to be ready
echo "⏳ Waiting for frontend..."
for i in {1..30}; do
    if curl --noproxy '*' -s http://localhost:8001 > /dev/null 2>&1; then
        echo "✅ Frontend is ready"
        break
    fi
    sleep 2
done

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "🌐 Access the application:"
echo "   Frontend:  http://localhost:8001"
echo "   Core API:  http://localhost:8101"
echo "   IPAM API:  http://localhost:8102"
echo "   Collector: http://localhost:8103"
echo ""
echo "📝 Next steps:"
echo "   1. Open http://localhost:8001 in your browser"
echo "   2. Guests can only browse/query; click 登录 to unlock changes"
echo "   3. Initial admin username: admin"
echo "      Temporary password: $DOCKER_COMPOSE_CMD logs backend-core | grep 初始管理员"
echo "      (shown once in the logs - change it right after the first login)"
echo "   4. Go to 'Switches' page and add your network switches"
echo "   5. Start looking up IP addresses!"
echo ""
echo "🛠️  Useful commands:"
echo "   View logs:     docker-compose logs -f"
echo "   Stop:          docker-compose down"
echo "   Restart:       docker-compose restart"
echo ""
