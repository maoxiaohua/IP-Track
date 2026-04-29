"""
数据收集策略配置

根据厂商和型号定义最佳的数据收集策略
"""

from typing import Dict, List
from enum import Enum


class CollectionMethod(str, Enum):
    """收集方法枚举"""
    CLI_ONLY = "cli_only"              # 仅使用CLI
    SNMP_ONLY = "snmp_only"            # 仅使用SNMP
    SNMP_PRIMARY = "snmp_primary"      # SNMP优先，CLI作为备用
    CLI_PRIMARY = "cli_primary"        # CLI优先，SNMP作为备用
    AUTO = "auto"                      # 自动选择


class CollectionStrategy:
    """
    收集策略映射

    按厂商和型号定义最佳收集方式。

    注意：
    - ARP/MAC（L2 表项）已切换为全局 CLI-only 策略，避免不同厂商的
      SNMP FDB/ARP 实现差异、超时和隐私级别兼容问题。
    - 这里的 vendor/model 策略主要仍服务于设备信息、光模块等其它采集项。
    """

    GLOBAL_L2_TABLE_METHOD: CollectionMethod = CollectionMethod.CLI_ONLY

    # 厂商级别的默认策略
    VENDOR_DEFAULTS: Dict[str, CollectionMethod] = {
        'alcatel': CollectionMethod.CLI_ONLY,
        'cisco': CollectionMethod.SNMP_PRIMARY,
        'dell': CollectionMethod.SNMP_PRIMARY,
        'juniper': CollectionMethod.AUTO,
    }

    # 型号级别的精确策略（覆盖厂商默认策略）
    MODEL_STRATEGIES: Dict[str, Dict[str, CollectionMethod]] = {
        'alcatel': {
            # Nokia 7220系列 - SR Linux OS
            '7220 IXR': CollectionMethod.CLI_ONLY,
            '7220 IXR-D1': CollectionMethod.CLI_ONLY,
            '7220 IXR-D2': CollectionMethod.CLI_ONLY,
            '7220 IXR-D2L': CollectionMethod.CLI_ONLY,

            # Nokia 7250系列 - SR OS
            '7250 IXR': CollectionMethod.CLI_ONLY,
            '7250 IXR-e2': CollectionMethod.CLI_ONLY,
            '7250 IXR-x': CollectionMethod.CLI_ONLY,

            # WBX系列 - SR OS
            'WBX220': CollectionMethod.CLI_ONLY,
        },

        'cisco': {
            # Nexus 9000系列 - NX-OS (支持SNMP)
            'N9K': CollectionMethod.SNMP_PRIMARY,
            'N9K-C9': CollectionMethod.SNMP_PRIMARY,

            # Catalyst 3650系列 - IOS-XE (支持SNMP)
            'C3650': CollectionMethod.SNMP_PRIMARY,

            # Catalyst 3560系列 - IOS (支持SNMP)
            'C3560': CollectionMethod.SNMP_PRIMARY,
            'C3560E': CollectionMethod.SNMP_PRIMARY,
            'C3560E-UNIVERSALK9-M': CollectionMethod.SNMP_PRIMARY,

            # Catalyst 2960系列 - IOS (支持SNMP)
            'C2960': CollectionMethod.SNMP_PRIMARY,
            'C2960S': CollectionMethod.SNMP_PRIMARY,
            'C2960X': CollectionMethod.SNMP_PRIMARY,
            'C2960S-UNIVERSALK9-M': CollectionMethod.SNMP_PRIMARY,
            'C2960X-UNIVERSALK9-M': CollectionMethod.SNMP_PRIMARY,

            # Nexus系列 - NX-OS (支持SNMP) - 通用匹配
            'NX': CollectionMethod.SNMP_PRIMARY,
        },

        'dell': {
            # S3000系列 - DNOS9/Force10 (CLI-only due to SNMP timeout issues)
            'S3048': CollectionMethod.CLI_ONLY,
            'S3048-ON': CollectionMethod.CLI_ONLY,
            'S3148': CollectionMethod.CLI_ONLY,

            # S4000系列 - DNOS9/Force10 (CLI-only due to SNMP timeout issues)
            'S4048': CollectionMethod.CLI_ONLY,
            'S4048-ON': CollectionMethod.CLI_ONLY,
            'S4048T-ON': CollectionMethod.CLI_ONLY,
            'S4148F-ON': CollectionMethod.CLI_ONLY,

            # S5000系列 - OS10 (支持SNMP)
            'S5232F-ON': CollectionMethod.SNMP_PRIMARY,

            # Z9000系列 - DNOS9/Force10 (CLI-only)
            'Z9100-ON': CollectionMethod.CLI_ONLY,
        },
    }

    @classmethod
    def get_strategy(cls, vendor: str, model: str) -> CollectionMethod:
        """
        获取指定厂商和型号的收集策略

        Args:
            vendor: 厂商名称
            model: 型号名称

        Returns:
            CollectionMethod: 推荐的收集方法
        """
        vendor_lower = vendor.lower() if vendor else ''

        # 1. 先查找型号级别的精确匹配
        if vendor_lower in cls.MODEL_STRATEGIES:
            model_strategies = cls.MODEL_STRATEGIES[vendor_lower]

            # 精确匹配
            if model in model_strategies:
                return model_strategies[model]

            # 模糊匹配（处理带后缀的型号）
            for model_pattern, strategy in model_strategies.items():
                if model and model.startswith(model_pattern):
                    return strategy

        # 2. 使用厂商级别的默认策略
        if vendor_lower in cls.VENDOR_DEFAULTS:
            return cls.VENDOR_DEFAULTS[vendor_lower]

        # 3. 最终默认策略
        return CollectionMethod.AUTO

    @classmethod
    def should_try_cli(cls, vendor: str, model: str) -> bool:
        """是否应该尝试CLI收集"""
        strategy = cls.get_strategy(vendor, model)
        return strategy in [
            CollectionMethod.CLI_ONLY,
            CollectionMethod.CLI_PRIMARY,
            CollectionMethod.AUTO
        ]

    @classmethod
    def should_try_snmp(cls, vendor: str, model: str) -> bool:
        """是否应该尝试SNMP收集"""
        strategy = cls.get_strategy(vendor, model)
        return strategy in [
            CollectionMethod.SNMP_ONLY,
            CollectionMethod.SNMP_PRIMARY,
            CollectionMethod.AUTO
        ]

    @classmethod
    def get_primary_method(cls, vendor: str, model: str) -> str:
        """获取首选收集方法（用于日志显示）"""
        strategy = cls.get_strategy(vendor, model)

        if strategy == CollectionMethod.CLI_ONLY:
            return "CLI"
        elif strategy == CollectionMethod.SNMP_ONLY:
            return "SNMP"
        elif strategy == CollectionMethod.SNMP_PRIMARY:
            return "SNMP (CLI fallback)"
        elif strategy == CollectionMethod.CLI_PRIMARY:
            return "CLI (SNMP fallback)"
        else:
            return "Auto"

    @classmethod
    def should_fallback_to_snmp(cls, vendor: str, model: str) -> bool:
        """CLI失败后是否应该fallback到SNMP"""
        strategy = cls.get_strategy(vendor, model)
        return strategy in [
            CollectionMethod.SNMP_PRIMARY,
            CollectionMethod.AUTO
        ]

    @classmethod
    def should_fallback_to_cli(cls, vendor: str, model: str) -> bool:
        """SNMP失败后是否应该fallback到CLI"""
        strategy = cls.get_strategy(vendor, model)
        return strategy in [
            CollectionMethod.CLI_PRIMARY,
            CollectionMethod.AUTO
        ]

    @classmethod
    def get_l2_table_method(cls) -> CollectionMethod:
        """Global ARP/MAC collection method shared by all switches."""
        return cls.GLOBAL_L2_TABLE_METHOD

    @classmethod
    def get_l2_table_primary_method(cls) -> str:
        """Human-friendly description for the global ARP/MAC policy."""
        if cls.GLOBAL_L2_TABLE_METHOD == CollectionMethod.CLI_ONLY:
            return "CLI only (global)"
        if cls.GLOBAL_L2_TABLE_METHOD == CollectionMethod.SNMP_ONLY:
            return "SNMP only (global)"
        return cls.GLOBAL_L2_TABLE_METHOD.value


