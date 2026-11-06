# Manual Deployment —— 无 Docker 部署指南（systemd + Nginx）

> 适用对象：服务器**不能/不想使用 Docker**（典型场景：内网离线服务器），需要把 IP-Track 的三个后端服务与前端直接跑在宿主机上的工程师。
>
> 如果你能用 Docker，请优先使用 [QUICK_START.md](QUICK_START.md)，那是最省事、最不容易出错的路径。

---

## 0. 部署后的形态

| 进程 | 代码入口 | 监听地址 | 职责 |
|---|---|---|---|
| `iptrack-backend-core` | `main_core:app` | `127.0.0.1:8101` | 交换机、IP 查询、历史、告警、SNMP、BMC、登录 |
| `iptrack-backend-ipam` | `main_ipam:app` | `127.0.0.1:8102` | IPAM、子网扫描、子网存活探测 |
| `iptrack-backend-collector` | `main_collector:app` | `127.0.0.1:8103` | ARP/MAC/光模块采集、自动发现 |
| Nginx | 静态文件 + 反向代理 | `0.0.0.0:8001` | 提供前端页面，并把 `/api/*` 分发到三个后端 |

> 手动部署时三个后端各自监听 8101/8102/8103（与 Docker 不同：容器内部统一 8100，这里没有容器，直接按端口区分）。
> **唯一对外入口是 Nginx 的 8001**，后端不要直接暴露到公网。

---

## 1. 服务器要求

| 项目 | 要求 |
|---|---|
| 操作系统 | CentOS/RHEL 7+ 或 Ubuntu/Debian 20.04+ |
| Python | 3.11（3.10 可能可用但未验证） |
| Node.js | 18+（仅构建前端用，构建完可不需要） |
| PostgreSQL | 14+，推荐 16 |
| Redis | 6+（可无密码，建议设密码） |
| 内存 / 磁盘 | ≥ 4GB / ≥ 20GB |
| 系统工具 | `curl`、`ping`、`arp-scan`、`ipmitool`、`net-tools` |
| 网络 | 能访问被管理交换机的 TCP 22/23、UDP 161、ICMP |

