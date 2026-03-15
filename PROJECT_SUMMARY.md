# IP-Track 项目总结 / Project Summary

## 📋 项目概述 / Project Overview

**IP-Track** 是一个生产级的开源网络设备管理和 IP 地址追踪系统，专为企业级网络环境设计。系统提供 IP 地址定位、IPAM（IP 地址管理）、自动化网络数据采集以及多厂商设备支持。

**IP-Track** is a production-ready, open-source network monitoring and IP address management (IPAM) platform designed for enterprise multi-vendor environments.

---

## ✨ 核心功能 / Key Features

### 1. IP 地址查询 / IP Address Lookup
- **缓存模式**: 查询数据库，响应时间 <100ms
- **实时模式**: 直接 SSH 查询交换机，20-30秒（更准确）
- **自动模式**: 优先缓存，失败后自动切换实时模式
- 智能端口过滤：自动排除 trunk/uplink 端口
- 置信度评分系统

**Features:**
- Cache mode: Database query (<100ms)
- Realtime mode: Direct SSH to switches (20-30s, more accurate)
- Auto mode: Cache first, realtime fallback
- Trunk port filtering with confidence scoring

### 2. 多厂商支持 / Multi-Vendor Support
- **Cisco**: IOS, IOS-XE, Catalyst（CLI + SNMP 混合策略）
- **Dell**: Force10 (S系列), OS10（CLI + SNMP 混合策略）
- **Alcatel/Nokia**: SROS (7250/7750), SR Linux (7220)（仅CLI）
- **Juniper**: JunOS（CLI + SNMP 混合策略）

**Collection Strategy:**
- **Cisco & Dell**: CLI primary, SNMP fallback (mature SNMP support)
- **Alcatel/Nokia**: CLI only (limited SNMP MIB support)
- **Juniper**: CLI primary, SNMP fallback

### 3. IPAM (IP 地址管理) / IP Address Management
- 子网管理和自动扫描（每 60 分钟）
- IP 可达性状态监控（ICMP ping）
- IP 生命周期追踪（活跃/非活跃）
- 批量 IP 扫描和导入
- 子网使用率统计

**Features:**
- Subnet management with auto-scan (every 60 min)
- IP reachability monitoring (ICMP)
- Lifecycle tracking (active/inactive)
- Usage statistics per subnet

### 4. 网络数据采集 / Network Data Collection
- **自动化采集**: 每 120 分钟采集所有交换机
- **ARP 表收集**: IP ↔ MAC 映射关系
- **MAC 表收集**: MAC ↔ 端口映射关系
- **端口分析**: 智能分类access/trunk/uplink端口
- **重试机制**: 指数退避策略，最多重试 3 次
- **批处理**: 每批 5 台交换机并发采集

**Features:**
- Automated collection every 120 minutes
- ARP table: IP ↔ MAC mappings
- MAC table: MAC ↔ Port mappings
- Port analysis: Access/trunk/uplink classification
- Retry logic with exponential backoff
- Batch processing (5 switches per batch, concurrent)

### 5. 端口分析 / Port Analysis
- **分类算法**: 基于 MAC 数量、VLAN 数量、端口命名模式
- **置信度评分**: 0-100 分
- **分类规则**:
  - 1-2 个 MAC → Access 端口（高置信度）
  - 3-5 个 MAC → 可能是 Access（灰色区域）
  - 6-10 个 MAC → 可能是 Trunk
  - >10 个 MAC → Trunk/Uplink（高置信度）

**Classification Logic:**
- 1-2 MACs → Access port (high confidence)
- 3-5 MACs → Possible access (gray area)
- 6-10 MACs → Likely trunk
- >10 MACs → Trunk/uplink (high confidence)

### 6. 告警管理 / Alarm Management
- 采集失败告警（INFO/WARNING/ERROR/CRITICAL）
- 认证失败检测
- 超时监控
- 自动告警解除
- 告警历史保留（默认 30 天）
- 每日自动清理（凌晨 3:00）

