# IPAM IP扫描增强功能说明

**日期**: 2026-03-19
**版本**: 1.0

---

## 概述

本文档说明IPAM IP扫描的增强功能，包括DNS反向解析、SNMP设备识别和设备类型自动识别。

---

## IP扫描流程

```
开始扫描
   │
   ▼
Ping IP (ICMP)
   │
   ▼
在线？
   │
 ┌─Yes─────────────────────┐
 │                         │
 ▼                         ▼
SNMP查询              DNS反向查询
(需要SNMP Profile)    (需要dnspython)
 │                         │
 ▼                         ▼
获取:                    获取:
- hostname (sysName)     - hostname (PTR记录)
- contact (sysContact)
- location (sysLocation)
- 设备类型 (sysDescr)
- vendor
- 启动时间 (sysUpTime)
 │                         │
 └────────┬────────────────┘
          ▼
     更新hostname (优先级: SNMP > DNS > ARP)
          ▼
     MAC地址查询 (ARP)
          ▼
     OS检测 (TTL/nmap)
          ▼
     更新last_seen时间
          ▼
     完成
```

---

## 功能特性

### 1. 多层次主机名识别

主机名获取优先级（从高到低）：

1. **SNMP sysName** (最高优先级)
   - 通过SNMP查询 OID `1.3.6.1.2.1.1.5.0`
   - 需要配置SNMP profile
   - 最准确，适用于网络设备和支持SNMP的服务器

2. **DNS PTR记录** (次优先级)
   - 通过DNS反向查询
   - 需要安装 `dnspython` 模块
   - 适用于Windows PC、Linux服务器等

3. **ARP表** (备用)
   - 从交换机ARP表获取
   - 不一定有主机名信息

**字段说明**：
- `hostname`: 最终使用的主机名（根据优先级选择）
- `hostname_source`: 主机名来源（`SNMP`、`DNS`、`ARP`、`MANUAL`）
- `dns_name`: DNS PTR查询结果
- `system_name`: SNMP sysName查询结果

---

### 2. SNMP设备识别

通过SNMP获取详细设备信息：

| SNMP OID | 字段 | 说明 |
|----------|------|------|
| 1.3.6.1.2.1.1.5.0 | system_name | 系统主机名 |
| 1.3.6.1.2.1.1.4.0 | contact | 联系人信息 |
| 1.3.6.1.2.1.1.6.0 | location | 物理位置 |
| 1.3.6.1.2.1.1.1.0 | machine_type | 设备类型（从sysDescr解析） |
| 1.3.6.1.2.1.1.1.0 | vendor | 厂商（从sysDescr解析） |
| 1.3.6.1.2.1.1.3.0 | last_boot_time | 上次启动时间（从sysUpTime计算） |

**要求**：
- 子网必须配置SNMP profile
- 设备必须支持SNMPv3或SNMPv2c
- 需要正确的SNMP凭据

---

### 3. 增强设备类型识别

#### 3.1 基于SNMP sysDescr识别

从SNMP sysDescr字段自动识别设备类型：

| 检测关键词 | 识别结果 | 示例 |
|-----------|---------|------|
| switch | {Vendor} Switch | Cisco Switch |
| router | {Vendor} Router | Juniper Router |
| firewall, fortigate | {Vendor} Firewall | Fortinet Firewall |
| access point, wireless, ap | {Vendor} Access Point | Aruba Access Point |
| base station, bts, enodeb, gnodeb | Nokia Base Station | Nokia Base Station |
| server | {Vendor} Server | Dell Server |
| workstation, pc, desktop | {Vendor} PC | HP PC |
| laptop, notebook | {Vendor} Laptop | Dell Laptop |
| printer | {Vendor} Printer | HP Printer |
| camera, ipc | {Vendor} IP Camera | - |

**支持的厂商识别**：
- Cisco
- Dell
- HP (Hewlett-Packard)
- Juniper
- Nokia / Alcatel
- Huawei
- ZTE
- Aruba
- Fortinet

#### 3.2 基于TTL值识别

当SNMP/nmap不可用时，使用TTL值推测OS类型：

| TTL范围 | OS类型 | 说明 |
|---------|--------|------|
| ≤ 64 | Linux/Unix | 默认TTL=64 |
| ≤ 128 | Windows | 默认TTL=128 |
| ≤ 255 | Network Device | 路由器/交换机，默认TTL=255 |

#### 3.3 基于nmap OS检测

如果安装了nmap，会执行详细的OS指纹识别：
- Windows版本（7/8/10/11/Server 2016/2019/2022）
- Linux发行版（Ubuntu/CentOS/RedHat/Debian）
- 网络设备（Cisco IOS、Junos、HP Procurve等）
- 打印机、摄像头等IoT设备

---

## 配置要求

### 1. 启用DNS反向解析

**当前状态**：❌ dnspython未安装

**安装步骤**：

