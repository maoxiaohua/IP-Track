"""Windows WinRM 硬件资产采集（SN / 型号 / 厂商）。

用途：PC / Windows 终端普遍不开 SNMP。除 WMI(DCOM 135 + 动态 RPC 端口) 外，
再补一条 WinRM(WSMan 5985/5986) 通路——它更容易被防火墙放行，二者互补。
查询的 WMI 类与 wmi_inventory_service 完全一致：
Win32_BIOS / Win32_ComputerSystemProduct / Win32_ComputerSystem / Win32_BaseBoard。

安全约定：
- 凭据由调用方解密后作为参数传入，本模块不读设置、不写日志中的口令
- 凭据只作为 pywinrm 的进程内参数传递，绝不拼进命令行（不经 argv）
- 日志只记录 IP 与失败类型，不包含用户名/口令

依赖 pywinrm 为可选：未安装时 is_available() 返回 False，调用方跳过采集，
不影响 IPAM 其他功能。
"""

import json
from typing import Any, Dict, Optional

from utils.logger import logger

# 只读查询，输出单行 JSON；SilentlyContinue 保证单个类不可用时仍能返回其它字段
_HARDWARE_PS = """
$ErrorActionPreference = 'SilentlyContinue'
$bios = Get-CimInstance -ClassName Win32_BIOS
$product = Get-CimInstance -ClassName Win32_ComputerSystemProduct
$system = Get-CimInstance -ClassName Win32_ComputerSystem
$baseboard = Get-CimInstance -ClassName Win32_BaseBoard
[pscustomobject]@{
  BiosSerial = $bios.SerialNumber
  ProductId = $product.IdentifyingNumber
  ProductName = $product.Name
  ProductVendor = $product.Vendor
  SystemManufacturer = $system.Manufacturer
  SystemModel = $system.Model
  BaseboardSerial = $baseboard.SerialNumber
  BaseboardManufacturer = $baseboard.Manufacturer
} | ConvertTo-Json -Compress
"""

# 字段取值优先级：与 WMI 通路保持一致，避免两条通路结果口径漂移
_FIELD_SOURCES = (
    ('serial_number', ('BiosSerial', 'ProductId', 'BaseboardSerial')),
    ('device_model', ('ProductName', 'SystemModel')),
    ('hardware_vendor', ('SystemManufacturer', 'ProductVendor', 'BaseboardManufacturer')),
)


def is_available() -> bool:
    """pywinrm 是否可用（镜像未重建时依赖可能尚未安装）。"""
    try:
        import winrm  # noqa: F401
        return True
    except Exception:
        return False


def _decode_output(raw: Any) -> str:
    """pywinrm 返回 bytes；兼容 BOM 与非法字节，避免解析阶段抛异常。"""
    if isinstance(raw, str):
        return raw
    if not raw:
        return ''
    if raw[:2] == b'\xff\xfe':
        return raw.decode('utf-16-le', errors='replace')
    return raw.decode('utf-8', errors='replace')


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从输出里截取第一个 {...} 再解析，容忍脚本回显/换行等噪声。"""
    if not text:
        return None
    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def parse_hardware_payload(raw: Any) -> Optional[Dict[str, Any]]:
    """
    解析 PowerShell 输出的 JSON，返回硬件字段字典；无效输出返回 None。

    取值优先级与 wmi_inventory_service 一致：BIOS → 整机产品 → 主板。
    占位值（To Be Filled By O.E.M. 等）由 clean_hardware_value 过滤。
    """
    from services.snmp_service import clean_hardware_value

    data = _extract_json_object(_decode_output(raw))
    if not data:
        return None

    result: Dict[str, Any] = {
        'serial_number': None,
        'device_model': None,
        'hardware_vendor': None,
        'hardware_source': 'winrm',
    }
    for field, keys in _FIELD_SOURCES:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                value = value[0] if value else None
            cleaned = clean_hardware_value(value)
            if cleaned:
                result[field] = cleaned
                break

    if not result['serial_number'] and not result['device_model']:
        return None
    return result


def _build_session(ip: str, creds: Dict[str, str]) -> Any:
    """构造 pywinrm Session；端口/HTTPS/认证方式全部来自配置，不硬编码。"""
    import winrm
    from core.config import settings

    username = (creds or {}).get('username') or ''
    password = (creds or {}).get('password') or ''
    domain = (creds or {}).get('domain') or ''
    if not username or not password:
        raise ValueError('WinRM credentials incomplete')

    # 域账号写成 DOMAIN\\user，本机账号直接用用户名
    user = f"{domain}\\{username}" if domain else username
    scheme = 'https' if settings.WINRM_USE_SSL else 'http'
    endpoint = f"{scheme}://{ip}:{settings.WINRM_PORT}/wsman"
    timeout = max(5, int(settings.WINRM_TIMEOUT_SECONDS))
    return winrm.Session(
        endpoint,
        auth=(user, password),
        transport=settings.WINRM_TRANSPORT or 'ntlm',
        server_cert_validation=(
            'validate' if settings.WINRM_SERVER_CERT_VALIDATION else 'ignore'
        ),
        operation_timeout_sec=max(5, timeout - 5),
        read_timeout_sec=timeout,
    )


def collect_winrm(ip: str, creds: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """
    同步入口，供 asyncio.to_thread 调用；任何异常都收敛成 None。

    注：底层是阻塞 HTTP 调用，超时由 Session 参数与调用方的 asyncio.wait_for 双重控制。
    """
    try:
        session = _build_session(ip, creds)
        result = session.run_ps(_HARDWARE_PS)
        status = getattr(result, 'status_code', 1)
        if status != 0:
            logger.debug(f"WinRM query failed for {ip}: exit={status}")
            return None
        return parse_hardware_payload(getattr(result, 'std_out', b''))
    except Exception as e:
        # 只记录类型与 IP，避免把凭据带进日志
        logger.debug(f"WinRM query failed for {ip}: {type(e).__name__}")
        return None