**Features:**
- Collection failure alarms (INFO/WARNING/ERROR/CRITICAL)
- Authentication failure detection
- Timeout monitoring
- Auto-resolve on success
- Alarm retention (30 days default)
- Daily cleanup (3:00 AM)

### 7. 光模块监控 / Optical Module Monitoring
- **数据采集**: 每 720 分钟（12 小时）
- **监控参数**:
  - 温度（Temperature）
  - 发射功率（TX Power）
  - 接收功率（RX Power）
  - 波长（Wavelength）
  - 模块型号和序列号

**Features:**
- Collection every 720 minutes (12 hours)
- Monitor temperature, TX/RX power, wavelength
- SFP/SFP+ module information
- Model and serial number tracking

### 8. 状态检查器 / Status Checker
- **实时监控**: 每 30 秒 ICMP ping 所有启用的交换机
- **更新字段**: `is_reachable`, `response_time_ms`, `last_check_at`
- **前端实时显示**: 交换机在线/离线状态
- **响应时间统计**: 毫秒级精度

**Features:**
- ICMP ping every 30 seconds
- Real-time online/offline status
- Response time tracking (millisecond precision)
- Frontend real-time display

### 9. 现代化 UI / Modern UI
- **框架**: Vue 3 Composition API + TypeScript
- **组件库**: Element Plus
- **响应式设计**: 支持桌面和移动端
- **页面**:
  - IP Lookup - IP 地址查询
  - Switches - 交换机管理
  - IPAM - IP 地址管理
  - Discovery - 批量发现
  - Alarms - 告警管理
  - History - 查询历史
  - Optical Modules - 光模块监控

---

## 🏗️ 技术架构 / Technical Architecture

### 后端技术栈 / Backend Stack
- **框架**: FastAPI 0.109+ (Python 3.11+)
- **数据库**: PostgreSQL 16 (15+ 张表)
- **缓存**: Redis 6+
- **ORM**: SQLAlchemy 2.0 (async)
- **网络库**:
  - Netmiko 4.3+ (多厂商 SSH 支持)
  - pysnmp 7.1+ (SNMP v2/v3)
- **并发**: asyncio + ThreadPoolExecutor
- **任务调度**: APScheduler 3.10+
- **加密**: Fernet (AES-256)

### 前端技术栈 / Frontend Stack
- **框架**: Vue 3 + TypeScript 5.0+
- **UI 库**: Element Plus
- **路由**: Vue Router
- **状态管理**: Pinia
- **构建工具**: Vite 5.0+
- **HTTP 客户端**: Axios

### 部署方式 / Deployment
- **Docker Compose** (推荐): 一键部署所有服务
- **手动部署**: 支持传统环境部署
- **环境变量配置**: 完全基于 `.env` 文件

---

## ⚙️ 配置系统 / Configuration System

### 环境变量配置 / Environment Variables

**核心原则**:
- ✅ **零硬编码**: 所有配置均通过环境变量或数据库
- ✅ **安全第一**: 凭据加密存储，密钥不提交仓库
- ✅ **灵活调整**: 50+ 可配置参数

**Key Principles:**
- ✅ Zero hardcoding: All config via `.env` or database
- ✅ Security first: Encrypted credentials, keys never committed
- ✅ Flexible tuning: 50+ configurable parameters

### 关键配置项 / Key Settings

