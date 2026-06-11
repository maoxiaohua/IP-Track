# AI Coding Rules (Low Token Mode)

# Claude Code Project Rules
你是我的项目开发助手。我不是专业开发者，所以你必须主动控制风险，不能为了快速完成而跳过验证。
## 核心原则
1. 不要偏离用户原始需求。
2. 不要做无关重构。
3. 不要随意修改目录结构。
4. 不要删除已有功能。
5. 不要引入不必要的新依赖。
6. 不要只改前端忘记后端。
7. 不要只改后端忘记前端。
8. 不要声称问题解决，除非真实验证过。
9. 如果无法验证，必须明确说"无法完全验证"。
10. 所有修改都要以减少 bug 为目标，而不是看起来更复杂。
11. 严禁硬编码，该项目必须适用于所有的网络环境。
12. 不同地方的同样功能在每次修复或者修改的时候必须同步生效。不能丢三落四。
## 开发前必须做
每次写代码前先说明：
- 用户要解决的问题
- 涉及范围
- 计划修改的文件
- 不会修改的内容
- 风险点
- 验证方法
## 前后端规则
如果修改前端：
- 必须检查后端接口是否存在
- 必须检查请求 method 是否一致
- 必须检查字段名是否一致
- 必须检查返回数据是否匹配
- 必须检查错误提示和 loading 状态
如果修改后端：
- 必须检查前端是否调用该接口
- 必须检查前端字段是否同步
- 必须检查错误格式是否前端可识别
- 必须检查接口是否可以真实访问
## UI 规则
所有按钮必须检查：
- 文字颜色
- 图标颜色
- 背景颜色
- hover 状态
- disabled 状态
- loading 状态
禁止出现：
- 白字白底
- 黑字黑底
- 图标和背景同色
- hover 后文字消失
- disabled 后完全看不见
- 危险按钮和普通按钮没有区别
## 测试规则
修改完成后必须说明：
- 运行了什么命令
- 命令是否成功
- 是否验证了用户真正的问题
- 哪些部分没有验证
- 最终结论是：已解决 / 部分解决 / 未解决 / 无法完全验证
禁止：
- 只跑 build 就说功能完成
- 只跑 lint 就说 bug 修复
- 没运行测试却说已测试
- 测试失败但说完成
- 修改测试来掩盖问题
## 默认工作流
1. 理解需求
2. 限定范围
3. 找相关文件
4. 最小修改
5. 检查前后端一致性
6. 检查 UI 可见性
7. 运行真实测试
8. 汇报已验证和未验证内容
## 推荐使用的 agents
- project-manager：开发前控制范围
- frontend-backend-reviewer：检查前后端一致性
- ui-quality-reviewer：检查按钮、图标、文字可见性
- test-verifier：确认是否真实解决
- bug-hunter：查隐藏 bug
## 推荐使用的 skills
- /project-guard
- /minimal-change
- /frontend-backend-sync
- /ui-visibility-check
- /real-test-verification


## Core Rules
- Only modify minimal code
- Always use diff format
- Never output full file
- Keep answers under 200 tokens

## Bug Fix Workflow
1. Identify root cause (1 line)
2. Provide minimal patch

## Forbidden
- Long explanations
- Multiple solutions
- Refactoring unrelated code
- Adding new features

## Context Control
- Only use provided code
- Do not assume project structure
- Do not use Hard-coded
- 使用中文回复

---

# 项目结构 / Project Structure

## 架构概览

采用微服务 + Docker Compose 部署，3 个后端服务 + 1 个前端：

| 容器名 | 入口文件 | 端口 | 职责 |
|---|---|---|---|
| `iptrack-postgres` | - | 5432 | PostgreSQL 16 数据库 |
| `iptrack-redis` | - | 6379 | Redis 缓存 |
| `iptrack-backend-core` | `backend/src/main_core.py` | 8101→8100 | 核心 API：交换机管理、IP 查询、告警、SNMP 配置、BMC |
| `iptrack-backend-ipam` | `backend/src/main_ipam.py` | 8102→8100 | IPAM：IP 扫描、子网管理、SolarWinds 集成 |
| `iptrack-backend-collector` | `backend/src/main_collector.py` | 8103→8100 | 采集服务：ARP/MAC/光模块定时采集、交换机发现 |
| `iptrack-frontend` | Vite dev server | 8001→5173 | Vue3 前端 |

## 重启命令

修改代码后**必须重启对应的服务**才能生效：

