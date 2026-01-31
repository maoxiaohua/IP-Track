# IP Track System

A web-based application for tracking IP addresses on network switches. Query any IP address to discover which switch port a device is connected to, supporting multiple switch vendors (Cisco, Dell, Alcatel-Lucent).

## Features

- **Multi-Vendor Support**: Works with Cisco IOS/IOS-XE, Dell Networking OS, and Alcatel-Lucent switches
- **IP Address Lookup**: Enter an IP address to find the connected switch and port
- **MAC Address Normalization**: Handles different MAC address formats across vendors
- **Switch Management**: Add, edit, and manage network switches through a web interface
- **Query History**: Track all lookup queries with timestamps and results
- **Connection Testing**: Test SSH connectivity to switches before adding them
- **Real-time Results**: Fast queries with caching for improved performance
- **RESTful API**: Full API access for automation and integration

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vue 3)                     │
│              IP Input → Results Display                 │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/REST
┌────────────────────────▼────────────────────────────────┐
│                 Backend API (FastAPI)                   │
│         Multi-Vendor Switch Connection Manager          │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐
│ PostgreSQL   │  │   Redis     │  │  Network   │
│ - Switches   │  │ - Caching   │  │  Switches  │
│ - History    │  │             │  │  (SSH)     │
└──────────────┘  └─────────────┘  └────────────┘
```

## Technology Stack

### Backend
- **FastAPI** - Modern async Python web framework
- **netmiko** - Multi-vendor SSH library for network devices
- **PostgreSQL** - Reliable database for switches and history
- **SQLAlchemy** - Async ORM
- **Redis** - Caching layer
- **Pydantic** - Data validation

### Frontend
- **Vue 3** - Progressive JavaScript framework
- **TypeScript** - Type-safe development
- **Element Plus** - UI component library
- **Vite** - Fast build tool
- **Pinia** - State management

## Prerequisites

- Docker and Docker Compose (recommended)
- OR:
  - Python 3.11+
  - Node.js 20+
  - PostgreSQL 16+
  - Redis 7+

## Quick Start with Docker

1. **Clone the repository**
   ```bash
   cd /opt/ip-track
   ```

2. **Generate encryption key**
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. **Configure environment**
   ```bash
   cp backend/.env.example backend/.env
   # Edit backend/.env and set ENCRYPTION_KEY to the generated key
   ```

4. **Start the application**
   ```bash
   docker-compose up -d
   ```

5. **Access the application**
   - Frontend: http://localhost:8001
   - Backend API: http://localhost:8100
   - API Documentation: http://localhost:8100/api/docs

## Manual Installation

### Backend Setup

1. **Install Python dependencies**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your database and Redis URLs
   ```

3. **Initialize database**
   ```bash
   psql -U postgres -f ../database/init/01_create_tables.sql
   ```

4. **Run the backend**
   ```bash
   cd src
   uvicorn main:app --host 0.0.0.0 --port 8100 --reload
   ```

### Frontend Setup

1. **Install Node dependencies**
   ```bash
   cd frontend
   npm install
   ```

2. **Configure environment**
   ```bash
   # Create .env file
   echo "VITE_API_BASE_URL=http://localhost:8100" > .env
   ```

3. **Run the frontend**
   ```bash
   npm run dev
   ```

## Configuration

### Backend Configuration (backend/.env)

```env
# Application
APP_NAME=IP Track System
DEBUG=true

# Database
DATABASE_URL=postgresql+asyncpg://iptrack:iptrack123@localhost:5432/iptrack

# Redis
REDIS_URL=redis://localhost:6379/0

# Security - IMPORTANT: Generate a secure key
ENCRYPTION_KEY=your-32-byte-base64-encoded-key-here

# Switch Connection
DEFAULT_SSH_TIMEOUT=30
MAX_CONCURRENT_CONNECTIONS=10
```

### Switch Configuration Requirements

Ensure your network switches have:
- SSH enabled
- Valid user credentials with appropriate privileges
- For Cisco: Enable mode password (if required)
- Network connectivity from the backend server

## Usage Guide

### Adding a Switch

1. Navigate to **Switches** page
2. Click **Add Switch**
3. Fill in the form:
   - **Name**: Descriptive name (e.g., "Core-Switch-01")
   - **IP Address**: Switch management IP
   - **Vendor**: Select Cisco, Dell, or Alcatel
   - **Username/Password**: SSH credentials
   - **Enable Password**: For Cisco switches (optional)
4. Click **Test** to verify connectivity
5. Click **Create** to save

### Looking Up an IP Address