```bash
# 数据库 / Database
DATABASE_USER=iptrack
DATABASE_PASSWORD=auto_generated
DATABASE_HOST=postgres

# 安全 / Security
ENCRYPTION_KEY=auto_generated_fernet_key

# 采集调度 / Collection Schedule
COLLECTION_INTERVAL_MINUTES=120         # ARP/MAC 采集
IPAM_SCAN_INTERVAL_MINUTES=60          # IPAM 扫描
OPTICAL_MODULE_INTERVAL_MINUTES=720    # 光模块采集

# 工作线程池 / Worker Pools
COLLECTION_WORKERS=10                  # 并发采集器
IP_LOOKUP_WORKERS=50                   # 并发 SSH 连接
DISCOVERY_WORKERS=20                   # 批量发现
IPAM_SCAN_WORKERS=20                   # IPAM 扫描器

# 功能开关 / Feature Toggles
FEATURE_IPAM=true
FEATURE_ALARMS=true
FEATURE_OPTICAL_MODULES=true
FEATURE_PORT_ANALYSIS=true
FEATURE_STATUS_CHECKER=true
```

---

## 📊 性能优化 / Performance Optimization

### 1. 智能查询策略 / Smart Query Strategy
```
传统方式 / Traditional: 串行查询所有交换机
优化方式 / Optimized: 按优先级分组 + 并发查询

示例（340 台交换机）/ Example (340 switches):
- 优化前 / Before: ~20-30 分钟
- 优化后 / After: ~30 秒（trunk 过滤 + 置信度评分）
提升 / Improvement: 40 倍+
```

### 2. 并发采集 / Concurrent Collection
- 批量处理：每批 5 台交换机
- 线程池管理：最多 10 个并发采集器
- 独立会话：每个交换机独立数据库会话（避免并发冲突）
- 失败隔离：单个交换机失败不影响其他交换机

**Strategies:**
- Batch processing: 5 switches per batch
- Thread pool: Up to 10 concurrent collectors
- Independent sessions: Isolated DB session per switch
- Failure isolation: One failure doesn't affect others

### 3. 缓存机制 / Caching
- MAC 地址缓存（Redis）
- 查询结果缓存
- 减少重复 SSH 连接
- TTL 管理（300 秒）

### 4. 数据库优化 / Database Optimization
- 关键字段索引（IP、MAC、switch_id、port_name）
- 连接池管理（pool_size=20, max_overflow=10）
- 批量插入操作
- 查询优化（JOIN、WHERE 优化）

---

## 🔒 安全特性 / Security Features

### 1. 凭据保护 / Credential Protection
- **Fernet 加密**: 所有密码 AES-256 加密存储
- **环境变量隔离**: 密钥存储在 `.env`（不提交仓库）
- **Git 排除**: `.gitignore` 防止泄露
- **自动密钥生成**: `scripts/generate_key.py`

**Implementation:**
- Fernet encryption for all passwords (AES-256)
- Environment variable isolation
- Git exclusions (`.gitignore`)
- Auto-generated encryption keys

### 2. 访问控制 / Access Control
- CORS 配置（可自定义允许的来源）
- SQL 注入防护（Pydantic + SQLAlchemy）
- XSS 防护（Vue 3 自动转义）
- 连接超时控制

### 3. 审计日志 / Audit Logging
- 查询历史记录
- 采集日志追踪
- 告警历史保留
- 操作时间戳

---

## 📁 项目结构 / Project Structure