```bash
# 方法1: 在线安装（需要网络连接）
sudo docker exec iptrack-backend pip install dnspython==2.4.2

# 方法2: 使用代理安装
sudo docker exec iptrack-backend bash -c 'http_proxy=http://YOUR_PROXY:PORT pip install dnspython==2.4.2'

# 方法3: 离线安装（推荐）
# 1. 在有网络的机器上下载whl文件
pip download dnspython==2.4.2 -d /tmp/pip-packages

# 2. 复制到服务器
scp /tmp/pip-packages/*.whl user@server:/tmp/

# 3. 在容器中安装
sudo docker cp /tmp/dnspython-2.4.2-py3-none-any.whl iptrack-backend:/tmp/
sudo docker exec iptrack-backend pip install /tmp/dnspython-2.4.2-py3-none-any.whl

# 4. 重启backend
sudo docker restart iptrack-backend
```

**验证安装**：

```bash
sudo docker exec iptrack-backend python -c "import dns.resolver; print('dnspython OK')"
```

---

### 2. 配置SNMP Profile

要启用SNMP设备识别，需要为子网配置SNMP profile。

#### 2.1 创建SNMP Profile

在前端页面操作：

1. 导航到 **SNMP Profiles** 页面
2. 点击 **新建SNMP Profile**
3. 填写以下信息：
   - **名称**: 如 "Default SNMPv3 Profile"
   - **版本**: v3 (推荐) 或 v2c
   - **SNMPv3配置**:
     - Username: SNMP用户名
     - Auth Protocol: SHA (推荐) 或 MD5
     - Auth Password: 认证密码
     - Priv Protocol: AES (推荐) 或 DES
     - Priv Password: 加密密码
   - **端口**: 161 (默认)
   - **超时**: 5秒 (默认)
   - **重试次数**: 3 (默认)
4. 点击 **保存**

#### 2.2 为子网关联SNMP Profile

1. 导航到 **IPAM** 页面
2. 找到要配置的子网
3. 点击 **编辑**
4. 在 **SNMP Profile** 下拉框中选择已创建的profile
5. 点击 **保存**

#### 2.3 测试SNMP配置

扫描子网后，查看IP地址详情：
- 如果 `hostname_source` = `SNMP`，说明SNMP工作正常
- 如果 `system_name`、`contact`、`location` 有值，说明SNMP查询成功
- 如果 `machine_type` 和 `vendor` 有值，说明设备类型识别成功

---

## 扫描类型

### Quick Scan (快速扫描)
- 仅执行Ping检查
- 返回IP是否在线和响应时间
- 速度快，适合大批量扫描

### Full Scan (完整扫描)
- Ping + SNMP + DNS + MAC + OS检测
- 获取完整设备信息
- 速度较慢，但信息最全面

**配置**：在子网扫描时选择扫描类型

---

## 数据库字段映射

### ip_addresses 表主要字段

| 字段 | 类型 | 说明 | 数据来源 |
|------|------|------|---------|
| hostname | String | 最终使用的主机名 | SNMP/DNS/ARP（优先级） |
| hostname_source | String | 主机名来源 | SNMP/DNS/ARP/MANUAL |
| dns_name | String | DNS PTR查询结果 | DNS反向查询 |
| system_name | String | SNMP主机名 | SNMP sysName |
| contact | String | 联系人 | SNMP sysContact |
| location | String | 位置 | SNMP sysLocation |
| machine_type | String | 设备类型 | SNMP sysDescr解析 |
| vendor | String | 厂商 | SNMP sysDescr解析 |
| last_boot_time | DateTime | 启动时间 | SNMP sysUpTime计算 |
| os_type | String | OS类型 | TTL/nmap |
| os_name | String | OS名称 | TTL/nmap |
| os_version | String | OS版本 | nmap |
| os_vendor | String | OS厂商 | nmap/sysDescr |
| mac_address | MACADDR | MAC地址 | ARP查询 |
| is_reachable | Boolean | 是否在线 | Ping |
| response_time | Integer | 响应时间(ms) | Ping |
| last_seen_at | DateTime | 最后在线时间 | Ping成功时更新 |

---

## 使用示例

### 示例1: Windows PC识别

**场景**: 扫描到Windows 10工作站

**扫描结果**:
```json
{
  "ip_address": "10.106.195.100",
  "is_reachable": true,
  "response_time": 2,
  "hostname": "WIN10-PC-001",
  "hostname_source": "DNS",
  "dns_name": "WIN10-PC-001.company.local",
  "system_name": null,
  "os_type": "windows",
  "os_name": "Windows",
  "os_vendor": "Microsoft",
  "mac_address": "00:50:56:aa:bb:cc"
}
```

**说明**:
- DNS PTR查询成功，获取到主机名
- TTL检测识别为Windows
- 未配置SNMP，所以system_name为空

---

### 示例2: 网络设备识别（配置SNMP）

**场景**: 扫描到Cisco交换机（已配置SNMP profile）