1. Navigate to **Home** page
2. Enter the target IP address
3. Click **Lookup IP Address**
4. View results showing:
   - MAC address
   - Switch name and IP
   - Port number
   - VLAN ID

### Viewing Query History

1. Navigate to **History** page
2. View all past queries with:
   - Target IP
   - Found MAC address
   - Switch port
   - Query status
   - Timestamp

## API Documentation

Full API documentation is available at: http://localhost:8100/api/docs

### Key Endpoints

#### Switch Management
- `POST /api/v1/switches` - Create a switch
- `GET /api/v1/switches` - List all switches
- `GET /api/v1/switches/{id}` - Get switch details
- `PUT /api/v1/switches/{id}` - Update switch
- `DELETE /api/v1/switches/{id}` - Delete switch
- `POST /api/v1/switches/{id}/test` - Test connection

#### IP Lookup
- `POST /api/v1/lookup/ip` - Lookup an IP address

#### Query History
- `GET /api/v1/history` - Get query history (paginated)
- `GET /api/v1/history/{id}` - Get specific query

## How It Works

1. **ARP Table Query**: The system queries all enabled switches for ARP entries matching the target IP
2. **MAC Discovery**: Extracts the MAC address associated with the IP
3. **MAC Table Query**: Queries switches for MAC address table entries
4. **Port Identification**: Identifies which port learned the MAC address
5. **Result Display**: Shows switch name, port, and VLAN information
6. **History Logging**: Stores query results in the database

## Vendor-Specific Details

### Cisco IOS/IOS-XE
- MAC Format: `aaaa.bbbb.cccc`
- Commands: `show ip arp`, `show mac address-table`
- Requires enable mode for privileged commands

### Dell Networking OS
- MAC Format: `aa:bb:cc:dd:ee:ff`
- Commands: `show arp`, `show mac-address-table`

### Alcatel-Lucent (Nokia)
- MAC Format: `aa:bb:cc:dd:ee:ff`
- Commands: `show ip arp`, `show mac-address-table`

## Troubleshooting

### Connection Issues

**Problem**: "Connection timeout" error
- Check network connectivity to switch
- Verify SSH port is correct (default: 22)
- Ensure firewall allows SSH traffic

**Problem**: "Authentication failed" error
- Verify username and password are correct
- For Cisco: Check if enable password is required
- Ensure user has appropriate privileges

### Lookup Issues

**Problem**: "No ARP entry found"
- Device may not be active on the network
- IP address may be incorrect
- ARP entry may have expired

**Problem**: "MAC address not found in MAC table"
- Device may be connected to a different switch
- MAC table entry may have aged out
- Check if all switches are configured

## Security Considerations

1. **Credential Encryption**: Switch passwords are encrypted using AES-256
2. **SSH Security**: Uses secure SSH connections to switches
3. **Input Validation**: All inputs are validated to prevent injection attacks
4. **Network Isolation**: Deploy backend in a secure network segment
5. **Access Control**: Consider adding authentication for production use

## Future Enhancements

- **Batch Processing**: Process thousands of IPs with task queue
- **Scheduled Scanning**: Periodic network discovery
- **Change Detection**: Alert on port changes
- **Network Topology**: Visualize switch connections
- **SNMP Support**: Alternative to SSH for some vendors
- **Export Functionality**: CSV/Excel export of results
- **Multi-tenancy**: Support multiple network environments
- **Authentication**: User login and role-based access control

## Development

### Running Tests

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm run test
```

### Project Structure

```
ip-track/
├── backend/          # FastAPI backend
│   ├── src/
│   │   ├── api/      # API endpoints
│   │   ├── core/     # Configuration and security
│   │   ├── models/   # Database models
│   │   ├── schemas/  # Pydantic schemas
│   │   ├── services/ # Business logic
│   │   └── utils/    # Utilities
│   └── requirements.txt
├── frontend/         # Vue 3 frontend
│   ├── src/
│   │   ├── api/      # API client
│   │   ├── components/ # Vue components
│   │   ├── views/    # Page views
│   │   ├── stores/   # Pinia stores
│   │   └── router/   # Vue Router
│   └── package.json
├── database/         # Database initialization
│   └── init/
└── docker-compose.yml
```

## Contributing

Contributions are welcome! Please follow these guidelines:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is provided as-is for network management purposes.

## Support

For issues and questions:
- Check the troubleshooting section
- Review API documentation at `/api/docs`
- Check application logs in `backend/logs/`

## Acknowledgments

- Built with FastAPI, Vue 3, and Element Plus
- Uses netmiko for multi-vendor network device support
- Inspired by network operations teams worldwide
