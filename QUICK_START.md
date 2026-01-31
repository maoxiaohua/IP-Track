# Quick Start Guide

## Get Started in 3 Steps

### Step 1: Run Setup Script

```bash
cd /opt/ip-track
./setup.sh
```

This will:
- Generate encryption key
- Create configuration files
- Start all Docker containers
- Initialize the database

### Step 2: Add Your First Switch

1. Open http://localhost:8001 in your browser
2. Click on **Switches** in the navigation menu
3. Click **Add Switch** button
4. Fill in the form:

   **Example for Cisco Switch:**
   ```
   Name: Core-Switch-01
   IP Address: 192.168.1.1
   Vendor: Cisco
   Model: Catalyst 3850
   SSH Port: 22
   Username: admin
   Password: your-password
   Enable Password: your-enable-password (if required)
   Connection Timeout: 30
   Enabled: ✓
   ```

5. Click **Test** to verify connectivity
6. Click **Create** to save

### Step 3: Lookup an IP Address

1. Go back to **Home** page
2. Enter an IP address (e.g., `192.168.1.100`)
3. Click **Lookup IP Address**
4. View the results showing:
   - MAC address
   - Switch name and IP
   - Port number
   - VLAN ID

## Manual Docker Commands

If you prefer manual control:

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Restart a specific service
docker-compose restart backend
docker-compose restart frontend
```

## Accessing the Application

- **Frontend UI**: http://localhost:8001
- **Backend API**: http://localhost:8100
- **API Documentation**: http://localhost:8100/api/docs
- **Health Check**: http://localhost:8100/health

## Troubleshooting

### Services won't start

```bash
# Check if ports are already in use
netstat -tuln | grep -E '8001|8100|5432|6379'

# View container logs
docker-compose logs backend
docker-compose logs frontend
docker-compose logs postgres
```

### Can't connect to switches

1. Verify network connectivity:
   ```bash
   docker exec -it iptrack-backend ping <switch-ip>
   ```

2. Test SSH manually:
   ```bash
   docker exec -it iptrack-backend ssh <username>@<switch-ip>
   ```

3. Check switch credentials in the UI

### Database issues

```bash
# Restart PostgreSQL
docker-compose restart postgres

# Reinitialize database
docker-compose down -v
docker-compose up -d
```

## Configuration

### Change Ports

Edit `docker-compose.yml`:

```yaml
services:
  frontend:
    ports:
      - "3000:5173"  # Change 3000 to your desired port (currently using 8001)

  backend:
    ports:
      - "8000:8100"  # Change 8000 to your desired port
```

### Update Environment Variables

Edit `backend/.env`:

```env
DEBUG=false  # Set to false for production
DEFAULT_SSH_TIMEOUT=60  # Increase timeout if needed
```

## Next Steps

1. **Add more switches**: Configure all your network switches
2. **Test lookups**: Try looking up various IP addresses
3. **View history**: Check the History page to see all queries
4. **Explore API**: Visit http://localhost:8100/api/docs for API documentation

## Production Deployment

For production use:

1. Change default passwords in `docker-compose.yml`
2. Set `DEBUG=false` in `backend/.env`
3. Use a reverse proxy (nginx) for SSL/TLS
4. Implement authentication and authorization
5. Set up regular database backups
6. Configure firewall rules
7. Use Docker secrets for sensitive data

## Support

- Check [README.md](README.md) for detailed documentation
- Review API docs at http://localhost:8100/api/docs
- Check logs in `backend/logs/` directory
