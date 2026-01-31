# IP Track System - 手动部署指南（无 Docker）

本指南适用于没有 Docker 的 Linux 服务器（如内网环境）。

## 系统要求

- **操作系统**: CentOS 7+, Ubuntu 18.04+, 或其他 Linux 发行版
- **Python**: 3.11+
- **Node.js**: 18+
- **PostgreSQL**: 14+
- **Redis**: 6+
- **内存**: 至少 2GB
- **磁盘**: 至少 10GB

## 一、安装依赖

### 1.1 安装 Python 3.11

```bash
# CentOS/RHEL
sudo yum install -y python3.11 python3.11-pip python3.11-devel

# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 验证安装
python3.11 --version
```

### 1.2 安装 Node.js 18+

```bash
# 使用 NodeSource 仓库
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install -y nodejs

# 或者 Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# 验证安装
node --version
npm --version
```

### 1.3 安装 PostgreSQL 16

```bash
# CentOS/RHEL
sudo yum install -y postgresql16-server postgresql16-contrib
sudo postgresql-16-setup initdb
sudo systemctl enable postgresql-16
sudo systemctl start postgresql-16

# Ubuntu/Debian
sudo apt install -y postgresql-16 postgresql-contrib-16
sudo systemctl enable postgresql
sudo systemctl start postgresql

# 验证安装
sudo -u postgres psql --version
```

### 1.4 安装 Redis

```bash
# CentOS/RHEL
sudo yum install -y redis
sudo systemctl enable redis
sudo systemctl start redis

# Ubuntu/Debian
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# 验证安装
redis-cli ping  # 应该返回 PONG
```

## 二、下载代码

```bash
# 克隆仓库（替换 YOUR_USERNAME）
cd /opt
git clone https://github.com/YOUR_USERNAME/IP-TRACK.git
cd IP-TRACK
```

## 三、配置数据库

### 3.1 创建数据库和用户

```bash
sudo -u postgres psql << EOF
CREATE USER iptrack WITH PASSWORD 'iptrack123';
CREATE DATABASE iptrack OWNER iptrack;
GRANT ALL PRIVILEGES ON DATABASE iptrack TO iptrack;
\q
EOF
```

### 3.2 初始化数据库表

```bash
sudo -u postgres psql -U iptrack -d iptrack -f database/init/01_create_tables.sql
```

### 3.3 配置 PostgreSQL 允许本地连接

编辑 `/var/lib/pgsql/16/data/pg_hba.conf`（路径可能不同）：

```bash
# 添加以下行
host    iptrack         iptrack         127.0.0.1/32            md5
```

重启 PostgreSQL：
```bash
sudo systemctl restart postgresql-16
```

## 四、部署后端

### 4.1 创建 Python 虚拟环境

```bash
cd /opt/IP-TRACK/backend
python3.11 -m venv venv
source venv/bin/activate
```

### 4.2 安装 Python 依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4.3 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 生成加密密钥
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 编辑 .env 文件
cat > .env << EOF
# Application Settings
APP_NAME=IP Track System
APP_VERSION=1.0.0
DEBUG=false

# API Configuration
API_V1_PREFIX=/api/v1
BACKEND_CORS_ORIGINS=["http://localhost:8001","http://YOUR_SERVER_IP:8001"]

# Database Configuration
DATABASE_URL=postgresql+asyncpg://iptrack:iptrack123@localhost:5432/iptrack

# Redis Configuration
REDIS_URL=redis://localhost:6379/0
REDIS_CACHE_TTL=300

# Security Configuration
ENCRYPTION_KEY=$ENCRYPTION_KEY

# Switch Connection Settings
DEFAULT_SSH_TIMEOUT=30
MAX_CONCURRENT_CONNECTIONS=10
EOF
```

**重要**: 替换 `YOUR_SERVER_IP` 为你的服务器 IP 地址。

### 4.4 测试后端

```bash
cd /opt/IP-TRACK/backend
source venv/bin/activate
export PYTHONPATH=/opt/IP-TRACK/backend/src
uvicorn main:app --host 0.0.0.0 --port 8100
```

访问 http://YOUR_SERVER_IP:8100/health 验证。

按 Ctrl+C 停止测试。

### 4.5 创建后端 systemd 服务

```bash
sudo tee /etc/systemd/system/iptrack-backend.service > /dev/null << 'EOF'
[Unit]
Description=IP Track Backend API
After=network.target postgresql-16.service redis.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/IP-TRACK/backend
Environment="PYTHONPATH=/opt/IP-TRACK/backend/src"
ExecStart=/opt/IP-TRACK/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable iptrack-backend
sudo systemctl start iptrack-backend

