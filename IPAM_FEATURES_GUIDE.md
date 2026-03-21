# IPAM功能配置指南（快速诊断版）

## 🚀 快速诊断工具

我已创建了诊断脚本来帮你快速排查问题：

```bash
# 进入backend容器
docker exec -it iptrack-backend bash

# 运行诊断工具
cd /app
python diagnose_ipam.py
```

诊断工具会检查：
- ✅ DNS PTR查询是否工作
- ✅ OS检测工具（nmap）是否安装
- ✅ SNMP工具是否可用
- ✅ IPAM子网配置是否正确
- ✅ SNMP Profile是否关联
- ✅ SNMP连接是否成功

---

## 目录
1. [常见问题快速解答](#常见问题快速解答)
2. [DNS主机名识别](#dns主机名识别)
3. [操作系统检测](#操作系统检测)
4. [Last Boot Time采集](#last-boot-time采集)
5. [SNMP配置说明](#snmp配置说明)

---

## 常见问题快速解答

### ❓ 为什么Windows域机器的hostname没显示？

**快速诊断**：
```bash
# 1. 进入容器
docker exec -it iptrack-backend bash

# 2. 测试DNS PTR
nslookup 10.101.35.10

# 如果返回 "** server can't find..." 说明DNS PTR记录不存在
```

**解决方法（二选一）**：

#### 方案A: 配置DNS PTR记录（推荐）
在Windows DNS服务器上：
```powershell
# 打开DNS管理器
dnsmgmt.msc

# 右键"反向查找区域" → 新建区域
# 区域类型: 主要区域
# 区域名称: 35.101.10.in-addr.arpa (对应 10.101.35.0/24)

# 添加PTR记录
Add-DnsServerResourceRecordPtr -Name "10" `
    -ZoneName "35.101.10.in-addr.arpa" `
    -PtrDomainName "pc10.example.com"
```

#### 方案B: 使用SNMP（如果已配置）
1. 在IPAM主页编辑子网
2. 确认已选择SNMP Profile
3. 重新扫描子网

---

### ❓ OS检测不准确/全部显示Unknown？

**原因**: nmap未安装，只能用TTL猜测（不准确）

**解决方法**: 安装nmap获取精确检测

修改 [backend/Dockerfile](backend/Dockerfile)：
```dockerfile
# 在第6-10行修改:
RUN apt-get update && apt-get install -y \
    iputils-ping \
    arp-scan \
    net-tools \
    nmap \
    && rm -rf /var/lib/apt/lists/*
```

重建镜像：
```bash
docker-compose down
docker-compose build backend
docker-compose up -d
```

---

### ❓ Last Boot Time为什么一直是空的？

**重要**：Last Boot Time **只针对配置了SNMP的设备**（通常是交换机/路由器）

**检查清单**：
- [ ] 子网是否关联了SNMP Profile？（IPAM → 编辑子网 → SNMP Profile）
- [ ] SNMP Profile是否启用？
- [ ] 设备是否真的支持SNMP？（PC/服务器需要手动启用SNMP服务）

**快速验证**：
```bash
# 进入容器
docker exec -it iptrack-backend bash

# 运行诊断
python diagnose_ipam.py
# 输入子网ID → 会显示SNMP Profile配置状态
# 输入IP地址 → 测试SNMP连接
```

---

## DNS主机名识别

### 功能说明
IP-Track通过以下**优先级顺序**获取主机名：
1. **SNMP sysName** (OID: 1.3.6.1.2.1.1.5.0) - 最高优先级
2. **DNS PTR记录** (反向DNS查询) - 第二优先级
3. **手动输入** - 最低优先级

### 为什么Windows域机器的hostname没有被识别？

#### 原因1: DNS PTR记录未配置
**问题**: 大多数情况下，DNS服务器只配置了正向解析（主机名→IP），没有配置反向解析（IP→主机名）。

**解决方法**:
1. 在Windows DNS服务器上配置PTR记录：
   ```
   DNS管理器 → 反向查找区域 → 新建反向查找区域
   示例: 10.101.35.0/24 网段
   - 区域名称: 35.101.10.in-addr.arpa
   - 为每个IP添加PTR记录指向主机名
   ```

2. 验证PTR记录是否生效：
   ```bash
   # Linux/Mac
   nslookup 10.101.35.10
   # 或
   dig -x 10.101.35.10

   # Windows
   nslookup 10.101.35.10
   ```

3. 如果返回hostname，说明PTR记录配置正确，IP-Track会自动识别。

#### 原因2: SNMP未启用
**问题**: Windows机器默认不启用SNMP服务。

**解决方法**:
1. 在Windows机器上启用SNMP服务：
   ```
   控制面板 → 程序和功能 → 启用或关闭Windows功能 →
   简单网络管理协议(SNMP) → 勾选
   ```

2. 配置SNMPv3（推荐）：
   ```
   services.msc → SNMP Service → 安全 → 添加
   - 用户名: snmp_monitor
   - 认证协议: SHA
   - 认证密码: your_auth_password
   - 加密协议: AES-128
   - 加密密码: your_priv_password
   ```

3. 在IP-Track中配置SNMP Profile（见下文SNMP配置章节）

### 当前检测优先级示例

假设IP `10.101.35.10`：
- **场景1**: 有SNMP，有DNS PTR
  - ✅ 使用SNMP sysName: `DESKTOP-ABC123`
  - ❌ 忽略DNS PTR: `pc10.example.com`

- **场景2**: 无SNMP，有DNS PTR
  - ✅ 使用DNS PTR: `pc10.example.com`

- **场景3**: 无SNMP，无DNS PTR
  - ❌ hostname为空

### DNS PTR批量配置脚本（Windows DNS Server）

```powershell
# PowerShell脚本示例 - 批量添加PTR记录
$subnet = "10.101.35"
$domain = "example.com"

For ($i=1; $i -le 254; $i++) {
    $ip = "$subnet.$i"
    $hostname = "pc$i.$domain"

    # 添加PTR记录
    Add-DnsServerResourceRecordPtr -Name "$i" `
        -ZoneName "35.101.10.in-addr.arpa" `
        -PtrDomainName "$hostname"
}
```

---

## 操作系统检测

### 功能说明
IP-Track支持两种OS检测方式：
1. **nmap OS检测** (精确) - 需要安装nmap
2. **TTL-based检测** (简单) - 根据ping的TTL值推测

### 当前状态
- ✅ TTL-based检测：已启用（基于ping TTL值）
- ❌ nmap检测：**未安装nmap**

### TTL-based检测规则

| TTL范围 | 推测OS | 准确度 |
|---------|-------|-------|
| <= 64   | Linux/Unix | 中等 |
| <= 128  | Windows | 中等 |
| <= 255  | 网络设备 | 低 |

**代码位置**: `backend/src/services/ip_scan.py:203-264`

### 如何启用nmap精确检测？

#### 方法1: 在Docker容器中安装nmap

修改 `backend/Dockerfile`：
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（添加nmap）
RUN apt-get update && apt-get install -y \
    iputils-ping \
    net-tools \
    nmap \
    && rm -rf /var/lib/apt/lists/*

# ... 其余配置不变
```

重新构建Docker镜像：
```bash
docker-compose down
docker-compose build backend
docker-compose up -d
```

#### 方法2: 在运行中的容器安装

```bash
# 进入backend容器
docker exec -it iptrack-backend bash

# 安装nmap
apt-get update
apt-get install -y nmap

# 验证安装
nmap --version

# 退出容器
exit

# 重启backend
docker restart iptrack-backend
```

### nmap检测能力

安装nmap后，IP-Track可检测：
- ✅ Windows 10/11
- ✅ Windows Server 2019/2022
- ✅ Ubuntu 20.04/22.04
- ✅ CentOS 7/8
- ✅ macOS
- ✅ 网络设备厂商和型号

**代码位置**: `backend/src/services/ip_scan.py:168-202`

---

## Last Boot Time采集

### 功能说明
Last Boot Time (上次启动时间) 通过SNMP sysUpTime (OID: 1.3.6.1.2.1.1.3.0) 采集。

### 为什么Last Boot Time一直为空？

#### 原因: 没有配置SNMP Profile

**Last Boot Time需要SNMP支持**，ping/DNS无法获取此信息。

### 配置步骤

#### 1. 在IP-Track中创建SNMP Profile

前端界面操作：
1. 进入 **SNMP配置** 页面
2. 点击 **添加SNMP Profile**
3. 填写配置：
   ```
   名称: Windows_SNMP_Profile
   版本: SNMPv3
   用户名: snmp_monitor
   认证协议: SHA
   认证密码: your_auth_password
   加密协议: AES-128
   加密密码: your_priv_password
   端口: 161
   超时: 5秒
   重试次数: 3
   ```

#### 2. 为IP子网关联SNMP Profile

编辑子网时，选择刚创建的SNMP Profile：
```
IPAM → 编辑子网 → SNMP Profile: Windows_SNMP_Profile
```

#### 3. 在Windows机器上配置SNMP

**启用SNMP服务**:
```
控制面板 → 程序和功能 → 启用或关闭Windows功能
勾选: 简单网络管理协议(SNMP)
```

**配置SNMPv3**:
1. 打开服务管理: `services.msc`
2. 找到 `SNMP Service` → 右键属性
3. **安全选项卡**:
   - 添加SNMPv3用户
   - 用户名: `snmp_monitor`
   - 认证协议: SHA
   - 认证密码: `your_auth_password`
   - 加密协议: AES-128
   - 加密密码: `your_priv_password`

4. **代理选项卡** (可选):
   - 联系人: IT部门
   - 位置: XX楼XX机房
   - 服务: 勾选所有

5. 重启SNMP服务:
   ```powershell
   Restart-Service SNMP
   ```

#### 4. 验证SNMP配置

在IP-Track服务器上测试SNMP连接：
```bash
# 进入backend容器
docker exec -it iptrack-backend bash

# 安装snmpwalk工具（如果没有）
apt-get update && apt-get install -y snmp

# 测试SNMPv3连接
snmpwalk -v3 \
  -u snmp_monitor \
  -l authPriv \
  -a SHA \
  -A your_auth_password \
  -x AES \
  -X your_priv_password \
  10.101.35.10 \
  1.3.6.1.2.1.1.5.0

# 应该返回: SNMPv2-MIB::sysName.0 = STRING: DESKTOP-ABC123

# 测试sysUpTime
snmpwalk -v3 \
  -u snmp_monitor \
  -l authPriv \
  -a SHA \
  -A your_auth_password \
  -x AES \
  -X your_priv_password \
  10.101.35.10 \
  1.3.6.1.2.1.1.3.0

# 应该返回: DISMAN-EVENT-MIB::sysUpTimeInstance = Timeticks: (123456789) 14 days, 6:56:07.89
```

#### 5. 触发扫描

配置完成后，在IPAM主页点击 **扫描** 按钮，或等待自动扫描（默认2小时）。

### 采集的SNMP信息

配置SNMP Profile后，IP-Track会采集以下信息：

| SNMP字段 | OID | 说明 | 显示在IPAM |
|---------|-----|------|----------|
| sysName | 1.3.6.1.2.1.1.5.0 | 主机名 | ✅ DNS列 |
| sysDescr | 1.3.6.1.2.1.1.1.0 | 系统描述 | ✅ Machine Type |
| sysUpTime | 1.3.6.1.2.1.1.3.0 | 运行时间 | ✅ Last Boot Time |
| sysContact | 1.3.6.1.2.1.1.4.0 | 联系人 | ❌ 已移除 |
| sysLocation | 1.3.6.1.2.1.1.6.0 | 位置 | ❌ 已移除 |

**代码位置**: `backend/src/services/snmp_service.py:569-697`

---

## SNMP配置说明

### SNMPv3 vs SNMPv2c

| 特性 | SNMPv3 | SNMPv2c |
|-----|--------|---------|
| 安全性 | ✅ 高（加密） | ❌ 低（明文community） |
| 认证 | ✅ 用户名+密码 | ❌ Community字符串 |
| 加密 | ✅ AES/DES | ❌ 无 |
| 推荐度 | ✅ 强烈推荐 | ❌ 仅测试用 |

**建议**: 生产环境使用SNMPv3

### Windows批量配置SNMP脚本

```powershell
# 批量启用SNMP服务（需管理员权限）
# 保存为: Enable-SNMP.ps1

# 1. 安装SNMP功能
Add-WindowsCapability -Online -Name "SNMP.Client~~~~0.0.1.0"

# 2. 配置SNMP服务
$snmpService = Get-Service -Name SNMP -ErrorAction SilentlyContinue

if ($snmpService) {
    # 设置SNMP服务为自动启动
    Set-Service -Name SNMP -StartupType Automatic

    # 配置SNMP安全（使用注册表）
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\SNMP\Parameters"

    # 设置联系人和位置
    Set-ItemProperty -Path "$regPath\RFC1156Agent" -Name "sysContact" -Value "IT Support"
    Set-ItemProperty -Path "$regPath\RFC1156Agent" -Name "sysLocation" -Value "Data Center"

    # 启动服务
    Start-Service -Name SNMP

    Write-Host "✅ SNMP服务已启用并启动" -ForegroundColor Green
} else {
    Write-Host "❌ SNMP服务安装失败" -ForegroundColor Red
}
```

运行脚本：
```powershell
# 以管理员身份运行PowerShell
Set-ExecutionPolicy Bypass -Scope Process -Force
.\Enable-SNMP.ps1
```

### 组策略批量部署SNMP（域环境）

对于域环境，可通过组策略批量配置：

1. **创建GPO**: `gpedit.msc` → 计算机配置 → Windows设置 → 安全设置 → 系统服务
2. **启用SNMP服务**: SNMP Service → 自动
3. **配置防火墙规则**: 允许UDP 161入站
4. **应用到OU**: 链接GPO到目标组织单位

---

## 故障排查

### 问题1: DNS主机名仍然为空

**检查清单**:
- [ ] DNS PTR记录是否存在？ (`nslookup IP_ADDRESS`)
- [ ] SNMP Profile是否配置？
- [ ] SNMP Profile是否关联到子网？
- [ ] Windows机器SNMP服务是否启动？
- [ ] 防火墙是否允许UDP 161端口？

**查看日志**:
```bash
docker logs iptrack-backend | grep -i "snmp\|dns"
```

### 问题2: Last Boot Time为空

**检查清单**:
- [ ] 是否配置了SNMP Profile？
- [ ] SNMP Profile是否关联到子网？
- [ ] 手动snmpwalk测试是否成功？
- [ ] Windows防火墙是否允许SNMP？

**手动测试**:
```bash
# 测试sysUpTime
snmpget -v3 -u snmp_monitor -l authPriv \
  -a SHA -A auth_pass \
  -x AES -X priv_pass \
  10.101.35.10 1.3.6.1.2.1.1.3.0
```

### 问题3: OS检测不准确

**解决方法**:
- 安装nmap获取精确检测（见上文）
- TTL-based检测仅供参考

### 问题4: 扫描超时

**调整超时设置**:
1. 编辑SNMP Profile
2. 超时时间: 5秒 → 10秒
3. 重试次数: 3 → 5

---

## 推荐配置方案

### 小型网络 (<100台设备)
- ✅ DNS PTR记录: 推荐配置
- ✅ SNMP: 推荐配置（用于关键服务器）
- ❌ nmap: 可选

### 中型网络 (100-500台设备)
- ✅ DNS PTR记录: **必须配置**
- ✅ SNMP: 推荐配置
- ✅ nmap: 推荐安装

### 大型网络 (>500台设备)
- ✅ DNS PTR记录: **必须配置**
- ✅ SNMP: **必须配置**（通过组策略批量部署）
- ✅ nmap: **必须安装**
- ✅ 分段扫描: 调整扫描间隔避免网络拥塞

---

## 相关文件位置

| 功能 | 文件路径 | 说明 |
|-----|---------|------|
| IP扫描服务 | `backend/src/services/ip_scan.py` | Ping、DNS、SNMP集成 |
| SNMP服务 | `backend/src/services/snmp_service.py` | SNMP数据采集 |
| IPAM服务 | `backend/src/services/ipam_service.py` | 子网扫描逻辑 |
| 配置文件 | `backend/.env` | 扫描间隔、工作线程数 |

---

## 配置示例总结

### 1. 快速启用DNS主机名（无SNMP）

```bash
# 仅配置DNS PTR记录
# Windows DNS服务器:
Add-DnsServerResourceRecordPtr -Name "10" \
  -ZoneName "35.101.10.in-addr.arpa" \
  -PtrDomainName "pc10.example.com"
```

### 2. 完整配置（推荐）

```yaml
步骤1: 在IP-Track创建SNMP Profile
  - 名称: Production_SNMP
  - 版本: SNMPv3
  - 用户名: monitor
  - 认证: SHA + your_auth_password
  - 加密: AES-128 + your_priv_password

步骤2: 关联子网到SNMP Profile
  - 编辑子网 → SNMP Profile: Production_SNMP

步骤3: 在Windows机器配置SNMP
  - 启用SNMP服务
  - 配置SNMPv3用户
  - 启动服务

步骤4: 配置DNS PTR记录
  - 反向查找区域: XX.XX.XX.in-addr.arpa
  - 添加PTR记录

步骤5: 安装nmap（可选）
  - 修改Dockerfile添加nmap
  - 重建镜像
```

### 3. 验证配置

```bash
# 测试1: DNS PTR
nslookup 10.101.35.10
# 期望: 返回主机名

# 测试2: SNMP sysName
snmpget -v3 -u monitor -l authPriv -a SHA -A pass -x AES -X pass \
  10.101.35.10 1.3.6.1.2.1.1.5.0
# 期望: 返回sysName

# 测试3: SNMP sysUpTime
snmpget -v3 -u monitor -l authPriv -a SHA -A pass -x AES -X pass \
  10.101.35.10 1.3.6.1.2.1.1.3.0
# 期望: 返回Timeticks

# 测试4: 在IP-Track触发扫描
# IPAM → 点击子网 → 扫描
# 等待5-10秒 → 刷新页面 → 查看结果
```

---

**最后更新**: 2026-03-18
**作者**: Claude Code Assistant
