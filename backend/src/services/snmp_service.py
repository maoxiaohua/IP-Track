"""
SNMP helpers for lightweight switch discovery and enrichment.

The live ARP/MAC collection path uses per-vendor strategy with automatic SNMP/CLI fallback.
(SSH/Telnet) because vendor SNMP FDB/ARP implementations vary widely and can
be expensive on long-running deployments.

SNMP remains useful here for:
1. Device identification (sysName, sysDescr, sysObjectID)
2. Optional interface and optical inventory enrichment
3. Legacy L2 helper methods that are still available for troubleshooting

Standard SNMP OIDs used:
- IP-MIB::ipNetToMediaPhysAddress (1.3.6.1.2.1.4.22.1.2) - ARP MAC addresses
- IP-MIB::ipNetToMediaNetAddress (1.3.6.1.2.1.4.22.1.3) - ARP IP addresses
- BRIDGE-MIB::dot1dTpFdbAddress (1.3.6.1.2.1.17.4.3.1.1) - MAC addresses
- BRIDGE-MIB::dot1dTpFdbPort (1.3.6.1.2.1.17.4.3.1.2) - Port indexes
- IF-MIB::ifName (1.3.6.1.2.1.31.1.1.1.1) - Interface names
"""

import fnmatch
from typing import Any, Dict, List, Optional, Tuple
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd, next_cmd, CommunityData,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol, usmHMAC256SHA384AuthProtocol, usmHMAC384SHA512AuthProtocol,
    usmDESPrivProtocol, usmAesCfb128Protocol, usmAesCfb192Protocol, usmAesCfb256Protocol
)
from pysnmp.proto.rfc1902 import OctetString
from pysnmp.proto.rfc1905 import EndOfMibView
import asyncio
from utils.logger import logger
from core.security import decrypt_password


def normalize_protocol_key(name: Optional[str]) -> str:
    """
    协议名归一化：转大写、抹掉连字符/下划线/空格，再把同义写法折叠到同一个键。

    第一层（去标点）解决的是**格式**差异：系统里同一个协议有两种写法 ——
    snmp_profiles 表按 RFC 7860 的写法存 'SHA-256' / 'AES-192'，switches 表按
    pysnmp 的写法存 'SHA256' / 'AES192'。此前查表只做 .upper()，'SHA-256'
    匹配不上任何键，于是**静默退化成默认的 SHA**：选了 SHA-256 的模板，实际却用
    SHA 去认证，设备侧回 WrongDigest，和「口令配错」的症状完全一样。

    第二层（折叠同义）解决的是**命名**差异：'AES' 和 'AES-128' / 'AES128'
    是同一个算法的三种写法，去标点之后仍然得到 'AES' 和 'AES128' 两个不同的键。
    只做第一层的话，这两个值在 _credential_mismatch 里会被判成「协议不同」——
    而它们指向的协议对象是同一个。已实测：模板存 'AES'、239 台交换机存
    'AES128'，干跑 adopt 会把其中 237 台误报成「加密协议不同」，于是这批设备
    永远挂不上模板。折叠之后两者等价，模板不需要为了迁就写法去改。

    Args:
        name: 原始协议名，如 'SHA-256' / 'sha256' / 'AES_192' / 'AES'

    Returns:
        归一化并折叠后的键，如 'SHA256' / 'AES128'；name 为空时返回空串
    """
    key = ''.join(ch for ch in str(name or '').upper() if ch.isalnum())
    return PROTOCOL_SYNONYMS.get(key, key)


# 同义协议名折叠表：值是「代表性写法」，必须同时是 AUTH_PROTOCOL_MAP 或
# PRIV_PROTOCOL_MAP 的键，否则折叠之后反而查不到表。
#
# 只收**确凿等价**的写法，也就是两张映射表里已经指向同一个协议对象的那几组：
#   'AES' 与 'AES128'  -> usmAesCfb128Protocol
#   'SHA' 与 'SHA1'    -> usmHMACSHAAuthProtocol
# 不做 128/192/256 之间的折叠 —— 那是不同的算法，摘要/密钥长度都不同。
PROTOCOL_SYNONYMS = {
    'AES': 'AES128',
    'SHA1': 'SHA',
}


# 认证协议名 -> pysnmp 协议对象。
# 键是归一化后的形式（全大写、无连字符），查表前必须先过 normalize_protocol_key：
# 否则库里存 'md5' 这类小写值、或 'SHA-256' 这类带连字符的值时会静默退化成
# 默认协议 SHA，造成「某个入口用 MD5、另一个入口用 SHA」这种极难察觉的分叉。
#
# 注意 SHA224/SHA256/SHA384/SHA512 必须各自对上 RFC 7860 的 HMAC 变体，
# 尤其 'SHA256' 不能写成 usmHMAC128SHA224AuthProtocol —— 那是 SHA-224，
# 报文摘要长度都不同，设备侧会直接判 HMAC 失败并回 WrongDigest，
# 症状和「口令配错」一模一样，极难查。
AUTH_PROTOCOL_MAP = {
    'MD5': usmHMACMD5AuthProtocol,
    'SHA': usmHMACSHAAuthProtocol,
    'SHA1': usmHMACSHAAuthProtocol,
    'SHA224': usmHMAC128SHA224AuthProtocol,
    'SHA256': usmHMAC192SHA256AuthProtocol,
    'SHA384': usmHMAC256SHA384AuthProtocol,
    'SHA512': usmHMAC384SHA512AuthProtocol,
}

# 加密协议名 -> pysnmp 协议对象。同样先过 normalize_protocol_key，
# 让 'des' / 'AES-128' / 'AES_256' 这些写法都能正确命中。
PRIV_PROTOCOL_MAP = {
    'DES': usmDESPrivProtocol,
    'AES': usmAesCfb128Protocol,
    'AES128': usmAesCfb128Protocol,
    'AES192': usmAesCfb192Protocol,
    'AES256': usmAesCfb256Protocol,
}


def build_snmp_auth(
    username: Optional[str],
    auth_protocol: Optional[str],
    auth_password: Optional[str],
    priv_protocol: Optional[str] = None,
    priv_password: Optional[str] = None,
    snmp_version: Optional[str] = None,
) -> Any:
    """
    构建 SNMP 认证凭据对象 —— 全系统唯一的构造入口。

    SNMPv1/v2c 用 CommunityData（团体字走 auth_password 传入）；
    SNMPv3 用 UsmUserData；未配置加密口令时退化为 authNoPriv。

    此前连接测试、SNMP 配置测试、设备发现各自内联复制了一份实现，协议名归一化、
    v1/v2c 分支、默认值互不相同，同一份配置换个入口就可能构造出不同的认证参数。
    统一到这里之后，任何入口对同一台交换机都生成完全一致的凭据。

    Args:
        username: SNMPv3 用户名（v1/v2c 时忽略）
        auth_protocol: 'MD5' / 'SHA' / 'SHA256'（大小写不敏感）
        auth_password: 认证口令（v1/v2c 时是团体字）
        priv_protocol: 'DES' / 'AES' / 'AES128' / 'AES192' / 'AES256'（大小写不敏感）
        priv_password: 加密口令；为空则用 authNoPriv
        snmp_version: '1'/'2c' -> CommunityData，其它 -> SNMPv3

    Returns:
        CommunityData 或 UsmUserData
    """
    if str(snmp_version or '').lower() in ('1', '2c', 'v1', 'v2c'):
        # v1/v2c：auth_password 位置放的是解密后的团体字
        return CommunityData(auth_password, mpModel=1)

    auth_proto = AUTH_PROTOCOL_MAP.get(
        normalize_protocol_key(auth_protocol), usmHMACSHAAuthProtocol
    )
    if not priv_password:
        return UsmUserData(
            username,
            authKey=auth_password,
            authProtocol=auth_proto
        )

    priv_proto = PRIV_PROTOCOL_MAP.get(
        normalize_protocol_key(priv_protocol) or 'AES128', usmAesCfb128Protocol
    )
    return UsmUserData(
        username,
        authKey=auth_password,
        privKey=priv_password,
        authProtocol=auth_proto,
        privProtocol=priv_proto
    )


# 标准 SNMP 配置字典的字段清单，顺序即 normalize_snmp_config 的输出顺序
_SNMP_CONFIG_FIELDS = (
    'snmp_version',
    'snmp_username',
    'snmp_auth_protocol',
    'snmp_auth_password_encrypted',
    'snmp_priv_protocol',
    'snmp_priv_password_encrypted',
    'snmp_port',
)


