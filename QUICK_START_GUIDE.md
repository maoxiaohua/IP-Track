# 专项排障指南：主机名 / OS 类型 / Last Boot Time

> 本文只解决一类问题：**IPAM 子网扫描结果里的 `Hostname`、`Machine Type`、`Last Boot Time` 不对或为空。**
>
> 部署问题请看 [QUICK_START.md](QUICK_START.md) 或 [MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md)；日常运维请看 [INTERNAL_DEPLOYMENT.md](INTERNAL_DEPLOYMENT.md)。

---

## 0. 先搞清楚每个字段的数据来源

扫描分两步：先并发 **ping** 判断存活（quick 阶段），再对存活 IP 做**增强**（DNS / NetBIOS / mDNS / SNMP）。

| 字段 | 来源 | 没有数据时的表现 |
|---|---|---|
| `Status` 在线/离线 | ICMP ping（辅以 ARP） | 目标禁 ping → 显示离线 |
| `MAC` | 扫描机所在网段的 ARP 表 | 跨三层/跨网段扫描通常拿不到 |
| `Hostname` | SNMP `sysName` > DNS PTR > NetBIOS > mDNS | 留空（`hostname_source` 为空） |
| `OS Type / Machine Type` | ping 的 **TTL 值**初步判断，SNMP `sysDescr` 再修正 | 留空或只显示 `Linux/Unix`、`Windows` |
| `Last Boot Time` | SNMP `sysUpTime` 换算 | 留空（几乎一定是 SNMP 没打通） |

> **`Last Boot Time` 只能来自 SNMP**。普通 PC/服务器默认不开 SNMP，因此永远不会有这一列，这是正常现象，不是 bug。

---

## 1. 关于 nmap：当前版本不参与扫描

- 扫描流程实际使用的是 **TTL 判断**（`ip_scan.py` 的 `_detect_os_simple`）：`TTL ≤ 64` → Linux/Unix；`≤ 128` → Windows；`≤ 255` → Network Device。
- 代码里存在 nmap 识别函数，但**当前扫描流程没有调用它**，所以给镜像装 nmap 不会改变扫描结果。
- 仓库根目录的 `install_nmap.sh` 是旧的：它执行 `docker compose build backend`，并访问 `iptrack-backend` 容器——这两个名字在当前 6 容器架构中都已不存在，**执行会失败**。请忽略该脚本，不要按它操作。

**结论**：想提高设备类型识别准确度，正确做法是配好 SNMP（见第 2 节），而不是装 nmap。

---

## 2. 让 `Last Boot Time` 有数据

### 2.1 原理

扫描时对每个存活 IP，如果**子网绑定了启用的 SNMP Profile**，且该 IP 满足下列任一条件，才会发起 SNMP 查询：

- TTL 判断为网络设备（`os_type == network`），或
- 该 IP 还没有拿到任何主机名。

随后读取 `sysName / sysDescr / sysContact / sysLocation / sysUpTime`，用 `sysUpTime` 换算 `Last Boot Time`。

### 2.2 当前版本的重要限制

数据库模型 `ip_subnets` 有 `snmp_profile_id` 字段，扫描代码也会读取它，但：

- 子网的创建/更新接口（`IPSubnetCreate` / `IPSubnetUpdate`）**没有包含该字段**；
- 前端“添加子网/编辑子网”表单里**也没有 SNMP Profile 下拉框**。

也就是说，**当前版本无法通过界面把 SNMP Profile 绑定到子网**，IPAM 扫描不会走 SNMP。旧文档里的“IPAM 主页 → 编辑子网 → 选择 SNMP Profile”步骤在当前代码中不存在。

需要确认这一点时，扫描日志里不会出现 `Using SNMP profile ... for subnet ...`；出现该行才说明绑定生效。

> 交换机管理模块（Switches 页面）的 SNMP 是**正常可用**的：在交换机上配置/选择 SNMP 模板后，“设备信息 / 主机名 / 序列号”等都能采到。这与 IPAM 子网扫描是两条独立链路。