```
IP-TRACK/
├── backend/                    # 后端 API
│   ├── src/
│   │   ├── api/v1/            # API 路由
│   │   │   ├── switches.py        # 交换机管理
│   │   │   ├── lookup.py          # IP 查询
│   │   │   ├── ipam.py            # IPAM 管理
│   │   │   ├── discovery.py       # 批量发现
│   │   │   ├── alarms.py          # 告警管理
│   │   │   └── collection.py      # 数据采集
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py          # 配置类（50+ 环境变量）
│   │   │   ├── database.py        # 数据库连接
│   │   │   └── security.py        # 加密服务
│   │   ├── models/            # 数据模型（15+ 张表）
│   │   ├── schemas/           # Pydantic schemas
│   │   ├── services/          # 业务逻辑
│   │   │   ├── cli_service.py         # CLI 执行和解析
│   │   │   ├── snmp_service.py        # SNMP 采集
│   │   │   ├── ip_lookup.py           # IP 查询服务
│   │   │   ├── network_data_collector.py  # 网络数据采集器
│   │   │   ├── port_analysis_service.py   # 端口分析
│   │   │   ├── ipam_service.py        # IPAM 服务
│   │   │   ├── alarm_service.py       # 告警服务
│   │   │   ├── status_checker.py      # 状态检查器
│   │   │   └── network_scheduler.py   # 任务调度器
│   │   └── utils/             # 工具函数
│   ├── Dockerfile
│   └── requirements.txt       # 42 个依赖包
├── frontend/                  # 前端界面
│   ├── src/
│   │   ├── api/              # API 客户端
│   │   ├── components/       # Vue 组件
│   │   ├── views/            # 页面视图
│   │   │   ├── IPLookup.vue       # IP 查询
│   │   │   ├── Switches.vue       # 交换机管理
│   │   │   ├── Discovery.vue      # 批量发现
│   │   │   ├── IPAM.vue           # IPAM 管理
│   │   │   ├── Alarms.vue         # 告警管理
│   │   │   ├── History.vue        # 查询历史
│   │   │   └── OpticalModules.vue # 光模块
│   │   ├── router/           # 路由配置
│   │   └── stores/           # 状态管理
│   ├── Dockerfile.dev
│   └── package.json
├── database/                 # 数据库脚本
│   └── init/
│       ├── 01_create_tables.sql
│       ├── 02_migration_add_role_priority.sql
│       ├── 07_create_alarms.sql
│       └── 08_create_optical_modules.sql
├── scripts/                  # 辅助脚本
│   ├── generate_key.py       # 生成加密密钥
│   ├── init_config.sh        # 初始化配置
│   └── migrate_from_v1.sh    # 从 v1.x 迁移
├── .env.example              # 配置模板（180+ 行）
├── docker-compose.yml        # Docker 编排
├── README.md                 # 项目说明
├── QUICK_START.md            # 快速开始
├── CLAUDE.md                 # 开发指南
├── CONTRIBUTING.md           # 贡献指南
├── PROJECT_SUMMARY.md        # 项目总结（本文件）
└── LICENSE                   # MIT 许可证
```

---

## 📈 使用统计 / Usage Statistics

- **版本 / Version**: 2.2.0
- **后端代码 / Backend**: 61 个文件, ~15,000 行
- **前端代码 / Frontend**: 28 个文件, ~8,000 行
- **支持厂商 / Vendors**: 4 个（Cisco, Dell, Alcatel/Nokia, Juniper）
- **API 端点 / Endpoints**: 25+ 个
- **数据库表 / DB Tables**: 15+ 张
- **环境变量 / Env Vars**: 50+ 个可配置参数
- **性能 / Performance**: 缓存查询 <100ms, 实时查询 20-30s
- **规模 / Scale**: 已测试 340+ 台交换机, 50,000+ IP 地址

---

## 🚀 部署选项 / Deployment Options

### 选项 1: Docker（推荐）/ Option 1: Docker (Recommended)

```bash
# 1. 克隆仓库
git clone https://github.com/yourusername/ip-track.git
cd ip-track

# 2. 初始化配置
./scripts/init_config.sh

# 3. 启动所有服务
docker-compose up -d

# 4. 访问应用
# 前端: http://localhost:8001
# API 文档: http://localhost:8101/api/docs
```

### 选项 2: 手动部署 / Option 2: Manual Deployment

参考 README.md 的开发部署章节 / See README.md Development section

---

## 🔄 后台服务 / Background Services

系统运行以下自动化后台任务 / Automated background tasks:

1. **状态检查器** (每 30 秒)
   - ICMP ping 所有启用的交换机
   - 更新在线/离线状态和响应时间

2. **网络数据采集** (每 120 分钟)
   - 采集 ARP 表（IP → MAC）
   - 采集 MAC 表（MAC → 端口）
   - 执行端口分析
   - 更新 IP 位置数据库