def _normalize_snmp_version(value: Optional[str]) -> str:
    """
    版本号归一化：统一成交换机表的 '3' / '2c' 写法。

    SNMP 模板存的是 'v3' / 'v2c'（snmp_profiles.version），交换机表存的是 '3' / '2c'，
    两套写法必须收敛到一处，否则「拿模板判断版本」的分支会全部走错。
    """
    text = str(value or '').strip().lower()
    if text.startswith('v'):
        text = text[1:]
    return '2c' if text in ('1', '2', '2c') else '3'


def _read_snmp_field(config: Any, field_name: str) -> Any:
    """
    从一份 SNMP 配置里读字段，dict 和对象两种载体都认，带不带 snmp_ 前缀都认。

    读的顺序是「先带前缀、再裸名」：交换机行的属性叫 snmp_auth_password_encrypted，
    SNMP 模板的属性叫 auth_password_encrypted，两种载体喂进同一个解析函数，
    不必在调用点先判断自己拿到的是哪一种。
    """
    if config is None:
        return None
    bare = field_name[len('snmp_'):] if field_name.startswith('snmp_') else field_name
    if isinstance(config, dict):
        if field_name in config:
            return config[field_name]
        return config.get(bare)
    value = getattr(config, field_name, None)
    if value is None:
        value = getattr(config, bare, None)
    return value


def normalize_snmp_config(config: Any) -> Dict[str, Any]:
    """
    把任意来源的 SNMP 配置统一成内部标准字典（键一律带 snmp_ 前缀）。

    系统里同时存在两种叫法：

    - 交换机行：``snmp_version='3'``、``snmp_auth_password_encrypted=...``
    - SNMP 模板：``version='v3'``、``auth_password_encrypted=...``、``community_encrypted=...``

    两种写法此前在六七个采集入口里各自内联解析，协议名怎么归一化、v2c 团体字放哪个
    字段全靠各处自觉。统一到这里之后，模板和交换机行可以互相替换，不会再出现
    「同一份配置换个入口就构造出不同凭据」。

    v2c 的团体字一律落到 ``snmp_auth_password_encrypted`` —— 这是交换机表的历史约定，
    采集侧只认这个字段；模板侧的 ``community_encrypted`` 在这里换算过来。

    Args:
        config: 交换机行、SNMP 模板对象，或它们对应的 dict

    Returns:
        标准配置字典，键为 _SNMP_CONFIG_FIELDS，可直接交给采集/测试代码使用
    """
    version = _normalize_snmp_version(_read_snmp_field(config, 'snmp_version'))

    if version == '2c':
        # v2c 只认团体字，用户名/协议一律清空，避免残留的 v3 字段误导排查
        community = (
            _read_snmp_field(config, 'snmp_auth_password_encrypted')
            or _read_snmp_field(config, 'snmp_community_encrypted')
        )
        return {
            'snmp_version': '2c',
            'snmp_username': None,
            'snmp_auth_protocol': None,
            'snmp_auth_password_encrypted': community,
            'snmp_priv_protocol': None,
            'snmp_priv_password_encrypted': None,
            'snmp_port': _read_snmp_field(config, 'snmp_port') or 161,
        }

    priv_password = _read_snmp_field(config, 'snmp_priv_password_encrypted')
    return {
        'snmp_version': '3',
        'snmp_username': _read_snmp_field(config, 'snmp_username'),
        'snmp_auth_protocol': _read_snmp_field(config, 'snmp_auth_protocol'),
        'snmp_auth_password_encrypted': _read_snmp_field(config, 'snmp_auth_password_encrypted'),
        # 没有加密口令就不该留着加密协议，否则界面上显示「AES128」而实际走的是 authNoPriv
        'snmp_priv_protocol': _read_snmp_field(config, 'snmp_priv_protocol') if priv_password else None,
        'snmp_priv_password_encrypted': priv_password,
        'snmp_port': _read_snmp_field(config, 'snmp_port') or 161,
    }


def _load_switch_snmp_profile(switch: Any) -> Any:
    """
    安全地取出交换机引用的 SNMP 模板，取不到一律返回 None。

    关系用 lazy='selectin' 声明，正常查询出来的交换机都是预加载好的；但刚创建还没
    flush 的对象、或走裸 SQL 拿到的行，关系可能尚未加载，异步上下文里直接访问会抛
    MissingGreenlet。这里统一兜住，退化成「未引用模板」—— 绝不因为取不到模板
    就把整个采集/连接测试打成异常。
    """
    if not getattr(switch, 'snmp_profile_id', None):
        return None
    try:
        return getattr(switch, 'snmp_profile', None)
    except Exception:
        return None


def build_switch_snmp_config(switch: Any) -> Dict[str, Any]:
    """
    取出一台交换机**实际生效**的 SNMP 配置 —— 采集、连接测试、设备发现统一从这里取。

    交换机引用了 SNMP 模板（``snmp_profile_id`` 非空）时**整体以模板为准**，包括端口；
    没引用模板时用交换机自己那份。两种来源都经 normalize_snmp_config 归一化，
    所以调用方拿到的永远是同一种形状、同一套协议名。

    注意：整体以模板为准是有意为之 —— 「引用模板」的语义就是这份凭据连同传输参数
    只在模板上维护一处。界面上选中模板时会把模板的版本/端口一并回写到交换机行，
    两边显示不会打架。

    Args:
        switch: Switch 实例（或任何带 snmp_* 字段的对象）

    Returns:
        标准配置字典，键为 _SNMP_CONFIG_FIELDS
    """
    profile = _load_switch_snmp_profile(switch)
    if profile is not None:
        return normalize_snmp_config(profile)
    return normalize_snmp_config(switch)


def switch_has_snmp_credentials(switch: Any) -> bool:
    """
    判断一台交换机是否有可用的 SNMP 凭据 —— 全系统统一的判定入口。

    此前各处直接写 ``switch.snmp_enabled and switch.snmp_auth_password_encrypted``。
    交换机改成引用模板之后，自己那份 ``snmp_auth_password_encrypted`` 会是空的，
    这些判断会**集体静默失效**：采集会跳过 SNMP 而不报错，界面显示「未配置凭据」，
    但设备其实配得好好的。所以判定必须走这个函数，不能再直接读列。

    Args:
        switch: Switch 实例

    Returns:
        SNMP 已启用且解析出的凭据里确有口令/团体字时为 True
    """
    if not getattr(switch, 'snmp_enabled', False):
        return False
    return bool(build_switch_snmp_config(switch).get('snmp_auth_password_encrypted'))


def apply_profile_display_fields(switch: Any, profile: Any) -> None:
    """
    把模板上的**非口令**展示字段回填到交换机行，让列表页/详情页显示的就是当前生效值。

    只回填版本、端口、用户名、两个协议名这类可以公开展示的字段。**口令一律不落回
    交换机行** —— 那正是这次改造要消灭的「同一份凭据抄 200 多份，改口令漏改一台」。
    真正生效的凭据始终取自模板（见 build_switch_snmp_config），回填纯粹是为了显示。

    注意这里**不动 snmp_enabled**：那是「这台设备到底用不用 SNMP」的开关，属于调用方
    的决定，不是模板能覆盖的传输参数。

    模板被编辑之后，引用它的交换机由 snmp_profiles 的更新接口统一重新回填；
    这里不做也无法做自动同步。
    """
    if profile is None:
        return
    config = normalize_snmp_config(profile)
    switch.snmp_version = config['snmp_version']
    switch.snmp_port = config['snmp_port']
    switch.snmp_username = config['snmp_username']
    switch.snmp_auth_protocol = config['snmp_auth_protocol']
    switch.snmp_priv_protocol = config['snmp_priv_protocol']