### 2.3 可以正常使用的 SNMP 路径：交换机

1. 打开 **More → SNMP Profiles**，点 **Add SNMP Profile** 新建模板：
   - 版本支持 SNMPv2c（community）与 SNMPv3（用户名 + 认证/加密协议与密码）；
   - 确认 **启用状态** 已打开；
   - 密码字段需要重新填写才会保存（编辑时留空表示不修改）。
2. 打开 **Switches** 页面，新增或编辑交换机：
   - 打开 **SNMP 启用**；
   - **凭据来源** 选择刚才的模板（或选“本机自带”手填）；
   - 点 **测试**，日志/弹窗会分别给出 CLI 与 SNMP 的结果。
3. 保存后回到列表，点 **刷新主机名 / 刷新设备信息**。

### 2.4 验证 SNMP 是否真的通

从**采集服务容器**里验证（宿主机上无法确认容器内网络）：

```bash
cd /opt/IP-Track

# 容器里是否有 snmp 工具（镜像不一定带，缺失时用第 3 节的日志验证）
docker exec -it iptrack-backend-collector sh -c 'command -v snmpget || echo "no snmpget"'

# 采集日志
docker compose logs --tail=200 backend-collector | grep -i -E "snmp|profile|timeout|denied"
```

判断依据：
- `Using SNMP profile ...` → 模板已加载；
- `timeout` / `No SNMP response` → UDP 161 不通、community/用户名密码错、ACL 拦截；
- `authorizationError` → 权限级别不匹配（例如只选了认证没选加密但设备要求 authPriv）。

---

## 3. 手工触发扫描并观察

### 3.1 界面

IPAM 页面 → 对应子网 → **扫描**。全量扫描会对存活 IP 做增强；**快速扫描只判断存活**，不查 SNMP/DNS，因此快速模式下这些列本来就不会更新。

### 3.2 直接用数据库确认结果

```bash
cd /opt/IP-Track
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "
SELECT ip_address, status, hostname, hostname_source,
       os_type, machine_type, last_boot_time
FROM ip_addresses
ORDER BY last_seen_at DESC NULLS LAST
LIMIT 20;"
```

字段含义：
- `hostname_source`：`SNMP` / `DNS` / `NETBIOS` / `MDNS` / `ARP`，能直接看出主机名来源；
- `os_type`：`linux` / `windows` / `network`（TTL 判断结果）；
- `machine_type`：优先来自 SNMP `sysDescr`，否则为空；
- `last_boot_time`：只有 SNMP 成功才有值。

### 3.3 查看扫描记录

```bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "
SELECT id, subnet_id, status, scan_type, started_at, finished_at, error_message
FROM ip_scan_history ORDER BY id DESC LIMIT 10;"
```

---

## 4. 常见现象与处理

| 现象 | 最可能原因 | 处理 |
|---|---|---|
| 全部离线 | 扫描机到目标网段不通；ICMP 被禁 | 在采集容器内 `ping` 目标；确认路由与 ACL |
| 在线但没有 MAC | 跨三层扫描，ARP 表里没有 | 属正常现象；只能在同一广播域获得 MAC |
| `Last Boot Time` 全空 | 子网未绑定 SNMP Profile（当前版本无界面入口） | 见 2.2；改用交换机侧 SNMP 验证 |
| 个别设备有、多数没有 | 只有网络设备/开了 SNMP 的主机支持 | 普通 PC 无 SNMP 属正常 |
| `Hostname` 为空 | 无 SNMP、DNS 无 PTR、无 NetBIOS/mDNS | 配 SNMP；或补齐内网 DNS 反向解析 |
| `Machine Type` 为 `Linux/Unix` 或 `Windows` | TTL 粗判，且无 SNMP 修正 | 配 SNMP 获取 `sysDescr` |
| 主机名是 DNS 名但不是设备名 | DNS PTR 优先于 NetBIOS/mDNS，但低于 SNMP | 配 SNMP 后 `sysName` 会覆盖 |
| 扫描卡在“快速模式” | 快速扫描只做存活判断 | 等扫描完成；需要增强结果请用全量扫描 |
| 页面数据没变化 | 浏览器缓存或查询缓存 | 刷新页面；确认扫描确实已完成（看 `ip_scan_history`） |

