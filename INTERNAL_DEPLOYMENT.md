# Internal Deployment —— 运维 / 备份 / 监控 / 故障处置

> **本文定位**：系统已经部署好之后，日常运维怎么管、怎么备份、出问题怎么查。
>
> - 第一次部署（Docker）→ [QUICK_START.md](QUICK_START.md)
> - 没有 Docker，用 systemd + Nginx → [MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md)
> - 主机名 / Last Boot Time / OS 识别专项问题 → [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)

---

## 1. 运行形态速查

| 容器 | 镜像 | 宿主机端口 | 数据卷 / 挂载 |
|---|---|---|---|
| `iptrack-postgres` | postgres:16-alpine | `127.0.0.1:5432` | 卷 `ip-track_postgres_data`；`./database/init` 仅首次初始化 |
| `iptrack-redis` | redis:7-alpine | `127.0.0.1:6379` | 卷 `ip-track_redis_data` |
| `iptrack-backend-core` | `ip-track-backend:latest` | `127.0.0.1:8101 → 8100` | `./backend/src`、`./backend/logs` |
| `iptrack-backend-ipam` | `ip-track-backend:latest` | `127.0.0.1:8102 → 8100` | `./backend/src`、`./backend/logs` |
| `iptrack-backend-collector` | `ip-track-backend:latest` | `127.0.0.1:8103 → 8100` | `./backend/src`、`./backend/logs` |
| `iptrack-frontend` | `Dockerfile.dev` (Vite) | `${FRONTEND_PORT:-8001} → 5173` | `./frontend/src`、`public`、`vite.config.ts` |

- 三个后端**容器内统一 8100**；8101/8102/8103 只是宿主映射，容器间通信必须用 8100。
- 配置来源：宿主机 `/opt/IP-Track/.env`（由 `setup.sh` 生成，含 `ENCRYPTION_KEY`、数据库/Redis 密码）。
- 卷名前缀来自目录名（`/opt/IP-Track` → `ip-track_*`）。目录改名后前缀会变，用 `docker volume ls | grep postgres_data` 确认。

---

## 2. 日常巡检（1 分钟）

```bash
cd /opt/IP-Track

# 1) 容器状态：6 个都应 Up，后端与数据库/Redis 应为 healthy
docker compose ps

# 2) 健康检查（8001 是 Vite 页面，没有 /health，检查根路径）
for p in 8101 8102 8103; do
  printf "backend %s " $p; curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:$p/health
done
printf "frontend "; curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/

# 3) 数据库与 Redis
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SELECT 1;"
docker exec -it iptrack-redis sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping'

# 4) 磁盘与资源
df -h /; docker system df; docker stats --no-stream
```

> 前端是 Vite dev server，`/health` 未定义时会返回 404，这属正常；只要 `curl http://127.0.0.1:8001` 返回 200 即可。

正常基线：

```bash
curl --noproxy '*' -s -o /dev/null -w "switches %{http_code}\n" "http://127.0.0.1:8101/api/v1/switches?limit=1"   # 200
curl --noproxy '*' -s -o /dev/null -w "auth/me %{http_code}\n" http://127.0.0.1:8101/api/v1/auth/me              # 401（未登录）
curl --noproxy '*' -s -o /dev/null -w "docs %{http_code}\n" http://127.0.0.1:8101/docs                            # 404（默认关闭）
```

---

## 3. 日志

```bash
cd /opt/IP-Track

# 实时
docker compose logs -f backend-core
docker compose logs -f backend-ipam
docker compose logs -f backend-collector
docker compose logs -f frontend

# 最近一段
docker compose logs --since 30m backend-collector
docker compose logs --tail=200 backend-core

# 过滤
docker compose logs --tail=500 backend-collector | grep -iE "error|exception|timeout|snmp"
docker compose logs --tail=500 backend-core      | grep -iE "error|exception|认证|登录"
```

文件日志（由 `LOG_FILE_ENABLED` 控制，默认开启）：

- 容器内 `/app/logs/iptrack.log`，错误另写 `error.log`；
- 宿主机对应 `./backend/logs/`；
- loguru 按 10MB 轮转、保留 5 份并压缩（`LOG_FILE_MAX_BYTES` / `LOG_FILE_BACKUP_COUNT`）。