# pysnmp 的 errorIndication 原文 -> 面向运维的中文解释与处置建议。
# 键是报文里实际出现的子串（小写比较）；查不到时退回通用提示，原文始终保留在 details 里。
_ERROR_HINTS = (
    ('wrong snmp pdu digest',
     '设备拒绝了 SNMPv3 认证（HMAC 校验失败）：设备上存在这个用户名，但认证口令或认证协议与系统里存的不一致。'
     '请在设备上执行 show snmp user 核对该用户的 auth 协议和口令，或在系统里把该交换机的 SNMP 认证口令改成设备实际值。'),
    ('unknown usm user',
     '设备上不存在这个 SNMPv3 用户名。请在设备上执行 show snmp user 确认用户名，或在系统里改成正确的用户名。'),
    ('not in time window',
     '设备与服务器的时间偏差超出 SNMPv3 允许窗口（默认 150 秒）。请校准两侧时钟或配置 NTP 同步。'),
    ('unsupported snmp security level',
     '设备不支持该安全级别：系统要求认证+加密，但设备侧该用户可能只配了认证。'
     '请在设备上补齐加密配置，或在系统里清空加密口令改走 authNoPriv。'),
    ('no such oid',
     '设备不支持查询该 OID（通常不影响连通性判定，属于采集项缺失）。'),
    # 注意 pysnmp 的超时原文是 'RequestTimedOut'（没有 'timeout' 这个子串），
    # 单独列一条，不能只靠下面的 'timeout' 兜住。
    ('requesttimedout',
     '设备未在超时时间内响应：可能是 SNMP 未启用、团体字或端口不对，也可能有 ACL 拦截。'),
    ('timeout', '设备未在超时时间内响应：可能是 SNMP 未启用、团体字或端口不对，也可能有 ACL 拦截。'),
)


def describe_snmp_error(error_indication: Any) -> str:
    """
    把 pysnmp 的 errorIndication 翻译成可操作的中文说明。

    只做「解释」，不吞原文 —— 调用方应把本函数的返回值当作给人看的 message，
    同时把 str(error_indication) 原样放进 details['raw_error']，
    排障时仍然看得到 pysnmp 的原始英文错误。

    Args:
        error_indication: pysnmp get_cmd/next_cmd 返回的 errorIndication

    Returns:
        中文说明；命中已知错误时附带处置建议
    """
    text = str(error_indication or '').strip()
    lowered = text.lower()
    for needle, hint in _ERROR_HINTS:
        if needle in lowered:
            return hint
    return f'SNMP 请求失败：{text}' if text else 'SNMP 请求失败（设备无响应）'


