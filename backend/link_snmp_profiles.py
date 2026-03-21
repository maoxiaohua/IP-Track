#!/usr/bin/env python3
"""
批量关联SNMP Profile到所有子网
"""

import sys
sys.path.insert(0, '/app/src')

def main():
    from sqlalchemy import create_engine
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
        # 查询所有SNMP Profile
        profiles = session.query(SNMPProfile).filter(SNMPProfile.enabled == True).all()

        if not profiles:
            print("❌ 没有启用的SNMP Profile")
            return

        # 使用第一个启用的Profile
        profile = profiles[0]
        print(f"使用SNMP Profile: {profile.name} (ID: {profile.id})")
        print("")

        # 查询所有子网
        subnets = session.query(IPSubnet).all()

        print(f"找到 {len(subnets)} 个子网")
        print("")

        updated_count = 0
        already_linked = 0

        for subnet in subnets:
            if subnet.snmp_profile_id:
                print(f"  {subnet.network:20s} - 已关联Profile (ID: {subnet.snmp_profile_id})")
                already_linked += 1
            else:
                subnet.snmp_profile_id = profile.id
                print(f"  {subnet.network:20s} - ✅ 已关联Profile")
                updated_count += 1

        if updated_count > 0:
            session.commit()
            print("")
            print(f"✅ 成功关联 {updated_count} 个子网到SNMP Profile")

        if already_linked > 0:
            print(f"ℹ️  {already_linked} 个子网已经关联了Profile")

        print("")
        print("下一步: 在IPAM主页手动扫描子网，查看SNMP采集效果")

if __name__ == "__main__":
    main()
