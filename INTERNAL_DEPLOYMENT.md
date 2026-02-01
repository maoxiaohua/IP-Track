# IP Track System - 内网部署指南

本文档提供完整的内网部署步骤、配置说明和故障排查指南。

## 📋 目录

- [部署前准备](#部署前准备)
- [方式一：Docker 部署（推荐）](#方式一docker-部署推荐)
- [方式二：手动部署](#方式二手动部署)
- [配置说明](#配置说明)
- [安全加固](#安全加固)
- [故障排查](#故障排查)
- [维护和备份](#维护和备份)

---

## 部署前准备

### 系统要求

**最低配置**：
- CPU: 2 核
- 内存: 4GB
- 硬盘: 20GB
- 操作系统: CentOS 7+, Ubuntu 18.04+, Debian 10+

**推荐配置**：
- CPU: 4 核
- 内存: 8GB
- 硬盘: 50GB
- 操作系统: CentOS 8+, Ubuntu 20.04+, Rocky Linux 8+

### 网络要求

1. **服务器网络**：
   - 能够访问所有需要管理的交换机
   - 开放端口：8001（前端）、8101（后端）
   - 如果使用防火墙，需要开放相应端口

2. **交换机要求**：
   - SSH 已启用
   - 有管理员账号和密码
   - 网络可达（能 ping 通）

### 软件依赖

**Docker 部署**：
- Docker 20.10+
- Docker Compose 2.0+

**手动部署**：
- Python 3.11+
- Node.js 18+
- PostgreSQL 16+
- Redis 6+
- Nginx（可选）

---

## 方式一：Docker 部署（推荐）

### 1. 安装 Docker 和 Docker Compose

#### CentOS/Rocky Linux

```bash
# 安装 Docker
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 验证安装
docker --version
docker compose version
```

#### Ubuntu/Debian

```bash
# 更新包索引
sudo apt-get update

# 安装依赖
sudo apt-get install -y ca-certificates curl gnupg

# 添加 Docker 官方 GPG 密钥
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 Docker 仓库
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 验证安装
docker --version
docker compose version
```

### 2. 获取项目代码

```bash
# 从 GitHub 克隆（推荐）
cd /opt
git clone https://github.com/YOUR_USERNAME/IP-TRACK.git
cd IP-TRACK

# 或者从其他服务器复制
scp -r user@source-server:/opt/ip-track /opt/
cd /opt/ip-track
```

### 3. 配置环境变量

```bash
# 生成加密密钥
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 复制环境变量模板
cp backend/.env.example backend/.env

# 编辑配置文件
vi backend/.env
```

**backend/.env 配置示例**：

```env
# 应用配置
APP_NAME=IP Track System
APP_VERSION=2.0.0
DEBUG=false

# API 配置
API_V1_PREFIX=/api/v1
BACKEND_CORS_ORIGINS=["http://YOUR_SERVER_IP:8001"]

# 数据库配置
DATABASE_URL=postgresql+asyncpg://iptrack:YOUR_DB_PASSWORD@postgres:5432/iptrack

# Redis 配置
REDIS_URL=redis://redis:6379/0
REDIS_CACHE_TTL=300

# 安全配置 - 重要：使用上面生成的密钥
ENCRYPTION_KEY=YOUR_GENERATED_KEY_HERE

# 交换机连接配置
DEFAULT_SSH_TIMEOUT=30
MAX_CONCURRENT_CONNECTIONS=10
```

### 4. 配置 Docker Compose

编辑 `docker-compose.yml`，修改以下内容：

```yaml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD: YOUR_SECURE_PASSWORD  # 修改为强密码

  backend:
    ports:
      - "8101:8100"  # 如需修改端口，改左边的数字

  frontend:
    ports:
      - "8001:80"    # 如需修改端口，改左边的数字
```

### 5. 启动服务

```bash
# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f backend
docker compose logs -f frontend
```

### 6. 初始化数据库

数据库会自动初始化，但你可以验证：

```bash
# 进入数据库容器
docker exec -it iptrack-postgres psql -U iptrack -d iptrack

# 查看表
\dt

# 退出
\q
```

### 7. 访问系统

打开浏览器访问：
- 前端：`http://YOUR_SERVER_IP:8001`
- 后端 API：`http://YOUR_SERVER_IP:8101/api/docs`

---

## 方式二：手动部署

### 1. 安装系统依赖

#### CentOS/Rocky Linux

```bash
# 安装 Python 3.11
sudo yum install -y python3.11 python3.11-devel

# 安装 Node.js 18
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install -y nodejs

# 安装 PostgreSQL 16
sudo yum install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-8-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo yum install -y postgresql16-server postgresql16
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl start postgresql-16
sudo systemctl enable postgresql-16

# 安装 Redis
sudo yum install -y redis
sudo systemctl start redis
sudo systemctl enable redis

# 安装 Nginx
sudo yum install -y nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

#### Ubuntu/Debian

```bash
# 安装 Python 3.11
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-dev python3.11-venv

# 安装 Node.js 18
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# 安装 PostgreSQL 16
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
sudo apt-get update
sudo apt-get install -y postgresql-16

# 安装 Redis
sudo apt-get install -y redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 安装 Nginx
sudo apt-get install -y nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

### 2. 配置 PostgreSQL

```bash
# 切换到 postgres 用户
sudo -u postgres psql

# 创建数据库和用户
CREATE DATABASE iptrack;
CREATE USER iptrack WITH PASSWORD 'YOUR_SECURE_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE iptrack TO iptrack;
\q

# 配置 PostgreSQL 允许本地连接
sudo vi /var/lib/pgsql/16/data/pg_hba.conf
# 添加以下行：
# local   all   iptrack   md5
# host    all   iptrack   127.0.0.1/32   md5

# 重启 PostgreSQL
sudo systemctl restart postgresql-16
```

### 3. 初始化数据库

```bash
cd /opt/ip-track

# 执行初始化脚本
psql -U iptrack -d iptrack -f database/init/01_create_extensions.sql
psql -U iptrack -d iptrack -f database/init/02_create_schemas.sql
psql -U iptrack -d iptrack -f database/init/03_create_tables.sql
psql -U iptrack -d iptrack -f database/init/04_create_indexes.sql
psql -U iptrack -d iptrack -f database/init/03_migration_add_ipam.sql
```

### 4. 部署后端

```bash
cd /opt/ip-track/backend

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
vi .env
# 修改数据库连接、Redis 连接等配置

# 创建日志目录
mkdir -p logs

# 测试运行
cd src
python main.py
# 按 Ctrl+C 停止

# 创建 systemd 服务
sudo vi /etc/systemd/system/iptrack-backend.service
```

**iptrack-backend.service 内容**：

```ini
[Unit]
Description=IP Track Backend Service
After=network.target postgresql-16.service redis.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ip-track/backend/src
Environment="PATH=/opt/ip-track/backend/venv/bin"
ExecStart=/opt/ip-track/backend/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# 启动后端服务
sudo systemctl daemon-reload
sudo systemctl start iptrack-backend
sudo systemctl enable iptrack-backend
sudo systemctl status iptrack-backend
```

### 5. 部署前端

```bash
cd /opt/ip-track/frontend

# 安装依赖
npm install

# 配置环境变量
echo "VITE_API_BASE_URL=http://YOUR_SERVER_IP:8101" > .env.production

# 构建生产版本
npm run build

# 复制构建文件到 Nginx
sudo mkdir -p /var/www/iptrack
sudo cp -r dist/* /var/www/iptrack/

# 配置 Nginx
sudo vi /etc/nginx/conf.d/iptrack.conf
```

**iptrack.conf 内容**：

```nginx
server {
    listen 8001;
    server_name _;

    root /var/www/iptrack;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://127.0.0.1:8101;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
# 测试 Nginx 配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

---

## 配置说明

### 端口配置

默认端口：
- 前端：8001
- 后端：8101
- PostgreSQL：5432
- Redis：6379

修改端口：
1. Docker 部署：修改 `docker-compose.yml`
2. 手动部署：修改 Nginx 配置和后端 `main.py`

### 防火墙配置

#### CentOS/Rocky Linux (firewalld)

```bash
# 开放端口
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --permanent --add-port=8101/tcp
sudo firewall-cmd --reload

# 查看开放的端口
sudo firewall-cmd --list-ports
```

#### Ubuntu/Debian (ufw)

```bash
# 开放端口
sudo ufw allow 8001/tcp
sudo ufw allow 8101/tcp
sudo ufw reload

# 查看状态
sudo ufw status
```

### 数据库配置优化

编辑 PostgreSQL 配置文件：

```bash
sudo vi /var/lib/pgsql/16/data/postgresql.conf
```

推荐配置（根据服务器内存调整）：

```ini
# 内存配置（8GB 内存服务器）
shared_buffers = 2GB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
work_mem = 16MB

# 连接配置
max_connections = 100

# 日志配置
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_rotation_age = 1d
log_rotation_size = 100MB
```

重启 PostgreSQL：

```bash
sudo systemctl restart postgresql-16
```

---

## 安全加固

### 1. 修改默认密码

```bash
# 修改数据库密码
sudo -u postgres psql
ALTER USER iptrack WITH PASSWORD 'NEW_STRONG_PASSWORD';
\q

# 更新 backend/.env 中的数据库密码
```

### 2. 配置 HTTPS（推荐）

使用 Let's Encrypt 免费证书：

```bash
# 安装 certbot
sudo yum install -y certbot python3-certbot-nginx  # CentOS
sudo apt-get install -y certbot python3-certbot-nginx  # Ubuntu

# 获取证书（需要域名）
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo systemctl enable certbot-renew.timer
```

### 3. 限制访问

在 Nginx 配置中添加 IP 白名单：

```nginx
server {
    listen 8001;

    # 只允许内网访问
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;

    # ... 其他配置
}
```

### 4. 配置日志轮转

创建 `/etc/logrotate.d/iptrack`：

```
/opt/ip-track/backend/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 root root
    sharedscripts
}
```

---

## 故障排查

### 问题 1：无法访问前端

**症状**：浏览器无法打开 http://SERVER_IP:8001

**排查步骤**：

```bash
# 1. 检查前端容器/服务状态
docker compose ps frontend  # Docker 部署
sudo systemctl status nginx  # 手动部署

# 2. 检查端口是否监听
sudo netstat -tlnp | grep 8001
sudo ss -tlnp | grep 8001

# 3. 检查防火墙
sudo firewall-cmd --list-ports  # CentOS
sudo ufw status  # Ubuntu

# 4. 查看日志
docker compose logs frontend  # Docker
sudo tail -f /var/log/nginx/error.log  # 手动部署

# 5. 测试本地访问
curl http://localhost:8001
```

**解决方案**：
- 如果容器未运行：`docker compose up -d frontend`
- 如果端口未监听：检查 Nginx 配置，重启服务
- 如果防火墙阻止：开放 8001 端口
- 如果 Nginx 配置错误：`sudo nginx -t` 检查配置

### 问题 2：后端 API 500 错误

**症状**：API 请求返回 500 Internal Server Error

**排查步骤**：

```bash
# 1. 查看后端日志
docker compose logs backend  # Docker
sudo journalctl -u iptrack-backend -f  # 手动部署
tail -f /opt/ip-track/backend/logs/app.log

# 2. 检查数据库连接
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SELECT 1;"

# 3. 检查 Redis 连接
docker exec -it iptrack-redis redis-cli ping

# 4. 检查环境变量
docker exec iptrack-backend env | grep DATABASE_URL
```

**常见原因**：
- 数据库连接失败：检查 DATABASE_URL 配置
- Redis 连接失败：检查 REDIS_URL 配置
- 加密密钥错误：检查 ENCRYPTION_KEY 配置
- Python 依赖缺失：重新安装依赖

### 问题 3：无法连接交换机

**症状**：测试交换机连接失败

**排查步骤**：

```bash
# 1. 测试网络连通性
ping SWITCH_IP

# 2. 测试 SSH 连接
ssh username@SWITCH_IP

# 3. 检查后端是否能访问交换机
docker exec iptrack-backend ping -c 3 SWITCH_IP

# 4. 检查 SSH 端口
telnet SWITCH_IP 22
nc -zv SWITCH_IP 22
```

**常见原因**：
- 网络不通：检查路由和防火墙
- SSH 未启用：在交换机上启用 SSH
- 认证失败：检查用户名和密码
- 超时设置太短：增加 DEFAULT_SSH_TIMEOUT

### 问题 4：IPAM 扫描失败

**症状**：IPAM 扫描显示所有设备离线

**排查步骤**：

```bash
# 1. 测试 ping 功能
docker exec iptrack-backend ping -c 3 TARGET_IP

# 2. 检查 ICMP 是否被阻止
# 在目标网络测试 ping

# 3. 查看扫描日志
docker compose logs backend | grep -i scan

# 4. 检查 nmap 是否安装（用于 OS 检测）
docker exec iptrack-backend which nmap
```

**解决方案**：
- 如果 ping 不通：检查网络和防火墙
- 如果 ICMP 被阻止：联系网络管理员
- 如果 nmap 未安装：`docker exec iptrack-backend apt-get install -y nmap`

### 问题 5：数据库连接池耗尽

**症状**：大量请求后出现数据库连接错误

**排查步骤**：

```bash
# 查看当前连接数
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SELECT count(*) FROM pg_stat_activity;"

# 查看最大连接数
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SHOW max_connections;"
```

**解决方案**：

增加 PostgreSQL 最大连接数：

```bash
# 编辑配置
docker exec -it iptrack-postgres vi /var/lib/postgresql/data/postgresql.conf
# 修改：max_connections = 200

# 重启数据库
docker compose restart postgres
```

### 问题 6：前端图表不显示

**症状**：IPAM 页面图表区域空白

**排查步骤**：

```bash
# 1. 检查浏览器控制台错误
# 按 F12 打开开发者工具，查看 Console 标签

# 2. 检查前端容器日志
docker compose logs frontend

# 3. 验证 echarts 是否安装
docker exec iptrack-frontend ls node_modules | grep echarts

# 4. 重新构建前端
docker compose up -d --build frontend
```

### 问题 7：导出功能不工作

**症状**：点击导出按钮没有反应

**排查步骤**：

```bash
# 1. 检查浏览器控制台
# F12 → Console 查看错误

# 2. 验证 xlsx 库是否安装
docker exec iptrack-frontend ls node_modules | grep xlsx

# 3. 检查数据是否为空
# 确保有子网数据可以导出
```

### 问题 8：Docker 容器频繁重启

**症状**：容器状态显示 Restarting

**排查步骤**：

```bash
# 查看容器状态
docker compose ps

# 查看容器日志
docker compose logs CONTAINER_NAME

# 查看容器资源使用
docker stats

# 检查磁盘空间
df -h
```

**常见原因**：
- 内存不足：增加服务器内存或减少容器资源限制
- 磁盘空间不足：清理磁盘空间
- 配置错误：检查环境变量和配置文件
- 依赖服务未就绪：检查数据库和 Redis

---

## 维护和备份

### 日常维护

#### 1. 查看系统状态

```bash
# Docker 部署
docker compose ps
docker compose logs --tail=100

# 手动部署
sudo systemctl status iptrack-backend
sudo systemctl status nginx
sudo systemctl status postgresql-16
sudo systemctl status redis
```

#### 2. 更新系统

```bash
# 停止服务
docker compose down

# 拉取最新代码
git pull origin main

# 重新构建和启动
docker compose up -d --build

# 查看日志确认启动成功
docker compose logs -f
```

#### 3. 清理日志

```bash
# 清理 Docker 日志
docker compose logs --tail=0 > /dev/null

# 清理应用日志
find /opt/ip-track/backend/logs -name "*.log" -mtime +30 -delete

# 清理 PostgreSQL 日志
find /var/lib/pgsql/16/data/log -name "*.log" -mtime +30 -delete
```

### 数据备份

#### 1. 数据库备份

**自动备份脚本** (`/opt/scripts/backup-iptrack-db.sh`)：

```bash
#!/bin/bash

# 配置
BACKUP_DIR="/opt/backups/iptrack"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="iptrack_db_${DATE}.sql"
RETENTION_DAYS=30

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份数据库
docker exec iptrack-postgres pg_dump -U iptrack iptrack > $BACKUP_DIR/$BACKUP_FILE

# 压缩备份
gzip $BACKUP_DIR/$BACKUP_FILE

# 删除旧备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +$RETENTION_DAYS -delete

echo "Backup completed: $BACKUP_FILE.gz"
```

```bash
# 设置执行权限
chmod +x /opt/scripts/backup-iptrack-db.sh

# 添加到 crontab（每天凌晨 2 点备份）
crontab -e
# 添加：0 2 * * * /opt/scripts/backup-iptrack-db.sh
```

#### 2. 恢复数据库

```bash
# 解压备份文件
gunzip /opt/backups/iptrack/iptrack_db_20260201_020000.sql.gz

# 恢复数据库
docker exec -i iptrack-postgres psql -U iptrack -d iptrack < /opt/backups/iptrack/iptrack_db_20260201_020000.sql
```

#### 3. 完整系统备份

```bash
# 备份整个项目目录
tar -czf /opt/backups/iptrack_full_$(date +%Y%m%d).tar.gz \
  /opt/ip-track \
  --exclude=/opt/ip-track/backend/venv \
  --exclude=/opt/ip-track/frontend/node_modules \
  --exclude=/opt/ip-track/backend/logs

# 备份 Docker 卷
docker run --rm \
  -v iptrack_postgres_data:/data \
  -v /opt/backups:/backup \
  alpine tar czf /backup/postgres_data_$(date +%Y%m%d).tar.gz /data
```

### 监控建议

#### 1. 系统资源监控

使用 `htop` 或 `glances` 监控：

```bash
# 安装 htop
sudo yum install -y htop  # CentOS
sudo apt-get install -y htop  # Ubuntu

# 运行
htop
```

#### 2. 日志监控

```bash
# 实时监控错误日志
docker compose logs -f | grep -i error

# 监控后端日志
tail -f /opt/ip-track/backend/logs/app.log | grep -i error
```

#### 3. 磁盘空间监控

```bash
# 检查磁盘使用
df -h

# 检查 Docker 磁盘使用
docker system df

# 清理 Docker 未使用的资源
docker system prune -a
```

---

## 性能优化

### 1. PostgreSQL 优化

根据服务器配置调整 `postgresql.conf`：

```ini
# 4GB 内存服务器
shared_buffers = 1GB
effective_cache_size = 3GB
maintenance_work_mem = 256MB
work_mem = 8MB

# 8GB 内存服务器
shared_buffers = 2GB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
work_mem = 16MB

# 16GB 内存服务器
shared_buffers = 4GB
effective_cache_size = 12GB
maintenance_work_mem = 1GB
work_mem = 32MB
```

### 2. Redis 优化

编辑 Redis 配置：

```bash
# 设置最大内存
maxmemory 512mb
maxmemory-policy allkeys-lru

# 持久化配置
save 900 1
save 300 10
save 60 10000
```

### 3. 应用优化

在 `backend/.env` 中调整：

```env
# 增加并发连接数
MAX_CONCURRENT_CONNECTIONS=20

# 调整缓存时间
REDIS_CACHE_TTL=600

# 调整超时时间
DEFAULT_SSH_TIMEOUT=60
```

---

## 联系支持

如果遇到无法解决的问题：

1. 查看项目文档：`README.md`
2. 查看 API 文档：`http://YOUR_SERVER_IP:8101/api/docs`
3. 查看日志文件：`/opt/ip-track/backend/logs/`
4. 提交 Issue：GitHub Issues

---

**文档版本**: 2.0.0
**最后更新**: 2026-02-01
**维护者**: IP Track System Team