3. **IPAM 自动扫描** (每 60 分钟)
   - 扫描配置的子网
   - 更新 IP 可达性状态
   - 追踪 IP 生命周期

4. **光模块采集** (每 720 分钟)
   - 采集 SFP/SFP+ 模块信息
   - 监控温度、功率、波长

5. **告警清理** (每天凌晨 3:00)
   - 删除过期告警（默认保留 30 天）

---

## 🎯 适用场景 / Use Cases

✅ **大型企业网络** (100+ 交换机)
✅ **树状网络拓扑** (核心-汇聚-接入)
✅ **混合厂商环境** (Cisco + Dell + Nokia)
✅ **三层/二层混合架构**
✅ **EVPN/VXLAN 环境**
✅ **需要 IP 地址追踪** (故障排查、安全审计)
✅ **IPAM 需求** (IP 地址生命周期管理)

---

## 📝 开源协议 / License

**MIT License**

- ✅ 允许商业使用
- ✅ 允许修改
- ✅ 允许分发
- ✅ 允许私有使用
- ⚠️ 无担保
- ⚠️ 需包含许可证和版权声明

---

## 📚 文档链接 / Documentation Links

- **README.md** - 完整项目文档
- **QUICK_START.md** - 快速开始指南（5 分钟部署）
- **CLAUDE.md** - 开发指南（架构和规范）
- **CONTRIBUTING.md** - 贡献指南
- **.env.example** - 配置模板（180+ 行详细说明）
- **API 文档** - http://localhost:8101/api/docs（运行后访问）

---

## 🎓 技术亮点 / Technical Highlights

### 1. 混合采集策略 / Hybrid Collection Strategy
- **智能选择**: Cisco/Dell 优先 CLI，失败后 SNMP 兜底
- **厂商优化**: Alcatel/Nokia 纯 CLI（SNMP MIB 支持有限）
- **自动降级**: 采集失败时自动尝试备用方法

### 2. 端口过滤算法 / Port Filtering Algorithm
- **多维度分析**: MAC 数量 + VLAN 数量 + 命名模式
- **置信度评分**: 0-100 分精确度量
- **自动学习**: 随着数据积累，分类准确率提升

### 3. 并发架构 / Concurrent Architecture
- **异步编程**: asyncio + SQLAlchemy async
- **线程池**: ThreadPoolExecutor 管理 SSH 连接
- **会话隔离**: 每个并发任务独立数据库会话
- **错误隔离**: 单点故障不影响全局

### 4. 配置驱动 / Configuration-Driven
- **零硬编码**: 所有配置外部化
- **环境隔离**: 开发/测试/生产环境独立配置
- **动态调整**: 无需重新编译，重启生效

---

## 🔗 相关项目 / Related Projects

- [Netmiko](https://github.com/ktbyers/netmiko) - 多厂商 SSH 库
- [NAPALM](https://github.com/napalm-automation/napalm) - 网络自动化库
- [Netbox](https://github.com/netbox-community/netbox) - IPAM 和 DCIM 工具
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Python Web 框架
- [Vue 3](https://vuejs.org/) - 渐进式 JavaScript 框架

---

## 👥 贡献者 / Contributors

- **开发 / Development**: Open Source Community
- **维护 / Maintenance**: IP-Track Contributors
- **技术支持 / Support**: GitHub Issues & Discussions

---

## 📞 支持与反馈 / Support & Feedback

- **Issues**: [GitHub Issues](https://github.com/yourusername/ip-track/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/ip-track/discussions)
- **API 文档 / API Docs**: http://localhost:8101/api/docs

---

**最后更新 / Last Updated**: 2026-03-15
**当前版本 / Current Version**: 2.2.0
**维护者 / Maintained By**: IP-Track Contributors

---

**⭐ 如果觉得有用，请给项目点个 Star！**
**⭐ Star this repository if you find it useful!**
