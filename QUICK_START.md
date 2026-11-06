# Quick Start —— Docker 部署快速上手

> 适用对象：**第一次接触本项目**、手上有一台 Linux 服务器，希望在 30 分钟内把系统跑起来，并完成一次真实 IP 查询的工程师。
>
> - 服务器**没有 Docker** → 请看 [MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md)
> - 已经部署好、要做日常运维/备份/监控 → 请看 [INTERNAL_DEPLOYMENT.md](INTERNAL_DEPLOYMENT.md)
> - SNMP 取不到主机名/Last Boot Time、OS 识别不准 → 请看 [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)

---

## 0. 先认识这套系统

系统由 **6 个容器**组成（不是单体应用）：

| 容器 | 镜像 / 入口 | 宿主机端口 | 职责 |
|---|---|---|---|
| `iptrack-postgres` | postgres:16-alpine | 127.0.0.1:5432 | 数据库 |
| `iptrack-redis` | redis:7-alpine | 127.0.0.1:6379 | 缓存 |
| `iptrack-backend-core` | `main_core.py` | 127.0.0.1:8101 → 容器内 8100 | 交换机、IP 查询、历史、告警、SNMP、BMC、用户登录 |
| `iptrack-backend-ipam` | `main_ipam.py` | 127.0.0.1:8102 → 容器内 8100 | IPAM 子网、扫描、子网存活探测 |
| `iptrack-backend-collector` | `main_collector.py` | 127.0.0.1:8103 → 容器内 8100 | ARP/MAC/光模块采集、自动发现 |
| `iptrack-frontend` | Vite dev server | 0.0.0.0:8001 → 容器内 5173 | Vue3 网页界面 |

### 最重要的两条规则

