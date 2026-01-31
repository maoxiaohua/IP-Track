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

# Generate encryption key if .env doesn't exist
if [ ! -f backend/.env ]; then
    echo "📝 Creating backend/.env file..."

    # Generate encryption key using Python
    ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

    # Copy example and replace encryption key
    cp backend/.env.example backend/.env

    # Replace the encryption key in .env file
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" backend/.env
    else
        # Linux
        sed -i "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY|" backend/.env
    fi

    echo "✅ Generated encryption key and created backend/.env"
else
    echo "ℹ️  backend/.env already exists, skipping..."
fi

echo ""
echo "=========================================="
echo "Starting Docker containers..."
echo "=========================================="
echo ""

# Start Docker containers
$DOCKER_COMPOSE_CMD up -d

echo ""
echo "=========================================="
echo "Waiting for services to be ready..."
echo "=========================================="
echo ""

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL..."
sleep 5

# Wait for backend to be ready
echo "⏳ Waiting for backend API..."
for i in {1..30}; do
    if curl -s http://localhost:8100/health > /dev/null 2>&1; then
        echo "✅ Backend API is ready"
        break
    fi
    sleep 2
done

# Wait for frontend to be ready
echo "⏳ Waiting for frontend..."
for i in {1..30}; do
    if curl -s http://localhost:8001 > /dev/null 2>&1; then
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
echo "   Backend:   http://localhost:8100"
echo "   API Docs:  http://localhost:8100/api/docs"
echo ""
echo "📝 Next steps:"
echo "   1. Open http://localhost:8001 in your browser"
echo "   2. Go to 'Switches' page and add your network switches"
echo "   3. Start looking up IP addresses!"
echo ""
echo "🛠️  Useful commands:"
echo "   View logs:     docker-compose logs -f"
echo "   Stop:          docker-compose down"
echo "   Restart:       docker-compose restart"
echo ""