---

## 5. 子网（IPAM）自身的配置检查

```bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "
SELECT id, name, network, enabled, auto_scan, scan_interval,
       snmp_profile_id, last_scan_at
FROM ip_subnets ORDER BY id;"
```

同时确认：

```bash
docker exec -it iptrack-postgres psql -U iptrack -d iptrack -c "
SELECT id, name, version, enabled FROM snmp_profiles ORDER BY id;"
```

- `ip_subnets.enabled = false` → 不参与自动扫描；
- `auto_scan = false` → 只响应手动扫描；
- `snmp_profile_id IS NULL` → 该子网不会做 SNMP 增强（当前版本预期如此）。

自动扫描间隔以 `ip_subnets.scan_interval`（秒，默认 3600，最小 300）为准；全局 `IPAM_SCAN_INTERVAL_MINUTES` 是调度器默认值。

---

## 6. 交换机侧 SNMP 取不到数据的排查顺序

1. **UDP 161 是否可达**：从采集容器执行 `nc -zu SWITCH_IP 161`（容器内有 `nc` 时）或看日志是否 `timeout`；
2. **版本是否匹配**：设备是 v2c 而模板填 v3（或反之）一定失败；
3. **SNMPv3 参数**：
   - 认证协议（MD5/SHA/SHA-256…）与设备一致；
   - 加密协议（DES/AES-128/AES-192…）与设备一致；
   - 设备要求 authPriv 时，必须同时填认证密码与加密密码；
4. **ACL / 访问控制**：交换机上 `snmp-server community`、`snmp-server host`、`access-list` 是否放行采集机 IP；
5. **模板未启用**：`SNMP Profiles` 里的启用开关；
6. **交换机引用了模板但模板密码为空**：编辑模板时密码留空表示“不修改”，不是“清空”；新建时必须填写。

日志定位：

```bash
docker compose logs --tail=300 backend-collector | grep -iE "snmp|oid|timeout|auth"
docker compose logs --tail=300 backend-core      | grep -iE "snmp|oid|认证"
```

---

## 7. 提醒：旧文档里的两个脚本已不存在

以下命令在旧版文档中出现过，当前代码里已经**没有这两个文件**，执行会报 `No such file`：

```bash
# ❌ 已不存在
docker exec -it iptrack-backend python /app/check_snmp.py
docker exec -it iptrack-backend python /app/diagnose_ipam.py
```

用本文第 3、5 节的 SQL 与日志命令替代。

---

## 8. 相关文档

| 文档 | 内容 |
|---|---|
| [QUICK_START.md](QUICK_START.md) | Docker 部署 + 首次使用 |
| [MANUAL_DEPLOYMENT.md](MANUAL_DEPLOYMENT.md) | 无 Docker 部署 |
| **QUICK_START_GUIDE.md（本文）** | 主机名 / OS / Last Boot Time 专项排障 |
| [INTERNAL_DEPLOYMENT.md](INTERNAL_DEPLOYMENT.md) | 运维、备份、监控、故障处置 |

---

**验证状态**：本文与 `backend/src/services/ip_scan.py`（`_detect_os_simple`、`_enrich_single_ip`、SNMP 触发条件）、`snmp_service.py`（`get_device_identification`、OID 列表）、`ipam_service.py`（子网 SNMP 绑定）、`schemas/ipam.py`（子网字段）、`models/ipam.py`（表名/字段）逐项核对；确认 `check_snmp.py`、`diagnose_ipam.py` 已不存在，`install_nmap.sh` 仍引用旧服务名。**未验证**：真实设备上的 SNMP 连通性、不同厂商 v3 参数差异、IPAM 扫描端到端结果（需要真实交换机/主机环境）。

**最后更新**：2026-11-05