# 检查状态
sudo systemctl status iptrack-backend
```

## 五、部署前端

### 5.1 安装依赖

```bash
cd /opt/IP-TRACK/frontend
npm install
```

### 5.2 配置环境变量

```bash
cat > .env.production << EOF
VITE_API_BASE_URL=http://YOUR_SERVER_IP:8100
EOF
```

**重要**: 替换 `YOUR_SERVER_IP` 为你的服务器 IP 地址。

### 5.3 构建前端

```bash
npm run build
```

构建完成后，生成的文件在 `dist/` 目录。

### 5.4 安装 Nginx

```bash
# CentOS/RHEL
sudo yum install -y nginx

# Ubuntu/Debian
sudo apt install -y nginx

sudo systemctl enable nginx
```

### 5.5 配置 Nginx

```bash
sudo tee /etc/nginx/conf.d/iptrack.conf > /dev/null << 'EOF'
server {
    listen 8001;
    server_name _;

    root /opt/IP-TRACK/frontend/dist;
    index index.html;

    # Gzip compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理（可选）
    location /api/ {
        proxy_pass http://localhost:8100;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

# 测试配置
sudo nginx -t

# 启动 Nginx
sudo systemctl start nginx
sudo systemctl status nginx
```

## 六、配置防火墙

```bash
# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --permanent --add-port=8100/tcp
sudo firewall-cmd --reload

# Ubuntu/Debian (ufw)
sudo ufw allow 8001/tcp
sudo ufw allow 8100/tcp
sudo ufw reload
```

## 七、验证部署

### 7.1 检查所有服务状态

```bash
# 检查后端
sudo systemctl status iptrack-backend

# 检查 Nginx
sudo systemctl status nginx

# 检查 PostgreSQL
sudo systemctl status postgresql-16

# 检查 Redis
sudo systemctl status redis
```

### 7.2 访问系统

- **前端**: http://YOUR_SERVER_IP:8001
- **后端 API**: http://YOUR_SERVER_IP:8100
- **API 文档**: http://YOUR_SERVER_IP:8100/api/docs

## 八、日常维护

### 8.1 查看日志

```bash
# 后端日志
sudo journalctl -u iptrack-backend -f

# Nginx 日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### 8.2 重启服务

```bash
# 重启后端
sudo systemctl restart iptrack-backend

# 重启前端
sudo systemctl restart nginx
```

### 8.3 更新代码

```bash
# 1. 拉取最新代码
cd /opt/IP-TRACK
git pull

# 2. 更新后端
cd backend
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart iptrack-backend

# 3. 更新前端
cd ../frontend
npm install
npm run build
sudo systemctl restart nginx
```

## 九、故障排查

### 9.1 后端无法启动

```bash
# 检查日志
sudo journalctl -u iptrack-backend -n 50

# 检查数据库连接
psql -U iptrack -d iptrack -h localhost

# 检查 Redis 连接
redis-cli ping
```

### 9.2 前端无法访问

```bash
# 检查 Nginx 配置
sudo nginx -t

# 检查 Nginx 日志
sudo tail -f /var/log/nginx/error.log

# 检查端口占用
sudo netstat -tlnp | grep 8001
```

### 9.3 CORS 错误

编辑 `/opt/IP-TRACK/backend/.env`，添加你的服务器 IP 到 CORS 列表：

```bash
BACKEND_CORS_ORIGINS=["http://localhost:8001","http://YOUR_SERVER_IP:8001"]
```

重启后端：
```bash
sudo systemctl restart iptrack-backend
```

## 十、安全建议

1. **修改默认密码**: 更改数据库密码和加密密钥
2. **使用 HTTPS**: 配置 SSL 证书（Let's Encrypt）
3. **限制访问**: 使用防火墙限制只允许内网访问
4. **定期备份**: 备份数据库和配置文件
5. **更新系统**: 定期更新系统和依赖包

## 十一、备份和恢复

### 备份数据库

```bash
pg_dump -U iptrack iptrack > /backup/iptrack_$(date +%Y%m%d).sql
```

### 恢复数据库

```bash
psql -U iptrack iptrack < /backup/iptrack_20260131.sql
```

## 支持

如有问题，请查看：
- GitHub Issues: https://github.com/YOUR_USERNAME/IP-TRACK/issues
- API 文档: http://YOUR_SERVER_IP:8100/api/docs