> `nmap` **不需要安装**。当前扫描流程用 ping 的 TTL 值判断 OS 类型（必要时由 SNMP `sysDescr` 修正），不会调用 nmap；`install_nmap.sh` 脚本已失效，请勿执行。详见 [QUICK_START_GUIDE.md §1](QUICK_START_GUIDE.md#1-关于-nmap当前版本不参与扫描)。

---

## 2. 安装系统依赖

### 2.1 网络工具（**必须**）

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y iputils-ping arp-scan ipmitool net-tools curl

# CentOS / RHEL
sudo yum install -y iputils arp-scan ipmitool net-tools curl

# 不要安装 nmap：扫描流程不会调用它（OS 类型用 TTL 判断）
```

### 2.2 Python 3.11

```bash
# Ubuntu 22.04+ 自带的 python3 通常已是 3.10/3.11，先检查
python3 --version

# Ubuntu/Debian
sudo apt install -y python3 python3-venv python3-dev build-essential

# CentOS/RHEL
sudo yum install -y python3 python3-devel gcc
```

如果发行版自带版本低于 3.11，请用发行版提供的 `python3.11` 包或 pyenv 安装，不要用源码乱编。

### 2.3 Node.js 18+

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# CentOS/RHEL
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install -y nodejs

node --version    # 应 >= v18
npm --version
```

> 内网无法访问 nodesource 时，使用公司内部镜像源或离线 Node 压缩包；构建完成后宿主机不再需要 Node。

### 2.4 PostgreSQL 16

```bash
# Ubuntu/Debian（发行版仓库版本可能较低，够用即可）
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql

# CentOS/RHEL
sudo yum install -y postgresql-server postgresql-contrib
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

### 2.5 Redis

```bash
# Ubuntu/Debian
sudo apt install -y redis-server
sudo systemctl enable --now redis-server

# CentOS/RHEL
sudo yum install -y redis
sudo systemctl enable --now redis

redis-cli ping    # PONG
```

---

## 3. 放置代码

```bash
sudo mkdir -p /opt/IP-Track
# git clone YOUR_REPO_URL /opt/IP-Track   （或解压离线包）
cd /opt/IP-Track
ls backend/src/main_core.py database/migrations frontend/package.json
```

后文统一使用 `/opt/IP-Track` 作为代码目录；如果你的路径不同，替换系统服务与 Nginx 中的对应路径。

---

## 4. 初始化数据库

### 4.1 创建用户与库

```bash
sudo -u postgres psql <<'SQL'
CREATE USER iptrack WITH PASSWORD 'YOUR_DB_PASSWORD';
CREATE DATABASE iptrack OWNER iptrack;
SQL
```

> `YOUR_DB_PASSWORD` 请替换成强密码，并同步写进第 5 节的 `.env`。

### 4.2 执行建表脚本（**只在新库上执行一次**）

顺序很重要：先执行 `database/init/`，再执行 `database/migrations/`，都按文件名排序。

```bash
cd /opt/IP-Track

export PGPASSWORD='YOUR_DB_PASSWORD'
PSQL="psql -h 127.0.0.1 -U iptrack -d iptrack -v ON_ERROR_STOP=1"

# 1) 基础表结构（init 脚本带 IF NOT EXISTS，只应在新库上跑）
for f in $(ls database/init/*.sql | sort); do
  echo "▶ $f"
  $PSQL -f "$f"
done

# 2) 增量迁移，并用 schema_migrations 记录，避免重复执行
$PSQL -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());"

for f in $(ls database/migrations/*.sql | sort); do
  name=$(basename "$f")
  applied=$($PSQL -tAc "SELECT 1 FROM schema_migrations WHERE filename='$name'" | tr -d '[:space:]')
  [ -n "$applied" ] && continue
  echo "▶ $name"
  $PSQL -f "$f"
  $PSQL -c "INSERT INTO schema_migrations(filename) VALUES ('$name') ON CONFLICT DO NOTHING;"
done

$PSQL -c "SELECT count(*) AS migrations FROM schema_migrations;"
```

> ⚠️ 排序是字符串排序（`09_...` 会排在 `010_...` 前面），这是历史遗留结构，**不要手工调整顺序或跳着执行**。
> 迁移中 `030_add_users.sql` 会创建登录用户表；没有它，初始管理员无法创建，页面写操作全部不可用。

### 4.3 允许本地密码登录

编辑 `pg_hba.conf`（路径示例：`/etc/postgresql/16/main/pg_hba.conf` 或 `/var/lib/pgsql/data/pg_hba.conf`），确保有：

```
host    iptrack    iptrack    127.0.0.1/32    scram-sha-256
```

然后重启：

```bash
sudo systemctl restart postgresql     # CentOS: postgresql
```

验证：

```bash
PGPASSWORD='YOUR_DB_PASSWORD' psql -h 127.0.0.1 -U iptrack -d iptrack -c 'select 1;'
```

---

## 5. 部署后端

### 5.1 创建虚拟环境并安装依赖

```bash
cd /opt/IP-Track/backend
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> 内网需要 pip 镜像/代理：`pip install -i https://YOUR_MIRROR/simple -r requirements.txt`。
> `asyncpg` 若需要编译，先装好 `python3-dev` 与 `gcc`。

### 5.2 准备 `.env`（**关键**）

后端配置读取的是**进程工作目录下的 `.env`**。本指南把工作目录固定为 `/opt/IP-Track/backend`，因此 `.env` 必须放在那里。

必须使用**仓库根目录**的 `.env.example`（组件式配置），不要用旧的 `DATABASE_URL=...` 写法：

```bash
cd /opt/IP-Track
cp .env.example backend/.env

# 生成加密密钥（用于加密设备密码、签发登录令牌）
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

# 生成 Redis 密码（可选）
python3 -c "import secrets; print(secrets.token_hex(24))"
```

编辑 `/opt/IP-Track/backend/.env`，至少修改以下项：

```bash
# 数据库（手动部署在本机）
DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_USER=iptrack
DATABASE_PASSWORD=YOUR_DB_PASSWORD
DATABASE_NAME=iptrack

# Redis（本机）
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=            # 若 Redis 配了 requirepass，这里必须填同样的值
REDIS_BIND=127.0.0.1

# 安全：把上面生成的密钥填进来
ENCRYPTION_KEY=YOUR_GENERATED_KEY

# 允许浏览器访问来源（前端地址）
BACKEND_CORS_ORIGINS=["http://localhost:8001","http://YOUR_SERVER_IP:8001"]

# 可选：不设置则系统随机生成一次性管理员密码并打印到日志
# INITIAL_ADMIN_PASSWORD=YOUR_TEMP_ADMIN_PASSWORD
```

权限收紧：

```bash
chmod 600 /opt/IP-Track/backend/.env
```

> **`ENCRYPTION_KEY` 一旦确定就不要更换**，它用于解密数据库中已保存的交换机/SNMP/BMC 密码；更换会导致所有已保存凭据无法解密。备份数据库时必须一起备份这个文件。

### 5.3 先手工试跑

```bash
cd /opt/IP-Track/backend
source venv/bin/activate
export PYTHONPATH=/opt/IP-Track/backend/src

# 三个终端分别执行
uvicorn main_core:app      --host 127.0.0.1 --port 8101
uvicorn main_ipam:app      --host 127.0.0.1 --port 8102
uvicorn main_collector:app --host 127.0.0.1 --port 8103
```

验证：

```bash
curl -s http://127.0.0.1:8101/health
curl -s http://127.0.0.1:8102/health
curl -s http://127.0.0.1:8103/health
```

三个都返回 200 后按 Ctrl+C 停止，交给 systemd 托管。

### 5.4 配置 systemd

```bash
sudo tee /etc/systemd/system/iptrack-backend-core.service >/dev/null <<'EOF'
[Unit]
Description=IP Track Backend Core API
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/IP-Track/backend
Environment="PYTHONPATH=/opt/IP-Track/backend/src"
ExecStart=/opt/IP-Track/backend/venv/bin/uvicorn main_core:app --host 127.0.0.1 --port 8101
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/iptrack-backend-ipam.service >/dev/null <<'EOF'
[Unit]
Description=IP Track Backend IPAM API
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/IP-Track/backend
Environment="PYTHONPATH=/opt/IP-Track/backend/src"
ExecStart=/opt/IP-Track/backend/venv/bin/uvicorn main_ipam:app --host 127.0.0.1 --port 8102
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/iptrack-backend-collector.service >/dev/null <<'EOF'
[Unit]
Description=IP Track Backend Collector API
After=network.target postgresql.service redis-server.service
Wants=postgresql.service redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/IP-Track/backend
Environment="PYTHONPATH=/opt/IP-Track/backend/src"
ExecStart=/opt/IP-Track/backend/venv/bin/uvicorn main_collector:app --host 127.0.0.1 --port 8103
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector
systemctl status iptrack-backend-core --no-pager
```

> CentOS 的 Redis 服务名可能是 `redis` 而非 `redis-server`；如果 `systemctl status` 提示找不到依赖，把 `After/Wants` 中的名字改成实际服务名。

### 5.5 取管理员临时密码

```bash
sudo journalctl -u iptrack-backend-core --no-pager | grep 初始管理员
```

输出示例（密码只出现一次）：

```
已创建初始管理员账户，请立即登录并修改密码：
  用户名: admin
  临时密码: XXXXXXXXXXXX
```

如果 `.env` 中设置了 `INITIAL_ADMIN_PASSWORD`，日志只显示“密码来自 INITIAL_ADMIN_PASSWORD”，请使用该值登录。

首次登录会强制修改密码（至少 8 位）。**未登录状态是只读访客**，可浏览查询，不可增删改。

---

## 6. 部署前端

### 6.1 安装依赖并构建

```bash
cd /opt/IP-Track/frontend
npm ci            # 有 package-lock.json，使用 ci 保证依赖一致
npm run build     # 等价于 vue-tsc && vite build
ls dist/          # 构建产物
```

> 内网 npm：`npm ci --registry https://YOUR_NPM_MIRROR` 或配置 `.npmrc`。
> `npm run build` 会先做 TypeScript 检查；如果历史代码有类型告警导致构建失败，请勿删检查，先看报错。

前端**不需要** `.env.production`：页面通过同源 `/api/*` 访问后端，由 Nginx 代理，`VITE_API_BASE_URL` 保持为空即可。

### 6.2 安装 Nginx 并配置

```bash
sudo apt install -y nginx      # CentOS: sudo yum install -y nginx
sudo tee /etc/nginx/conf.d/iptrack.conf >/dev/null <<'EOF'
server {
    listen 8001;
    server_name _;

    root /opt/IP-Track/frontend/dist;
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript application/xml;

    # 前端单页应用
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 代理公共头
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 320s;      # IPAM 扫描/光模块采集耗时较长

    # IPAM 服务
    location /api/v1/ipam/          { proxy_pass http://127.0.0.1:8102; }
    location /api/v1/subnet-probe/  { proxy_pass http://127.0.0.1:8102; }

    # 采集 / 发现服务
    location /api/v1/network/           { proxy_pass http://127.0.0.1:8103; }
    location /api/v1/discovery/         { proxy_pass http://127.0.0.1:8103; }
    location /api/v1/command-templates/ { proxy_pass http://127.0.0.1:8103; }

    # 其余 API 走 Core
    location /api/ { proxy_pass http://127.0.0.1:8101; }
}
EOF

sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

> 前缀与顺序必须和前端 `vite.config.ts` 的代理规则一致；`/api/v1/subnet-probe/` 若遗漏，子网存活探测页面会 404/500。
> `/api/v1/command-templates/` 在 core 与 collector 中都有注册，这里按前端既有规则指向 collector 即可。

---

## 7. 防火墙

```bash
# CentOS firewalld
sudo firewall-cmd --permanent --add-port=8001/tcp
sudo firewall-cmd --reload

# Ubuntu ufw
sudo ufw allow 8001/tcp
sudo ufw reload
```

**不要**对公网开放 5432、6379、8101/8102/8103。

---

## 8. 验证部署

```bash
# 系统服务
systemctl status iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector nginx --no-pager

# 后端健康
curl -s -o /dev/null -w "core %{http_code}\n"      http://127.0.0.1:8101/health
curl -s -o /dev/null -w "ipam %{http_code}\n"      http://127.0.0.1:8102/health
curl -s -o /dev/null -w "collector %{http_code}\n" http://127.0.0.1:8103/health

# 经 Nginx 的只读接口（应 200）
curl -s -o /dev/null -w "switches %{http_code}\n" http://127.0.0.1:8001/api/v1/switches?limit=1

# 登录态接口未登录应为 401
curl -s -o /dev/null -w "auth/me %{http_code}\n" http://127.0.0.1:8001/api/v1/auth/me

# 前端页面
curl -s -o /dev/null -w "frontend %{http_code}\n" http://127.0.0.1:8001/
```

浏览器访问 `http://YOUR_SERVER_IP:8001`，登录后按 [QUICK_START.md 第 4 节](QUICK_START.md#4-第一次使用从空库到查出-ip-在哪台交换机的哪个口) 完成“加交换机 → 测试 → 采集 → 查询 IP”的闭环。

### 接口文档

默认关闭（`/docs` 返回 404）。需要时在 `/opt/IP-Track/backend/.env` 加：

```bash
API_DOCS_ENABLED=true
```

然后 `sudo systemctl restart iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector`，访问 `http://127.0.0.1:8101/docs` 等。生产用完请关闭。

---

## 9. 日常维护

### 9.1 日志

```bash
sudo journalctl -u iptrack-backend-core -f
sudo journalctl -u iptrack-backend-ipam -f
sudo journalctl -u iptrack-backend-collector -f
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

### 9.2 重启 / 停止

```bash
sudo systemctl restart iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector
sudo systemctl reload nginx
# 停止
sudo systemctl stop iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector
```

### 9.3 更新代码

```bash
cd /opt/IP-Track

# 1) 数据库迁移（幂等：已执行的会跳过；新增迁移会自动执行）
export PGPASSWORD='YOUR_DB_PASSWORD'
PSQL="psql -h 127.0.0.1 -U iptrack -d iptrack -v ON_ERROR_STOP=1"
for f in $(ls database/migrations/*.sql | sort); do
  name=$(basename "$f")
  applied=$($PSQL -tAc "SELECT 1 FROM schema_migrations WHERE filename='$name'" | tr -d '[:space:]')
  [ -n "$applied" ] && continue
  echo "▶ $name"; $PSQL -f "$f" || break
  $PSQL -c "INSERT INTO schema_migrations(filename) VALUES ('$name') ON CONFLICT DO NOTHING;"
done

# 2) 后端依赖
cd backend && source venv/bin/activate && pip install -r requirements.txt && cd ..

# 3) 前端
cd frontend && npm ci && npm run build && cd ..

# 4) 重启
sudo systemctl restart iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector
sudo systemctl reload nginx
```

### 9.4 备份与恢复

```bash
# 备份数据库 + .env（.env 内含 ENCRYPTION_KEY，必须一起备份）
sudo mkdir -p /backup/iptrack
PGPASSWORD='YOUR_DB_PASSWORD' pg_dump -h 127.0.0.1 -U iptrack -d iptrack \
  > /backup/iptrack/iptrack_$(date +%F).sql
sudo cp /opt/IP-Track/backend/.env /backup/iptrack/env_$(date +%F).bak
sudo chmod 600 /backup/iptrack/*

# 恢复
sudo systemctl stop iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector
PGPASSWORD='YOUR_DB_PASSWORD' psql -h 127.0.0.1 -U iptrack -d iptrack < iptrack_YYYY-MM-DD.sql
sudo cp env_YYYY-MM-DD.bak /opt/IP-Track/backend/.env
sudo systemctl start iptrack-backend-core iptrack-backend-ipam iptrack-backend-collector
```

（恢复时如果 `.env` 中的 `ENCRYPTION_KEY` 与备份时不同，已保存的设备密码将无法解密。）

---

## 10. 常见问题

### 10.1 后端启动即退出
```bash
sudo journalctl -u iptrack-backend-core -n 80 --no-pager
```
常见原因：
- 找不到模块 → `PYTHONPATH` 未设置（必须是 `/opt/IP-Track/backend/src`）；
- 读不到 `.env` → `WorkingDirectory` 不等于 `.env` 所在目录；
- 数据库连接失败 → `DATABASE_HOST/PASSWORD` 错误，或 `pg_hba.conf` 未允许 127.0.0.1 密码登录；
- Redis 认证失败 → `.env` 的 `REDIS_PASSWORD` 与 `redis.conf` 的 `requirepass` 不一致。

### 10.2 页面打开但接口 500 / 404
```bash
sudo nginx -t
sudo tail -n 100 /var/log/nginx/error.log
```
逐条核对第 6.2 节的 `location` 前缀；缺 `/api/v1/subnet-probe/` 会导致探测功能异常。

### 10.3 CORS 报错
在 `/opt/IP-Track/backend/.env` 的 `BACKEND_CORS_ORIGINS` 中加入实际访问地址（JSON 数组），重启三个后端。

### 10.4 登录不了 / 提示初始管理员检查失败
- 确认迁移 `030_add_users.sql` 已执行：
  ```bash
  PGPASSWORD='YOUR_DB_PASSWORD' psql -h 127.0.0.1 -U iptrack -d iptrack \
    -c "select filename from schema_migrations order by filename;"
  ```
- 确认日志中有“已创建初始管理员账户”：
  ```bash
  sudo journalctl -u iptrack-backend-core --no-pager | grep 初始管理员
  ```

### 10.5 状态一直显示离线
状态检查间隔为 **300 秒**，启动后请等待 5 分钟。排查连通性：
```bash
ping -c 3 SWITCH_IP
nc -zv SWITCH_IP 22          # 或 telnet SWITCH_IP 22
snmpwalk -v3 -l authPriv ... # 若使用 SNMPv3
```
并确认运行用户对 `arp-scan`、`ipmitool` 有执行权限（`arp-scan` 需要 root 或 `CAP_NET_RAW`）。

### 10.6 `arp-scan` 提示权限不足
systemd 单元以 `User=root` 运行即可；若要降权，需额外配置 capabilities，属于非必须优化。

---

## 11. 安全建议

1. `.env` 权限 `600`，包含数据库密码与 `ENCRYPTION_KEY`；
2. 只对外开放 8001，前端前置 HTTPS（Nginx + 证书）；
3. 初始管理员登录后立即修改密码，并删除/替换 `INITIAL_ADMIN_PASSWORD`；
4. 定期备份数据库 + `.env`；
5. 接口文档默认关闭，排障时临时打开，用完关闭；
6. 交换机凭据按最小权限配置（只读账号优先）。

---

## 12. 与其他文档的关系

| 文档 | 内容 |
|---|---|
| [QUICK_START.md](QUICK_START.md) | Docker 部署 + 首次使用（推荐首选） |
| **MANUAL_DEPLOYMENT.md（本文）** | 无 Docker 的 systemd + Nginx 部署 |
| [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) | SNMP / Last Boot Time / OS 识别专项排障 |
| [INTERNAL_DEPLOYMENT.md](INTERNAL_DEPLOYMENT.md) | 备份恢复、监控、性能调优、故障处置 |

---

**验证状态**：本文命令与 `docker-compose.yml`、`setup.sh`、`backend/src/core/config.py`、`main_*.py`、`vite.config.ts`、`backend/Dockerfile` 的配置方式逐一核对；系统工具清单取自 `backend/Dockerfile`。**未验证**：在真实无 Docker 主机上完整执行一遍（含 PostgreSQL/Redis 具体版本差异、systemd 服务名差异、Nginx 配置加载、`npm run build` 类型检查结果）。

**最后更新**：2026-11-05
