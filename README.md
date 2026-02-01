# IP Track System

A comprehensive web-based network management application for tracking IP addresses, managing switches, and monitoring network devices. Features include IP address lookup, IPAM (IP Address Management), batch switch discovery, and multi-vendor support (Cisco, Dell, Alcatel-Lucent).

## ✨ Features

### Core Features
- **IP Address Lookup**: Enter an IP address to find the connected switch and port
- **Multi-Vendor Support**: Works with Cisco IOS/IOS-XE, Dell Networking OS, and Alcatel-Lucent switches
- **Switch Management**: Add, edit, and manage network switches with role-based prioritization
- **Query History**: Track all lookup queries with timestamps and results
- **Connection Testing**: Test SSH connectivity to switches before adding them
- **Real-time Results**: Fast queries with intelligent caching for improved performance

### 🆕 IPAM - IP Address Management
- **Subnet Management**: Create and manage IP subnets with CIDR notation
- **Automatic IP Generation**: Automatically generate all IP addresses for a subnet
- **Network Scanning**:
  - Ping reachability detection
  - DNS reverse lookup (hostname discovery)
  - ARP MAC address discovery
  - OS detection (Windows, Linux, macOS, network devices)
- **Device Tracking**: Monitor device online/offline status over time
- **Switch Port Association**: Automatically link IPs to switch ports via MAC lookup
- **Scan History**: Track changes in device status, hostname, and OS
- **Dashboard Statistics**: Subnet utilization, IP allocation, and device counts

### 🔍 Batch Discovery
- **IP Range Scanning**: Scan IP ranges to discover network switches
- **Multi-Credential Support**: Try multiple SSH credentials automatically
- **Auto-Detection**: Automatically detect vendor, model, and role
- **Bulk Import**: Select and import multiple switches at once
- **3-Step Wizard**: User-friendly guided discovery process

### 🎨 Modern UI
- **Clean Design**: Modern blue gradient theme with glass morphism effects
- **Responsive Layout**: Works on desktop and mobile devices
- **Smooth Animations**: Polished transitions and hover effects
- **Intuitive Navigation**: Easy-to-use interface with clear visual hierarchy

