#!/usr/bin/env python3
"""
检查SNMP Profile配置和Last Boot Time采集状态
"""

import sys
import os

# Add src to path
sys.path.insert(0, '/app/src')

def check_snmp_profiles():
    """检查所有SNMP Profile配置"""
    print(f"\n{'='*60}")
    print(f"检查SNMP Profile配置")
    print(f"{'='*60}")

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from models.ipam import SNMPProfile, IPSubnet
        from core.config import settings

        # 创建数据库连接
        engine = create_engine(
            settings.DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'),
            echo=False
        )
        Session = sessionmaker(bind=engine)

        with Session() as session:
            # 查询所有SNMP Profiles
            profiles = session.query(SNMPProfile).all()

            if not profiles:
                print("❌ 没有配置SNMP Profile")
                print("\n建议: 在Web界面创建SNMP Profile")
                print("   路径: http://10.56.4.137:8001/snmp-profiles")
                return

            print(f"✅ 找到 {len(profiles)} 个SNMP Profile:\n")

            for profile in profiles:
                print(f"Profile ID: {profile.id}")
                print(f"  名称: {profile.name}")
                print(f"  版本: {profile.version}")
                print(f"  用户名: {profile.username}")
                print(f"  认证协议: {profile.auth_protocol}")
                print(f"  加密协议: {profile.priv_protocol}")
                print(f"  端口: {profile.port}")
                print(f"  启用状态: {'启用' if profile.enabled else '禁用'}")

                # 查询使用此profile的子网
                subnets = session.query(IPSubnet).filter(
                    IPSubnet.snmp_profile_id == profile.id
                ).all()

                if subnets:
                    print(f"  关联子网: {len(subnets)} 个")
                    for subnet in subnets[:5]:  # 最多显示5个
                        print(f"    - {subnet.network} ({subnet.name})")
                    if len(subnets) > 5:
                        print(f"    ... 还有 {len(subnets) - 5} 个")
                else:
                    print(f"  ⚠️  未关联任何子网")

                print()

    except Exception as e:
        print(f"❌ 检查失败: {str(e)}")
        import traceback
        traceback.print_exc()


def check_last_boot_time_status():
    """检查Last Boot Time采集状态"""
    print(f"\n{'='*60}")
    print(f"检查Last Boot Time采集状态")
    print(f"{'='*60}")

    try:
        from sqlalchemy import create_engine, func
        from sqlalchemy.orm import sessionmaker
        from models.ipam import IPAddress
        from core.config import settings

        # 创建数据库连接
        engine = create_engine(
            settings.DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'),
            echo=False
        )
        Session = sessionmaker(bind=engine)

        with Session() as session:
            # 统计有last_boot_time的IP数量
            total_ips = session.query(func.count(IPAddress.id)).scalar()
            ips_with_boot_time = session.query(func.count(IPAddress.id)).filter(
                IPAddress.last_boot_time.isnot(None)
            ).scalar()

            print(f"总IP地址数: {total_ips}")
            print(f"有Last Boot Time的: {ips_with_boot_time}")

            if ips_with_boot_time == 0:
                print("\n❌ 没有IP地址有Last Boot Time数据")
                print("\n可能原因:")
                print("1. 子网未关联SNMP Profile")
                print("2. SNMP Profile未启用")
                print("3. 设备不支持SNMP或SNMP服务未启动")
                print("4. 子网还未扫描过（或扫描失败）")
                print("\n建议:")
                print("1. 检查子网是否关联了SNMP Profile")
                print("2. 手动扫描子网: IPAM主页 → 点击'扫描'按钮")
                print("3. 使用诊断工具测试: python /app/diagnose_ipam.py")
            else:
                print(f"\n✅ 有 {ips_with_boot_time} 个IP有Last Boot Time数据")

                # 显示最近的几个
                recent_ips = session.query(IPAddress).filter(
                    IPAddress.last_boot_time.isnot(None)
                ).order_by(IPAddress.last_boot_time.desc()).limit(5).all()

                print("\n最近启动的设备:")
                for ip in recent_ips:
                    print(f"  {ip.ip_address} - {ip.hostname or 'Unknown'}")
                    print(f"    Last Boot: {ip.last_boot_time}")
                    print(f"    Machine Type: {ip.machine_type or 'N/A'}")

    except Exception as e:
        print(f"❌ 检查失败: {str(e)}")
        import traceback
        traceback.print_exc()


def check_recent_scans():
    """检查最近的扫描记录"""
    print(f"\n{'='*60}")
    print(f"检查最近的扫描记录")
    print(f"{'='*60}")

    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from models.ipam import IPSubnet
        from core.config import settings

        # 创建数据库连接
        engine = create_engine(
            settings.DATABASE_URL.replace('postgresql+asyncpg', 'postgresql'),
            echo=False
        )
        Session = sessionmaker(bind=engine)

        with Session() as session:
            # 查询最近扫描的子网
            recent_scans = session.query(IPSubnet).filter(
                IPSubnet.last_scan_at.isnot(None)
            ).order_by(IPSubnet.last_scan_at.desc()).limit(10).all()

            if not recent_scans:
                print("❌ 没有扫描记录")
                print("\n建议: 在IPAM主页手动触发扫描")
            else:
                print(f"✅ 最近扫描的 {len(recent_scans)} 个子网:\n")

                for subnet in recent_scans:
                    print(f"{subnet.network} ({subnet.name})")
                    print(f"  最后扫描: {subnet.last_scan_at}")
                    print(f"  SNMP Profile: {'已配置' if subnet.snmp_profile_id else '未配置'}")
                    print()

    except Exception as e:
        print(f"❌ 检查失败: {str(e)}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    print(f"\n{'#'*60}")
    print(f"# SNMP Profile 和 Last Boot Time 检查工具")
    print(f"{'#'*60}")

    # 1. 检查SNMP Profiles
    check_snmp_profiles()

    # 2. 检查Last Boot Time状态
    check_last_boot_time_status()

    # 3. 检查最近的扫描
    check_recent_scans()

    print(f"\n{'='*60}")
    print(f"检查完成")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