1. **三个后端容器内部都监听 8100**。宿主机上的 8101/8102/8103 只是映射端口，只能给宿主机用。容器之间、前端 Vite 代理一律用 **8100**。
2. 默认所有端口只绑定 `127.0.0.1`，**只有前端 8001 对外开放**。需要局域网/远程访问，见 [第 5 节](#5-局域网--远程访问)。

---

## 1. 前置条件

| 项目 | 要求 |
|---|---|
| 操作系统 | Linux（Ubuntu 20.04+ / CentOS 7+ 等） |
| Docker | Engine 20.10+，Compose v2（`docker compose`） |
| 宿主机软件 | `python3`、`curl`（安装脚本生成密钥和健康检查要用） |
| 硬件 | 最低 2 核 / 4GB 内存 / 20GB 磁盘；IPAM 默认给后端预留 2 核 2G |
| 网络 | 能访问 Docker Hub（或用内网镜像仓库）；能访问被管理交换机的 TCP 22/23、UDP 161、ICMP |

检查：

```bash
docker --version
docker compose version
python3 --version
curl --version | head -1
```

---

## 2. 部署（5 步）

### 第 1 步：把代码放到服务器

```bash
sudo mkdir -p /opt/IP-Track
# 方式一：git clone YOUR_REPO_URL /opt/IP-Track
# 方式二：将项目压缩包解压到 /opt/IP-Track
cd /opt/IP-Track
ls docker-compose.yml setup.sh   # 能列出即正确
```

### 第 2 步：构建后端镜像（**必做，否则后面一定失败**）

`docker-compose.yml` 中三个后端服务只写了 `image: ip-track-backend:latest`，**没有 `build:` 配置**，`setup.sh` 也不会构建镜像。全新服务器必须先手动构建一次：

```bash
cd /opt/IP-Track
docker build -t ip-track-backend:latest ./backend
```

确认：

```bash
docker images | grep ip-track-backend
# ip-track-backend   latest   ...   ...
```

> 后端镜像内已包含 `ping`、`arp-scan`、`net-tools`、`ipmitool`。`nmap` **不需要安装**：当前扫描流程用 TTL + SNMP 判断设备类型，不会调用 nmap（详见 [QUICK_START_GUIDE.md §1](QUICK_START_GUIDE.md#1-关于-nmap当前版本不参与扫描)）。

### 第 3 步：运行安装脚本

```bash
cd /opt/IP-Track
chmod +x setup.sh
./setup.sh
```

`setup.sh` 会自动完成：

1. 从 `.env.example` 生成 `.env`，并生成随机 `ENCRYPTION_KEY`、`DATABASE_PASSWORD`、`REDIS_PASSWORD`；
2. 启动 PostgreSQL / Redis 并等待就绪；
3. 创建 `schema_migrations` 表，按文件名排序执行 `database/migrations/*.sql`（已执行过的会跳过）；
4. 启动全部 6 个容器；
5. 轮询 `8101/8102/8103 /health` 和 `8001` 直到就绪。

> ⚠️ **前端镜像构建失败的常见原因**：拉不到 Node 基础镜像，或 `npm install` 连不上 npm 源 / 需要代理。这些都在 `.env` 里配置，**不需要改 Dockerfile**：
>
> ```bash
> # 在项目根目录的 .env 中（还没有就先 cp .env.example .env）
> NODE_IMAGE=node:20-alpine             # Docker Hub 不可达时换成公司内网镜像或加速地址
> NPM_REGISTRY=https://registry.npmjs.org/   # 或内网 npm 镜像
> NPM_PROXY=http://proxy.example.com:8080    # 只有需要代理时才填
> ```
>
> 改完后执行 `docker compose up -d --build frontend`（或重新 `./setup.sh`）。三项都留空 = 使用官方默认地址、不走代理。

### 第 4 步：确认 6 个容器都在运行

```bash
cd /opt/IP-Track
docker compose ps
```

正常结果应有 6 行，`postgres`、`redis`、三个 `backend-*` 为 `Up (healthy)`，`frontend` 为 `Up`：

```
NAME                       STATUS
iptrack-postgres           Up (healthy)
iptrack-redis              Up (healthy)
iptrack-backend-core       Up (healthy)
iptrack-backend-ipam       Up (healthy)
iptrack-backend-collector  Up (healthy)
iptrack-frontend           Up
```

再逐个验证健康接口：

```bash
curl --noproxy '*' -s -o /dev/null -w "core %{http_code}\n"      http://127.0.0.1:8101/health
curl --noproxy '*' -s -o /dev/null -w "ipam %{http_code}\n"      http://127.0.0.1:8102/health
curl --noproxy '*' -s -o /dev/null -w "collector %{http_code}\n" http://127.0.0.1:8103/health
curl --noproxy '*' -s -o /dev/null -w "frontend %{http_code}\n"  http://127.0.0.1:8001
```

4 个都应返回 `200`。

### 第 5 步：拿到管理员临时密码

系统启用登录机制：**未登录是只读访客**，可以浏览和查询；新增/修改/删除必须登录。

初始管理员只在**用户表为空时**自动创建一次，用户名默认 `admin`，临时密码**只打印一次**：

```bash
cd /opt/IP-Track
docker compose logs backend-core | grep 初始管理员
```

> 看不到？说明日志已经滚动或管理员已创建过。可在 `.env` 中设置 `INITIAL_ADMIN_PASSWORD` 后**在空库前提下**重建，或参考 INTERNAL_DEPLOYMENT.md 的用户管理章节。
>
> 密码属于敏感信息，不要截图外发，也不要写进任何文档/工单。

---

## 3. 首次登录

1. 浏览器打开 `http://YOUR_SERVER_IP:8001`
2. 右上角点击 **登录**
3. 输入 `admin` 和上一步的临时密码
4. 系统会强制要求修改密码（**至少 8 位**，且不能与当前密码相同）
5. 修改完成后即可正常使用

登录页提示原文：*“未登录时只能浏览和查询（只读访客）；新增、修改、删除等操作需要登录。”*

---

## 4. 第一次使用：从空库到查出 IP 在哪台交换机的哪个口

### 4.1 添加第一台交换机

进入 **Switches** 页面 → 点击 **新增交换机**，按实际填写：

| 字段 | 说明 |
|---|---|
| Name | 自定义名称，如 `Core-Switch-01` |
| IP Address | 交换机管理地址，如 `192.0.2.1` |
| Vendor | 下拉只有 **Cisco / Dell / Alcatel-Lucent** 三种 |
| Model | 如 `Catalyst 3850` |
| 启用 CLI 认证 | 打开后填写：**CLI 协议**（SSH/Telnet）、CLI 端口（默认 22）、用户名、密码、Enable 密码（Cisco/Dell Force10 常用，Alcatel 可留空） |
| 自动收集 ARP / 自动收集 MAC | 建议勾选 |
| SNMP 启用 | 需要 SNMP 时打开：版本（当前界面为 SNMPv3）、SNMP 端口（161）、**凭据来源**（选已建模板，或“本机自带”手填用户名/认证协议/认证密码/加密协议等） |

> 想让多台交换机复用同一套 SNMP 凭据：先去 **More → SNMP Profiles** 建模板，再回来在“凭据来源”里选择。

### 4.2 测试连接

在新增/编辑弹窗中点击 **测试**。绿色提示成功；失败时会列出 CLI/SNMP 各自的失败原因。

> 注意：SNMP 测试失败不等于采集一定失败——ARP/MAC 默认走 SSH CLI。

### 4.3 触发第一次采集

1. 在交换机列表找到该设备（或进入详情页）
2. 点击 **采集**（详情页可分别对 ARP、MAC、光模块点击采集/刷新）
3. 等待 20–60 秒，查看“最近采集状态 / 最近采集时间”

自动采集默认**每 120 分钟**一次（`COLLECTION_INTERVAL_MINUTES`），首次部署不要干等，请手动采集。

### 4.4 查询 IP

首页就是 **IP Address Lookup**：输入 `192.0.2.100` → 查询。

**重要**：查询走的是**数据库缓存**（依赖已有 ARP/MAC 采集结果），不实时登录交换机。所以顺序必须是“先采集、后查询”。刚部署、未采集时会查不到。

结果包含：所在交换机、端口、MAC、VLAN、匹配时间等。

### 4.5 IPAM：建子网并扫描

进入 **IPAM** 页面：

1. **添加子网**：子网名称、网络地址（如 `192.0.2.0/24`）、网关、VLAN ID、DNS 服务器、描述
2. 子网列表中点击 **扫描**，等待进度条完成
3. 查看 IP 在线状态、主机名、OS 类型、Last Boot Time（需 SNMP）

自动扫描默认 **60 分钟**（`.env` 中 `IPAM_SCAN_INTERVAL_MINUTES`，代码默认 30；以你的 `.env` 为准）。

> OS 类型来自 ping 的 **TTL 值**粗判（必要时由 SNMP `sysDescr` 修正），**不使用 nmap**。`Last Boot Time` 只能来自 SNMP；子网绑定 SNMP Profile 的界面入口在当前版本缺失，详见 [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) 第 1、2 节。

### 4.6 其他功能入口

页面右上角 **More** 菜单：

| 菜单 | 用途 |
|---|---|
| SNMP Profiles | SNMP 凭证模板（多交换机复用） |
| Batch Discovery | 按网段/凭据批量发现交换机并导入 |
| Templates | CLI 命令模板（不同厂商命令） |
| Alarms | 告警查看与处理 |
| History | IP 查询历史 |
| Settings | 查询缓存时间窗口等参数 |
| BMC Reset | 服务器 BMC 批量重置 |
| 子网存活探测 | 快速 ping 探测一个子网内哪些 IP 存活（独立工具，不写库） |

主菜单另有 **Optical Modules**：光模块单独查询页，支持按交换机/端口搜索与统计。

### 4.7 验证“部署真的成功”的最小闭环

```bash
# 1) 容器都在
docker compose ps

# 2) 后端健康
curl --noproxy '*' -s http://127.0.0.1:8101/health

# 3) 只读接口可用（无需登录）
curl --noproxy '*' -s "http://127.0.0.1:8101/api/v1/switches?limit=1"

# 4) 写操作需要登录：应返回 401
curl --noproxy '*' -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8101/api/v1/auth/me
```

然后在网页里完成：登录 → 加交换机 → 测试 → 采集 → 用该交换机下真实 IP 查询 → 能定位到端口。**这一步通过，才算真正部署成功。**

---

## 5. 局域网 / 远程访问

默认配置下只有前端 8001 对外开放，后端只监听本机。要从其他机器访问：

```bash
cd /opt/IP-Track
# 1) 修改 .env（不存在则先运行 setup.sh）
#    BACKEND_BIND=0.0.0.0      # 让 8101/8102/8103 也对外（通常不需要）
#    FRONTEND_PORT=8001        # 改前端端口

# 2) 必须重建容器，restart 不会重新读取 .env
docker compose up -d

# 3) 防火墙按需放行
sudo firewall-cmd --permanent --add-port=8001/tcp && sudo firewall-cmd --reload   # CentOS
sudo ufw allow 8001/tcp                                                            # Ubuntu
```

如果要通过域名/其他端口访问前端，需把地址加入 `.env` 的 `BACKEND_CORS_ORIGINS`（JSON 数组），然后 `docker compose up -d`：

```bash
BACKEND_CORS_ORIGINS=["http://YOUR_SERVER_IP:8001","http://iptrack.example.com"]
```

生产环境建议：只暴露前端，由 Nginx/网关反向代理 `/api/*` 到三个后端，不要直接暴露 5432/6379。

---

## 6. 日常运维命令

```bash
cd /opt/IP-Track

# 日志
docker compose logs -f backend-core
docker compose logs -f backend-ipam
docker compose logs -f backend-collector
docker compose logs -f frontend
docker compose logs --tail=100 backend-core

# 重启
docker compose restart backend-core
docker compose restart frontend

# 停止 / 启动
docker compose down
docker compose up -d

# 危险：连数据一起删除
# docker compose down -v

# 进容器排查
docker exec -it iptrack-backend-collector bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack
```

**修改后端代码后**：源码是 volume 挂载的，但容器启动命令**没有 `--reload`**，不会自动热加载，必须 `docker compose restart <服务名>`。
**修改 `.env` / `docker-compose.yml` / `vite.config.ts` 后**：必须 `docker compose up -d`（必要时 `--force-recreate`），`restart` 无效。

### 备份（务必同时保存 `.env`）

```bash
# 数据库
docker exec iptrack-postgres pg_dump -U iptrack -d iptrack > iptrack_$(date +%F).sql

# .env 含 ENCRYPTION_KEY：丢失后数据库里的设备密码全部无法解密
sudo cp .env /secure/backup/env_$(date +%F).bak
sudo chmod 600 /secure/backup/env_*.bak
```

---

## 7. 常用配置项（`.env`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `COLLECTION_INTERVAL_MINUTES` | 120 | ARP/MAC 自动采集间隔（分钟） |
| `IPAM_SCAN_INTERVAL_MINUTES` | 60（示例文件）/ 30（代码默认） | IPAM 子网自动扫描间隔 |
| `OPTICAL_MODULE_INTERVAL_MINUTES` | 720 | 光模块采集间隔 |
| `STATUS_CHECK_INTERVAL_SECONDS` | 300 | 交换机在线状态检查间隔（秒） |
| `COLLECTION_WORKERS` | 10 | 采集并发数 |
| `IP_LOOKUP_WORKERS` | 50 | 查询并发数 |
| `COLLECTION_BATCH_SIZE` | 5 | 采集批大小 |
| `DATABASE_POOL_SIZE` | 20（示例文件）/ 40（代码默认） | 数据库连接池 |
| `REDIS_CACHE_TTL` | 300 | Redis 缓存秒数 |
| `API_DOCS_ENABLED` | false | 是否开放 `/docs` 接口文档 |

大网（300+ 交换机）建议：`COLLECTION_WORKERS=20`、`COLLECTION_BATCH_SIZE=5`、`COLLECTION_INTERVAL_MINUTES=180`、`IP_LOOKUP_WORKERS=100`、`DATABASE_POOL_SIZE=30`。

---

## 8. API 与接口文档

- 健康检查：`http://YOUR_SERVER_IP:8101/health`、`:8102/health`、`:8103/health`
- 业务接口前缀：`/api/v1`
- 路由归属：
  - Core（8101）：`/api/v1/auth`、`/switches`、`/lookup`、`/history`、`/alarms`、`/snmp-profiles`、`/snmp-config`、`/command-templates`、`/snmp-oid-overrides`、`/settings`、`/bmc`
  - IPAM（8102）：`/api/v1/ipam`、`/api/v1/subnet-probe`
  - Collector（8103）：`/api/v1/network`、`/api/v1/discovery`、`/api/v1/command-templates`
- **接口文档默认关闭**（`/docs`、`/redoc`、`/openapi.json` 均为 404）。需要时在 `.env` 加：

```bash
API_DOCS_ENABLED=true
```

然后 `docker compose up -d backend-core backend-ipam backend-collector`，访问 `http://127.0.0.1:8101/docs`（各服务端口同理）。**生产环境用完请关掉。**

---

## 9. 常见问题

### Q1. `docker compose up -d` 报 `pull access denied for ip-track-backend`
没构建镜像。执行第 2 步 `docker build -t ip-track-backend:latest ./backend`。

### Q2. 前端容器一直构建失败 / 拉不到 node 镜像 / npm install 超时
用 `.env` 的三个构建参数解决，无需改代码：`NODE_IMAGE`（换镜像地址）、`NPM_REGISTRY`（换 npm 源）、`NPM_PROXY`（走代理），然后 `docker compose up -d --build frontend`。详见第 2 节第 3 步。

### Q3. 端口被占用（8001/8101/8102/8103/5432/6379）
```bash
sudo ss -tlnp | grep -E '8001|8101|8102|8103|5432|6379'
```
改 `.env` 中 `FRONTEND_PORT`、`BACKEND_BIND`/对应端口（注意 compose 中三个后端端口是写死的 8101/8102/8103 映射，改动需同时改 `docker-compose.yml`），或停掉占用进程，然后 `docker compose up -d`。

### Q4. 所有交换机显示离线 / 状态不更新
状态检查间隔是 **300 秒**（不是 30 秒），启动后等 5 分钟再刷新。仍不行则：
```bash
docker exec -it iptrack-backend-collector ping -c 3 SWITCH_IP
docker compose logs --tail=100 backend-collector
```

### Q5. 采集后仍查不到 IP
- 查询是**缓存模式**，先确认对应交换机“最近采集状态=成功”；
- 确认查询的 IP 确实在该交换机的 ARP 表里；
- 检查交换机 CLI 账号是否有读取 ARP/MAC 的权限。

### Q6. 页面能打开，但接口全部 500
多半是 Vite 代理端口写成 8101/8102/8103 了。容器内部必须用 **8100**：检查 `docker-compose.yml` 的 `VITE_PROXY_*` 与 `frontend/vite.config.ts`，然后 `docker compose up -d frontend`。

### Q7. 修改了 `.env` 不生效
`restart` 不会重读环境变量，必须 `docker compose up -d <服务名>`。

### Q8. 登录提示“初始管理员检查失败”
说明 `users` 表不存在，迁移没跑完。检查：
```bash
docker compose logs backend-core | grep -i "migration\|错误\|失败"
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "select filename from schema_migrations order by filename;"
```
确认 `030_add_users.sql` 在列表中；缺失则重新执行 `./setup.sh`。

### Q9. 想看接口文档 / 旧文档里的 `/api/docs`
不存在该路径。当前代码默认关闭文档；按第 8 节设置 `API_DOCS_ENABLED=true` 后使用 `/docs`。

### Q10. 旧文档里的 `iptrack-backend` 容器不见了
它已被拆分为 `iptrack-backend-core / -ipam / -collector` 三个容器，`docker logs iptrack-backend`、`docker restart iptrack-backend` 这类命令均已失效。

---

## 10. 文档导航

| 文档 | 何时看 |
|---|---|
| [README.md](README.md) | 项目总览、功能清单、文档索引 |
| **QUICK_START.md（本文）** | Docker 服务器，首次部署 + 首次使用 |
| [MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md) | 没有 Docker，用 systemd + Nginx 部署 |
| [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md) | SNMP 取不到数据、Last Boot Time 为空、OS 识别不准 |
| [INTERNAL_DEPLOYMENT.md](INTERNAL_DEPLOYMENT.md) | 运维：备份恢复、监控、性能调优、故障处置 |

---

**验证状态**：本文所有命令均对照 `docker-compose.yml`、`setup.sh`、`backend/src/core/config.py`、路由注册代码核对；健康检查、鉴权 401、`/docs` 404 已在运行中的实例上实测。**未验证**：全新服务器的完整从零部署（含受限网络下的 `NODE_IMAGE` / `NPM_REGISTRY` / `NPM_PROXY` 构建参数）、以及需要真实交换机参与的采集/查询闭环。

**最后更新**：2026-11-05