清理旧日志：

```bash
find /opt/IP-Track/backend/logs -name "*.zip" -mtime +30 -delete
docker system df          # 查看镜像/卷/构建缓存占用
```

> 不要用 `docker system prune -a`：它会删除未使用镜像（包括 `ip-track-backend:latest`），下次启动就会失败。需要清理时先确认。

---

## 4. 改配置 / 改代码后，什么命令才生效（最容易踩坑）

| 你改了什么 | 生效方式 |
|---|---|
| `.env`、`docker-compose.yml` | `docker compose up -d`（**`restart` 不会重新读取环境变量**） |
| `backend/src/**` 代码 | `docker compose restart backend-core`（或对应服务）。容器启动命令**没有 `--reload`**，不会自动热加载 |
| `backend/requirements.txt`、`backend/Dockerfile` | 重新 `docker build -t ip-track-backend:latest ./backend`，再 `docker compose up -d` |
| `frontend/src/**`、`public/**` | Vite 热更新；不生效就 `docker compose restart frontend` |
| `frontend/vite.config.ts` | `docker compose up -d --force-recreate frontend` |
| `frontend/package.json` / 依赖 | `docker compose up -d --build frontend` |
| `.env` 的 `NODE_IMAGE` / `NPM_REGISTRY` / `NPM_PROXY`（前端构建参数） | `docker compose up -d --build frontend`（`restart` 不会重新构建镜像） |
| `database/migrations/*.sql` | 重新执行 `./setup.sh`（自动跳过已执行），或按下面第 6 节手工执行 |

> 只改 Python 代码时不要 `down` 整个栈，`restart` 单个服务即可，避免中断采集。

---

## 5. 升级更新

```bash
cd /opt/IP-Track

# 0) 先备份（见第 6 节），再更新
git pull origin main

# 1) 后端依赖有变化时重建镜像
#    判断方法：git diff 上一次的 backend/requirements.txt backend/Dockerfile
docker build -t ip-track-backend:latest ./backend

# 2) 数据库迁移（幂等）
./setup.sh

# 3) 若前端依赖有变化
docker compose up -d --build frontend

# 4) 重启后端并确认
docker compose restart backend-core backend-ipam backend-collector
docker compose ps
docker compose logs --tail=100 backend-core
```

确认迁移状态：

```bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack \
  -c "SELECT filename, applied_at FROM schema_migrations ORDER BY filename;"
```

---

## 6. 备份与恢复（**备份必须带上 `.env`**）

### 6.1 为什么必须备份 `.env`

`.env` 中的 `ENCRYPTION_KEY` 用于解密数据库中保存的交换机 / SNMP / BMC 密码，并参与登录令牌签发。**只恢复数据库、不恢复原来的 `ENCRYPTION_KEY`，所有已保存的设备凭据都会无法解密。**

### 6.2 手工备份

```bash
sudo mkdir -p /opt/backups/iptrack
D=$(date +%Y%m%d_%H%M%S)

# 数据库
docker exec -t iptrack-postgres pg_dump -U iptrack -d iptrack | gzip > /opt/backups/iptrack/db_$D.sql.gz

# 配置（含 ENCRYPTION_KEY）与编排文件
sudo cp /opt/IP-Track/.env             /opt/backups/iptrack/env_$D.bak
sudo cp /opt/IP-Track/docker-compose.yml /opt/backups/iptrack/compose_$D.yml
sudo chmod 600 /opt/backups/iptrack/*
```

### 6.3 自动备份脚本

```bash
sudo tee /opt/scripts/backup-iptrack.sh >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/opt/backups/iptrack"
RETENTION_DAYS=30
D=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

cd /opt/IP-Track
docker exec -t iptrack-postgres pg_dump -U iptrack -d iptrack | gzip > "$BACKUP_DIR/db_$D.sql.gz"
cp .env "$BACKUP_DIR/env_$D.bak"
chmod 600 "$BACKUP_DIR/db_$D.sql.gz" "$BACKUP_DIR/env_$D.bak"

find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "env_*.bak"   -mtime +$RETENTION_DAYS -delete
echo "backup ok: $BACKUP_DIR/db_$D.sql.gz"
EOF

sudo chmod +x /opt/scripts/backup-iptrack.sh
( crontab -l 2>/dev/null; echo "0 2 * * * /opt/scripts/backup-iptrack.sh >> /var/log/iptrack-backup.log 2>&1" ) | crontab -
```

