#!/usr/bin/env python3
"""
修复交换机型号识别

1. Alcatel: SR Linux -> 7220/7250 (从名称解析)
2. Cisco/Dell Unknown -> 通过SNMP获取正确型号
"""
import sys
import re
import asyncio
sys.path.insert(0, '/app/src')

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import sessionmaker
from models.switch import Switch
from core.security import decrypt_password

# SNMP相关导入
try:
    from pysnmp.hlapi import *
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False
    print("⚠️  pysnmp未安装，将跳过SNMP型号检测")


def parse_alcatel_model_from_name(name):
    """从Alcatel交换机名称解析型号"""
    patterns = [
        (r'7220D1', '7220 IXR-D1'),
        (r'7220D2L', '7220 IXR-D2L'),
        (r'7220D2', '7220 IXR-D2'),
        (r'7250[eE]2', '7250 IXR-e2'),
        (r'7250[xX]', '7250 IXR-x'),
        (r'7250', '7250 IXR'),
        (r'7220', '7220 IXR'),
    ]

    for pattern, model in patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return model

    return None


def get_snmp_sysdescr(ip, username, auth_pass, priv_pass):
    """通过SNMP获取系统描述"""
    if not SNMP_AVAILABLE:
        return None

    try:
        oid = ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0)

        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(SnmpEngine(),
                   UsmUserData(username,
                              authKey=auth_pass,
                              privKey=priv_pass,
                              authProtocol=usmHMACSHAAuthProtocol,
                              privProtocol=usmAesCfb128Protocol),
                   UdpTransportTarget((ip, 161), timeout=3, retries=1),
                   ContextData(),
                   ObjectType(oid))
        )

        if errorIndication or errorStatus:
            return None

        for varBind in varBinds:
            return str(varBind[1])
    except Exception:
        return None


def parse_cisco_model(sysdescr):
    """从Cisco sysDescr解析型号"""
    patterns = [
        r'[,\s]+(C\d+[A-Z]*)',  # C3560, C3560E, C2960S
        r'cisco\s+([A-Z]+\d+\w*)',  # Cisco NX9K等
    ]

    for pattern in patterns:
        match = re.search(pattern, sysdescr, re.IGNORECASE)
        if match:
            model = match.group(1).strip()
            # 移除后缀
            model = re.sub(r'-UNIVERSALK9.*', '', model)
            return model

    return None


def parse_dell_model(sysdescr):
    """从Dell sysDescr解析型号"""
    patterns = [
        r'Series:\s*([SZ]\d+[A-Z]*[-\w]*)',  # Series: S4048-ON
        r'Dell.*?Networking\s+([SZ]\d+[A-Z]*[-\w]*)',  # Dell EMC Networking S3048-ON
    ]

    for pattern in patterns:
        match = re.search(pattern, sysdescr, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


async def fix_alcatel_models(db: AsyncSession):
    """修复Alcatel型号"""
    print("\n" + "=" * 100)
    print("【1】修复Alcatel交换机型号（SR Linux -> 7220/7250）")
    print("=" * 100)

    result = await db.execute(
        select(Switch).where(
            Switch.vendor == 'alcatel',
            Switch.model.like('%SR Linux%')
        )
    )
    switches = result.scalars().all()

    print(f"\n找到 {len(switches)} 台Alcatel交换机型号为SR Linux\n")

    updated = 0
    for sw in switches:
        new_model = parse_alcatel_model_from_name(sw.name)

        if new_model:
            print(f"ID {sw.id:5d}: {sw.name[:60]:60s}")
            print(f"         {sw.model:20s} -> {new_model}")

            sw.model = new_model
            updated += 1

    if updated > 0:
        await db.commit()
        print(f"\n✅ 成功更新 {updated} 台Alcatel交换机型号")
    else:
        print("\n⚠️  没有需要更新的Alcatel交换机")

    return updated


async def fix_cisco_dell_models(db: AsyncSession):
    """修复Cisco和Dell Unknown型号"""
    print("\n" + "=" * 100)
    print("【2】修复Cisco和Dell Unknown型号（通过SNMP）")
    print("=" * 100)

    if not SNMP_AVAILABLE:
        print("\n⚠️  pysnmp未安装，跳过SNMP检测")
        return 0

    result = await db.execute(
        select(Switch).where(
            or_(
                and_(Switch.vendor == 'cisco', or_(Switch.model == 'Unknown', Switch.model == None, Switch.model == '')),
                and_(Switch.vendor == 'dell', or_(Switch.model == 'Unknown', Switch.model == None, Switch.model == ''))
            ),
            Switch.snmp_enabled == True
        )
    )
    switches = result.scalars().all()

    print(f"\n找到 {len(switches)} 台Cisco/Dell交换机型号为Unknown且启用SNMP\n")

    updated = 0
    for sw in switches:
        print(f"ID {sw.id:5d}: {sw.name[:50]:50s} (IP: {sw.ip_address})")

        # 解密SNMP密码
        if not sw.snmp_auth_password_encrypted or not sw.snmp_priv_password_encrypted:
            print(f"         ⚠️  缺少SNMP凭据，跳过")
            continue

        try:
            auth_pass = decrypt_password(sw.snmp_auth_password_encrypted)
            priv_pass = decrypt_password(sw.snmp_priv_password_encrypted)
        except Exception as e:
            print(f"         ❌ 解密SNMP密码失败: {e}")
            continue

        # 通过SNMP获取sysDescr
        sysdescr = get_snmp_sysdescr(
            str(sw.ip_address),
            sw.snmp_username or 'NSBsct',
            auth_pass,
            priv_pass
        )

        if not sysdescr:
            print(f"         ❌ SNMP查询失败")
            continue

        print(f"         sysDescr: {sysdescr[:70]}...")

        # 解析型号
        new_model = None
        if sw.vendor == 'cisco':
            new_model = parse_cisco_model(sysdescr)
        elif sw.vendor == 'dell':
            new_model = parse_dell_model(sysdescr)

        if new_model:
            print(f"         ✅ 识别型号: {new_model}")
            sw.model = new_model
            updated += 1
        else:
            print(f"         ⚠️  无法从sysDescr解析型号")

    if updated > 0:
        await db.commit()
        print(f"\n✅ 成功更新 {updated} 台Cisco/Dell交换机型号")
    else:
        print("\n⚠️  没有需要更新的Cisco/Dell交换机")

    return updated


async def main():
    print("=" * 100)
    print("修复交换机型号识别工具")
    print("=" * 100)

    # 连接数据库
    engine = create_async_engine(
        'postgresql+asyncpg://iptrack:iptrack@database:5432/iptrack',
        echo=False
    )

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as db:
        # 1. 修复Alcatel型号
        alcatel_updated = await fix_alcatel_models(db)

        # 2. 修复Cisco和Dell Unknown型号
        cisco_dell_updated = await fix_cisco_dell_models(db)

        # 总结
        print("\n" + "=" * 100)
        print(f"总计更新: {alcatel_updated + cisco_dell_updated} 台交换机")
        print("=" * 100)

    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