# 优化的CLI命令模板
OPTIMIZED_CLI_TEMPLATES: List[Dict] = [
    # ==================== Alcatel/Nokia Templates ====================

    # Nokia 7220 IXR系列 - SR Linux OS
    {
        'vendor': 'alcatel',
        'model_pattern': '7220 ixr*',  # 匹配 7220 IXR, 7220 IXR-D1, 7220 IXR-D2, 7220 IXR-D2L
        'device_type': 'nokia_srl',
        'arp_command': 'show arpnd arp-entries',
        'arp_parser_type': 'nokia_7220',
        'arp_enabled': True,
        'mac_command': 'show network-instance bridge-table mac-table all',
        'mac_parser_type': 'nokia_7220',
        'mac_enabled': True,
        'priority': 210,  # 最高优先级
        'enabled': True,
        'description': 'Nokia 7220 IXR系列 - SR Linux OS'
    },

    # Nokia 7250 IXR系列 - SR OS
    {
        'vendor': 'alcatel',
        'model_pattern': '7250 ixr*',  # 匹配 7250 IXR-e2, 7250 IXR-x
        'device_type': 'nokia_sros',
        'arp_command': 'show router arp',
        'arp_parser_type': 'nokia_7250',
        'arp_enabled': True,
        'mac_command': 'show service fdb-mac',
        'mac_parser_type': 'nokia_7250',
        'mac_enabled': True,
        'priority': 210,
        'enabled': True,
        'description': 'Nokia 7250 IXR系列 - SR OS'
    },

    # Nokia WBX系列 - SR OS
    {
        'vendor': 'alcatel',
        'model_pattern': 'wbx*',
        'device_type': 'nokia_sros',
        'arp_command': 'show router arp',
        'arp_parser_type': 'nokia_7250',
        'arp_enabled': True,
        'mac_command': 'show service fdb-mac',
        'mac_parser_type': 'nokia_7250',
        'mac_enabled': True,
        'priority': 210,
        'enabled': True,
        'description': 'Nokia WBX系列 - SR OS'
    },

    # ==================== Dell Templates ====================

    # Dell S3000/S4000系列 - DNOS9/Force10
    {
        'vendor': 'dell',
        'model_pattern': 's3*',  # S3048, S3148
        'device_type': 'dell_force10',
        'arp_command': 'show arp',
        'arp_parser_type': 'dell_force10',
        'arp_enabled': True,
        'mac_command': 'show mac-address-table',
        'mac_parser_type': 'dell_force10',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Dell S3000系列 - Force10 DNOS9'
    },

    {
        'vendor': 'dell',
        'model_pattern': 's4*',  # S4048, S4048-ON, S4048T-ON, S4148F-ON
        'device_type': 'dell_force10',
        'arp_command': 'show arp',
        'arp_parser_type': 'dell_force10',
        'arp_enabled': True,
        'mac_command': 'show mac-address-table',
        'mac_parser_type': 'dell_force10',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Dell S4000系列 - Force10 DNOS9'
    },

    # Dell S5000系列 - OS10
    {
        'vendor': 'dell',
        'model_pattern': 's5*',  # S5232F-ON
        'device_type': 'dell_os10',
        'arp_command': 'show arp',
        'arp_parser_type': 'dell_os10',
        'arp_enabled': True,
        'mac_command': 'show mac-address-table',
        'mac_parser_type': 'dell_os10',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Dell S5000系列 - Dell OS10'
    },

    # Dell Z9000系列 - DNOS9/Force10
    {
        'vendor': 'dell',
        'model_pattern': 'z9*',  # Z9100-ON
        'device_type': 'dell_force10',
        'arp_command': 'show arp',
        'arp_parser_type': 'dell_force10',
        'arp_enabled': True,
        'mac_command': 'show mac-address-table',
        'mac_parser_type': 'dell_force10',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Dell Z9000系列 - Force10 DNOS9'
    },

    # ==================== Cisco Templates ====================

    # Cisco Catalyst 3650系列 - IOS-XE
    {
        'vendor': 'cisco',
        'model_pattern': 'c3650*',
        'device_type': 'cisco_ios',  # IOS-XE使用cisco_ios驱动
        'arp_command': 'show ip arp',
        'arp_parser_type': 'cisco_ios',
        'arp_enabled': True,
        'mac_command': 'show mac address-table',
        'mac_parser_type': 'cisco_ios',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Cisco Catalyst 3650系列 - IOS-XE'
    },

    # Cisco Catalyst 3560系列 - IOS
    {
        'vendor': 'cisco',
        'model_pattern': 'c3560*',
        'device_type': 'cisco_ios',
        'arp_command': 'show ip arp',
        'arp_parser_type': 'cisco_ios',
        'arp_enabled': True,
        'mac_command': 'show mac address-table',
        'mac_parser_type': 'cisco_ios',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Cisco Catalyst 3560系列 - IOS'
    },

    # Cisco Catalyst 2960系列 - IOS
    {
        'vendor': 'cisco',
        'model_pattern': 'c2960*',
        'device_type': 'cisco_ios',
        'arp_command': 'show ip arp',
        'arp_parser_type': 'cisco_ios',
        'arp_enabled': True,
        'mac_command': 'show mac address-table',
        'mac_parser_type': 'cisco_ios',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Cisco Catalyst 2960系列 - IOS'
    },

    # Cisco Nexus 9000系列 - NX-OS (高优先级，匹配 N9K-C* 型号)
    {
        'vendor': 'cisco',
        'model_pattern': 'n9k*',
        'device_type': 'cisco_nxos',
        'arp_command': 'show ip arp',
        'arp_parser_type': 'cisco_nxos',
        'arp_enabled': True,
        'mac_command': 'show mac address-table',
        'mac_parser_type': 'cisco_nxos',
        'mac_enabled': True,
        'priority': 210,
        'enabled': True,
        'description': 'Cisco Nexus 9000系列 - NX-OS'
    },

    # Cisco Nexus系列 - NX-OS
    {
        'vendor': 'cisco',
        'model_pattern': 'nx*',
        'device_type': 'cisco_nxos',
        'arp_command': 'show ip arp',
        'arp_parser_type': 'cisco_nxos',
        'arp_enabled': True,
        'mac_command': 'show mac address-table',
        'mac_parser_type': 'cisco_nxos',
        'mac_enabled': True,
        'priority': 200,
        'enabled': True,
        'description': 'Cisco Nexus系列 - NX-OS'
    },

    # Cisco通用IOS模板（低优先级，作为兜底）
    {
        'vendor': 'cisco',
        'model_pattern': '*',
        'device_type': 'cisco_ios',
        'arp_command': 'show ip arp',
        'arp_parser_type': 'cisco_ios',
        'arp_enabled': True,
        'mac_command': 'show mac address-table',
        'mac_parser_type': 'cisco_ios',
        'mac_enabled': True,
        'priority': 100,
        'enabled': True,
        'description': 'Cisco通用IOS模板'
    },

    # ==================== Juniper Templates ====================

    {
        'vendor': 'juniper',
        'model_pattern': '*',
        'device_type': 'juniper_junos',
        'arp_command': 'show arp',
        'arp_parser_type': 'juniper',
        'arp_enabled': True,
        'mac_command': 'show ethernet-switching table',
        'mac_parser_type': 'juniper',
        'mac_enabled': True,
        'priority': 150,
        'enabled': True,
        'description': 'Juniper JunOS通用模板'
    },
]