验证脚本：

```bash
sudo /opt/scripts/backup-iptrack.sh
ls -lh /opt/backups/iptrack | tail -5
```

### 6.4 恢复

```bash
cd /opt/IP-Track

# 1) 停止写入
docker compose stop backend-core backend-ipam backend-collector

# 2) 恢复数据库（会覆盖现有数据）
gunzip -c /opt/backups/iptrack/db_YYYYMMDD_HHMMSS.sql.gz \
  | docker exec -i iptrack-postgres psql -U iptrack -d iptrack

# 3) 恢复同一份 .env（ENCRYPTION_KEY 必须与备份时一致）
sudo cp /opt/backups/iptrack/env_YYYYMMDD_HHMMSS.bak /opt/IP-Track/.env
sudo chmod 600 /opt/IP-Track/.env

# 4) 启动（.env 变更用 up -d，不用 restart）
docker compose up -d

# 5) 验证
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SELECT count(*) FROM switches;"
curl --noproxy '*' -s -o /dev/null -w "core %{http_code}\n" http://127.0.0.1:8101/api/v1/switches?limit=1
```

> `pg_dump` 的备份恢复到**已有的**库即可。不要删除 `postgres_data` 卷，除非你确认可以从别处重建全部数据。

### 6.5 极端故障：卷损坏 / 迁移到新服务器

```bash
# 新服务器上部署同一版本代码后：
# 1) 停后端，导入数据库备份（同 6.4）
# 2) 放回 .env（含同一个 ENCRYPTION_KEY）
# 3) docker compose up -d

# 如需直接搬运卷（不推荐代替 pg_dump，仅作快照）：
docker run --rm -v ip-track_postgres_data:/data -v /opt/backups:/backup alpine \
  tar czf /backup/pgdata_$(date +%F).tar.gz -C /data .
```

---

## 7. 监控建议

系统**没有内置 Prometheus/Grafana**，建议从以下 5 个维度做外部巡检：

1. **容器存活**：`docker compose ps` 或 `docker inspect -f '{{.State.Status}}' iptrack-backend-core`；
2. **HTTP 健康**：轮询 `8101/8102/8103 /health`，非 200 告警；
3. **数据库**：`SELECT count(*) FROM pg_stat_activity;` 与 `SHOW max_connections;`，接近上限时告警；
4. **磁盘**：`df -h`、`docker system df`，镜像/日志/备份增长；
5. **业务指标**：`switches` 总数、`last_successful_collection` 过旧的交换机数量、`ip_scan_history` 失败记录。

```bash
# 近 24 小时采集失败的交换机（按实际表结构调整字段）
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "
SELECT id, name, last_successful_collection
FROM switches
WHERE last_successful_collection IS NULL
   OR last_successful_collection < NOW() - INTERVAL '24 hours'
ORDER BY id;"

# 最近的扫描记录
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "
SELECT id, subnet_id, status, scan_type, started_at, finished_at, error_message
FROM ip_scan_history ORDER BY id DESC LIMIT 10;"
```

调度周期默认值（以 `.env` 为准）：

| 任务 | 变量 | 默认 |
|---|---|---|
| 交换机在线状态检查 | `STATUS_CHECK_INTERVAL_SECONDS` | 300 秒 |
| ARP/MAC 自动采集 | `COLLECTION_INTERVAL_MINUTES` | 120 分钟 |
| IPAM 自动扫描 | `IPAM_SCAN_INTERVAL_MINUTES`（代码默认 30，示例文件 60） | 以 `.env` 为准 |
| 光模块采集 | `OPTICAL_MODULE_INTERVAL_MINUTES` | 720 分钟 |

---

## 8. 性能调优