```bash
# 代码修改后重启（修改挂载的源码卷，重启容器即可）
docker compose restart backend-core      # 核心 API 修改后
docker compose restart backend-ipam      # IPAM 修改后
docker compose restart backend-collector # 采集服务/SNMP/CLI 修改后
docker compose restart frontend          # 前端修改后

# 完整重启（修改了依赖、配置、或不确定时用）
docker compose down && docker compose up -d

# 查看日志
docker compose logs -f backend-collector  # 采集服务日志
docker compose logs -f backend-core       # 核心 API 日志
docker compose logs -f frontend           # 前端日志

# 进入容器调试
docker exec -it iptrack-backend-collector bash
docker exec -it iptrack-backend-core bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack
```

**重要**：源码通过 volume 挂载 (`./backend/src:/app/src`)，修改 Python 文件后 uvicorn 会自动 reload。如果没生效，手动 `docker compose restart <服务名>`。

## Docker 端口与网络规则（critical - 已发生事故）

### 核心规则：所有后端容器内部均监听 8100 端口

```
容器内部端口          主机映射端口       用途
iptrack-backend-core:8100     → 8101   核心 API
iptrack-backend-ipam:8100     → 8102   IPAM
iptrack-backend-collector:8100 → 8103  采集服务
```

**主机映射端口 (8101/8102/8103) 只能在宿主机访问 Docker 容器时使用，容器之间（包括前端 Vite 代理）必须使用内部端口 8100。**

### Vite 代理配置必须用 8100

- `vite.config.ts` 的 proxy target 和**默认值**必须使用 8100，因为 Vite dev server 运行在 Docker 网络内部
- `docker-compose.yml` 的 `VITE_PROXY_*` 环境变量也必须使用 8100
- `.env.example` 里的 `localhost:8101/8102/8103` 仅适用于本地 `npm run dev`，不适用于 Docker 部署

### 事故案例（2026-06-09）

commit `77159cc` 把 `vite.config.ts` 的 proxy 默认值从 8100 改成了 8102/8103：
```typescript
// 错误：Docker 内部无法访问 8102/8103
const backendIpam = env.VITE_PROXY_IPAM || 'http://iptrack-backend-ipam:8102'
const backendCollector = env.VITE_PROXY_COLLECTOR || 'http://iptrack-backend-collector:8103'
```
导致 IPAM 页面和光模块页面所有 API 请求 500 错误。正确值应该是 8100。

### docker compose restart ≠ docker compose up -d

- `docker compose restart` 只重启容器进程，**不会**重新读取 docker-compose.yml 的环境变量变更
- 修改了环境变量（`.env` 或 `docker-compose.yml` 的 `environment`）后，必须用 `docker compose up -d <服务名>` 重建容器
- 修改了 `vite.config.ts` 后也必须重建前端容器

## 目录结构