def get_collection_info(vendor: str, model: str) -> Dict:
    """
    获取指定厂商和型号的完整收集信息

    Returns:
        包含收集策略和模板信息的字典
    """
    strategy = CollectionStrategy.get_strategy(vendor, model)
    primary_method = CollectionStrategy.get_primary_method(vendor, model)

    # 查找匹配的CLI模板
    matching_template = None
    vendor_lower = vendor.lower() if vendor else ''
    model_lower = model.lower() if model else ''

    sorted_templates = sorted(OPTIMIZED_CLI_TEMPLATES, key=lambda t: t.get('priority', 100), reverse=True)

    for template in sorted_templates:
        if template['vendor'].lower() != vendor_lower:
            continue

        model_pattern = template['model_pattern'].lower()
        if model_pattern == '*':
            matching_template = template
            continue

        if model_pattern.replace('*', '') in model_lower:
            matching_template = template
            break

    return {
        'vendor': vendor,
        'model': model,
        'collection_strategy': strategy.value,
        'primary_method': primary_method,
        'cli_template': matching_template,
        'should_try_cli': CollectionStrategy.should_try_cli(vendor, model),
        'should_try_snmp': CollectionStrategy.should_try_snmp(vendor, model),
        'snmp_fallback_enabled': CollectionStrategy.should_fallback_to_snmp(vendor, model),
        'cli_fallback_enabled': CollectionStrategy.should_fallback_to_cli(vendor, model),
    }
