# 交换机命令参考 / Switch Commands Reference

本文档详细说明了系统支持的各品牌交换机的命令格式。

## Cisco IOS / IOS-XE

### ARP 表查询
**主命令**: `show ip arp <IP地址>`
**备用命令**: `show arp <IP地址>`

示例输出:
```
Internet  192.168.1.100   12   0050.56c0.0001  ARPA   Vlan1
```

### MAC 地址表查询
**命令**: `show mac address-table address <MAC地址>`
- MAC 格式: `aaaa.bbbb.cccc` (Cisco点分格式)

示例输出:
```
Vlan    Mac Address       Type        Ports
----    -----------       --------    -----
  1     0050.56c0.0001    DYNAMIC     Gi1/0/1
```

**字段说明**:
- Vlan: VLAN ID
- Mac Address: MAC地址 (Cisco点分格式)
- Type: 类型 (DYNAMIC/STATIC)
- Ports: 端口号

---

## Dell Networking (OS9/OS10)

### ARP 表查询
**主命令**: `show arp <IP地址>`
**备用命令**: `show ip arp <IP地址>`

示例输出:
```
192.168.1.100   00:50:56:c0:00:01   Vlan 1          Dynamic
```

### MAC 地址表查询
**命令**: `show mac-address-table address <MAC地址>`
- MAC 格式: `nn:nn:nn:nn:nn:nn` (标准冒号格式)

示例输出:
```
VlanId  Mac Address         Type      Interface
------  -----------------   -------   ---------
1       00:50:56:c0:00:01   Dynamic   ethernet 1/g1
```

或者 (OS10):
```
Vlan ID    MAC Address         Interface              Type
-------    -----------------   ---------------------  ------
10         00:11:22:33:44:55   GigabitEthernet 1/0/1  Dynamic
```

**字段说明**:
- VlanId/Vlan ID: VLAN ID
- Mac Address/MAC Address: MAC地址 (标准冒号格式)
- Type: 类型 (Dynamic/Static)
- Interface: 接口名称

---

## Alcatel-Lucent / Nokia OmniSwitch

### ARP 表查询
**命令**: `show arp`
- 注意: Alcatel 返回完整的 ARP 表,需要在输出中过滤目标 IP

示例输出:
```
IP Address       Physical Address  Type       Age (sec) VLAN  Port
---------------------------------------------------------------------------
192.168.1.100    00:50:56:c0:00:01 dynamic    3600      1     1/1/1
```

**字段说明**:
- IP Address: IP 地址
- Physical Address: MAC 地址 (标准冒号格式)
- Type: 类型 (dynamic/static)
- Age: 老化时间(秒)
- VLAN: VLAN ID
- Port: 端口号 (格式: slot/module/port)

### MAC 地址表查询
**命令**: `show mac-address <MAC地址>`
或: `show mac-learning mac-address <MAC地址>`

示例输出 (show mac-address):
```
MAC Address         VLAN    Port           Type
---------------------------------------------------
00:50:56:c0:00:01   1       1/1/1          learned
```

示例输出 (show mac-learning):
```
vlan   mac                 port      age
-----------------------------------------------
1      00:50:56:c0:00:01   1/1/1     0
```

**字段说明**:
- MAC Address/mac: MAC 地址 (标准冒号格式)
- VLAN/vlan: VLAN ID
- Port/port: 端口号 (格式: slot/module/port)
- Type: 类型 (learned/static)
- age: 老化时间

---

## MAC 地址格式转换

系统会自动处理不同厂商的 MAC 地址格式:

| 厂商 | 原始格式 | 标准化格式 |
|------|----------|------------|
| Cisco | aaaa.bbbb.cccc | aa:bb:cc:dd:ee:ff |
| Dell | aa:bb:cc:dd:ee:ff | aa:bb:cc:dd:ee:ff |
| Alcatel | aa:bb:cc:dd:ee:ff | aa:bb:cc:dd:ee:ff |

---

## 端口格式说明

不同厂商的端口命名格式:

### Cisco
- `Gi1/0/1` - GigabitEthernet 1/0/1
- `Fa0/1` - FastEthernet 0/1
- `Te1/0/1` - TenGigabitEthernet 1/0/1

### Dell
- `ethernet 1/g1` - Gigabit Ethernet 端口 1
- `GigabitEthernet 1/0/1` - 千兆以太网 1/0/1
- `Gi1/0/1` - 简写格式

### Alcatel
- `1/1/1` - Slot 1, Module 1, Port 1
- `2/3/5` - Slot 2, Module 3, Port 5

---

## 命令执行流程

系统查询 IP 地址的流程:

1. **ARP 表查询**: 在所有已启用的交换机上查询 ARP 表,找到 IP 对应的 MAC 地址
   - 优先级高的交换机先查询
   - 如果主命令失败,自动尝试备用命令
   
2. **MAC 地址表查询**: 使用找到的 MAC 地址,在交换机上查询 MAC 地址表,找到对应的端口
   - 同样按优先级查询
   - 返回 VLAN 和端口信息

3. **结果返回**: 返回完整的设备位置信息:
   - 交换机名称和 IP
   - 端口号
   - VLAN ID
   - MAC 地址

---

## 故障排查

### ARP 表未找到
- 确认设备是否在线
- 检查设备是否在正确的 VLAN
- 确认交换机是否为该网段的网关

### MAC 表未找到
- MAC 地址可能已老化
- 设备可能连接到未纳管的交换机
- 检查端口是否禁用

### 命令执行失败
- 检查交换机认证凭据
- 确认交换机类型配置正确
- 查看系统日志获取详细错误信息
