import asyncio
import sys
sys.path.insert(0, '/app/src')

from core.database import AsyncSessionLocal
from sqlalchemy import text
from netmiko import ConnectHandler
from core.security import decrypt_password

async def test_nokia_device_types():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text('''
            SELECT ip_address, username, password_encrypted, name, model
            FROM switches WHERE id = 73
        '''))
        row = result.fetchone()
        ip, username, password_enc, name, model = row

        password = decrypt_password(password_enc)

        print(f"交换机: {name} ({ip})")
        print(f"型号: {model}\n")

        # Try different device types for Nokia 7220
        device_types = [
            'nokia_srl',  # SR Linux
            'generic',    # Generic terminal server
            'linux',      # Generic Linux
        ]

        for device_type in device_types:
            print(f"\n{'='*80}")
            print(f"尝试设备类型: {device_type}")
            print('='*80)

            device = {
                'device_type': device_type,
                'host': str(ip),
                'username': username,
                'password': password,
                'port': 22,
                'timeout': 30,
            }

            try:
                connection = ConnectHandler(**device)
                print(f"✅ SSH连接成功 (device_type={device_type})")

                cmd = 'show network-instance bridge-table mac-table all'
                print(f"执行命令: {cmd}\n")

                # Try to send command
                output = connection.send_command(cmd, read_timeout=90, expect_string=r'#')

                print(f"✅ 命令执行成功!")
                print(f"输出长度: {len(output)} 字符")
                print(f"\n前500字符:")
                print(output[:500])

                connection.disconnect()
                print(f"\n✅ device_type='{device_type}' 可用！\n")
                break

            except Exception as e:
                print(f"❌ device_type='{device_type}' 失败: {e}")
                continue

asyncio.run(test_nokia_device_types())