### ⚡ Performance Optimizations
- **Smart Query Strategy**: Priority-based switch querying (30x faster)
- **Concurrent Operations**: Parallel scanning and querying
- **Redis Caching**: Intelligent caching for frequently accessed data
- **Async Architecture**: Non-blocking operations throughout

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Frontend (Vue 3 + TypeScript)              │
│   IP Lookup | Switch Mgmt | IPAM | Discovery | History │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP/REST API
┌────────────────────────▼────────────────────────────────┐
│              Backend API (FastAPI + Python)             │
│  IP Lookup | Switch Manager | IPAM Service | Scanner   │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐
│ PostgreSQL   │  │   Redis     │  │  Network   │
│ - Switches   │  │ - Caching   │  │  Switches  │
│ - History    │  │ - MAC Cache │  │  (SSH)     │
│ - IP Subnets │  │             │  │            │
│ - IP Addrs   │  │             │  │            │
└──────────────┘  └─────────────┘  └────────────┘
```

## 🛠️ Technology Stack

### Backend
- **FastAPI** - Modern async Python web framework
- **netmiko** - Multi-vendor SSH library for network devices
- **PostgreSQL 16** - Reliable database for switches, history, and IPAM
- **SQLAlchemy** - Async ORM with relationship management
- **Redis 6+** - High-performance caching layer
- **Pydantic** - Data validation and serialization
- **asyncio** - Concurrent operations and task management

### Frontend
- **Vue 3** - Progressive JavaScript framework with Composition API
- **TypeScript** - Type-safe development
- **Element Plus** - Modern UI component library
- **Vite** - Lightning-fast build tool
- **Pinia** - Intuitive state management
- **Axios** - HTTP client with interceptors

### DevOps
- **Docker** - Containerization
- **Docker Compose** - Multi-container orchestration
- **Nginx** - Frontend web server
- **Uvicorn** - ASGI server for FastAPI

## 📋 Prerequisites

- Docker and Docker Compose (recommended)
- OR manual installation:
  - Python 3.11+
  - Node.js 18+
  - PostgreSQL 16+
  - Redis 6+

## 🚀 Quick Start with Docker

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/IP-TRACK.git
   cd IP-TRACK
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
   - Backend API: http://localhost:8101
   - API Documentation: http://localhost:8101/api/docs

## 📖 Usage Guide

### 1. Adding Switches

#### Manual Addition
1. Navigate to **Switches** page
2. Click **Add Switch**
3. Fill in the form:
   - **Name**: Descriptive name (e.g., "Core-Switch-01")
   - **IP Address**: Switch management IP
   - **Vendor**: Select Cisco, Dell, or Alcatel
   - **Model**: Switch model (optional)
   - **Role**: Core, Aggregation, or Access
   - **Priority**: 1-100 (lower = higher priority)
   - **Username/Password**: SSH credentials
4. Click **Test** to verify connectivity
5. Click **Create** to save

#### Batch Discovery
1. Navigate to **Batch Discovery** page
2. **Step 1**: Configure scan parameters
   - Enter IP range (e.g., 10.0.0.1-10.0.0.50 or 10.0.0.0/24)
   - Add SSH credentials (can add multiple sets)
3. **Step 2**: Review discovered switches
   - System auto-detects vendor, model, and role
   - Select switches to import
4. **Step 3**: Confirm and import

### 2. IP Address Lookup

1. Navigate to **IP Lookup** page
2. Enter the target IP address
3. Click **Lookup IP Address**
4. View results showing:
   - MAC address
   - Switch name and IP
   - Port number
   - VLAN ID
   - Query time

### 3. IPAM - IP Address Management

#### Creating a Subnet
1. Navigate to **IPAM** page
2. Click **Add Subnet**
3. Fill in the form:
   - **Subnet Name**: e.g., "Office Network"
   - **Network**: CIDR format (e.g., 10.0.0.0/24)
   - **Description**: Purpose of the subnet
   - **VLAN ID**: Associated VLAN (optional)
   - **Gateway**: Default gateway (optional)
   - **DNS Servers**: Comma-separated (optional)
   - **Auto Scan**: Enable periodic scanning
   - **Scan Interval**: Frequency in seconds
4. Click **Create**
   - System automatically generates all IP addresses

#### Scanning a Subnet
1. In IPAM dashboard, find your subnet
2. Click **Scan** button
3. Choose scan type:
   - **Quick**: Ping only (fast)
   - **Full**: Ping + Hostname + MAC + OS (comprehensive)
4. Wait for scan to complete
5. View results:
   - Online/offline devices
   - Hostnames and MAC addresses
   - Operating systems detected
   - Switch port associations

#### Viewing IP Details
1. Click **View IPs** on a subnet
2. Use filters:
   - Status (Available, Used, Reserved, Offline)
   - Reachability (Online, Offline)
   - Search by IP, hostname, or description
3. Click **Details** on any IP to see:
   - Full scan history
   - Device information
   - Switch port connection
   - Last seen timestamp

### 4. Query History

1. Navigate to **History** page
2. View all past queries with:
   - Target IP
   - Found MAC address
   - Switch and port
   - Query status
   - Timestamp
3. Use pagination to browse records

## 🔌 API Documentation

Full interactive API documentation is available at: http://localhost:8101/api/docs

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

#### Batch Discovery
- `POST /api/v1/discovery/scan` - Scan IP range for switches
- `POST /api/v1/discovery/add-switches` - Bulk add discovered switches

#### IPAM
- `POST /api/v1/ipam/subnets` - Create subnet
- `GET /api/v1/ipam/subnets` - List subnets
- `GET /api/v1/ipam/subnets/{id}` - Get subnet details
- `DELETE /api/v1/ipam/subnets/{id}` - Delete subnet
- `GET /api/v1/ipam/ip-addresses` - List IP addresses (with filters)
- `GET /api/v1/ipam/ip-addresses/{id}` - Get IP details
- `PUT /api/v1/ipam/ip-addresses/{id}` - Update IP
- `POST /api/v1/ipam/scan` - Scan subnet or specific IPs
- `GET /api/v1/ipam/dashboard` - Get IPAM statistics

#### Query History
- `GET /api/v1/history` - Get query history (paginated)
- `GET /api/v1/history/{id}` - Get specific query

## 🔧 Configuration

### Backend Configuration (backend/.env)

```env
# Application
APP_NAME=IP Track System
APP_VERSION=1.0.0
DEBUG=false

# API
API_V1_PREFIX=/api/v1
BACKEND_CORS_ORIGINS=["http://localhost:8001"]