class SNMPService:
    """Service for collecting data from switches via SNMP"""

    # Standard SNMP OIDs
    OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'       # sysName (hostname)
    OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'      # sysDescr (system description)
    OID_SYS_OBJECT_ID = '1.3.6.1.2.1.1.2.0'  # sysObjectID (vendor enterprise OID)
    OID_SYS_CONTACT = '1.3.6.1.2.1.1.4.0'    # sysContact (contact info)
    OID_SYS_LOCATION = '1.3.6.1.2.1.1.6.0'   # sysLocation (location)
    OID_SYS_UPTIME = '1.3.6.1.2.1.1.3.0'     # sysUpTime (time ticks since boot)
    # ENTITY-MIB: physical chassis description (index 1 = chassis)
    # Returns hardware platform string, e.g. "Nokia 7220 IXR-D2" on SR Linux
    OID_ENTITY_PHYS_DESCR = '1.3.6.1.2.1.47.1.1.1.1.2.1'
    OID_ARP_MAC = '1.3.6.1.2.1.4.22.1.2'     # ipNetToMediaPhysAddress
    OID_ARP_IP = '1.3.6.1.2.1.4.22.1.3'  # ipNetToMediaNetAddress
    OID_MAC_ADDRESS = '1.3.6.1.2.1.17.4.3.1.1'  # dot1dTpFdbAddress
    OID_MAC_PORT = '1.3.6.1.2.1.17.4.3.1.2'  # dot1dTpFdbPort
    OID_IF_NAME = '1.3.6.1.2.1.31.1.1.1.1'  # ifName
    OID_IF_INDEX = '1.3.6.1.2.1.2.2.1.1'  # ifIndex
    OID_BRIDGE_PORT_MAP = '1.3.6.1.2.1.17.1.4.1.2'  # dot1dBasePortIfIndex

    # Q-BRIDGE-MIB MAC table OIDs (fallback for switches not supporting BRIDGE-MIB)
    OID_Q_BRIDGE_MAC_ADDRESS = '1.3.6.1.2.1.17.7.1.2.1.1.1'  # dot1qTpFdbAddress
    OID_Q_BRIDGE_MAC_PORT = '1.3.6.1.2.1.17.7.1.2.2.1.2'  # dot1qTpFdbPort

    # ENTITY-MIB OIDs for optical module information
    OID_ENTITY_PHYS_DESCR_TABLE = '1.3.6.1.2.1.47.1.1.1.1.2'  # entPhysicalDescr
    OID_ENTITY_PHYS_NAME = '1.3.6.1.2.1.47.1.1.1.1.7'  # entPhysicalName
    OID_ENTITY_PHYS_MODEL = '1.3.6.1.2.1.47.1.1.1.1.13'  # entPhysicalModelName
    OID_ENTITY_PHYS_SERIAL = '1.3.6.1.2.1.47.1.1.1.1.11'  # entPhysicalSerialNum
    OID_ENTITY_PHYS_MFG = '1.3.6.1.2.1.47.1.1.1.1.12'  # entPhysicalMfgName
    OID_ENTITY_PHYS_CONTAINED_IN = '1.3.6.1.2.1.47.1.1.1.1.4'  # entPhysicalContainedIn
    OID_ENTITY_PHYS_CLASS = '1.3.6.1.2.1.47.1.1.1.1.5'  # entPhysicalClass
    OID_IF_HIGH_SPEED = '1.3.6.1.2.1.31.1.1.1.15'  # ifHighSpeed (in Mbps)

    def __init__(self):
        # Don't create a singleton engine - create per-request to avoid event loop issues
        import os
        # Numeric OIDs do not require explicit MIB package configuration.
        # Setting PYSNMP_MIB_PKGS to an empty string causes pysnmp 7.x to try
        # importing an empty module name during SnmpEngine() initialization.
        os.environ.pop('PYSNMP_MIB_PKGS', None)
        logger.info("SNMP service initialized with asyncio")

    @staticmethod
    def _dispose_engine(engine: Optional[SnmpEngine]) -> None:
        """
        pysnmp's asyncio SnmpEngine keeps dispatcher/security state alive unless
        it is closed explicitly. In long-running IPAM scans this turns repeated
        SNMP GETs into unbounded anonymous memory growth.
        """
        if engine is None:
            return

        try:
            engine.close_dispatcher()
        except Exception:
            pass

        try:
            engine._close()
        except Exception:
            pass

    @staticmethod
    def resolve_oid_overrides(
        overrides: List[Dict],
        vendor: str,
        model: str
    ) -> Dict[str, str]:
        """
        Resolve vendor-specific SNMP OID overrides for a given switch.

        Returns a dict mapping oid_role -> oid_value for all matching overrides.
        Falls back to empty dict when no overrides match, allowing callers to
        use standard OIDs.

        Matching rules:
          - vendor case-insensitive exact match
          - model_pattern NULL/empty = match-all; otherwise glob-match against model
          - highest priority wins per oid_role; specific model_pattern beats NULL on tie
        """
        if not overrides:
            return {}

        vendor_lower = (vendor or '').lower()
        model_lower = (model or '').lower()

        candidates = [
            o for o in overrides
            if (o.get('vendor', '') or '').lower() == vendor_lower
            and o.get('enabled', True)
            and (
                not o.get('model_pattern')
                or fnmatch.fnmatch(model_lower, (o.get('model_pattern', '') or '').lower())
            )
        ]

        candidates.sort(
            key=lambda o: (
                o.get('priority', 100),
                1 if o.get('model_pattern') else 0,
            ),
            reverse=True,
        )

        resolved: Dict[str, str] = {}
        for o in candidates:
            role = o.get('oid_role', '') or ''
            if role and role not in resolved:
                resolved[role] = o.get('oid_value', '') or ''
        return resolved

    @staticmethod
    def _oid_index_suffix(oid_str: str, base_oid: str) -> str:
        """Extract the instance-index suffix from an SNMP walk result."""
        if oid_str.startswith(base_oid + '.'):
            return oid_str[len(base_oid) + 1:]
        return oid_str

    def _create_snmp_auth(
        self,
        username: str,
        auth_protocol: str,
        auth_password: str,
        priv_protocol: Optional[str],
        priv_password: Optional[str],
        snmp_version: Optional[str] = None,
    ) -> Any:
        """
        Create SNMP authentication credentials.

        保留这个方法是为了兼容既有的 self._create_snmp_auth(...) 调用点，
        实际构造逻辑已统一到模块级的 build_snmp_auth()，保证所有入口一致。

        Args:
            username: SNMPv3 username (ignored for v1/v2c)
            auth_protocol: 'MD5', 'SHA', 'SHA256'
            auth_password: Authentication password (v1/v2c: decrypted community)
            priv_protocol: 'DES', 'AES', 'AES128', 'AES192', 'AES256'
            priv_password: Privacy password. When omitted, authNoPriv is used.
            snmp_version: '1'/'2c' -> CommunityData, otherwise SNMPv3
        """
        return build_snmp_auth(
            username=username,
            auth_protocol=auth_protocol,
            auth_password=auth_password,
            priv_protocol=priv_protocol,
            priv_password=priv_password,
            snmp_version=snmp_version,
        )

    @staticmethod
    def _decrypt_optional_password(encrypted_text: Optional[str]) -> Optional[str]:
        """Decrypt an optional password field and return None when not configured."""
        if not encrypted_text:
            return None
        return decrypt_password(encrypted_text)

    async def _walk_oid(
        self,
        target_ip: str,
        oid: str,
        auth_data: UsmUserData,
        port: int = 161,
        timeout: int = 5,
        retries: int = 2
    ) -> List[Tuple[str, any]]:
        """
        Perform SNMP WALK on a specific OID using asyncio

        Returns:
            List of (OID, value) tuples
        """
        engine: Optional[SnmpEngine] = None
        try:
            results = []
            # Create a new SnmpEngine for each request to avoid event loop issues
            engine = SnmpEngine()

            # Create transport target using .create() method for pysnmp 7.x
            transport = await UdpTransportTarget.create((target_ip, port), timeout=timeout, retries=retries)

            # In pysnmp 7.x asyncio, we need to manually loop for WALK operations
            # Start with the base OID
            varBinds = [ObjectType(ObjectIdentity(oid))]

            while True:
                errorIndication, errorStatus, errorIndex, varBinds = await next_cmd(
                    engine,
                    auth_data,
                    transport,
                    ContextData(),
                    *varBinds,
                    lexicographicMode=False
                )

                if errorIndication:
                    logger.debug(f"SNMP walk ended on {target_ip}: {errorIndication}")
                    break
                elif errorStatus:
                    logger.error(f"SNMP error on {target_ip}: {errorStatus.prettyPrint()}")
                    break
                else:
                    for varBind in varBinds:
                        oid_str = str(varBind[0])
                        value = varBind[1]
                        # Stop on EndOfMibView (no more variables in this MIB view)
                        if isinstance(value, EndOfMibView):
                            return results
                        # Stop if we've walked past our OID tree
                        if not oid_str.startswith(oid):
                            return results
                        results.append((oid_str, value))

            return results

        except Exception as e:
            logger.error(f"SNMP walk failed for {target_ip} OID {oid}: {str(e)}")
            return []
        finally:
            self._dispose_engine(engine)

    async def _get_oid(
        self,
        target_ip: str,
        oid: str,
        auth_data: UsmUserData,
        port: int = 161,
        timeout: int = 10,  # Increased timeout from 5 to 10 seconds for slow devices
        retries: int = 2,
        log_errors: bool = True
    ) -> Optional[any]:
        """
        Perform SNMP GET on a specific OID using asyncio
        """
        engine: Optional[SnmpEngine] = None
        try:
            logger.debug(f"Starting SNMP GET on {target_ip} OID {oid} with timeout={timeout}s")

            # Create a new SnmpEngine for each request to avoid event loop issues
            engine = SnmpEngine()

            # Create transport target using .create() method for pysnmp 7.x
            transport = await UdpTransportTarget.create((target_ip, port), timeout=timeout, retries=retries)
            logger.debug(f"Transport created for {target_ip}:{port}")

            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                engine,
                auth_data,
                transport,
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )

            log_fn = logger.error if log_errors else logger.debug
            if errorIndication:
                log_fn(
                    f"❌ SNMP GET errorIndication on {target_ip} OID {oid}: "
                    f"{errorIndication} (type: {type(errorIndication).__name__})"
                )
                return None
            elif errorStatus:
                log_fn(
                    f"❌ SNMP GET errorStatus on {target_ip} OID {oid}: "
                    f"{errorStatus.prettyPrint()} at index {errorIndex}"
                )
                return None
            else:
                for varBind in varBinds:
                    value = varBind[1]
                    logger.debug(f"✅ SNMP GET success on {target_ip} OID {oid}: {value}")
                    return value

                # If we get here, varBinds was empty
                logger.warning(f"⚠️ SNMP GET returned empty varBinds for {target_ip} OID {oid}")
                return None

        except Exception as e:
            log_fn = logger.error if log_errors else logger.debug
            log_fn(f"❌ SNMP GET exception for {target_ip} OID {oid}: {type(e).__name__}: {str(e)}")
            if log_errors:
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
            return None
        finally:
            self._dispose_engine(engine)

    def _format_mac_address(self, mac_bytes) -> str:
        """
        Convert SNMP MAC address bytes to standard format

        Args:
            mac_bytes: Can be OctetString or bytes

        Returns:
            MAC address in format 'aa:bb:cc:dd:ee:ff'
        """
        try:
            if isinstance(mac_bytes, OctetString):
                mac_bytes = mac_bytes.asOctets()

            if isinstance(mac_bytes, bytes):
                # Convert bytes to hex string with colons
                mac_hex = ':'.join([f'{b:02x}' for b in mac_bytes])
                return mac_hex.lower()
            else:
                # Try to convert to string and parse
                mac_str = str(mac_bytes)
                # Handle hex string format
                if len(mac_str) == 12:
                    return ':'.join([mac_str[i:i+2] for i in range(0, 12, 2)]).lower()
                return mac_str.lower()

        except Exception as e:
            logger.debug(f"MAC format error: {str(e)}")
            return str(mac_bytes)

    def _format_ip_address(self, ip_bytes) -> Optional[str]:
        """
        Convert SNMP IP address bytes to dotted decimal format

        Args:
            ip_bytes: IP address in bytes or OctetString

        Returns:
            IP address in format '192.168.1.1' or None if invalid
        """
        try:
            if isinstance(ip_bytes, OctetString):
                ip_bytes = ip_bytes.asOctets()

            if isinstance(ip_bytes, bytes) and len(ip_bytes) == 4:
                return '.'.join([str(b) for b in ip_bytes])
            else:
                # Try to parse from string
                ip_str = str(ip_bytes)
                return ip_str

        except Exception as e:
            logger.debug(f"IP format error: {str(e)}")
            return None

    async def collect_arp_table(
        self,
        switch_ip: str,
        switch_config: Dict,
        oid_overrides: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """
        Collect ARP table from a switch using asyncio

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SNMP credentials
            oid_overrides: Optional vendor-specific OID overrides

        Returns:
            List of ARP entries: [{ip, mac, vlan, interface}, ...]
        """
        try:
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = self._decrypt_optional_password(
                switch_config.get('snmp_priv_password_encrypted')
            )

            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config.get('snmp_priv_protocol'),
                priv_password=priv_password,
                snmp_version=switch_config.get('snmp_version'),
            )

            port = switch_config.get('snmp_port', 161)
            ov = oid_overrides or {}

            arp_ip_oid = ov.get('arp_ip', self.OID_ARP_IP)
            arp_mac_oid = ov.get('arp_mac', self.OID_ARP_MAC)

            # Walk ARP table
            arp_entries = []
            arp_data = {}

            # Get IP addresses from ARP table
            ip_results = await self._walk_oid(switch_ip, arp_ip_oid, auth_data, port)
            for oid, value in ip_results:
                index_key = self._oid_index_suffix(oid, arp_ip_oid)
                ip_addr = self._format_ip_address(value)
                if ip_addr:
                    arp_data[index_key] = {'ip': ip_addr}

            # Get MAC addresses from ARP table
            mac_results = await self._walk_oid(switch_ip, arp_mac_oid, auth_data, port)
            for oid, value in mac_results:
                index_key = self._oid_index_suffix(oid, arp_mac_oid)
                mac_addr = self._format_mac_address(value)
                if index_key in arp_data:
                    arp_data[index_key]['mac'] = mac_addr
                else:
                    arp_data[index_key] = {'mac': mac_addr}

            # Convert to list and filter complete entries
            for index, data in arp_data.items():
                if 'ip' in data and 'mac' in data:
                    arp_entries.append({
                        'ip_address': data['ip'],
                        'mac_address': data['mac'],
                        'vlan_id': None,
                        'interface': None,
                        'age_seconds': None
                    })

            logger.info(f"Collected {len(arp_entries)} ARP entries from {switch_ip}")
            return arp_entries

        except Exception as e:
            logger.error(f"Failed to collect ARP table from {switch_ip}: {str(e)}")
            return []

    async def collect_mac_table(
        self,
        switch_ip: str,
        switch_config: Dict,
        oid_overrides: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """
        Collect MAC address table from a switch using asyncio

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SNMP credentials
            oid_overrides: Optional vendor-specific OID overrides

        Returns:
            List of MAC entries: [{mac, port_name, vlan, is_dynamic}, ...]
        """
        try:
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = self._decrypt_optional_password(
                switch_config.get('snmp_priv_password_encrypted')
            )

            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config.get('snmp_priv_protocol'),
                priv_password=priv_password,
                snmp_version=switch_config.get('snmp_version'),
            )

            port = switch_config.get('snmp_port', 161)
            ov = oid_overrides or {}

            mac_addr_oid = ov.get('mac_address', self.OID_MAC_ADDRESS)
            mac_port_oid = ov.get('mac_port', self.OID_MAC_PORT)
            bridge_map_oid = ov.get('bridge_port_map', self.OID_BRIDGE_PORT_MAP)
            vlan_oid = ov.get('mac_vlan')
            has_vendor_oids = bool(ov)

            # Step 1: Collect MAC addresses via SNMP (vendor OIDs → Q-BRIDGE → BRIDGE fallback)
            # Only collect port_map and ifName when MAC data actually exists.
            mac_entries = []
            mac_data: Dict[str, Dict] = {}
            found_qbridge = False
            found_bridge = False

            # Try vendor OIDs first if available, with fallback to standard MIBs
            if has_vendor_oids:
                b_mac_results = await self._walk_oid(switch_ip, mac_addr_oid, auth_data, port, retries=0)
                for oid, value in b_mac_results:
                    mac_addr = self._format_mac_address(value)
                    index_key = self._oid_index_suffix(oid, mac_addr_oid)
                    mac_data[oid] = {
                        'mac': mac_addr, 'vlan': None, 'index_key': index_key,
                    }

                if mac_data:
                    # Collect VLAN data as optional enrichment (non-blocking)
                    if vlan_oid:
                        try:
                            vlan_results = await self._walk_oid(switch_ip, vlan_oid, auth_data, port, retries=0)
                            for oid, value in vlan_results:
                                index_key = self._oid_index_suffix(oid, vlan_oid)
                                try:
                                    vlan_id = int(value)
                                    for mac_oid, data in mac_data.items():
                                        if data.get('index_key') == index_key:
                                            data['vlan'] = vlan_id
                                            break
                                except (ValueError, TypeError):
                                    pass
                        except Exception:
                            logger.debug(f"VLAN OID walk failed for {switch_ip}, continuing without VLAN data")
                else:
                    logger.info(f"No MAC table via vendor OIDs on {switch_ip}, falling back to standard MIBs")
                    has_vendor_oids = False
                    mac_addr_oid = self.OID_MAC_ADDRESS
                    mac_port_oid = self.OID_MAC_PORT
                    bridge_map_oid = self.OID_BRIDGE_PORT_MAP

            if not has_vendor_oids and not mac_data:
                # Try Q-BRIDGE-MIB (modern standard) first
                q_mac_results = await self._walk_oid(
                    switch_ip, self.OID_Q_BRIDGE_MAC_ADDRESS, auth_data, port, retries=0
                )
                if q_mac_results:
                    found_qbridge = True
                    logger.info(f"Using Q-BRIDGE-MIB for {switch_ip}")
                    for oid, value in q_mac_results:
                        mac_addr = self._format_mac_address(value)
                        index_key = self._oid_index_suffix(oid, self.OID_Q_BRIDGE_MAC_ADDRESS)
                        try:
                            vlan_id = int(index_key.split('.')[0])
                        except (ValueError, IndexError):
                            vlan_id = None
                        mac_data[oid] = {
                            'mac': mac_addr, 'vlan': vlan_id, 'index_key': index_key,
                        }
                else:
                    # Fall back to BRIDGE-MIB
                    logger.info(f"No Q-BRIDGE-MIB data on {switch_ip}, trying BRIDGE-MIB")
                    b_mac_results = await self._walk_oid(
                        switch_ip, mac_addr_oid, auth_data, port, retries=0
                    )
                    if b_mac_results:
                        found_bridge = True
                        for oid, value in b_mac_results:
                            mac_addr = self._format_mac_address(value)
                            index_key = self._oid_index_suffix(oid, mac_addr_oid)
                            vlan_id = None
                            try:
                                vlan_id = int(str(oid).split('.')[-7])
                            except (ValueError, IndexError):
                                pass
                            mac_data[oid] = {
                                'mac': mac_addr, 'vlan': vlan_id, 'index_key': index_key,
                            }

            if not mac_data:
                logger.info(f"No MAC table via any SNMP method on {switch_ip}")
                return []

            # Step 2: Only now collect port mapping and interface names (needed for MAC→port resolution)
            port_map: Dict[int, int] = {}
            if not has_vendor_oids:
                bridge_results = await self._walk_oid(switch_ip, bridge_map_oid, auth_data, port, retries=0)
                for oid, value in bridge_results:
                    try:
                        bridge_port = int(str(oid).split('.')[-1])
                        port_map[bridge_port] = int(value)
                    except (ValueError, IndexError):
                        pass

            if_names: Dict[int, str] = {}
            name_results = await self._walk_oid(switch_ip, self.OID_IF_NAME, auth_data, port, retries=0)
            for oid, value in name_results:
                try:
                    if_index = int(str(oid).split('.')[-1])
                    if_names[if_index] = str(value)
                except (ValueError, IndexError):
                    pass

            # Step 3: Walk port OID and match with MAC addresses
            if found_qbridge:
                port_oid = self.OID_Q_BRIDGE_MAC_PORT
            else:
                port_oid = mac_port_oid

            port_results = await self._walk_oid(switch_ip, port_oid, auth_data, port, retries=0)
            for oid, value in port_results:
                index_key = self._oid_index_suffix(oid, port_oid)
                for mac_oid, data in mac_data.items():
                    if data.get('index_key') == index_key:
                        try:
                            port_value = int(value)
                        except (ValueError, TypeError):
                            continue
                        if has_vendor_oids:
                            port_name = if_names.get(port_value, f"Port{port_value}")
                        else:
                            if_index = port_map.get(port_value, port_value)
                            port_name = if_names.get(if_index, f"Port{port_value}")
                        mac_entries.append({
                            'mac_address': data['mac'],
                            'port_name': port_name,
                            'vlan_id': data['vlan'],
                            'is_dynamic': 1
                        })
                        break

            logger.info(f"Collected {len(mac_entries)} MAC entries from {switch_ip}")
            return mac_entries

        except Exception as e:
            logger.error(f"Failed to collect MAC table from {switch_ip}: {str(e)}")
            return []

    async def get_hostname(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[str]:
        """
        Get hostname from switch via SNMP sysName OID

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SNMP credentials

        Returns:
            Hostname string or None if failed
        """
        try:
            logger.info(f"Starting SNMP GET for hostname on {switch_ip}")

            # Decrypt SNMP passwords
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = self._decrypt_optional_password(
                switch_config.get('snmp_priv_password_encrypted')
            )

            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config.get('snmp_priv_protocol'),
                priv_password=priv_password,
                snmp_version=switch_config.get('snmp_version'),
            )

            port = switch_config.get('snmp_port', 161)

            # Get hostname via SNMP
            result = await self._get_oid(switch_ip, self.OID_SYS_NAME, auth_data, port)

            if result:
                hostname = str(result).strip()
                # Clean up hostname - remove any non-printable characters
                hostname = ''.join(char for char in hostname if char.isprintable())
                logger.info(f"✅ Got hostname from {switch_ip} via SNMP: {hostname}")
                return hostname
            else:
                logger.error(f"❌ No hostname returned from {switch_ip} - SNMP GET returned None")
                return None

        except Exception as e:
            logger.error(f"❌ Failed to get hostname from {switch_ip}: {str(e)}")
            return None

    async def get_device_info(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[Dict]:
        """
        Get device identity info (hostname, vendor, model) via SNMP.
        Queries sysName, sysDescr, sysObjectID, and (optionally) ENTITY-MIB
        entPhysicalDescr for chassis hardware identification.

        Returns dict with keys: hostname, sys_descr, sys_object_id, entity_phys_descr
        or None if SNMP fails.
        """
        try:
            logger.info(f"Getting device info from {switch_ip} via SNMP")

            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = self._decrypt_optional_password(
                switch_config.get('snmp_priv_password_encrypted')
            )

            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config.get('snmp_priv_protocol'),
                priv_password=priv_password,
                snmp_version=switch_config.get('snmp_version'),
            )

            port = switch_config.get('snmp_port', 161)

            hostname = None
            sys_descr = None
            sys_object_id = None

            for oid, label in [
                (self.OID_SYS_NAME, 'sysName'),
                (self.OID_SYS_DESCR, 'sysDescr'),
                (self.OID_SYS_OBJECT_ID, 'sysObjectID'),
            ]:
                value = await self._get_oid(switch_ip, oid, auth_data, port, timeout=8)
                if value is not None:
                    value_str = str(value).strip()
                    if label == 'sysName':
                        hostname = ''.join(c for c in value_str if c.isprintable())
                    elif label == 'sysDescr':
                        sys_descr = value_str
                    elif label == 'sysObjectID':
                        sys_object_id = value_str

            if not hostname and not sys_descr:
                logger.warning(f"No usable SNMP data from {switch_ip}")
                return None

            # Query ENTITY-MIB chassis description — optional, not all devices support it.
            # Useful for Nokia SR Linux where sysDescr only contains OS version, not hardware model.
            entity_phys_descr = None
            try:
                value = await self._get_oid(
                    switch_ip, self.OID_ENTITY_PHYS_DESCR, auth_data, port, timeout=5
                )
                if value is not None:
                    entity_phys_descr = str(value).strip()
                    logger.debug(f"ENTITY-MIB chassis descr from {switch_ip}: {entity_phys_descr}")
            except Exception:
                pass  # ENTITY-MIB is optional

            logger.info(
                f"Got device info from {switch_ip}: hostname={hostname} "
                f"OID={sys_object_id}"
            )
            return {
                'hostname': hostname,
                'sys_descr': sys_descr,
                'sys_object_id': sys_object_id,
                'entity_phys_descr': entity_phys_descr,
            }

        except Exception as e:
            logger.error(f"Failed to get device info from {switch_ip}: {str(e)}")
            return None

    async def get_chassis_serial(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[str]:
        """
        Collect chassis serial number via SNMP ENTITY-MIB.

        Walks entPhysicalClass to find the chassis entity (class=3),
        then GETs entPhysicalSerialNum at that index.
        Falls back to entPhysicalSerialNum.1 if the walk returns nothing.
        """
        try:
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = self._decrypt_optional_password(
                switch_config.get('snmp_priv_password_encrypted')
            )
            auth_data = self._create_snmp_auth(
                username=switch_config.get('snmp_username'),
                auth_protocol=switch_config.get('snmp_auth_protocol', 'SHA'),
                auth_password=auth_password,
                priv_protocol=switch_config.get('snmp_priv_protocol'),
                priv_password=priv_password,
                snmp_version=switch_config.get('snmp_version'),
            )
            if not auth_data:
                return None

            port = switch_config.get('snmp_port', 161)

            # Walk entPhysicalClass to find chassis index
            class_oid = self.OID_ENTITY_PHYS_CLASS
            chassis_index = None

            try:
                entries = await asyncio.wait_for(
                    self._walk_oid(switch_ip, class_oid, auth_data, port, timeout=5),
                    timeout=7.0
                )
                if entries:
                    for oid_str, value in entries:
                        if value == 3:  # chassis
                            chassis_index = oid_str.split('.')[-1]
                            break
            except asyncio.TimeoutError:
                logger.debug(f"ENTITY-MIB walk timed out for {switch_ip}, trying fallback")
            except Exception as e:
                logger.debug(f"ENTITY-MIB walk failed for {switch_ip}: {e}")

            # Fallback: try index 1
            if chassis_index is None:
                chassis_index = '1'

            serial_oid = f'{self.OID_ENTITY_PHYS_SERIAL}.{chassis_index}'
            serial = await self._get_oid(
                switch_ip, serial_oid, auth_data, port,
                timeout=5, retries=1, log_errors=False
            )

            if serial is not None:
                serial_str = str(serial).strip()
                if serial_str and serial_str.lower() not in (
                    '', 'null', 'none', 'na', 'n/a', 'n.a.', 'unknown', 'not available',
                ):
                    logger.info(f"Chassis serial for {switch_ip}: {serial_str}")
                    return serial_str

            return None

        except Exception as e:
            logger.debug(f"Serial collection failed for {switch_ip}: {e}")
            return None


    def _extract_os_from_sysdescr(self, sys_descr: str) -> Dict[str, Optional[str]]:
        """
        从SNMP sysDescr字符串提取OS类型、名称和版本

        Args:
            sys_descr: SNMP sysDescr字符串 (OID 1.3.6.1.2.1.1.1.0)

        Returns:
            包含os_type, os_name, os_version的字典
        """
        import re

        result = {'os_type': None, 'os_name': None, 'os_version': None}

        if not sys_descr:
            return result

        descr_lower = sys_descr.lower()

        # Cisco IOS/NX-OS/IOS-XE
        if any(kw in descr_lower for kw in ['ios', 'nx-os', 'ios-xe', 'ios-xr']):
            result['os_type'] = 'network'
            result['os_name'] = 'Cisco IOS'
            # 提取版本: "Version 15.2(4)E8" 或 "IOS Version 12.2"
            match = re.search(r'(?:Version|IOS.*Version)\s+([0-9]+\.[0-9]+[^\s,)]*)', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(1)

        # Linux
        elif 'linux' in descr_lower:
            result['os_type'] = 'linux'
            result['os_name'] = 'Ubuntu Linux' if 'ubuntu' in descr_lower else \
                               'CentOS Linux' if 'centos' in descr_lower else \
                               'Red Hat Linux' if ('red hat' in descr_lower or 'rhel' in descr_lower) else \
                               'Linux'
            # 提取内核版本: "Linux 5.4.0-42-generic"
            match = re.search(r'Linux\s+(?:kernel\s+)?([0-9]+\.[0-9]+\.[0-9]+[^\s,)]*)', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(1)

        # Windows
        elif 'windows' in descr_lower:
            result['os_type'] = 'windows'
            result['os_name'] = 'Windows'
            # 提取版本: "Windows Server 2019" 或 "Windows 10"
            match = re.search(r'Windows\s+(Server\s+)?([0-9]+(?:\.[0-9]+)*|[0-9]{4})', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(2)
                if match.group(1):  # 包含"Server"
                    result['os_name'] = 'Windows Server'

        # Juniper JUNOS
        elif any(kw in descr_lower for kw in ['junos', 'juniper']):
            result['os_type'] = 'network'
            result['os_name'] = 'Juniper JUNOS'
            match = re.search(r'JUNOS\s+([0-9]+\.[0-9]+[^\s,)]*)', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(1)

        # Dell Force10 OS
        elif 'force10' in descr_lower or ('dell' in descr_lower and 'os' in descr_lower):
            result['os_type'] = 'network'
            result['os_name'] = 'Dell Force10 OS'
            match = re.search(r'(?:OS\s+)?Version\s+([0-9]+\.[0-9]+[^\s,)]*)', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(1)

        # Nokia/Alcatel
        elif any(kw in descr_lower for kw in ['nokia', 'alcatel', 'timos', 'sr linux']):
            result['os_type'] = 'network'
            result['os_name'] = 'Nokia SR Linux' if 'sr linux' in descr_lower else \
                               'Nokia TiMOS' if 'timos' in descr_lower else \
                               'Nokia Network OS'
            match = re.search(r'(?:Version|TiMOS-|v)([0-9]+\.[0-9]+[^\s,)]*)', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(1)

        # FreeBSD/OpenBSD
        elif any(kw in descr_lower for kw in ['freebsd', 'openbsd', 'netbsd']):
            result['os_type'] = 'unix'
            result['os_name'] = 'FreeBSD' if 'freebsd' in descr_lower else \
                               'OpenBSD' if 'openbsd' in descr_lower else \
                               'NetBSD'
            match = re.search(r'(?:FreeBSD|OpenBSD|NetBSD)\s+([0-9]+\.[0-9]+[^\s,)]*)', sys_descr, re.IGNORECASE)
            if match:
                result['os_version'] = match.group(1)

        return result

    async def get_device_identification(
        self,
        target_ip: str,
        snmp_profile: Dict
    ) -> Optional[Dict]:
        """
        Get device identification info for IPAM (SolarWinds-style)

        Queries the following SNMP OIDs:
        - sysName (1.3.6.1.2.1.1.5.0): System hostname
        - sysContact (1.3.6.1.2.1.1.4.0): Contact information
        - sysLocation (1.3.6.1.2.1.1.6.0): Physical location
        - sysUpTime (1.3.6.1.2.1.1.3.0): Time since boot
        - sysDescr (1.3.6.1.2.1.1.1.0): System description (for machine_type/vendor)

        Args:
            target_ip: IP address of the device to query
            snmp_profile: SNMP profile dictionary with credentials

        Returns:
            Dictionary with keys:
            - system_name: SNMP sysName (hostname)
            - contact: SNMP sysContact
            - location: SNMP sysLocation
            - last_boot_time: Calculated datetime from sysUpTime
            - machine_type: Extracted from sysDescr
            - vendor: Extracted from sysDescr
            Or None if SNMP query fails
        """
        try:
            logger.debug(f"Getting device identification from {target_ip} via SNMP")

            # Decrypt SNMP passwords
            auth_password = decrypt_password(snmp_profile['auth_password_encrypted'])
            priv_password = self._decrypt_optional_password(
                snmp_profile.get('priv_password_encrypted')
            )

            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=snmp_profile['username'],
                auth_protocol=snmp_profile.get('auth_protocol', 'SHA'),
                auth_password=auth_password,
                priv_protocol=snmp_profile.get('priv_protocol'),
                priv_password=priv_password,
                snmp_version=snmp_profile.get('snmp_version'),
            )

            port = snmp_profile.get('port', 161)
            timeout = snmp_profile.get('timeout', 5)
            retries = max(0, int(snmp_profile.get('retries', 2) or 0))

            # Query all OIDs
            result = {
                'system_name': None,
                'contact': None,
                'location': None,
                'last_boot_time': None,
                'machine_type': None,
                'vendor': None,
                # OS information fields
                'os_type': None,
                'os_name': None,
                'os_version': None
            }

            # Probe the two key identification OIDs first. If both are missing, this
            # host is usually not a usable SNMP target for IPAM enrichment.
            sys_name = await self._get_oid(
                target_ip,
                self.OID_SYS_NAME,
                auth_data,
                port,
                timeout,
                retries=retries,
                log_errors=False
            )
            if sys_name:
                result['system_name'] = ''.join(c for c in str(sys_name) if c.isprintable()).strip()

            sys_descr = await self._get_oid(
                target_ip,
                self.OID_SYS_DESCR,
                auth_data,
                port,
                timeout,
                retries=retries,
                log_errors=False
            )
            if sys_descr:
                descr = str(sys_descr).strip()
                # Try to extract vendor and machine type from sysDescr
                descr_lower = descr.lower()

                # Enhanced vendor detection
                if 'cisco' in descr_lower:
                    result['vendor'] = 'Cisco'
                elif 'dell' in descr_lower:
                    result['vendor'] = 'Dell'
                elif 'hp' in descr_lower or 'hewlett' in descr_lower or 'hewlett-packard' in descr_lower:
                    result['vendor'] = 'HP'
                elif 'juniper' in descr_lower:
                    result['vendor'] = 'Juniper'
                elif 'nokia' in descr_lower or 'alcatel' in descr_lower:
                    result['vendor'] = 'Nokia'
                elif 'huawei' in descr_lower:
                    result['vendor'] = 'Huawei'
                elif 'zte' in descr_lower:
                    result['vendor'] = 'ZTE'
                elif 'aruba' in descr_lower:
                    result['vendor'] = 'Aruba'
                elif 'fortinet' in descr_lower or 'fortigate' in descr_lower:
                    result['vendor'] = 'Fortinet'

                # Enhanced device type detection
                machine_type = descr.split('\n')[0][:200] if descr else None

                # Categorize device types based on sysDescr patterns
                if 'switch' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Switch"
                elif 'router' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Router"
                elif 'firewall' in descr_lower or 'fortigate' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Firewall"
                elif 'access point' in descr_lower or 'wireless' in descr_lower or 'ap' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Access Point"
                elif 'base station' in descr_lower or 'bts' in descr_lower or 'enodeb' in descr_lower or 'gnodeb' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Nokia')} Base Station"
                elif 'server' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Server"
                elif 'workstation' in descr_lower or 'pc' in descr_lower or 'desktop' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} PC"
                elif 'laptop' in descr_lower or 'notebook' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Laptop"
                elif 'printer' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Printer"
                elif 'camera' in descr_lower or 'ipc' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} IP Camera"
                else:
                    # Use raw sysDescr as fallback
                    result['machine_type'] = machine_type

                # Extract OS information from sysDescr
                os_info = self._extract_os_from_sysdescr(descr)
                result['os_type'] = os_info['os_type']
                result['os_name'] = os_info['os_name']
                result['os_version'] = os_info['os_version']

                logger.debug(
                    f"OS from SNMP sysDescr for {target_ip}: "
                    f"type={os_info['os_type']}, name={os_info['os_name']}, version={os_info['os_version']}"
                )

            if not result['system_name'] and not sys_descr:
                logger.debug(
                    f"Skipping optional SNMP enrichment for {target_ip}: "
                    "both sysName and sysDescr were unavailable"
                )
                return None

            # sysContact and sysLocation are useful enrichment fields, but they are not
            # worth five separate timeout cycles on endpoints that barely respond.
            sys_contact = await self._get_oid(
                target_ip,
                self.OID_SYS_CONTACT,
                auth_data,
                port,
                timeout,
                retries=retries,
                log_errors=False
            )
            if sys_contact:
                result['contact'] = str(sys_contact).strip()

            sys_location = await self._get_oid(
                target_ip,
                self.OID_SYS_LOCATION,
                auth_data,
                port,
                timeout,
                retries=retries,
                log_errors=False
            )
            if sys_location:
                result['location'] = str(sys_location).strip()

            # sysUpTime (time ticks since boot, convert to last_boot_time)
            sys_uptime = await self._get_oid(
                target_ip,
                self.OID_SYS_UPTIME,
                auth_data,
                port,
                timeout,
                retries=retries,
                log_errors=False
            )
            if sys_uptime:
                try:
                    # sysUpTime is in hundredths of seconds
                    uptime_ticks = int(sys_uptime)
                    uptime_seconds = uptime_ticks / 100

                    # Calculate last boot time
                    from datetime import datetime, timedelta, timezone
                    now = datetime.now(timezone.utc)
                    last_boot = now - timedelta(seconds=uptime_seconds)
                    result['last_boot_time'] = last_boot.isoformat()

                    logger.debug(f"Device {target_ip} uptime: {uptime_seconds}s, last boot: {last_boot}")
                except Exception as e:
                    logger.warning(f"Failed to parse sysUpTime for {target_ip}: {str(e)}")

            # Return result if SNMP yielded any meaningful identification data.
            if any(value not in (None, '') for value in result.values()):
                logger.info(
                    f"Got device identification from {target_ip}: "
                    f"sysName={result['system_name']}, "
                    f"location={result['location']}, "
                    f"vendor={result['vendor']}, "
                    f"os_type={result['os_type']}, "
                    f"os_version={result['os_version']}"
                )
                return result
            else:
                logger.debug(f"No device identification data retrieved from {target_ip}")
                return None

        except Exception as e:
            logger.error(f"Failed to get device identification from {target_ip}: {str(e)}")
            return None

    # Keep compatibility with async wrappers
    async def collect_arp_table_async(
        self,
        switch_ip: str,
        switch_config: Dict,
        oid_overrides: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """Async wrapper for ARP table collection - now just calls the async method"""
        return await self.collect_arp_table(switch_ip, switch_config, oid_overrides)

    async def collect_mac_table_async(
        self,
        switch_ip: str,
        switch_config: Dict,
        oid_overrides: Optional[Dict[str, str]] = None
    ) -> List[Dict]:
        """Async wrapper for MAC table collection - now just calls the async method"""
        return await self.collect_mac_table(switch_ip, switch_config, oid_overrides)

    async def collect_optical_modules(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> List[Dict]:
        """
        Collect optical transceiver (SFP/QSFP) information from switch via SNMP

        Uses ENTITY-MIB to retrieve:
        - Module type (SFP, SFP+, QSFP, etc.)
        - Model number
        - Serial number
        - Vendor/manufacturer
        - Port mapping

        Args:
            switch_ip: IP address of the switch
            switch_config: SNMP configuration dictionary

        Returns:
            List of optical module dictionaries with keys:
            - port_name: Interface name
            - module_type: SFP/SFP+/QSFP/QSFP+/QSFP28
            - model: Model number
            - serial_number: Serial number
            - vendor: Manufacturer name
            - speed_gbps: Port speed in Gbps
        """
        logger.info(f"Collecting optical modules from {switch_ip} via SNMP")

        try:
            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config.get('snmp_auth_protocol', 'SHA'),
                auth_password=decrypt_password(switch_config['snmp_auth_password_encrypted']),
                priv_protocol=switch_config.get('snmp_priv_protocol'),
                priv_password=self._decrypt_optional_password(
                    switch_config.get('snmp_priv_password_encrypted')
                ),
                snmp_version=switch_config.get('snmp_version'),
            )

            # Step 1: Walk entPhysicalDescr and entPhysicalClass to find optical modules
            logger.debug(f"Walking entPhysicalDescr and entPhysicalClass on {switch_ip}")
            phys_descr = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_DESCR_TABLE, auth_data)
            phys_class = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_CLASS, auth_data)

            if not phys_descr:
                logger.warning(f"No entPhysicalDescr entries found on {switch_ip}")
                return []

            # Convert entPhysicalClass to dictionary
            # RFC 2737: 1=other, 2=unknown, 3=chassis, 4=backplane, 5=container,
            #           6=powerSupply, 7=fan, 8=sensor, 9=module, 10=port
            class_dict = {str(oid).split('.')[-1]: int(val) for oid, val in phys_class}

            # Filter entries that are optical modules
            optical_keywords = ['sfp', 'qsfp', 'transceiver', 'gbic', 'optic']
            exclude_keywords = [
                'fan', 'power supply', 'sensor', 'temperature', 'cpu', 'memory', 'stack',
                'container', 'slot', 'backplane', 'chassis', 'board',
                'motherboard', 'supervisor', 'linecard', 'switch system',
                # Exclude entire interface boards/modules (these contain multiple ports)
                ' x ', 'network module', 'routing module'
            ]

            module_indices = []
            for oid, value in phys_descr:
                # Extract index from OID (last component)
                index = str(oid).split('.')[-1]
                desc_lower = str(value).lower()

                # Get entPhysicalClass for this entity
                entity_class = class_dict.get(index, 0)

                # Check if this is an optical module
                is_optical = any(keyword in desc_lower for keyword in optical_keywords)
                is_excluded = any(keyword in desc_lower for keyword in exclude_keywords)

                if is_optical and not is_excluded:
                    module_indices.append((index, str(value)))
                    logger.debug(f"Found optical module at index {index} (class={entity_class}): {value}")
                elif is_optical and is_excluded:
                    logger.debug(f"Excluded at index {index} (class={entity_class}): {value[:80]}")

            if not module_indices:
                logger.info(f"No optical modules found on {switch_ip}")
                # Log first 10 physical entities for debugging
                logger.debug("First 10 entPhysicalDescr entries:")
                for i, (oid, value) in enumerate(phys_descr[:10]):
                    index = str(oid).split('.')[-1]
                    entity_class = class_dict.get(index, 0)
                    logger.debug(f"  [{index}] class={entity_class}: {str(value)[:80]}")
                return []

            logger.info(f"Found {len(module_indices)} optical modules on {switch_ip}")

            # Step 2: Collect additional info for each module
            modules = []

            # Walk all needed OIDs once
            logger.debug(f"Collecting model names, serials, vendors, names, and containment info")
            phys_model = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_MODEL, auth_data)
            phys_serial = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_SERIAL, auth_data)
            phys_vendor = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_MFG, auth_data)
            phys_name = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_NAME, auth_data)
            phys_contained = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_CONTAINED_IN, auth_data)
            if_names = await self._walk_oid(switch_ip, self.OID_IF_NAME, auth_data)
            if_speeds = await self._walk_oid(switch_ip, self.OID_IF_HIGH_SPEED, auth_data)

            # Convert to dictionaries for easy lookup
            model_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_model}
            serial_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_serial}
            vendor_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_vendor}
            phys_name_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_name}
            contained_dict = {str(oid).split('.')[-1]: int(val) for oid, val in phys_contained}
            ifname_dict = {str(oid).split('.')[-1]: str(val) for oid, val in if_names}
            ifspeed_dict = {str(oid).split('.')[-1]: int(val) for oid, val in if_speeds}

            # Step 3: Map modules to ports and collect info
            for index, description in module_indices:
                try:
                    # Determine module type from description
                    desc_lower = description.lower()
                    if 'qsfp28' in desc_lower or '100g' in desc_lower:
                        module_type = 'QSFP28'
                    elif 'qsfp+' in desc_lower or '40g' in desc_lower:
                        module_type = 'QSFP+'
                    elif 'qsfp' in desc_lower:
                        module_type = 'QSFP'
                    elif 'sfp+' in desc_lower or '10g' in desc_lower:
                        module_type = 'SFP+'
                    elif 'sfp' in desc_lower:
                        module_type = 'SFP'
                    else:
                        module_type = 'Transceiver'

                    # Get additional info
                    model = model_dict.get(index, '').strip()
                    serial = serial_dict.get(index, '').strip()
                    vendor = vendor_dict.get(index, '').strip()

                    # Find parent port (walk up containment hierarchy)
                    port_name = None
                    parent_index = contained_dict.get(index)

                    # Strategy 1: Try entPhysicalName directly (many vendors use this for port names)
                    entity_name = phys_name_dict.get(index, '').strip()
                    if entity_name and ('ethernet' in entity_name.lower() or
                                        'gigabit' in entity_name.lower() or
                                        'tengigabit' in entity_name.lower() or
                                        '/' in entity_name):  # Port names often have format like "1/0/1"
                        port_name = entity_name
                        logger.debug(f"Found port name from entPhysicalName: {port_name}")

                    # Strategy 2: Walk up containment hierarchy to find ifName
                    if not port_name and parent_index:
                        # Try up to 5 levels of parents
                        current_index = str(parent_index)
                        for level in range(5):
                            # Check if current parent has ifName
                            if_name = ifname_dict.get(current_index)
                            if if_name:
                                port_name = if_name
                                logger.debug(f"Found port name at level {level+1}: {port_name}")
                                break

                            # Check if current parent has entPhysicalName that looks like a port
                            parent_name = phys_name_dict.get(current_index, '').strip()
                            if parent_name and ('ethernet' in parent_name.lower() or
                                                'gigabit' in parent_name.lower() or
                                                '/' in parent_name):
                                port_name = parent_name
                                logger.debug(f"Found port name from parent entPhysicalName at level {level+1}: {port_name}")
                                break

                            # Go up one more level
                            if current_index not in contained_dict:
                                break
                            current_index = str(contained_dict[current_index])

                    # Strategy 3: Fallback - try using the module index directly as ifIndex
                    if not port_name:
                        port_name = ifname_dict.get(index)
                        if port_name:
                            logger.debug(f"Found port name from direct ifIndex mapping: {port_name}")

                    # Get port speed (in Mbps, convert to Gbps)
                    speed_mbps = None
                    if parent_index:
                        speed_mbps = ifspeed_dict.get(str(parent_index))
                    if not speed_mbps:
                        speed_mbps = ifspeed_dict.get(index)

                    speed_gbps = None
                    if speed_mbps and speed_mbps > 0:
                        speed_gbps = speed_mbps // 1000  # Convert Mbps to Gbps

                    # Only include if we successfully mapped to a port
                    if port_name:
                        modules.append({
                            'port_name': port_name,
                            'module_type': module_type,
                            'model': model if model else None,
                            'serial_number': serial if serial else None,
                            'vendor': vendor if vendor else None,
                            'speed_gbps': speed_gbps
                        })
                        logger.debug(
                            f"Mapped {module_type} to port {port_name} "
                            f"(model: {model}, SN: {serial}, vendor: {vendor})"
                        )
                    else:
                        logger.warning(
                            f"Could not map module at index {index} to port - "
                            f"parent: {parent_index}, desc: {description[:50]}"
                        )

                except Exception as e:
                    logger.error(f"Error processing module at index {index}: {str(e)}")
                    continue

            logger.info(f"Successfully collected {len(modules)} optical modules from {switch_ip}")
            return modules

        except Exception as e:
            logger.error(f"Failed to collect optical modules from {switch_ip}: {str(e)}")
            return []


# Singleton instance
snmp_service = SNMPService()
