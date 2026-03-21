#!/usr/bin/env python3
"""
测试SNMP连接到单个设备
使用方法: python test_snmp_device.py <IP地址>
"""

import sys
import asyncio

# Add src to path
sys.path.insert(0, '/app/src')

async def test_snmp_connection(ip_address: str):
    """测试SNMP连接到指定设备"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.ipam import SNMPProfile
    from services.snmp_service import snmp_service
    from core.config import settings
    from core.security import decrypt_password

    print(f"\n{'='*60}")
    print(f"测试SNMP连接: {ip_address}")
    print(f"{'='*60}\n")

    # 创建数据库连接
    engine = create_engine(
        settings.DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'),
        echo=False
    )
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # 获取第一个启用的SNMP Profile
        profile = session.query(SNMPProfile).filter(SNMPProfile.enabled == True).first()

        if not profile:
            print("❌ 没有启用的SNMP Profile")
            return

        print(f"使用SNMP Profile: {profile.name}")
        print(f"  版本: {profile.version}")
        print(f"  用户名: {profile.username}")
        print(f"  认证协议: {profile.auth_protocol}")
        print(f"  加密协议: {profile.priv_protocol}")
        print(f"  端口: {profile.port}")
        print(f"  超时: {profile.timeout}秒")
        print("")

        # 准备SNMP profile字典
        snmp_profile = {
            'username': profile.username,
            'auth_protocol': profile.auth_protocol,
            'auth_password_encrypted': profile.auth_password_encrypted,
            'priv_protocol': profile.priv_protocol,
            'priv_password_encrypted': profile.priv_password_encrypted,
            'port': profile.port,
            'timeout': profile.timeout
        }

        # 测试连接
        print(f"正在连接 {ip_address}...")
        try:
            result = await snmp_service.get_device_identification(ip_address, snmp_profile)

            if result:
                print(f"\n✅ SNMP连接成功!\n")
                print(f"设备信息:")
                print(f"  sysName (主机名): {result.get('system_name', 'N/A')}")
                print(f"  sysDescr (系统描述): {result.get('machine_type', 'N/A')[:100]}")
                print(f"  sysContact (联系人): {result.get('contact', 'N/A')}")
                print(f"  sysLocation (位置): {result.get('location', 'N/A')}")
                print(f"  Vendor (厂商): {result.get('vendor', 'N/A')}")
                print(f"  Last Boot Time: {result.get('last_boot_time', 'N/A')}")
            else:
                print(f"\n❌ SNMP查询失败: 没有返回数据")
                print(f"\n可能原因:")
                print(f"1. 设备的SNMP服务未启用")
                print(f"2. 设备上没有配置这个SNMP用户")
                print(f"3. SNMP认证信息不匹配")
                print(f"4. 防火墙阻止UDP 161端口")

        except Exception as e:
            print(f"\n❌ SNMP连接失败: {str(e)}\n")
            print(f"错误类型: {type(e).__name__}")
            print(f"\n常见原因:")
            print(f"1. SNMP用户名或密码错误")
            print(f"2. 认证协议不匹配（设备可能使用MD5而不是SHA）")
            print(f"3. 加密协议不匹配（设备可能使用DES而不是AES）")
            print(f"4. 设备不支持SNMPv3（可能只支持v2c）")
            print(f"5. 网络不可达或防火墙阻止")
            print(f"\n建议:")
            print(f"1. 检查交换机的SNMP配置:")
            print(f"   - 确认SNMPv3用户已创建")
            print(f"   - 确认用户名和密码正确")
            print(f"   - 确认认证和加密协议匹配")
            print(f"2. 在交换机上验证SNMP配置:")
            print(f"   show snmp user (Cisco)")
            print(f"   show configuration snmp (Nokia)")
            print(f"3. 测试网络连通性:")
            print(f"   ping {ip_address}")

    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python test_snmp_device.py <IP地址>")
        print("示例: python test_snmp_device.py 10.71.192.1")
        sys.exit(1)

    ip_address = sys.argv[1]
    asyncio.run(test_snmp_connection(ip_address))
