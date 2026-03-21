#!/usr/bin/env python3
"""
IPAM功能诊断工具
用于排查DNS、SNMP、OS检测问题
"""

import sys
import os
import socket
import subprocess
import shutil

# Add src to path
sys.path.insert(0, '/app/src')

def check_dns_ptr(ip_address):
    """检查DNS PTR记录"""
    print(f"\n{'='*60}")
    print(f"检查DNS PTR记录: {ip_address}")
    print(f"{'='*60}")

    # 方法1: socket.gethostbyaddr
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_address)
        print(f"✅ socket.gethostbyaddr: {hostname}")
    except Exception as e:
        print(f"❌ socket.gethostbyaddr失败: {str(e)}")

    # 方法2: dnspython
    try:
        import dns.resolver
        import dns.reversename

        rev_name = dns.reversename.from_address(ip_address)
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 5

        answers = resolver.resolve(rev_name, "PTR")
        if answers:
            ptr_record = str(answers[0])
            if ptr_record.endswith('.'):
                ptr_record = ptr_record[:-1]
            print(f"✅ dnspython PTR: {ptr_record}")
        else:
            print(f"❌ dnspython PTR: 无记录")
    except dns.resolver.NXDOMAIN:
        print(f"❌ dnspython PTR: 域不存在（DNS服务器没有该IP的PTR记录）")
    except dns.resolver.Timeout:
        print(f"❌ dnspython PTR: 查询超时")
    except Exception as e:
        print(f"❌ dnspython PTR失败: {str(e)}")

    # 方法3: nslookup命令
    try:
        result = subprocess.run(
            ['nslookup', ip_address],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        output = result.stdout.decode()
        if 'name =' in output.lower():
            print(f"✅ nslookup成功:")
            for line in output.split('\n'):
                if 'name' in line.lower():
                    print(f"   {line.strip()}")
        else:
            print(f"❌ nslookup: 无PTR记录")
    except FileNotFoundError:
        print(f"⚠️  nslookup命令不存在")
    except Exception as e:
        print(f"❌ nslookup失败: {str(e)}")

def check_os_detection():
    """检查OS检测能力"""
    print(f"\n{'='*60}")
    print(f"检查OS检测工具")
    print(f"{'='*60}")

    # 检查nmap
    nmap_path = shutil.which('nmap')
    if nmap_path:
        print(f"✅ nmap已安装: {nmap_path}")
        try:
            result = subprocess.run(
                ['nmap', '--version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            version = result.stdout.decode().split('\n')[0]
            print(f"   版本: {version}")
        except Exception as e:
            print(f"   无法获取版本: {str(e)}")
    else:
        print(f"❌ nmap未安装")
        print(f"   当前只能使用TTL-based简单检测:")
        print(f"   - TTL ≤ 64  → Linux/Unix")
        print(f"   - TTL ≤ 128 → Windows")
        print(f"   - TTL ≤ 255 → 网络设备")

    # 检查ping
    ping_path = shutil.which('ping')
    if ping_path:
        print(f"✅ ping已安装: {ping_path}")
    else:
        print(f"❌ ping未安装")

def check_snmp_tools():
    """检查SNMP工具"""
    print(f"\n{'='*60}")
    print(f"检查SNMP工具")
    print(f"{'='*60}")

    # 检查pysnmp
    try:
        import pysnmp
        print(f"✅ pysnmp已安装: {pysnmp.__version__}")
    except ImportError:
        print(f"❌ pysnmp未安装")

    # 检查snmpget命令
    snmpget_path = shutil.which('snmpget')
    if snmpget_path:
        print(f"✅ snmpget已安装: {snmpget_path}")
    else:
        print(f"⚠️  snmpget未安装（可选，用于手动测试）")
        print(f"   安装方法: apt-get install -y snmp")

def test_snmp_device(ip_address, snmp_profile):
    """测试SNMP设备连接"""
    print(f"\n{'='*60}")
    print(f"测试SNMP连接: {ip_address}")
    print(f"{'='*60}")

    try:
        from services.snmp_service import snmp_service
        import asyncio

        # 测试基本连接
        async def test():
            result = await snmp_service.get_device_identification(ip_address, snmp_profile)
            return result

        result = asyncio.run(test())

        if result:
            print(f"✅ SNMP连接成功!")
            print(f"   sysName (主机名): {result.get('system_name', 'N/A')}")
            print(f"   sysContact: {result.get('contact', 'N/A')}")
            print(f"   sysLocation: {result.get('location', 'N/A')}")
            print(f"   Last Boot Time: {result.get('last_boot_time', 'N/A')}")
            print(f"   Machine Type: {result.get('machine_type', 'N/A')}")
            print(f"   Vendor: {result.get('vendor', 'N/A')}")
        else:
            print(f"❌ SNMP查询失败: 未返回任何数据")
            print(f"   可能原因:")
            print(f"   1. SNMP服务未启用")
            print(f"   2. 认证信息错误")
            print(f"   3. 防火墙阻止UDP 161端口")

    except Exception as e:
        print(f"❌ SNMP连接失败: {str(e)}")
        print(f"   可能原因:")
        print(f"   1. 认证信息不正确")
        print(f"   2. 设备不支持SNMP或未启用")
        print(f"   3. 网络不可达")

def check_ipam_subnet_config(subnet_id):
    """检查IPAM子网配置"""
    print(f"\n{'='*60}")
    print(f"检查IPAM子网配置: ID {subnet_id}")
    print(f"{'='*60}")

    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker
        from models.ipam import IPSubnet, SNMPProfile
        from core.config import settings

        # 创建数据库连接
        engine = create_engine(
            settings.DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'),
            echo=False
        )
        Session = sessionmaker(bind=engine)

        with Session() as session:
            # 查询子网
            subnet = session.query(IPSubnet).filter(IPSubnet.id == subnet_id).first()

            if not subnet:
                print(f"❌ 子网不存在: ID {subnet_id}")
                return

            print(f"✅ 子网信息:")
            print(f"   名称: {subnet.name}")
            print(f"   网络: {subnet.network}")
            print(f"   自动扫描: {'是' if subnet.auto_scan else '否'}")
            print(f"   扫描间隔: {subnet.scan_interval}秒")

            # 检查SNMP Profile
            if subnet.snmp_profile_id:
                profile = session.query(SNMPProfile).filter(
                    SNMPProfile.id == subnet.snmp_profile_id
                ).first()

                if profile:
                    print(f"\n✅ SNMP Profile已配置:")
                    print(f"   Profile名称: {profile.name}")
                    print(f"   版本: {profile.version}")
                    print(f"   用户名: {profile.username}")
                    print(f"   认证协议: {profile.auth_protocol}")
                    print(f"   加密协议: {profile.priv_protocol}")
                    print(f"   端口: {profile.port}")
                    print(f"   超时: {profile.timeout}秒")
                    print(f"   启用状态: {'启用' if profile.enabled else '禁用'}")

                    return profile
                else:
                    print(f"\n❌ SNMP Profile不存在: ID {subnet.snmp_profile_id}")
            else:
                print(f"\n⚠️  未配置SNMP Profile")
                print(f"   说明: 不会采集Last Boot Time等SNMP信息")
                print(f"   只能采集: Ping状态、DNS PTR、简单OS检测")

    except Exception as e:
        print(f"❌ 检查失败: {str(e)}")
        import traceback
        traceback.print_exc()

    return None

def main():
    """主函数"""
    print(f"\n{'#'*60}")
    print(f"# IPAM功能诊断工具")
    print(f"{'#'*60}")

    # 1. 检查OS检测工具
    check_os_detection()

    # 2. 检查SNMP工具
    check_snmp_tools()

    # 获取用户输入
    print(f"\n{'='*60}")
    print(f"请输入测试参数（直接回车跳过）:")
    print(f"{'='*60}")

    # 测试DNS PTR
    test_ip = input("输入要测试DNS PTR的IP地址（例如: 10.101.35.10）: ").strip()
    if test_ip:
        check_dns_ptr(test_ip)

    # 测试IPAM子网配置
    subnet_id = input("\n输入要检查的IPAM子网ID（例如: 1）: ").strip()
    if subnet_id:
        try:
            subnet_id = int(subnet_id)
            profile = check_ipam_subnet_config(subnet_id)

            # 如果有SNMP profile，测试SNMP连接
            if profile and test_ip:
                test_snmp = input(f"\n是否测试SNMP连接到 {test_ip}? (y/n): ").strip().lower()
                if test_snmp == 'y':
                    from core.security import decrypt_password
                    snmp_profile = {
                        'username': profile.username,
                        'auth_protocol': profile.auth_protocol,
                        'auth_password_encrypted': profile.auth_password_encrypted,
                        'priv_protocol': profile.priv_protocol,
                        'priv_password_encrypted': profile.priv_password_encrypted,
                        'port': profile.port,
                        'timeout': profile.timeout
                    }
                    test_snmp_device(test_ip, snmp_profile)
        except ValueError:
            print(f"❌ 无效的子网ID")

    print(f"\n{'='*60}")
    print(f"诊断完成")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