### 8.1 应用并发（`.env`，改后 `docker compose up -d`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `COLLECTION_WORKERS` | 10 | 采集并发 |
| `COLLECTION_BATCH_SIZE` | 5 | 采集批大小 |
| `IP_LOOKUP_WORKERS` | 50 | 查询并发 |
| `IPAM_SCAN_WORKERS` | 20 | IPAM 扫描并发 |
| `OPTICAL_BATCH_SIZE` | 3 | 光模块批大小 |
| `DATABASE_POOL_SIZE` | 20（示例）/ 40（代码） | 单进程连接池；三个后端各有一份，注意总和不要超过 PG 的 `max_connections` |
| `REDIS_CACHE_TTL` | 300 | 查询缓存秒数 |
| `DEFAULT_SSH_TIMEOUT` | 30 | CLI 超时（秒） |

大网（300+ 交换机）参考：`COLLECTION_WORKERS=20`、`COLLECTION_BATCH_SIZE=5`、`COLLECTION_INTERVAL_MINUTES=180`、`IP_LOOKUP_WORKERS=100`、`DATABASE_POOL_SIZE=30`，并同步提高 PostgreSQL `max_connections`。

### 8.2 IPAM 资源上限

`docker-compose.yml` 给 IPAM 设了上限与预留（可用 `.env` 覆盖）：

```bash
IPAM_CPU_LIMIT=4.0
IPAM_MEMORY_LIMIT=4G
IPAM_CPU_RESERVE=2.0
IPAM_MEMORY_RESERVE=2G
```

内存较小的机器（4GB）请下调 `IPAM_MEMORY_LIMIT`，否则大子网扫描可能被 OOM kill（表现为容器反复重启）。

### 8.3 PostgreSQL

单机 Docker 部署不建议直接改容器内 `postgresql.conf`（重建容器会丢），推荐用 `command` 追加参数或统一在初始化时调整。常用参数（按内存）：

| 服务器内存 | shared_buffers | effective_cache_size | work_mem | max_connections |
|---|---|---|---|---|
| 4GB | 1GB | 3GB | 8MB | 100 |
| 8GB | 2GB | 6GB | 16MB | 150 |
| 16GB | 4GB | 12GB | 32MB | 200 |

### 8.4 Redis

通常无需调整。缓存类数据丢失不影响正确性（会回源数据库）。`REDIS_CACHE_TTL` 过大会让“采集后查询结果”更新变慢。

---

## 9. 故障排查

### 9.1 先做这三件事

```bash
cd /opt/IP-Track
docker compose ps
docker compose logs --tail=150 <服务名>
docker compose exec <服务名> env | grep -E "DATABASE_|REDIS_|ENCRYPTION"   # 注意：不要外发输出
```

### 9.2 常见故障对照表

| 现象 | 最可能原因 | 处理 |
|---|---|---|
| `docker compose up` 报 `pull access denied for ip-track-backend` | 后端镜像没构建 | `docker build -t ip-track-backend:latest ./backend` |
| 前端容器构建失败 / 拉不到 node 镜像 / npm 超时 | 基础镜像、npm 源或代理不通 | 在 `.env` 设置 `NODE_IMAGE` / `NPM_REGISTRY` / `NPM_PROXY`，再 `docker compose up -d --build frontend` |
| 页面能开，所有接口 500 | Vite 代理写成了 8101/8102/8103 | 容器内必须用 8100，检查 `VITE_PROXY_*` 与 `vite.config.ts`，`up -d frontend` |
| 接口 401 | 未登录（访客只读）或令牌过期 | 登录；JWT 默认 720 分钟 |
| 接口 403 | 已登录但权限不足 | 检查用户角色 |
| `/docs` 404 | 接口文档默认关闭 | `.env` 设 `API_DOCS_ENABLED=true` 后 `up -d` |
| 后端启动即退出，日志 `password authentication failed` | `.env` 中数据库密码与卷内实际密码不一致 | 恢复原 `.env`，或重置数据库用户密码 |
| 日志 `NOAUTH` / `invalid password` | `REDIS_PASSWORD` 与 Redis 启动密码不一致 | 统一 `.env` 中 `REDIS_PASSWORD`，`up -d redis` |
| 容器反复重启 | OOM、磁盘满、依赖（PG/Redis）不健康 | `docker stats --no-stream`、`df -h`、看日志退出原因 |
| 登录提示“初始管理员检查失败” | `users` 表不存在（迁移未跑） | 重新 `./setup.sh`，确认 `030_add_users.sql` 已执行 |
| 找不到管理员临时密码 | 日志已滚动 / 已创建过 | 空库前提下设 `INITIAL_ADMIN_PASSWORD` 重建；或由已有管理员重置 |
| 交换机一直“离线” | 状态检查周期 300 秒；或网络/ACL 不通 | 等待 5 分钟；从 collector 容器 `ping` 目标 |
| IPAM 扫描很慢/卡住 | 全量扫描会做 DNS/SNMP 增强 | 用快速扫描；检查 `IPAM_SCAN_HARD_TIMEOUT_SECONDS` |
| 采集成功但仍查不到 IP | 查询是**缓存模式**，依赖已有 ARP/MAC | 先采集、后查询；确认 IP 在该交换机 ARP 表内 |
| 旧命令 `docker logs iptrack-backend` 无效 | 已拆成 3 个后端容器 | 用 `backend-core / -ipam / -collector` |
| `install_nmap.sh` 执行失败 | 脚本引用旧服务名 `backend`、旧容器 `iptrack-backend` | 不要使用该脚本；nmap 当前不参与 IPAM 扫描 |