```
/opt/IP-Track/
├── docker-compose.yml          # Docker 编排
├── .env                        # 全局环境变量
├── setup.sh                    # 一键部署脚本
├── backend/
│   ├── Dockerfile              # 后端镜像
│   ├── requirements.txt        # Python 依赖
│   ├── src/
│   │   ├── main.py             # 旧单体入口 (不推荐)
│   │   ├── main_core.py        # 核心 API 入口 → backend-core 容器
│   │   ├── main_ipam.py        # IPAM 入口 → backend-ipam 容器
│   │   ├── main_collector.py   # 采集服务入口 → backend-collector 容器
│   │   ├── api/
│   │   │   ├── v1/             # REST API 端点
│   │   │   │   ├── switches.py          # 交换机 CRUD + ARP/MAC 采集触发
│   │   │   │   ├── discovery.py         # 交换机自动发现
│   │   │   │   ├── lookup.py            # IP 定位查询
│   │   │   │   ├── history.py           # 查询历史
│   │   │   │   ├── alarms.py            # 告警管理
│   │   │   │   ├── snmp_profiles.py     # SNMP 凭证模板
│   │   │   │   ├── snmp_oid_overrides.py # SNMP OID 覆盖配置
│   │   │   │   ├── command_templates.py # CLI 命令模板
│   │   │   │   ├── collection.py        # 采集任务队列
│   │   │   │   ├── settings.py          # 系统设置
│   │   │   │   ├── bmc.py              # BMC 管理
│   │   │   │   └── ipam.py             # IPAM API
│   │   │   └── routes/
│   │   │       ├── network.py           # 端口分析等网络相关路由
│   │   │       └── snmp_config.py       # SNMP 配置路由
│   │   ├── services/           # 业务逻辑层
│   │   │   ├── network_data_collector.py # 核心：ARP/MAC/光模块采集、端口分析、IP 匹配
│   │   │   ├── snmp_service.py           # SNMP GET/WALK/设备识别/序列号/光模块
│   │   │   ├── cli_service.py            # CLI/SSH/Telnet 命令执行和解析
│   │   │   ├── collection_worker.py      # 采集任务队列消费者
│   │   │   ├── switch_discovery.py       # 交换机自动发现
│   │   │   ├── switch_manager.py         # 实时交换机查询 (Netmiko CLI)
│   │   │   ├── ip_lookup.py              # IP 定位引擎 (缓存+在线查询)
│   │   │   ├── ip_scan.py                # IP 扫描
│   │   │   ├── ipam_service.py           # IPAM 核心逻辑
│   │   │   ├── alarm_service.py          # 告警服务
│   │   │   ├── port_analysis_service.py  # 端口分析
│   │   │   ├── ip_location_engine.py     # IP 位置匹配引擎
│   │   │   ├── port_lookup_policy_service.py # 端口查找策略
│   │   │   ├── network_scheduler.py      # 定时任务调度
│   │   │   ├── bmc_service.py            # BMC 重置服务
│   │   │   ├── bmc_reset_status.py       # BMC 重置状态跟踪
│   │   │   ├── bmc_reset_scheduler.py    # BMC 重置调度
│   │   │   ├── status_checker.py         # 设备状态检查
│   │   │   ├── data_freshness_service.py # 数据新鲜度检查
│   │   │   ├── duplicate_detector.py     # 重复交换机检测
│   │   │   ├── oui_lookup.py             # MAC OUI 厂商查询
│   │   │   ├── mac_utils.py              # MAC 地址工具
│   │   │   ├── settings_service.py       # 系统设置服务
│   │   │   ├── ipam_scan_status.py       # IPAM 扫描状态管理
│   │   │   └── vendors/                  # 厂商处理器
│   │   │       ├── base.py               # 基类
│   │   │       ├── cisco.py              # Cisco IOS/IOS-XE
│   │   │       ├── alcatel.py            # Nokia/Alcatel SR OS
│   │   │       └── dell.py               # Dell OS10
│   │   ├── models/              # 数据库模型 (SQLAlchemy)
│   │   │   ├── switch.py                 # 交换机模型 (核心表)
│   │   │   ├── arp_table.py              # ARP 表
│   │   │   ├── mac_table.py              # MAC 表
│   │   │   ├── port_analysis.py          # 端口分析结果
│   │   │   ├── optical_module.py         # 光模块信息
│   │   │   ├── ipam.py                   # IPAM 模型
│   │   │   ├── ip_location.py            # IP 定位记录
│   │   │   ├── mac_cache.py              # MAC 缓存
│   │   │   ├── alarm.py                  # 告警模型
│   │   │   ├── collection_job.py         # 采集任务
│   │   │   ├── query_history.py          # 查询历史
│   │   │   ├── switch_command_template.py # CLI 命令模板模型
│   │   │   ├── switch_command_cache.py   # 命令缓存
│   │   │   ├── snmp_oid_override.py      # SNMP OID 覆盖
│   │   │   ├── bmc_server.py             # BMC 服务器
│   │   │   ├── bmc_credential_profile.py # BMC 凭证模板
│   │   │   ├── bmc_reset_history.py      # BMC 重置历史
│   │   │   └── system_settings.py        # 系统设置
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   │   ├── switch.py
│   │   │   ├── discovery.py
│   │   │   ├── lookup.py
│   │   │   ├── history.py
│   │   │   ├── alarm.py
│   │   │   ├── snmp.py
│   │   │   ├── snmp_oid_override.py
│   │   │   ├── switch_command_template.py
│   │   │   ├── collection.py
│   │   │   ├── ipam.py
│   │   │   ├── bmc.py
│   │   │   └── settings.py
│   │   ├── config/
│   │   │   └── collection_strategy.py    # 采集策略 (CLI/SNMP 优先级)
│   │   ├── core/
│   │   │   ├── database.py               # 数据库连接 (AsyncSession)
│   │   │   ├── config.py                 # 应用配置
│   │   │   └── security.py               # 加密/解密
│   │   ├── utils/
│   │   │   ├── logger.py                 # 日志配置
│   │   │   └── network.py                # 网络工具
│   │   └── data/
│   │       └── oui_cache.txt             # MAC OUI 厂商缓存
│   ├── logs/                    # 后端日志
│   └── tests/                   # 测试文件
├── frontend/
│   ├── Dockerfile.dev           # 前端开发镜像
│   ├── vite.config.ts           # Vite 配置 (代理到后端)
│   ├── src/
│   │   ├── main.ts              # Vue 入口
│   │   ├── App.vue              # 根组件
│   │   ├── api/                 # API 调用封装
│   │   │   ├── index.ts         # Axios 实例 (base URL)
│   │   │   ├── switches.ts      # 交换机 API (ARP/MAC 采集触发)
│   │   │   ├── lookup.ts        # IP 查询 API
│   │   │   ├── ipam.ts          # IPAM API
│   │   │   ├── alarms.ts        # 告警 API
│   │   │   ├── bmc.ts           # BMC API
│   │   │   ├── snmp.ts          # SNMP 配置 API
│   │   │   ├── snmpProfiles.ts  # SNMP 模板 API
│   │   │   ├── commandTemplates.ts # 命令模板 API
│   │   │   └── settings.ts      # 设置 API
│   │   ├── views/               # 页面组件
│   │   │   ├── Home.vue         # 首页
│   │   │   ├── Switches.vue     # 交换机列表页
│   │   │   ├── SwitchDetail.vue # 交换机详情 (ARP/MAC/端口/光模块)
│   │   │   ├── Discovery.vue    # 交换机发现
│   │   │   ├── History.vue      # 查询历史
│   │   │   ├── Alarms.vue       # 告警管理
│   │   │   ├── SNMPConfig.vue   # SNMP 配置
│   │   │   ├── SNMPProfiles.vue # SNMP 模板
│   │   │   ├── CommandTemplates.vue # CLI 命令模板
│   │   │   ├── Settings.vue     # 系统设置
│   │   │   ├── IPAM_Simple.vue  # IPAM 管理
│   │   │   ├── SubnetDetail_SolarWinds.vue # 子网详情
│   │   │   ├── OSTypeIPList.vue # OS 类型 IP 列表
│   │   │   ├── BMCReset.vue     # BMC 重置管理
│   │   │   └── OpticalModules.vue # 光模块单独页
│   │   ├── components/          # 可复用组件
│   │   │   ├── SwitchList.vue   # 交换机卡片列表
│   │   │   ├── IPLookupForm.vue # IP 查询表单
│   │   │   ├── ResultDisplay.vue # 查询结果展示
│   │   │   ├── IPDetailDrawer.vue # IP 详情抽屉
│   │   │   ├── QueryHistory.vue # 查询历史列表
│   │   │   ├── Chart.vue        # 图表组件
│   │   │   ├── AddSwitchSNMP.vue # 添加交换机 (SNMP)
│   │   │   └── SNMPConfigForm.vue # SNMP 配置表单
│   │   ├── stores/              # Pinia 状态管理
│   │   │   ├── lookup.ts        # 查询状态
│   │   │   ├── bmc.ts           # BMC 状态
│   │   │   └── settings.ts      # 设置状态
│   │   ├── router/
│   │   │   └── index.ts         # Vue Router 路由配置
│   │   ├── utils/               # 工具函数
│   │   └── composables/         # Vue composables
│   └── public/                  # 静态资源
├── database/
│   ├── init/                    # 初始化 SQL (首次启动执行)
│   └── migrations/              # 增量迁移 SQL (按序号手动执行)
└── scripts/                     # 运维脚本
    ├── init_config.sh           # 初始化配置
    └── migrate_from_v1.sh       # v1 迁移脚本
```

## 常见修改路径

| 要改什么 | 文件 | 重启服务 |
|---|---|---|
| SNMP MAC/ARP 采集 | `backend/src/services/snmp_service.py` | `backend-collector` |
| SSH/CLI 采集 | `backend/src/services/cli_service.py` | `backend-collector` |
| 采集策略/数据保存 | `backend/src/services/network_data_collector.py` | `backend-collector` |
| 交换机发现 | `backend/src/services/switch_discovery.py` | `backend-collector` |
| IP 查询逻辑 | `backend/src/services/ip_lookup.py` | `backend-core` |
| 交换机 API | `backend/src/api/v1/switches.py` | `backend-core` + 前端 |
| 前端交换机页面 | `frontend/src/views/Switches.vue` | `frontend` |
| 前端交换机详情 | `frontend/src/views/SwitchDetail.vue` | `frontend` |
| 前端 API 调用 | `frontend/src/api/switches.ts` | `frontend` |
| 数据库模型 | `backend/src/models/*.py` | 所有后端 + 执行迁移 SQL |
| 环境变量 | `.env` | `docker compose down && docker compose up -d` |
