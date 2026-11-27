"""Windows WMI 硬件资产采集（SN / 型号 / 厂商）。

用途：PC / Windows 终端普遍不开 SNMP，通过 WMI 读取 BIOS/整机信息补采。

安全约定：
- 凭据由调用方解密后作为参数传入，本模块不读设置、不写日志中的口令
- 连接参数全部走函数参数，绝不拼进命令行（不经 argv）
- 日志只记录 IP 与失败类型，不包含用户名/口令

依赖 impacket 为可选：未安装时 is_available() 返回 False，调用方跳过采集，
不影响 IPAM 其他功能。
"""

from typing import Any, Dict, Optional

from utils.logger import logger

WMI_NAMESPACE = 'root\\cimv2'


def is_available() -> bool:
    """impacket 是否可用（镜像未重建时依赖可能尚未安装）。"""
    try:
        import impacket  # noqa: F401
        return True
    except Exception:
        return False


def _query(services: Any, query: str) -> list:
    """执行 WQL 查询并物化成列表；连接断开时抛异常由上层兜住。"""
    return list(services.ExecQuery(query))


def _collect_wmi(ip: str, creds: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    同步执行 WMI 查询，返回硬件字段字典；失败返回 None。

    creds 需包含 username/password，可选 domain。
    """
    from impacket.dcerpc.v5.dcomrt import DCOMConnection
    from impacket.dcerpc.v5.dcom import wmi
    from services.snmp_service import clean_hardware_value

    username = (creds or {}).get('username') or ''
    password = (creds or {}).get('password') or ''
    domain = (creds or {}).get('domain') or ''
    if not username or not password:
        return None

    dcom = None
    i_interface = None
    services = None
    try:
        dcom = DCOMConnection(
            remoteName=ip,
            remoteHost=ip,
            username=username,
            password=password,
            domain=domain,
            doKerberos=False,
        )
        i_interface = dcom.CoCreateInstanceEx(wmi.CLSID_WbemLocator, wmi.IID_IWbemLocator)
        i_wbem_locator = wmi.IWbemLocator(i_interface)
        services = i_wbem_locator.ConnectServer('', WMI_NAMESPACE, username, password)

        bios = _query(services, 'SELECT SerialNumber, Manufacturer, Version FROM Win32_BIOS')
        product = _query(
            services,
            'SELECT IdentifyingNumber, Name, Vendor FROM Win32_ComputerSystemProduct',
        )
        system = _query(
            services,
            'SELECT Manufacturer, Model FROM Win32_ComputerSystem',
        )
        baseboard = _query(
            services,
            'SELECT SerialNumber, Manufacturer, Product FROM Win32_BaseBoard',
        )

        def _first(rows: list, attr: str) -> Optional[str]:
            for row in rows:
                try:
                    value = getattr(row, attr, None)
                except Exception:
                    value = None
                cleaned = clean_hardware_value(value)
                if cleaned:
                    return cleaned
            return None

        serial = (
            _first(bios, 'SerialNumber')
            or _first(product, 'IdentifyingNumber')
            or _first(baseboard, 'SerialNumber')
        )
        model = _first(product, 'Name') or _first(system, 'Model')
        vendor = (
            _first(system, 'Manufacturer')
            or _first(product, 'Vendor')
            or _first(baseboard, 'Manufacturer')
        )

        if not serial and not model:
            return None
        return {
            'serial_number': serial,
            'device_model': model,
            'hardware_vendor': vendor,
            'hardware_source': 'wmi',
        }
    finally:
        # 逐级释放，任何一步失败都不影响返回值
        try:
            if services is not None:
                services.RemRelease()
        except Exception:
            pass
        try:
            if i_interface is not None:
                i_interface.RemRelease()
        except Exception:
            pass
        try:
            if dcom is not None:
                dcom.disconnect()
        except Exception:
            pass


def collect_wmi(ip: str, creds: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    同步入口，供 asyncio.to_thread 调用；任何异常都收敛成 None。

    注：底层是阻塞 socket，超时由调用方的 asyncio.wait_for 控制。
    """
    try:
        return _collect_wmi(ip, creds)
    except Exception as e:
        # 只记录类型与 IP，避免把凭据带进日志
        logger.debug(f"WMI query failed for {ip}: {type(e).__name__}")
        return None