### 9.3 容器反复重启时

```bash
docker compose ps
docker inspect -f '{{.State.ExitCode}} {{.State.OOMKilled}}' iptrack-backend-ipam
docker compose logs --tail=200 backend-ipam
docker stats --no-stream
df -h
```

- `OOMKilled=true` → 调低扫描并发或提高 `IPAM_MEMORY_LIMIT`；
- 退出码 1 且日志有配置错误 → 检查 `.env`；
- 依赖服务不健康 → 先修 postgres/redis。

### 9.4 数据库连接池耗尽

```bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "SHOW max_connections;"
```

三个后端各有一个连接池（`DATABASE_POOL_SIZE`），总需求约为三者之和再加余量。调大 `max_connections` 前先确认内存足够。

### 9.5 登录与权限

- 未登录 = 只读访客：`GET/HEAD/OPTIONS` 放行，`/api/v1/auth/` 始终要求登录；
- 初始管理员只在用户表为空时创建一次，临时密码只在日志出现一次：

```bash
docker compose logs backend-core | grep 初始管理员
```

- 首次登录强制改密（≥ 8 位，且不能与当前密码相同）。

---

## 10. 安全基线

1. **只暴露前端**：默认 `.env` 中 `POSTGRES_BIND`、`REDIS_BIND`、`BACKEND_BIND` 都是 `127.0.0.1`，不要改成 `0.0.0.0`，除非前面有防火墙/网关；
2. `.env` 权限 `600`，不要提交进 Git、不要截图外发；
3. 生产建议在 8001 前置 HTTPS（Nginx/Caddy），或加内网 IP 白名单；
4. 初始管理员登录后立即改密；`INITIAL_ADMIN_PASSWORD` 用过即从 `.env` 删除；
5. 接口文档默认关闭，排障临时开启后记得关闭；
6. 交换机/服务器凭据使用只读或最小权限账号；
7. 定期验证备份可恢复（只备份不验证等于没有备份）。

---

## 11. 文档地图

| 文档 | 内容 |
|---|---|
| [README.md](README.md) | 项目总览、功能清单 |
| [QUICK_START.md](QUICK_START.md) | Docker 首次部署 + 首次使用 |
| [MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md) | 无 Docker 的 systemd + Nginx 部署 |
| [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) | 主机名 / Last Boot Time / OS 识别专项排障 |
| **INTERNAL_DEPLOYMENT.md（本文）** | 运维、备份恢复、监控、性能、故障处置 |

---

**验证状态**：容器名/端口/卷名（`ip-track_postgres_data`、`ip-track_redis_data`）、健康检查、`switches` 200、`auth/me` 401、`/docs` 404 已在运行环境实测；环境变量名与 `backend/src/core/config.py`、`.env.example` 逐项核对；容器启动命令确认**没有 `--reload`**。**未验证**：OOM、卷损坏、跨服务器恢复等破坏性场景（未实际执行），以及大网性能调优的具体数值效果。

**最后更新**：2026-11-05