**扫描结果**:
```json
{
  "ip_address": "10.56.4.137",
  "is_reachable": true,
  "response_time": 1,
  "hostname": "CORE-SW-01",
  "hostname_source": "SNMP",
  "dns_name": "core-sw-01.company.local",
  "system_name": "CORE-SW-01",
  "contact": "Network Admin (admin@company.com)",
  "location": "Data Center - Rack 12",
  "machine_type": "Cisco Switch",
  "vendor": "Cisco",
  "os_type": "network",
  "os_name": "Cisco Network Device",
  "last_boot_time": "2026-02-15T08:30:00Z",
  "mac_address": "00:1a:2b:3c:4d:5e"
}
```

**说明**:
- SNMP查询成功，获取完整设备信息
- hostname优先使用SNMP sysName
- 从sysDescr解析出设备类型和厂商
- 计算出设备启动时间

---

### 示例3: Nokia基站识别

**场景**: 扫描到Nokia 5G基站（已配置SNMP profile）

**扫描结果**:
```json
{
  "ip_address": "10.200.50.10",
  "is_reachable": true,
  "response_time": 5,
  "hostname": "gNB-Site-001",
  "hostname_source": "SNMP",
  "system_name": "gNB-Site-001",
  "contact": "RAN Team",
  "location": "Cell Tower - Site 001",
  "machine_type": "Nokia Base Station",
  "vendor": "Nokia",
  "os_type": "network",
  "last_boot_time": "2026-03-01T12:00:00Z"
}
```

**说明**:
- 从sysDescr关键词（gnodeb/base station）识别为基站
- 自动标记vendor为Nokia

---

## 故障排查

### 问题1: 扫描后所有设备hostname都为空

**可能原因**:
1. dnspython未安装（DNS查询失败）
2. 未配置SNMP profile（SNMP查询跳过）
3. DNS服务器无PTR记录
4. 设备不支持SNMP

**解决方法**:
1. 安装dnspython（参考上方安装步骤）
2. 创建并配置SNMP profile
3. 检查DNS服务器配置
4. 手动为IP添加描述信息

---

### 问题2: SNMP查询失败

**检查步骤**:

```bash
# 1. 查看backend日志
sudo docker logs iptrack-backend --tail 100 | grep -i snmp

# 2. 手动测试SNMP
sudo docker exec iptrack-backend python3 << 'EOF'
import asyncio
from services.snmp_service import snmp_service

async def test():
    profile = {
        'username': 'your_username',
        'auth_protocol': 'SHA',
        'auth_password_encrypted': 'encrypted_password',
        'priv_protocol': 'AES',
        'priv_password_encrypted': 'encrypted_password',
        'port': 161,
        'timeout': 5
    }
    result = await snmp_service.get_device_identification('TARGET_IP', profile)
    print(result)

asyncio.run(test())
EOF
```

**常见错误**:
- `Timeout`: SNMP端口不通或设备未开启SNMP
- `Authentication failed`: SNMP凭据不正确
- `No Such Name`: 设备不支持该OID

---

### 问题3: 设备类型识别不准确

**解决方法**:

1. **检查sysDescr内容**:
   ```sql
   SELECT ip_address, machine_type, vendor, system_name
   FROM ip_addresses
   WHERE vendor IS NOT NULL;
   ```

2. **手动修正**:
   - 在前端编辑IP地址
   - 手动设置正确的设备类型和厂商

3. **提交改进建议**:
   - 如果某类设备无法识别，可以在代码中添加识别规则
   - 修改 `snmp_service.py` 的设备类型检测逻辑

---

## 性能优化

### 扫描性能

- **并发数**: 由 `IPAM_SCAN_WORKERS` 环境变量控制（默认20）
- **超时时间**: Ping超时2秒，SNMP超时5秒，DNS超时5秒
- **扫描速度**:
  - Quick scan: ~254 IPs in 10秒
  - Full scan: ~254 IPs in 30秒（无SNMP）
  - Full scan: ~254 IPs in 60秒（有SNMP）

### 优化建议

```bash
# 增加扫描并发数（.env文件）
IPAM_SCAN_WORKERS=50  # 默认20

# 重启backend应用配置
cd /opt/IP-Track
sudo docker compose down
sudo docker compose up -d
```

---

## 更新日志

### v1.0 (2026-03-19)

**新增功能**:
- ✅ 增强设备类型识别（Dell PC、HP PC、Nokia基站等）
- ✅ 支持SNMP设备识别（hostname、contact、location、vendor）
- ✅ 多层次hostname优先级（SNMP > DNS > ARP）
- ✅ 基于sysDescr的智能设备分类
- ✅ 支持多厂商识别（Cisco、Dell、HP、Nokia、Huawei等）
- ✅ TTL-based OS检测增强（区分Windows/Linux/Network Device）
- ✅ nmap检测增强（识别打印机、摄像头等IoT设备）

**待完成**:
- ⏳ 安装dnspython以启用DNS PTR查询（需要网络或离线包）

---

## 联系支持

如有问题，请参考：
- **主文档**: [CLAUDE.md](CLAUDE.md)
- **IPAM功能指南**: [IPAM_FEATURES_GUIDE.md](IPAM_FEATURES_GUIDE.md)
- **项目文档**: [QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)

---

**文档版本**: 1.0
**最后更新**: 2026-03-19