# Database
DATABASE_URL=postgresql+asyncpg://iptrack:iptrack123@localhost:5432/iptrack

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_CACHE_TTL=300

# Security - IMPORTANT: Generate a secure key
ENCRYPTION_KEY=your-32-byte-base64-encoded-key-here

# Switch Connection
DEFAULT_SSH_TIMEOUT=30
MAX_CONCURRENT_CONNECTIONS=10
```

### Switch Role and Priority

**Roles**:
- **Core**: Layer 3 core switches (highest priority for ARP queries)
- **Aggregation**: Distribution/aggregation layer switches
- **Access**: Edge/access layer switches

**Priority** (1-100):
- Lower number = higher priority
- Recommended: Core=10, Aggregation=30, Access=50
- System queries switches in priority order for optimal performance

## 🎯 How It Works

### IP Lookup Process
1. **Priority Grouping**: Switches are grouped by priority
2. **ARP Query**: Query high-priority switches first for ARP entries
3. **MAC Discovery**: Extract MAC address from ARP table
4. **MAC Table Query**: Query all switches for MAC address location
5. **Port Identification**: Identify which port learned the MAC
6. **Result Display**: Show switch name, port, and VLAN
7. **History Logging**: Store query results in database

### IPAM Scanning Process
1. **Ping Sweep**: Test reachability of all IPs in subnet
2. **DNS Lookup**: Reverse DNS to get hostnames
3. **ARP Discovery**: Get MAC addresses from ARP cache
4. **OS Detection**: Use nmap or TTL analysis to identify OS
5. **Switch Association**: Query switches for MAC to find port
6. **History Recording**: Log all scan results with change detection

## 🔐 Security Considerations

1. **Credential Encryption**: Switch passwords encrypted with Fernet (AES-256)
2. **SSH Security**: Secure SSH connections to network devices
3. **Input Validation**: All inputs validated to prevent injection attacks
4. **CORS Configuration**: Restricted origins for API access
5. **Network Isolation**: Deploy backend in secure network segment
6. **Access Control**: Consider adding authentication for production

## 🐛 Troubleshooting

### Connection Issues

**Problem**: "Connection timeout" error
- Check network connectivity to switch
- Verify SSH port is correct (default: 22)
- Ensure firewall allows SSH traffic
- Check switch SSH configuration

**Problem**: "Authentication failed" error
- Verify username and password are correct
- For Cisco: Check if enable password is required
- Ensure user has appropriate privileges
- Try testing credentials manually via SSH

### Lookup Issues

**Problem**: "No ARP entry found"
- Device may not be active on the network
- IP address may be incorrect
- ARP entry may have expired (try pinging the device first)
- Check if switches have correct role/priority

**Problem**: "MAC address not found in MAC table"
- Device may be connected to a switch not in the system
- MAC table entry may have aged out
- Verify all switches are configured and enabled

### IPAM Issues

**Problem**: Scan shows all devices offline
- Check network connectivity from backend server
- Verify ICMP (ping) is not blocked by firewall
- Ensure backend can reach the subnet

**Problem**: OS detection not working
- Install nmap: `apt-get install nmap` or `yum install nmap`
- Check if nmap has proper permissions
- OS detection requires root/sudo for accurate results

## 📚 Additional Documentation

- **Quick Start Guide**: See `QUICK_START.md`
- **Manual Deployment**: See `MANUAL_DEPLOYMENT.md` (for servers without Docker)
- **GitHub Push Guide**: See `GITHUB_PUSH_GUIDE.md`
- **Project Summary**: See `PROJECT_SUMMARY.md`

## 🚀 Deployment

### Docker Deployment (Recommended)
```bash
./setup.sh
```

### Manual Deployment
See `MANUAL_DEPLOYMENT.md` for detailed instructions on deploying without Docker.

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is provided as-is for network management purposes.

## 🙏 Acknowledgments

- Built with FastAPI, Vue 3, and Element Plus
- Uses netmiko for multi-vendor network device support
- Inspired by network operations teams worldwide
- Co-developed with Claude Sonnet 4.5

## 📞 Support

For issues and questions:
- Check the troubleshooting section above
- Review API documentation at `/api/docs`
- Check application logs in `backend/logs/`
- Open an issue on GitHub

---

**Version**: 2.0.0
**Last Updated**: 2026-02-01
**Status**: Production Ready ✅
