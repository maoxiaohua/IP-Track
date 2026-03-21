#!/usr/bin/env python3
"""
简单的SNMP测试 - 诊断CarrierError问题
"""

import sys
import asyncio

# Add src to path
sys.path.insert(0, '/app/src')

async def test_snmp_basic():
    """测试基本的SNMP连接"""
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity, get_cmd,
        usmHMACSHAAuthProtocol, usmAesCfb128Protocol
    )
    from core.security import decrypt_password
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.ipam import SNMPProfile
    from core.config import settings

    print(f"\n{'='*60}")
    print(f"SNMP连接诊断测试")
    print(f"{'='*60}\n")

    # 创建数据库连接
    engine = create_engine(
        settings.DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'),
        echo=False
    )
    Session = sessionmaker(bind=engine)

    with Session() as session:
        # 获取SNMP Profile
        profile = session.query(SNMPProfile).filter(SNMPProfile.enabled == True).first()

        if not profile:
            print("❌ 没有启用的SNMP Profile")
            return

        print(f"使用SNMP Profile: {profile.name}")
        print(f"  用户名: {profile.username}")
        print(f"  认证协议: {profile.auth_protocol}")
        print(f"  加密协议: {profile.priv_protocol}")
        print(f"  端口: {profile.port}")
        print(f"  超时: {profile.timeout}秒")
        print("")

        # 解密密码
        try:
            auth_password = decrypt_password(profile.auth_password_encrypted)
            priv_password = decrypt_password(profile.priv_password_encrypted)
            print("✅ 密码解密成功")
        except Exception as e:
            print(f"❌ 密码解密失败: {e}")
            return

        # 测试IP地址
        test_ip = "10.71.192.1"
        print(f"\n测试目标: {test_ip}")
        print(f"{'='*60}\n")

        # 创建SNMP认证
        snmp_auth = UsmUserData(
            profile.username,
            authKey=auth_password,
            privKey=priv_password,
            authProtocol=usmHMACSHAAuthProtocol,
            privProtocol=usmAesCfb128Protocol
        )

        # 创建传输目标
        transport = UdpTransportTarget(
            (test_ip, profile.port),
            timeout=profile.timeout,
            retries=1
        )

        # 测试查询 sysName
        print(f"正在查询 sysName (OID: 1.3.6.1.2.1.1.5.0)...")

        try:
            engine = SnmpEngine()

            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                engine,
                snmp_auth,
                transport,
                ContextData(),
                ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0'))
            )

            if errorIndication:
                print(f"❌ SNMP错误: {errorIndication}")
                print(f"   错误类型: {type(errorIndication).__name__}")

                # 详细诊断
                if 'timeout' in str(errorIndication).lower():
                    print(f"\n可能原因:")
                    print(f"1. 设备SNMP服务未启用")
                    print(f"2. 防火墙阻止UDP 161端口")
                    print(f"3. SNMP认证失败")
                    print(f"4. 网络不可达")
                elif 'carrier' in str(errorIndication).lower():
                    print(f"\n可能原因:")
                    print(f"1. Docker网络配置问题")
                    print(f"2. 容器无法创建UDP socket")
                    print(f"3. 权限不足")

            elif errorStatus:
                print(f"❌ SNMP协议错误: {errorStatus.prettyPrint()} at {errorIndex}")
            else:
                print(f"✅ SNMP查询成功!\n")
                for varBind in varBinds:
                    oid, value = varBind
                    print(f"  {oid.prettyPrint()} = {value.prettyPrint()}")

        except Exception as e:
            print(f"❌ 异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    asyncio.run(test_snmp_basic())
