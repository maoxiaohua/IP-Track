"""
CLI Service for collecting data from network switches via SSH

This service uses SSH/CLI commands when SNMP is not available or insufficient.
Supports multiple vendor platforms through netmiko.
Dynamically loads command templates from database.
Implements self-learning command cache to optimize command selection.
"""

from typing import Dict, List, Optional
import re
from netmiko import ConnectHandler
from netmiko.ssh_dispatcher import CLASS_MAPPER
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from utils.logger import logger
from core.security import decrypt_password
from fnmatch import fnmatch


class CLIService:
    """Service for collecting data from switches via SSH CLI"""

    SUPPORTED_CLI_TRANSPORTS = {'ssh', 'telnet'}
    ENABLE_MODE_DEVICE_TYPES = {'cisco_ios', 'cisco_xe', 'dell_force10'}
    PAGING_DISABLE_COMMANDS = {
        'cisco_ios': ['terminal length 0'],
        'cisco_xe': ['terminal length 0'],
        'cisco_nxos': ['terminal length 0'],
        'dell_force10': ['terminal length 0'],
        'dell_os10': ['terminal length 0'],
        'juniper_junos': ['set cli screen-length 0'],
        'nokia_sros': ['environment more false'],
        'nokia_srl': ['environment more false'],
        'alcatel_aos': ['environment no more'],
        'arista_eos': ['terminal length 0'],
        'hp_procurve': ['no page'],
        'hp_comware': ['screen-length disable'],
        'huawei': ['screen-length 0 temporary'],
    }
    TELNET_DEVICE_TYPE_ALIASES = {
        'cisco_xe': 'cisco_ios_telnet',
        'cisco_nxos': 'generic_telnet',
        'dell_force10': 'generic_telnet',
        'dell_os10': 'generic_telnet',
        'nokia_srl': 'generic_telnet',
        'alcatel_aos': 'generic_telnet',
        'hp_comware': 'generic_telnet',
        'arista_eos': 'generic_telnet',
        'hp_procurve': 'generic_telnet',
        'huawei': 'generic_telnet',
    }

    def __init__(self):
        logger.info("CLI service initialized")

    def normalize_cli_transport(self, transport: Optional[str]) -> str:
        """Normalize CLI transport to a supported value."""
        normalized = (transport or 'ssh').strip().lower()
        if normalized not in self.SUPPORTED_CLI_TRANSPORTS:
            logger.warning(f"Unsupported CLI transport '{transport}', defaulting to SSH")
            return 'ssh'
        return normalized

    def default_port_for_transport(self, transport: Optional[str]) -> int:
        """Return the standard port for a given CLI transport."""
        return 23 if self.normalize_cli_transport(transport) == 'telnet' else 22

    def normalize_cli_connection_settings(
        self,
        transport: Optional[str],
        port: Optional[int],
        *,
        port_was_explicit: bool
    ) -> tuple[str, int]:
        """Normalize transport and choose a default port when the caller did not provide one."""
        normalized_transport = self.normalize_cli_transport(transport)
        if port_was_explicit and port:
            return normalized_transport, port
        return normalized_transport, self.default_port_for_transport(normalized_transport)

    def _base_device_type(self, device_type: Optional[str]) -> str:
        """Strip transport-specific suffixes from a Netmiko device type."""
        normalized = (device_type or 'cisco_ios').strip()
        for suffix in ('_telnet', '_ssh', '_serial'):
            if normalized.endswith(suffix):
                return normalized[:-len(suffix)]
        return normalized

    def _resolve_transport_device_type(self, device_type: Optional[str], transport: Optional[str]) -> str:
        """Resolve the Netmiko driver that matches the requested CLI transport."""
        normalized_transport = self.normalize_cli_transport(transport)
        requested_device_type = (device_type or 'cisco_ios').strip()

        if normalized_transport == 'ssh':
            return requested_device_type

        if requested_device_type.endswith('_telnet') and requested_device_type in CLASS_MAPPER:
            return requested_device_type

        base_device_type = self._base_device_type(requested_device_type)
        direct_telnet_driver = f"{base_device_type}_telnet"
        if direct_telnet_driver in CLASS_MAPPER:
            return direct_telnet_driver

        alias_driver = self.TELNET_DEVICE_TYPE_ALIASES.get(base_device_type)
        if alias_driver and alias_driver in CLASS_MAPPER:
            logger.warning(
                f"Using Telnet fallback driver '{alias_driver}' for device type '{base_device_type}'"
            )
            return alias_driver

        logger.warning(
            f"No vendor-specific Telnet driver for device type '{base_device_type}', using generic_telnet"
        )
        return 'generic_telnet'

    def _strip_ansi_codes(self, text: str) -> str:
        """
        Remove ANSI escape codes and control characters from text

        Args:
            text: Input text potentially containing ANSI codes

        Returns:
            Cleaned text without ANSI codes
        """
        if not text:
            return text

        # Pattern to match ANSI escape sequences
        # Matches patterns like: \x1B[...m, \x1B[?...h, \x1B[J, etc.
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def _should_use_timing_commands(self, device_type: Optional[str], transport: Optional[str]) -> bool:
        """Only Telnet needs timing reads; SSH devices use prompt-based reads.

        FTOS (dell_force10) 曾经强制走 send_command_timing，实测会在设备输出延迟时
        提前返回（只拿到命令回显），导致后续命令丢失首字符、拓扑解析为 0 条；
        send_command 等待提示符更可靠，失败时 _execute_command 仍会回退到 timing。
        """
        return self.normalize_cli_transport(transport) == 'telnet'

    def _disable_paging(
        self,
        connection: ConnectHandler,
        base_device_type: str,
        host: str
    ) -> None:
        """Best-effort pagination disable so long outputs do not stall on '--More--'."""
        commands = self.PAGING_DISABLE_COMMANDS.get(base_device_type, [])
        if not commands:
            return

        for command in commands:
            try:
                connection.send_command_timing(command, delay_factor=2, max_loops=50)
                logger.debug(f"Disabled paging on {host} using '{command}'")
                return
            except Exception as paging_error:
                logger.debug(
                    f"Paging disable command '{command}' failed on {host}: {str(paging_error)[:120]}"
                )

        logger.warning(f"Unable to disable paging on {host} for device type {base_device_type}")

    def _execute_command(
        self,
        connection: ConnectHandler,
        command: str,
        *,
        device_type: Optional[str],
        transport: Optional[str],
        read_timeout: int = 90,
        delay_factor: float = 2,
        max_loops: int = 150
    ) -> str:
        """Execute a CLI command with prompt-safe fallback handling."""
        if self._should_use_timing_commands(device_type, transport):
            return connection.send_command_timing(
                command,
                delay_factor=delay_factor,
                max_loops=max_loops,
            )

        try:
            return connection.send_command(command, read_timeout=read_timeout)
        except Exception as cmd_error:
            logger.debug(f"send_command failed, trying send_command_timing: {str(cmd_error)[:100]}")
            return connection.send_command_timing(
                command,
                delay_factor=delay_factor,
                max_loops=max_loops,
            )

    def _create_cli_connection(
        self,
        host: str,
        username: str,
        password: str,
        device_type: str = 'dell_os10',
        port: Optional[int] = None,
        timeout: int = 30,
        enable_secret: str = None,
        transport: str = 'ssh',
        raise_on_error: bool = False,
        banner_timeout: Optional[int] = None,
        auth_timeout: Optional[int] = None,
    ) -> Optional[ConnectHandler]:
        """
        Create CLI connection to network device.

        Args:
            host: Device IP address
            username: CLI username
            password: CLI password
            device_type: Device type (dell_os10, cisco_ios, etc.)
            port: CLI port
            timeout: Connection timeout in seconds
            enable_secret: Enable password (for Cisco/Dell Force10)
            transport: CLI transport ('ssh' or 'telnet')

        Returns:
            ConnectHandler object or None if connection fails
        """
        try:
            normalized_transport, resolved_port = self.normalize_cli_connection_settings(
                transport,
                port,
                port_was_explicit=port is not None
            )
            base_device_type = self._base_device_type(device_type)
            netmiko_device_type = self._resolve_transport_device_type(device_type, normalized_transport)
            device = {
                'device_type': netmiko_device_type,
                'host': host,
                'username': username,
                'password': password,
                'port': resolved_port,
                'timeout': timeout,
                'session_timeout': timeout,
                'conn_timeout': timeout,
            }
            # 仅调用方显式给出时生效：慢链路上放宽 SSH 握手/认证超时
            if banner_timeout:
                device['banner_timeout'] = banner_timeout
            if auth_timeout:
                device['auth_timeout'] = auth_timeout

            # Add enable secret if provided (for Cisco and Dell Force10)
            if enable_secret and base_device_type in self.ENABLE_MODE_DEVICE_TYPES:
                device['secret'] = enable_secret
                logger.debug(f"Enable password provided for {base_device_type} on {host}")
            elif base_device_type in self.ENABLE_MODE_DEVICE_TYPES:
                logger.warning(f"No enable password provided for {base_device_type} on {host} - commands may fail")

            logger.debug(
                f"Connecting to {host} via {normalized_transport.upper()} as {username} "
                f"using driver {netmiko_device_type}"
            )
            connection = ConnectHandler(**device)
            logger.info(f"✅ {normalized_transport.upper()} connection established to {host}")

            # Enable privileged mode for devices that require it
            if base_device_type in self.ENABLE_MODE_DEVICE_TYPES:
                try:
                    # For Dell Force10, use send_command_timing throughout to avoid prompt issues
                    if base_device_type == 'dell_force10':
                        # Check current prompt
                        prompt_output = connection.send_command_timing('', delay_factor=1)

                        if '#' not in prompt_output:
                            # Not in enable mode, enter it
                            logger.debug(f"Entering enable mode on Dell Force10 {host}")
                            if enable_secret:
                                connection.send_command_timing('enable', delay_factor=2)
                                connection.send_command_timing(enable_secret, delay_factor=2)
                                logger.debug(f"✅ Sent enable credentials to {host}")
                            else:
                                connection.send_command_timing('enable', delay_factor=2)
                                logger.debug(f"✅ Sent enable command to {host}")
                        else:
                            logger.debug(f"Already in enable mode on {host}")

                        # Disable paging so long MAC/ARP tables are not truncated at '--More--'.
                        try:
                            connection.send_command_timing('terminal length 0', delay_factor=2)
                            logger.debug(f"Disabled pagination on Dell Force10 {host}")
                        except Exception as paging_error:
                            logger.warning(
                                f"Failed to disable pagination on Dell Force10 {host}: {str(paging_error)[:100]}"
                            )

                    # For Cisco, use standard method
                    else:
                        connection.clear_buffer()
                        current_prompt = connection.find_prompt()

                        if '#' in current_prompt:
                            logger.debug(f"Already in enable mode on {host}")
                        elif enable_secret:
                            output = connection.send_command_timing('enable', delay_factor=2)
                            if 'assword' in output.lower():
                                output = connection.send_command_timing(enable_secret, delay_factor=2)
                                if '#' in output:
                                    logger.debug(f"✅ Entered enable mode on {host} (with password)")
                        else:
                            output = connection.send_command_timing('enable', delay_factor=2)
                            if '#' in output:
                                logger.debug(f"✅ Entered enable mode on {host} (no password)")

                        connection.clear_buffer()

                except Exception as e:
                    logger.warning(f"Enable mode attempt on {host} had issues (continuing anyway): {str(e)[:100]}")

            try:
                self._disable_paging(connection, base_device_type, host)
            except Exception as paging_error:
                logger.warning(f"Pagination disable attempt on {host} had issues: {str(paging_error)[:100]}")

            try:
                connection.clear_buffer()
            except Exception:
                pass

            return connection

        except Exception as e:
            normalized_transport = self.normalize_cli_transport(transport)
            logger.error(f"❌ {normalized_transport.upper()} connection failed to {host}: {str(e)}")
            # 拓扑采集需要把「为什么连不上」（认证失败/超时/不可达）写进状态与告警，
            # 仅返回 None 无法区分，调用方可按需要求抛出原始异常。
            if raise_on_error:
                raise
            return None

    def _create_ssh_connection(
        self,
        host: str,
        username: str,
        password: str,
        device_type: str = 'dell_os10',
        port: int = 22,
        timeout: int = 30,
        enable_secret: str = None,
        banner_timeout: Optional[int] = None,
        auth_timeout: Optional[int] = None,
    ) -> Optional[ConnectHandler]:
        """Backward-compatible wrapper for legacy SSH-only call sites."""
        return self._create_cli_connection(
            host=host,
            username=username,
            password=password,
            device_type=device_type,
            port=port,
            timeout=timeout,
            enable_secret=enable_secret,
            transport='ssh',
            banner_timeout=banner_timeout,
            auth_timeout=auth_timeout,
        )

    async def _get_cached_command(
        self,
        db: AsyncSession,
        switch_id: int,
        command_type: str
    ) -> Optional[Dict[str, str]]:
        """
        Get cached successful command for a switch

        Args:
            db: Database session
            switch_id: Switch ID
            command_type: 'arp' or 'mac'

        Returns:
            Dict with 'command' and 'parser_type' or None if not cached
        """
        try:
            from models.switch_command_cache import SwitchSuccessfulCommand

            result = await db.execute(
                select(SwitchSuccessfulCommand).where(
                    SwitchSuccessfulCommand.switch_id == switch_id,
                    SwitchSuccessfulCommand.command_type == command_type
                )
            )
            cached = result.scalar_one_or_none()

            if cached:
                logger.info(f"🎯 Found cached {command_type.upper()} command for switch {switch_id}: {cached.successful_command}")
                return {
                    'command': cached.successful_command,
                    'parser_type': cached.parser_type
                }

            return None

        except Exception as e:
            logger.debug(f"Cache lookup failed: {str(e)}")
            return None

    async def _cache_successful_command(
        self,
        db: AsyncSession,
        switch_id: int,
        command_type: str,
        command: str,
        parser_type: str
    ):
        """
        Cache a successful command for future use

        Args:
            db: Database session
            switch_id: Switch ID
            command_type: 'arp' or 'mac'
            command: The successful command
            parser_type: Parser type used
        """
        try:
            from models.switch_command_cache import SwitchSuccessfulCommand
            from sqlalchemy.dialects.postgresql import insert

            # Use INSERT ... ON CONFLICT to update if exists
            stmt = insert(SwitchSuccessfulCommand).values(
                switch_id=switch_id,
                command_type=command_type,
                successful_command=command,
                parser_type=parser_type
            )

            # Update if already exists
            stmt = stmt.on_conflict_do_update(
                index_elements=['switch_id', 'command_type'],
                set_={
                    'successful_command': command,
                    'parser_type': parser_type,
                    'success_count': SwitchSuccessfulCommand.success_count + 1,
                    'last_used_at': stmt.excluded.last_used_at
                }
            )

            await db.execute(stmt)
            await db.commit()

            logger.info(f"💾 Cached successful {command_type.upper()} command for switch {switch_id}: {command}")

        except Exception as e:
            logger.debug(f"Failed to cache command: {str(e)}")

    def _parse_dell_os10_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Dell OS10 'show mac address-table' output

        Example output:
        VlanId Mac Address            Type          Interface
        ---------------------------------------------------------------------------------
        1      8c:47:be:b1:54:49      dynamic       ethernet1/1/33
        1      8c:47:be:bc:9c:4a      dynamic       ethernet1/1/34
        """
        mac_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and separator lines
            if not line or 'VlanId' in line or '---' in line:
                continue

            # Parse line with pattern: VLAN MAC TYPE INTERFACE
            # Handle multiple spaces between fields
            parts = line.split()
            if len(parts) >= 4:
                vlan_id = parts[0]
                mac_address = parts[1]
                mac_type = parts[2]
                interface = parts[3]

                # Skip if not a valid MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Determine if dynamic or static
                is_dynamic = 1 if 'dynamic' in mac_type.lower() else 0

                mac_entries.append({
                    'mac_address': mac_address.lower(),
                    'port_name': interface,
                    'vlan_id': int(vlan_id) if vlan_id.isdigit() else None,
                    'is_dynamic': is_dynamic
                })

        return mac_entries

    def _parse_cisco_ios_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Cisco IOS 'show mac address-table' output

        Example output:
        Mac Address Table
        -------------------------------------------
        Vlan    Mac Address       Type        Ports
        ----    -----------       --------    -----
           1    0050.56a3.1234    DYNAMIC     Gi1/0/1
        """
        mac_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and separator lines
            if not line or 'Mac Address' in line or 'Vlan' in line or '---' in line or 'Total' in line:
                continue

            # Parse line
            parts = line.split()
            if len(parts) >= 4:
                vlan_id = parts[0]
                mac_address = parts[1]
                mac_type = parts[2]
                interface = parts[3]

                # Dell Force10 has space between interface type and port number
                # e.g., "Gi 1/17" or "Te 1/52" instead of "Gi1/17"
                # Check if next part looks like a port number (contains digits and /)
                if len(parts) >= 5 and ('/' in parts[4] or parts[4].isdigit()):
                    interface = parts[3] + ' ' + parts[4]

                # Convert Cisco MAC format (0050.56a3.1234) to standard format
                if '.' in mac_address:
                    mac_clean = mac_address.replace('.', '')
                    if len(mac_clean) == 12:
                        mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

                # Skip if not a valid MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                is_dynamic = 1 if 'dynamic' in mac_type.lower() else 0

                mac_entries.append({
                    'mac_address': mac_address.lower(),
                    'port_name': interface,
                    'vlan_id': int(vlan_id) if vlan_id.isdigit() else None,
                    'is_dynamic': is_dynamic
                })

        return mac_entries

    def _parse_cisco_nxos_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Cisco NX-OS 'show mac address-table' output.

        Example output:
        *  998     0007.3285.73b7   dynamic  0         F      F    Eth1/48
        """
        mac_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            if (
                not line
                or line.startswith('Legend:')
                or 'MAC Address' in line
                or 'Ports' in line
                or '----' in line
            ):
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            # NX-OS may prefix entries with markers like "*" or "+"
            if parts[0] in {'*', '+', '#', 'G', '(R)', 'O'}:
                parts = parts[1:]

            if len(parts) < 4:
                continue

            vlan_id = parts[0]
            mac_address = parts[1]
            mac_type = parts[2]
            interface = parts[-1]

            if '.' in mac_address and len(mac_address.replace('.', '')) == 12:
                mac_clean = mac_address.replace('.', '')
                mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

            if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                continue

            mac_entries.append({
                'mac_address': mac_address.lower(),
                'port_name': interface,
                'vlan_id': int(vlan_id) if vlan_id.isdigit() else None,
                'is_dynamic': 1 if 'dynamic' in mac_type.lower() else 0
            })

        return mac_entries

    def _parse_nokia_7220_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Nokia 7220 'show arpnd arp-entries' output

        Example output format:
        +-------------------+---------------+----------------+--------+---------------------+
        | Interface         | Subinterface  | Neighbor       | Origin | Link layer address  |
        +===================+===============+================+========+=====================+
        | ethernet-1/51     | 0             | 10.10.10.130  | dynamic| 8C:47:BE:B1:50:91   |
        | irb4              | 0             | 10.10.20.25   | dynamic| A8:1E:84:F3:C8:43   |

        Column order: Interface, Subinterface, Neighbor(IP), Origin, Link layer address(MAC)
        """
        arp_entries = []
        lines = output.split('\n')

        logger.debug(f"Parsing Nokia 7220 ARP output: {len(lines)} lines")
        logger.debug(f"First 1000 chars of output: {output[:1000]}")

        line_count = 0
        skipped_count = 0
        parsed_count = 0

        for line in lines:
            line_count += 1
            line_stripped = line.strip()

            # Skip headers, separators, summary lines, and empty lines
            if (not line_stripped or
                'Interface' in line or 'Subinterface' in line or
                'Neighbor' in line or 'Origin' in line or
                '---' in line or '===' in line or '+++' in line or
                'Total' in line or
                not line_stripped.startswith('|')):
                skipped_count += 1
                if line_count <= 10:
                    logger.debug(f"Skipping line {line_count}: {repr(line[:100])}")
                continue

            # Parse table row - format: | Interface | Subinterface | Neighbor(IP) | Origin | Link layer address(MAC) |
            parts = [p.strip() for p in line_stripped.split('|') if p.strip()]

            logger.debug(f"Line {line_count} has {len(parts)} parts: {parts[:6] if len(parts) > 6 else parts}")

            if len(parts) >= 5:
                interface = parts[0]           # ethernet-1/51, irb4, irb5
                subinterface = parts[1]        # 0
                ip_address = parts[2]          # 10.10.10.130
                origin = parts[3]              # dynamic
                mac_address = parts[4]         # 8C:47:BE:B1:50:91

                # Validate IP address format (basic check)
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                    logger.debug(f"Invalid IP format: {ip_address}")
                    continue

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    logger.debug(f"Invalid MAC format: {mac_address}")
                    continue

                # Extract VLAN from interface name if it's an IRB interface
                vlan_id = None
                if interface.startswith('irb'):
                    # irb4 -> VLAN 4, irb5 -> VLAN 5
                    vlan_match = re.search(r'irb(\d+)', interface)
                    if vlan_match:
                        vlan_id = int(vlan_match.group(1))

                arp_entries.append({
                    'ip_address': ip_address,
                    'mac_address': mac_address.lower(),
                    'vlan_id': vlan_id,
                    'interface': interface,
                    'age_seconds': None
                })
                parsed_count += 1
                logger.debug(f"✓ Parsed ARP entry: {ip_address} -> {mac_address} on {interface}")

        logger.info(f"Nokia 7220 ARP parsing: {line_count} total lines, {skipped_count} skipped, {parsed_count} parsed")
        return arp_entries

    def _parse_dell_os10_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Dell OS10 'show arp' output

        Example output:
        Address         Hardware address    Interface       Egress Interface
        ---------------------------------------------------------------------
        10.0.0.1        00:11:22:33:44:55   vlan100         ethernet1/1/1
        10.0.0.2        aa:bb:cc:dd:ee:ff   vlan200         ethernet1/1/2
        """
        arp_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and separator lines
            if not line or 'Address' in line or 'Hardware' in line or '---' in line or 'Total' in line:
                continue

            # Parse line with pattern: IP MAC INTERFACE EGRESS
            parts = line.split()
            if len(parts) >= 4:
                ip_address = parts[0]
                mac_address = parts[1]
                interface = parts[2]

                # Validate IP address format
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                    continue

                # Convert MAC format if needed
                if ':' in mac_address or '-' in mac_address:
                    mac_clean = mac_address.replace(':', '').replace('-', '')
                    if len(mac_clean) == 12:
                        mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Extract VLAN from interface if present (e.g., "vlan100")
                vlan_id = None
                if 'vlan' in interface.lower():
                    vlan_match = re.search(r'vlan(\d+)', interface, re.IGNORECASE)
                    if vlan_match:
                        vlan_id = int(vlan_match.group(1))

                arp_entries.append({
                    'ip_address': ip_address,
                    'mac_address': mac_address.lower(),
                    'vlan_id': vlan_id,
                    'interface': interface,
                    'age_seconds': None
                })

        return arp_entries

    def _parse_cisco_ios_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Cisco IOS 'show ip arp' output

        Example output:
        Protocol  Address          Age (min)  Hardware Addr   Type   Interface
        Internet  10.0.0.1                -   0011.2233.4455  ARPA   Vlan100
        Internet  10.0.0.2               45   aabb.ccdd.eeff  ARPA   Vlan200
        """
        arp_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and empty lines
            if not line or 'Protocol' in line or 'Address' in line or len(line) < 20:
                continue

            # Parse line
            parts = line.split()
            if len(parts) >= 5:
                protocol = parts[0]
                ip_address = parts[1]
                # age = parts[2]  # Can be '-' or a number
                mac_address = parts[3]
                # arp_type = parts[4]
                interface = parts[5] if len(parts) > 5 else None

                # Only process Internet protocol entries
                if protocol.lower() != 'internet':
                    continue

                # Validate IP address format
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                    continue

                # Convert Cisco MAC format (0011.2233.4455) to standard format
                if '.' in mac_address and len(mac_address.replace('.', '')) == 12:
                    mac_clean = mac_address.replace('.', '')
                    mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Extract VLAN from interface if present
                vlan_id = None
                if interface and 'vlan' in interface.lower():
                    vlan_match = re.search(r'vlan(\d+)', interface, re.IGNORECASE)
                    if vlan_match:
                        vlan_id = int(vlan_match.group(1))

                arp_entries.append({
                    'ip_address': ip_address,
                    'mac_address': mac_address.lower(),
                    'vlan_id': vlan_id,
                    'interface': interface,
                    'age_seconds': None
                })

        return arp_entries

    def _parse_cisco_nxos_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Cisco NX-OS 'show ip arp' output.

        Example output:
        Address         Age       MAC Address     Interface
        10.10.10.1    00:05:44  e4f0.0428.7d80  Vlan998
        """
        arp_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            if (
                not line
                or line.startswith('Flags:')
                or line.startswith('IP ARP Table')
                or line.startswith('Total number of entries:')
                or 'MAC Address' in line
                or '---' in line
            ):
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            ip_address = parts[0]
            age = parts[1]
            mac_address = parts[2]
            interface = parts[3]

            if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                continue

            if '.' in mac_address and len(mac_address.replace('.', '')) == 12:
                mac_clean = mac_address.replace('.', '')
                mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

            if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                continue

            vlan_id = None
            if 'vlan' in interface.lower():
                vlan_match = re.search(r'vlan(\d+)', interface, re.IGNORECASE)
                if vlan_match:
                    vlan_id = int(vlan_match.group(1))

            arp_entries.append({
                'ip_address': ip_address,
                'mac_address': mac_address.lower(),
                'vlan_id': vlan_id,
                'interface': interface,
                'age_seconds': None if age == '-' else None
            })

        return arp_entries

    def _parse_dell_force10_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Dell Force10 (FTOS) 'show arp' output

        Example output:
        Protocol    Address         Age(min)  Hardware Address    Interface      VLAN             CPU
        ---------------------------------------------------------------------------------------------
        Internet    10.10.10.134        63   8c:47:be:b1:50:95   Fo 1/51         -               CP
        Internet    10.10.20.161         -   68:4f:64:fb:58:79        -         Vl 999           CP
        Internet    10.10.30.36         22   00:0e:c6:66:52:1c   Te 1/5         Vl 7             CP

        Note: Dell Force10 format is similar to Cisco IOS but:
        - MAC address uses colon format (aa:bb:cc:dd:ee:ff) instead of dot format
        - Interface may have space (e.g., "Te 1/5" or "Fo 1/51")
        - VLAN column is separate (not part of interface name)
        """
        arp_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers, separators, and empty lines
            if not line or 'Protocol' in line or 'Address' in line or '---' in line or len(line) < 20:
                continue

            # Parse line
            parts = line.split()
            if len(parts) >= 5:
                protocol = parts[0]
                ip_address = parts[1]
                # age = parts[2]  # Can be '-' or a number
                mac_address = parts[3]
                interface_part1 = parts[4] if len(parts) > 4 else None

                # Only process Internet protocol entries
                if protocol.lower() != 'internet':
                    continue

                # Validate IP address format
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                    continue

                # Dell Force10 uses colon format (aa:bb:cc:dd:ee:ff)
                # But also accepts dot format in some cases
                if '.' in mac_address and ':' not in mac_address:
                    # Convert dot format to colon format
                    mac_clean = mac_address.replace('.', '')
                    if len(mac_clean) == 12:
                        mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

                # Validate MAC address format (colon-separated)
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Dell Force10 interfaces may have space: "Te 1/5" → parts[4]="Te", parts[5]="1/5"
                interface = interface_part1
                if len(parts) > 5 and ('/' in parts[5] or parts[5].isdigit()):
                    interface = interface_part1 + ' ' + parts[5]

                # Extract VLAN from dedicated VLAN column (e.g., "Vl 999")
                # VLAN column is usually after interface column
                vlan_id = None
                for part in parts[5:]:  # Check columns after interface
                    if part.lower().startswith('vl'):
                        # Format: "Vl999" or "Vl 999"
                        vlan_match = re.search(r'vl\s*(\d+)', part, re.IGNORECASE)
                        if vlan_match:
                            vlan_id = int(vlan_match.group(1))
                            break
                    elif part.isdigit() and int(part) < 4096:  # Valid VLAN range
                        vlan_id = int(part)
                        break

                # Also check if interface itself contains VLAN info (e.g., "Vlan999")
                if not vlan_id and interface and 'vlan' in interface.lower():
                    vlan_match = re.search(r'vlan(\d+)', interface, re.IGNORECASE)
                    if vlan_match:
                        vlan_id = int(vlan_match.group(1))

                arp_entries.append({
                    'ip_address': ip_address,
                    'mac_address': mac_address.lower(),
                    'vlan_id': vlan_id,
                    'interface': interface,
                    'age_seconds': None
                })

        return arp_entries

    def _parse_dell_force10_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Dell Force10 (FTOS) 'show mac-address-table' output

        Example output:
        VlanId  Mac Address         Type      Interface
        ------  -----------------   -------   -----------------------
        7       00:0e:c6:66:52:1c   Dynamic   Te 1/5
        999     a4:ed:43:60:35:9f   Dynamic   Te 1/48

        Note: Dell Force10 format similar to Cisco but:
        - MAC uses colon format (not dot format like Cisco)
        - Interface may have space between type and port number
        """
        mac_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and separator lines
            if not line or 'Mac Address' in line or 'VlanId' in line or '---' in line or 'Total' in line:
                continue

            # Parse line
            parts = line.split()
            if len(parts) >= 4:
                vlan_id = parts[0]
                mac_address = parts[1]
                mac_type = parts[2]
                interface = parts[3]

                # Dell Force10 interface may have space: "Te 1/5" → parts[3]="Te", parts[4]="1/5"
                if len(parts) >= 5 and ('/' in parts[4] or parts[4].isdigit()):
                    interface = parts[3] + ' ' + parts[4]

                # Dell Force10 already uses colon format
                # But also convert dot format if present
                if '.' in mac_address and ':' not in mac_address:
                    mac_clean = mac_address.replace('.', '')
                    if len(mac_clean) == 12:
                        mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                is_dynamic = 1 if 'dynamic' in mac_type.lower() else 0

                mac_entries.append({
                    'mac_address': mac_address.lower(),
                    'port_name': interface,
                    'vlan_id': int(vlan_id) if vlan_id.isdigit() else None,
                    'is_dynamic': is_dynamic
                })

        return mac_entries

    def _parse_nokia_7220_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Nokia 7220 'show network-instance bridge-table mac-table all' output

        Only parse MAC entries under "Mac-table of network instance macvlan***"
        Ignore entries under "mac-vrf-****" (VXLAN interconnect)

        Example output format:
        Mac-table of network instance macvlan999
        | 50:E0:EF:A4:E0:93  | irb-interface    | 0  | irb-interface | true | N/A | ...
        | D8:97:3B:85:3C:B1  | ethernet-1/13.0  | 13 | learnt        | true | 263 | ...
        """
        mac_entries = []
        lines = output.split('\n')

        logger.debug(f"Parsing Nokia 7220 MAC output: {len(lines)} lines")
        logger.debug(f"First 1000 chars of output: {output[:1000]}")

        current_instance = None
        in_mac_table = False
        line_count = 0
        parsed_count = 0

        for line in lines:
            line_count += 1
            line_stripped = line.strip()

            # Detect network instance section
            if 'Mac-table of network instance' in line:
                # Extract the full instance name for VLAN extraction
                match = re.search(r'Mac-table of network instance\s+(\S+)', line)
                if match:
                    instance_name = match.group(1)
                    # Support both macvlan and mac-vrf instances
                    if 'macvlan' in instance_name.lower() or 'mac-vrf' in instance_name.lower():
                        current_instance = instance_name
                        in_mac_table = True
                        logger.debug(f"Entering network instance section: {instance_name}")
                    else:
                        current_instance = None
                        in_mac_table = False
                        logger.debug(f"Unknown instance type: {instance_name}")
                continue

            # Skip if not in a valid network instance section
            if not in_mac_table or not current_instance:
                continue

            # Skip headers, separators, summary lines, and empty lines
            if (not line_stripped or
                'Address' in line or 'Destination' in line or
                '---' in line or '===' in line or '+++' in line or
                'Total' in line or
                not line_stripped.startswith('|')):
                continue

            # Parse table row - format: | MAC | Destination | Index | Type | ...
            # Split by | and strip whitespace
            parts = [p.strip() for p in line_stripped.split('|') if p.strip()]

            if line_count <= 20 and len(parts) > 0:
                logger.debug(f"Line {line_count} has {len(parts)} parts: {parts[:5] if len(parts) > 5 else parts}")

            if len(parts) >= 4:
                mac_address = parts[0]
                destination = parts[1]
                dest_index = parts[2]
                mac_type = parts[3]

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    logger.debug(f"Invalid MAC format: {mac_address}")
                    continue

                # Skip irb-interface entries (router interfaces)
                if 'irb' in destination.lower():
                    logger.debug(f"Skipping IRB interface: {destination}")
                    continue

                # Extract ethernet port name
                if 'ethernet' in destination.lower():
                    # Extract VLAN from network instance name if available
                    vlan_id = None
                    if current_instance:
                        # Try to extract VLAN number from:
                        # - "macvlan999" -> 999
                        # - "mac-vrf-999" -> 999
                        vlan_match = re.search(r'(?:macvlan|mac-vrf-)(\d+)', current_instance)
                        if vlan_match:
                            vlan_id = int(vlan_match.group(1))

                    mac_entries.append({
                        'mac_address': mac_address.lower(),
                        'port_name': destination,
                        'vlan_id': vlan_id,
                        'is_dynamic': 1 if 'learnt' in mac_type.lower() else 0
                    })
                    parsed_count += 1
                    logger.debug(f"✓ Parsed MAC entry: {mac_address} -> {destination} (VLAN {vlan_id})")

        logger.info(f"Nokia 7220 MAC parsing: {line_count} total lines, {parsed_count} parsed")
        return mac_entries

    def _parse_nokia_7250_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Nokia 7250 'show router arp' output

        Example output:
        IP Address      HW Address        Type   Interface         Age
        -------------------------------------------------------------------------------
        10.10.20.1     4c:62:cd:37:f4:3d Dynamic  ies-vlan235       0d 00:00:23
        10.10.20.2     c8:f7:50:5c:96:c1 Dynamic  ies-vlan235       0d 00:00:13
        """
        arp_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and separator lines
            if not line or 'IP Address' in line or '---' in line or '===' in line:
                continue

            # Parse line with pattern: IP MAC TYPE INTERFACE AGE
            parts = line.split()
            if len(parts) >= 4:
                ip_address = parts[0]
                mac_address = parts[1]
                mac_type = parts[2]
                interface = parts[3]

                # Validate IP address format
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                    continue

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                arp_entries.append({
                    'ip_address': ip_address,
                    'mac_address': mac_address.lower(),
                    'vlan_id': None,  # VLAN extracted from interface name if needed
                    'interface': interface,
                    'age_seconds': 0
                })

        return arp_entries

    def _parse_nokia_7250_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Nokia 7250 'show service fdb-mac' output

        Example output:
        ServId     MAC               Source-Identifier       Type     Last Change
                   Transport:Tnl-Id                         Age
        -------------------------------------------------------------------------------
        236        96:db:56:32:48:64 sap:1/1/c4/1:236        L/30     02/28/26 03:25:47
        295        0c:7c:28:23:5f:a7 sap:1/1/c2/1:295        L/0      02/04/26 09:12:23

        Source-Identifier format: sap:PORT:VLAN
        Example: sap:1/1/c4/1:236 means port 1/1/c4/1, VLAN 236
        """
        mac_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers, separator lines, and empty lines
            if (not line or
                'ServId' in line or 'MAC' in line or
                '---' in line or '===' in line or
                'Transport' in line or 'Age' in line):
                continue

            # Parse line with pattern: SERVID MAC SOURCE-ID TYPE DATE
            parts = line.split()
            if len(parts) >= 3:
                servid = parts[0]  # This is the VLAN ID
                mac_address = parts[1]
                source_identifier = parts[2]

                # Validate MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Skip CPM entries (control plane)
                if 'cpm' in source_identifier.lower():
                    continue

                # Extract port from source_identifier
                # Format: sap:1/1/c4/1:236 or sap:1/1/c2/1:295
                port_name = None
                if source_identifier.startswith('sap:'):
                    # Remove 'sap:' prefix
                    sap_info = source_identifier[4:]
                    # Split by last ':' to separate port from VLAN
                    # e.g., "1/1/c4/1:236" -> port="1/1/c4/1", vlan="236"
                    if ':' in sap_info:
                        port_name = sap_info.rsplit(':', 1)[0]

                # Skip if no valid port extracted
                if not port_name:
                    continue

                try:
                    vlan_id = int(servid)
                except ValueError:
                    vlan_id = None

                mac_entries.append({
                    'mac_address': mac_address.lower(),
                    'port_name': port_name,
                    'vlan_id': vlan_id,
                    'is_dynamic': 1  # Assume dynamic by default for 7250
                })

        return mac_entries

    def _parse_nokia_7250_system_info(self, output: str) -> Dict[str, str]:
        """
        Parse Nokia/Alcatel 'show system information' output
        Enhanced version supporting 7220, 7250, WBX220, and other variants

        Extracts:
        - System Name: hostname
        - System Type: model
        - System Version: software version

        Example output formats supported:
        1. Standard: "System Name            : hostname"
        2. Compact: "System Name: hostname"
        3. With prefix: "System Name : A:mxh@hostname"

        Returns:
            Dict with keys: hostname, model, version
        """
        import re
        
        result = {
            'hostname': None,
            'model': None,
            'version': None
        }

        try:
            lines = output.strip().split('\n')

            for line in lines:
                line = line.strip()

                # Match System Name with flexible pattern (case-insensitive, flexible separator)
                name_match = re.search(r'System\s+Name\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if name_match:
                    hostname = name_match.group(1).strip()

                    # Strip ANSI control characters first
                    hostname = self._strip_ansi_codes(hostname)

                    # Remove common prefixes: "A:mxh@hostname", "*A:hostname", "A:hostname", "B:hostname"
                    if '@' in hostname:
                        hostname = hostname.split('@', 1)[1]
                    elif hostname.startswith('*A:'):
                        hostname = hostname[3:]
                    elif hostname.startswith('A:'):
                        hostname = hostname[2:]
                    elif hostname.startswith('B:'):
                        hostname = hostname[2:]

                    # Remove any remaining leading/trailing special characters
                    hostname = hostname.strip(' :')

                    # Validate hostname: must be at least 2 chars and alphanumeric with allowed chars
                    # Valid hostname chars: letters, digits, hyphens, underscores, dots
                    # Also reject if it still contains control characters
                    if (hostname and
                        len(hostname) >= 2 and
                        not hostname.strip() in [':', '-', '_', '.'] and
                        any(c.isalnum() for c in hostname) and
                        not any(ord(c) < 32 for c in hostname)):  # Reject control characters
                        result['hostname'] = hostname
                        logger.debug(f"Extracted hostname: {hostname}")
                    else:
                        logger.warning(f"Invalid hostname extracted: '{hostname}', skipping")

                # Match System Type (model)
                type_match = re.search(r'System\s+Type\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if type_match:
                    model = type_match.group(1).strip()
                    if model:
                        result['model'] = model
                        logger.debug(f"Extracted model: {model}")

                # Match System Version
                version_match = re.search(r'System\s+Version\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if version_match:
                    version = version_match.group(1).strip()
                    if version:
                        result['version'] = version
                        logger.debug(f"Extracted version: {version}")

            logger.info(f"Parsed Nokia/Alcatel system info: {result}")

        except Exception as e:
            logger.error(f"Error parsing Nokia/Alcatel system info: {str(e)}")

        return result

    def _parse_juniper_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Juniper 'show arp' output

        Example output:
        MAC Address       Address         Name                      Interface           Flags
        00:11:22:33:44:55 10.0.0.1        10.0.0.1                  vlan.100            none
        aa:bb:cc:dd:ee:ff 10.0.0.2        10.0.0.2                  vlan.200            none
        """
        arp_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers and separator lines
            if not line or 'MAC Address' in line or 'Address' in line or '---' in line or 'Total' in line:
                continue

            # Parse line with pattern: MAC IP NAME INTERFACE FLAGS
            parts = line.split()
            if len(parts) >= 4:
                mac_address = parts[0]
                ip_address = parts[1]
                interface = parts[3]

                # Validate IP address format
                if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_address):
                    continue

                # Validate and normalize MAC address
                if ':' in mac_address or '-' in mac_address:
                    mac_clean = mac_address.replace(':', '').replace('-', '')
                    if len(mac_clean) == 12:
                        mac_address = ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])

                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Extract VLAN from interface if present (e.g., "vlan.100")
                vlan_id = None
                if 'vlan' in interface.lower():
                    vlan_match = re.search(r'vlan\.?(\d+)', interface, re.IGNORECASE)
                    if vlan_match:
                        vlan_id = int(vlan_match.group(1))

                arp_entries.append({
                    'ip_address': ip_address,
                    'mac_address': mac_address.lower(),
                    'vlan_id': vlan_id,
                    'interface': interface,
                    'age_seconds': None
                })

        return arp_entries

    def _parse_juniper_mac_table(self, output: str) -> List[Dict]:
        """
        Parse Juniper 'show ethernet-switching table' output

        Example output:
        MAC flags (S - static MAC, D - dynamic MAC, L - locally learned, P - Persistent static
                   SE - statistics enabled, NM - non configured MAC, R - remote PE MAC, O - ovsdb MAC)

        Ethernet switching table : 2 entries, 2 learned
        Routing instance : default-switch
            Vlan                MAC                 MAC      Logical                NH        RTR
            name                address             flags    interface              Index     ID
            vlan100             00:11:22:33:44:55   D        ge-0/0/1.0             0         0
            vlan200             aa:bb:cc:dd:ee:ff   D        ge-0/0/2.0             0         0
        """
        mac_entries = []
        lines = output.split('\n')

        for line in lines:
            line = line.strip()
            # Skip headers, separator lines, and informational lines
            if (not line or
                'MAC flags' in line or
                'Ethernet switching table' in line or
                'Routing instance' in line or
                'Vlan' in line and 'MAC' in line and 'address' in line or
                '---' in line):
                continue

            # Parse line with pattern: VLAN MAC FLAGS INTERFACE NH RTR
            parts = line.split()
            if len(parts) >= 4:
                vlan_name = parts[0]
                mac_address = parts[1]
                mac_flags = parts[2]
                interface = parts[3]

                # Skip if not a valid MAC address format
                if not re.match(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$', mac_address):
                    continue

                # Extract VLAN ID from vlan name (e.g., "vlan100" -> 100)
                vlan_id = None
                vlan_match = re.search(r'vlan(\d+)', vlan_name, re.IGNORECASE)
                if vlan_match:
                    vlan_id = int(vlan_match.group(1))
                elif vlan_name.isdigit():
                    vlan_id = int(vlan_name)

                # Determine if dynamic or static
                is_dynamic = 1 if 'D' in mac_flags else 0

                mac_entries.append({
                    'mac_address': mac_address.lower(),
                    'port_name': interface,
                    'vlan_id': vlan_id,
                    'is_dynamic': is_dynamic
                })

        return mac_entries

    # ==================== Arista EOS Parsers ====================

    def _parse_arista_eos_arp_table(self, output: str) -> List[Dict]:
        """Parse Arista EOS 'show ip arp' output (similar to Cisco IOS format).

        Example:
        Address         Age (min)  Hardware Addr   Interface
        10.1.1.1        30         aabb.ccdd.eeff  Ethernet1
        """
        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or 'Address' in line or '---' in line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                ip = parts[0]
                mac = parts[2] if len(parts) > 2 else ''
                if not re.match(r'^\d+\.\d+\.\d+\.\d+$', ip):
                    continue
                mac = mac.replace('.', '').lower()
                if len(mac) == 12:
                    mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
                if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac):
                    continue
                interface = parts[3] if len(parts) > 3 else ''
                entries.append({'ip_address': ip, 'mac_address': mac, 'vlan_id': None, 'interface': interface})
        return entries

    def _parse_arista_eos_mac_table(self, output: str) -> List[Dict]:
        """Parse Arista EOS 'show mac address-table' output (similar to Cisco IOS).

        Example:
        Vlan    Mac Address       Type        Ports
        ----    -----------       ----        -----
        100     aabb.ccdd.eeff    DYNAMIC     Et1
        """
        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or 'Mac Address' in line or '---' in line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                vlan = parts[0]
                mac = parts[1].replace('.', '').lower()
                if len(mac) == 12:
                    mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
                if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac):
                    continue
                is_dynamic = 1 if 'dynamic' in parts[2].lower() else 0
                port = parts[3]
                entries.append({'mac_address': mac, 'port_name': port, 'vlan_id': int(vlan) if vlan.isdigit() else None, 'is_dynamic': is_dynamic})
        return entries

    # ==================== HPE ProCurve Parsers ====================

    def _parse_hpe_procurve_arp_table(self, output: str) -> List[Dict]:
        """Parse HPE ProCurve 'show arp' output.

        Example:
        IP ARP table
        IP Address     MAC Address       Type    Port
        -------------  ----------------- ------- ----------
        10.1.1.1       aabbcc-ddeeff     dynamic 1
        """
        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or 'IP Address' in line or '---' in line:
                continue
            parts = line.split()
            if len(parts) >= 3 and re.match(r'^\d+\.\d+\.\d+\.\d+$', parts[0]):
                ip = parts[0]
                mac = parts[1].replace('-', '').lower()
                if len(mac) == 12:
                    mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
                if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac):
                    continue
                interface = parts[3] if len(parts) > 3 else ''
                entries.append({'ip_address': ip, 'mac_address': mac, 'vlan_id': None, 'interface': interface})
        return entries

    def _parse_hpe_procurve_mac_table(self, output: str) -> List[Dict]:
        """Parse HPE ProCurve 'show mac-address' output.

        Example:
        Status and Counters - Port Address Table
        MAC Address     Located on Port
        -------------   ---------------
        aabbcc-ddeeff   1
        """
        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or 'MAC Address' in line or '---' in line or 'Status' in line:
                continue
            parts = line.split()
            if len(parts) >= 2 and re.match(r'^[0-9a-fA-F-]+$', parts[0]):
                mac = parts[0].replace('-', '').lower()
                if len(mac) == 12:
                    mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
                if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac):
                    continue
                port = parts[1]
                entries.append({'mac_address': mac, 'port_name': port, 'vlan_id': None, 'is_dynamic': 1})
        return entries

    # ==================== Huawei VRP Parsers ====================

    def _parse_huawei_vrp_arp_table(self, output: str) -> List[Dict]:
        """Parse Huawei VRP 'display arp all' output.

        Example:
        IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE INTERFACE      VPN-INSTANCE
        10.1.1.1        aabb-ccdd-eeff  19        D     GE0/0/1       --
        """
        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or 'IP ADDRESS' in line or '---' in line:
                continue
            parts = line.split()
            if len(parts) >= 4 and re.match(r'^\d+\.\d+\.\d+\.\d+$', parts[0]):
                ip = parts[0]
                mac = parts[1].replace('-', '').lower()
                if len(mac) == 12:
                    mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
                if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac):
                    continue
                interface = parts[4] if len(parts) > 4 else ''
                vlan = parts[5] if len(parts) > 5 and parts[5].isdigit() else None
                entries.append({'ip_address': ip, 'mac_address': mac, 'vlan_id': int(vlan) if vlan else None, 'interface': interface})
        return entries

    def _parse_huawei_vrp_mac_table(self, output: str) -> List[Dict]:
        """Parse Huawei VRP 'display mac-address' output.

        Example:
        MAC Address    VLAN/VSI          Learned-From        Type
        aabb-ccdd-eeff 100/-             GE0/0/1             dynamic
        """
        entries = []
        for line in output.split('\n'):
            line = line.strip()
            if not line or 'MAC Address' in line or '---' in line:
                continue
            parts = line.split()
            if len(parts) >= 3 and re.match(r'^[0-9a-fA-F-]+$', parts[0]):
                mac = parts[0].replace('-', '').lower()
                if len(mac) == 12:
                    mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
                if not re.match(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$', mac):
                    continue
                vlan_str = parts[1].split('/')[0] if '/' in parts[1] else parts[1]
                vlan = int(vlan_str) if vlan_str.isdigit() else None
                port = parts[2]
                is_dynamic = 1 if len(parts) > 3 and 'dynamic' in parts[3].lower() else 0
                entries.append({'mac_address': mac, 'port_name': port, 'vlan_id': vlan, 'is_dynamic': is_dynamic})
        return entries

    # ==================== H3C Comware Parsers ====================

    @staticmethod
    def _normalize_h3c_mac(value: str) -> Optional[str]:
        """Comware 的 aabb-ccdd-eeff / aa:bb:cc:dd:ee:ff 统一成 aa:bb:cc:dd:ee:ff。"""
        compact = re.sub(r'[-:.]', '', (value or '').strip().lower())
        if len(compact) != 12 or not re.fullmatch(r'[0-9a-f]{12}', compact):
            return None
        return ':'.join(compact[i:i + 2] for i in range(0, 12, 2))

    @staticmethod
    def _looks_like_h3c_interface(token: str) -> bool:
        """Comware 接口名（GE1/0/1、Ten-GigabitEthernet1/0/25、Port-channel1）。

        不能直接用 topology_utils.looks_like_port：它的前缀上限 16 字符，
        Ten-GigabitEthernet 这类长接口名会漏判；而它又会匹配裸数字，
        把 VLAN 列误当成端口。这里要求「字母前缀 + 数字」或纯数字的分层形式。
        """
        return bool(re.match(r'^(?:[A-Za-z][A-Za-z\-]*\d+(?:[/:\.]\d+)*|\d+(?:[/\.]\d+)+)$', token))

    def _parse_h3c_comware_arp_table(self, output: str) -> List[Dict]:
        """
        Parse H3C Comware 'display arp' / 'display arp all'.

        V5:  IP address  MAC address  VLAN ID   Port Name   Aging Type
        V7:  IP address  MAC address  VLAN/VSI name  Interface  Aging Type

        VLAN/VSI 列在部分 V7 设备上是 VSI 名称而非数字，接口列也可能因版本
        不同落在第 3 或第 4 列，所以先取第 3 列当 VLAN（数字才收），再从
        后续列里找第一个像接口的 token；找不到时说明该版本没有 VLAN 列。
        """
        entries = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or 'mac address' in line.lower() or line.startswith('---'):
                continue
            parts = line.split()
            if len(parts) < 4 or not re.match(r'^\d+\.\d+\.\d+\.\d+$', parts[0]):
                continue
            mac = self._normalize_h3c_mac(parts[1])
            if not mac:
                continue
            vlan = int(parts[2]) if parts[2].isdigit() else None
            interface = ''
            for token in parts[3:]:
                if self._looks_like_h3c_interface(token):
                    interface = token
                    break
            if not interface and self._looks_like_h3c_interface(parts[2]):
                # 少数版本没有 VLAN 列，接口直接落在第 3 列
                interface = parts[2]
            entries.append({
                'ip_address': parts[0],
                'mac_address': mac,
                'vlan_id': vlan,
                'interface': interface or '',
            })
        return entries

    def _parse_h3c_comware_mac_table(self, output: str) -> List[Dict]:
        """
        Parse H3C Comware 'display mac-address'.

        V5:  MAC Address  VLAN ID   State    Port/Nickname   Aging
        V7:  MAC Address  VLAN/VSI  Learned-From  Type

        VLAN/VSI 是第 2 列（数字才是 VLAN），端口在其后；找不到时说明该
        版本没有 VLAN 列。
        """
        entries = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or 'mac address' in line.lower() or line.startswith('---'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            mac = self._normalize_h3c_mac(parts[0])
            if not mac:
                continue
            vlan = int(parts[1]) if parts[1].isdigit() else None
            port = None
            for token in parts[2:]:
                if self._looks_like_h3c_interface(token):
                    port = token
                    break
            if not port and self._looks_like_h3c_interface(parts[1]):
                # 少数版本没有 VLAN 列，端口直接落在第 2 列
                port = parts[1]
            if not port:
                # 多端口安全、黑洞表项等没有端口，跳过
                continue
            joined = ' '.join(parts[1:]).lower()
            entries.append({
                'mac_address': mac,
                'port_name': port,
                'vlan_id': vlan,
                'is_dynamic': 1 if ('learned' in joined or 'dynamic' in joined) else 0,
            })
        return entries

    _H3C_LLDP_LABELS = ('system name', 'local interface', 'chassis id', 'port id')

    def _parse_h3c_comware_lldp(self, output: str) -> List[Dict]:
        """
        Parse H3C Comware LLDP 邻居。

        1. `display lldp neighbor-information list` 表格：列序随版本变化，
           按表头各列起始字符位置切片取值；
        2. `display lldp neighbor-information verbose` 块形态：
           `LLDP neighbor-information of port 25[XGE1/0/25]:`（V7）
           或 `LLDP neighbor information on port GE1/0/1:` + `字段 : 值`。
        """
        entries = self._parse_h3c_lldp_table(output)
        if entries:
            return entries
        entries = self._parse_h3c_lldp_verbose(output)
        if entries:
            return entries
        return self._parse_generic_lldp_table(output)

    def _parse_h3c_lldp_table(self, output: str) -> List[Dict]:
        from services.topology_utils import looks_like_port

        lines = output.splitlines()
        header_idx = None
        ordered = []
        for idx, raw_line in enumerate(lines):
            lowered = raw_line.lower()
            if 'local interface' not in lowered or 'chassis id' not in lowered:
                continue
            positions = sorted(
                (lowered.find(label), label)
                for label in self._H3C_LLDP_LABELS if lowered.find(label) >= 0
            )
            if len(positions) < 3:
                continue
            ordered = [
                (label, start, positions[i + 1][0] if i + 1 < len(positions) else None)
                for i, (start, label) in enumerate(positions)
            ]
            header_idx = idx
            break
        if header_idx is None:
            return []

        entries = []
        for raw_line in lines[header_idx + 1:]:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(('---', '===', 'Total')):
                if entries:
                    break
                continue
            fields = {
                label: (raw_line[start:end].strip() if end else raw_line[start:].strip())
                for label, start, end in ordered
            }
            local_port = fields.get('local interface')
            if not local_port or not looks_like_port(local_port):
                continue
            entries.append(self._build_neighbor_entry(
                'lldp',
                local_port_id=local_port,
                remote_sys_name=fields.get('system name') or None,
                remote_chassis_id=fields.get('chassis id') or None,
                remote_port_id=fields.get('port id') or None,
            ))
        return entries

    def _parse_h3c_lldp_verbose(self, output: str) -> List[Dict]:
        entries: List[Dict] = []
        local_port = None
        current: Dict = {}

        def flush():
            if current.get('remote_chassis_id') or current.get('remote_sys_name'):
                entries.append(self._build_neighbor_entry('lldp', local_port_id=local_port, **current))
            current.clear()

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # 真实 Comware 形态：`LLDP neighbor-information of port 25[XGE1/0/25]:`
            port_match = re.search(
                r'neighbor[- ]information\s+of\s+port\s+\d+\s*\[([^\]]+)\]',
                line, re.IGNORECASE
            )
            if not port_match:
                port_match = re.search(
                    r'neighbor information on (?:port|interface)\s+(\S+?):?$',
                    line, re.IGNORECASE
                )
            if port_match:
                flush()
                local_port = port_match.group(1).rstrip(':')
                continue
            if ':' not in line:
                continue
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip() or None
            if key == 'chassis id':
                current['remote_chassis_id'] = value
            elif key == 'port id':
                current['remote_port_id'] = value
            elif key in ('port description', 'interface description'):
                current['remote_port_desc'] = value
            elif key == 'system name':
                current['remote_sys_name'] = value
            elif key == 'system description':
                current['remote_sys_desc'] = value
        flush()
        return entries

    def _parse_h3c_system_info(self, output: str) -> Dict[str, str]:
        """Parse H3C Comware 'display version' output.

        V7 example:
            H3C Comware Software, Version 7.1.070, Release 3506P10
            H3C S5560X-30C-EI uptime is 12 weeks, 3 days, 4 hours, 5 minutes
        V5 example:
            Comware Software, Version 5.20.99, Release 2221P02
            H3C S5500-28C-EI uptime is 0 week, 0 day, 0 hour, 0 minute
        """
        result = {'hostname': None, 'model': None, 'version': None}
        try:
            text = self._strip_ansi_codes(output or '')

            # 版本行：优先带 "Comware Software" 的行，避免误取 Boot/System image 行
            version_match = re.search(
                r'Comware\s+Software,\s*Version\s+([0-9][^\s,]*)'
                r'(?:\s*,?\s*Release\s+(\S+))?',
                text, re.IGNORECASE
            )
            if not version_match:
                version_match = re.search(
                    r'Version\s+([0-9][^\s,]*)(?:\s*,?\s*Release\s+(\S+))?',
                    text, re.IGNORECASE
                )
            if version_match:
                version = version_match.group(1).strip()
                if version_match.group(2):
                    version = f"{version} Release {version_match.group(2).strip()}"
                result['version'] = version

            # 型号行："H3C S5560X-30C-EI uptime is ..." 或 "... with 1 Processor"
            model_match = re.search(
                r'^(?:H3C|HP)\s+(\S+)\s+uptime\s+is\b', text, re.IGNORECASE | re.MULTILINE
            )
            if not model_match:
                model_match = re.search(
                    r'^(?:H3C|HP)\s+(\S+)\s+with\s+\d+\s+Processor',
                    text, re.IGNORECASE | re.MULTILINE
                )
            if model_match:
                result['model'] = model_match.group(1).strip()

            # 'display version' 本身不含 sysname，兼容带配置/提示符回显的输出
            hostname_match = re.search(r'^\s*sysname\s+(\S+)', text, re.IGNORECASE | re.MULTILINE)
            if not hostname_match:
                hostname_match = re.search(r'^[<\[]~?([A-Za-z0-9._-]{2,63})[>\]]\s*$', text, re.MULTILINE)
            if hostname_match:
                hostname = hostname_match.group(1).strip()
                if not any(ord(c) < 32 for c in hostname):
                    result['hostname'] = hostname

            logger.info(f"Parsed H3C system info: {result}")
        except Exception as e:
            logger.error(f"Error parsing H3C system info: {str(e)}")
        return result

    def _parse_h3c_transceiver(self, output: str) -> List[Dict]:
        """Parse H3C Comware 'display transceiver interface' / 'manuinfo' output.

        Example:
            GigabitEthernet1/0/1 transceiver information:
              Transceiver Type           : 1000_BASE_SX_SFP
              Vendor Name                : H3C
              Vendor Part Number         : SFP-GE-SX-MM850-A
              Serial Number              : 210231A1234567
        """
        modules: List[Dict] = []
        current_port = None
        fields: Dict[str, str] = {}

        def flush():
            if not current_port:
                return
            type_hint = fields.get('transceiver type', '')
            model = fields.get('vendor part number') or fields.get('part number')
            serial = fields.get('serial number')
            if not (type_hint or model or serial):
                # 端口存在但没有模块（"The transceiver is absent"）时不落库
                return
            module_type = self._identify_module_type(type_hint)
            if module_type in ('Unknown', 'Transceiver'):
                module_type = self._infer_module_type_from_port_name(current_port)
            modules.append({
                'port_name': current_port,
                'model': model,
                'vendor': fields.get('vendor name') or fields.get('manufacturer name'),
                'serial_number': serial,
                'module_type': module_type,
                'speed_gbps': (
                    self._extract_speed_gbps(type_hint)
                    or self._extract_speed_gbps(current_port)
                ),
            })

        try:
            for raw_line in output.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                header = re.search(
                    r'^(\S+)\s+transceiver(?:\s+manufacture)?\s+information\s*:\s*$',
                    line, re.IGNORECASE
                )
                if header:
                    flush()
                    current_port = header.group(1).strip()
                    fields = {}
                    continue
                if current_port and ':' in line:
                    key, value = line.split(':', 1)
                    key = ' '.join(key.strip().lower().split())
                    value = value.strip().rstrip(',') or None
                    if value:
                        fields[key] = value
            flush()
        except Exception as e:
            logger.error(f"Error parsing H3C transceiver output: {str(e)}")
        return modules

    def _parse_juniper_system_info(self, output: str) -> Dict[str, str]:
        """
        Parse Juniper 'show system information' output

        Example output:
        Hostname:                      ex-switch-01
        Model:                         ex4200-48t
        Junos:                         12.3R12.4
        ...
        """
        import re

        result = {
            'hostname': None,
            'model': None,
            'version': None
        }

        try:
            lines = output.strip().split('\n')

            for line in lines:
                line = line.strip()

                # Match Hostname
                hostname_match = re.search(r'Hostname\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if hostname_match:
                    hostname = hostname_match.group(1).strip()
                    # Strip ANSI control characters
                    hostname = self._strip_ansi_codes(hostname)
                    # Validate: at least 2 chars, no control characters
                    if (hostname and len(hostname) >= 2 and
                        not any(ord(c) < 32 for c in hostname)):
                        result['hostname'] = hostname
                        logger.debug(f"Extracted hostname: {hostname}")

                # Match Model
                model_match = re.search(r'Model\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if model_match:
                    model = model_match.group(1).strip()
                    if model:
                        result['model'] = model
                        logger.debug(f"Extracted model: {model}")

                # Match Junos version
                version_match = re.search(r'Junos\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if version_match:
                    version = version_match.group(1).strip()
                    if version:
                        result['version'] = version
                        logger.debug(f"Extracted version: {version}")

            logger.info(f"Parsed Juniper system info: {result}")

        except Exception as e:
            logger.error(f"Error parsing Juniper system info: {str(e)}")

        return result

    def _parse_dell_system_info(self, output: str) -> Dict[str, str]:
        """
        Parse Dell OS10 'show version' output

        Example output:
        Dell EMC Networking OS10 Enterprise
        Copyright (c) 1999-2019 by Dell Inc. All Rights Reserved.
        OS Version: 10.5.1.0
        Build Version: 10.5.1.0.124
        Build Time: 2019-08-27T21:30:00+0000
        System Type: S4048-ON
        Architecture: x86_64
        ...
        """
        import re

        result = {
            'hostname': None,
            'model': None,
            'version': None
        }

        try:
            lines = output.strip().split('\n')

            for line in lines:
                line = line.strip()

                # Match System Type (model) - e.g., "System Type: S4048-ON"
                model_match = re.search(r'System\s+Type\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if model_match:
                    model = model_match.group(1).strip()
                    if model:
                        result['model'] = model
                        logger.debug(f"Extracted Dell model: {model}")

                # 版本行各 NOS 写法不同：OS10 是 "OS Version:"，FTOS/OS9 是
                # "Software Version:"（有时带结尾句点），都收下并去掉尾部标点。
                version_match = re.search(
                    r'(?:OS|Software|System|Firmware)\s+Version\s*[:=]\s*(\S+)',
                    line, re.IGNORECASE
                )
                if version_match:
                    version = version_match.group(1).strip().rstrip('.,;')
                    if version:
                        result['version'] = version
                        logger.debug(f"Extracted Dell version: {version}")

                # Match hostname from "Hostname:" line if present
                hostname_match = re.search(r'(?:Host[- ]?name|System\s+Name)\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if hostname_match:
                    hostname = hostname_match.group(1).strip()
                    # Strip ANSI control characters
                    hostname = self._strip_ansi_codes(hostname)
                    # Validate: at least 2 chars, no control characters
                    if (hostname and len(hostname) >= 2 and
                        not any(ord(c) < 32 for c in hostname)):
                        result['hostname'] = hostname
                        logger.debug(f"Extracted Dell hostname: {hostname}")

            # FTOS/OS9 的 'show version' 里通常没有 Hostname 行，主机名只能从命令行提示符
            # （"switch# show version" 或末尾的 "switch#"）里取。
            if not result['hostname']:
                prompt_match = re.search(
                    r'^\s*([A-Za-z0-9][A-Za-z0-9._-]{1,62})\s*[#>]\s*(?:show\b.*)?$',
                    output,
                    re.MULTILINE
                )
                if prompt_match:
                    candidate = prompt_match.group(1).strip()
                    if (candidate and len(candidate) >= 2 and
                        not any(ord(c) < 32 for c in candidate)):
                        result['hostname'] = candidate
                        logger.debug(f"Extracted Dell hostname from prompt: {candidate}")

            logger.info(f"Parsed Dell system info: {result}")

        except Exception as e:
            logger.error(f"Error parsing Dell system info: {str(e)}")

        return result

    def _parse_cisco_system_info(self, output: str) -> Dict[str, str]:
        """
        Parse Cisco IOS 'show version' output

        Example output:
        Cisco IOS Software, C3750 Software (C3750-IPSERVICESK9-M), Version 12.2(55)SE12, RELEASE SOFTWARE (fc1)
        Technical Support: http://www.cisco.com/techsupport
        Copyright (c) 1986-2016 by Cisco Systems, Inc.
        Compiled Mon 06-Jun-16 12:37 by prod_rel_team

        ROM: Bootstrap program is C3750 boot loader
        BOOTLDR: C3750 Boot Loader (C3750-HBOOT-M) Version 12.2(44)SE5, RELEASE SOFTWARE (fc1)

        switch uptime is 1 year, 2 weeks, 3 days, 4 hours, 5 minutes
        System returned to ROM by power-on
        System image file is "flash:/c3750-ipservicesk9-mz.122-55.SE12.bin"

        cisco WS-C3750G-24TS-1U (PowerPC405) processor (revision K0) with 131072K bytes of memory.
        Processor board ID FOC1234X5YZ
        ...
        """
        import re

        result = {
            'hostname': None,
            'model': None,
            'version': None
        }

        try:
            lines = output.strip().split('\n')

            for line in lines:
                line = line.strip()

                # Match version - e.g., "Cisco IOS Software, ..., Version 12.2(55)SE12, ..."
                version_match = re.search(r'(?:Version|IOS.*Version)\s+([0-9]+\.[0-9]+[^\s,]+)', line, re.IGNORECASE)
                if version_match and not result['version']:
                    version = version_match.group(1).strip()
                    if version:
                        result['version'] = version
                        logger.debug(f"Extracted Cisco version: {version}")

                # Match model - e.g., "cisco WS-C3750G-24TS-1U (PowerPC405) processor"
                model_match = re.search(r'cisco\s+(WS-[^\s(]+|C[0-9]+[^\s(]+|[A-Z]{2,3}[0-9]+[^\s(]+)', line, re.IGNORECASE)
                if model_match and not result['model']:
                    model = model_match.group(1).strip()
                    if model:
                        result['model'] = model
                        logger.debug(f"Extracted Cisco model: {model}")

                # Alternative model match - e.g., "System Type: catalyst 3750"
                alt_model_match = re.search(r'(?:System\s+Type|Model)\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if alt_model_match and not result['model']:
                    model = alt_model_match.group(1).strip()
                    if model:
                        result['model'] = model
                        logger.debug(f"Extracted Cisco model (alt): {model}")

                # Match hostname if present (less common in show version, but try anyway)
                hostname_match = re.search(r'(?:Host[- ]?name|System\s+Name)\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if hostname_match:
                    hostname = hostname_match.group(1).strip()
                    # Strip ANSI control characters
                    hostname = self._strip_ansi_codes(hostname)
                    # Validate: at least 2 chars, no control characters
                    if (hostname and len(hostname) >= 2 and
                        not any(ord(c) < 32 for c in hostname)):
                        result['hostname'] = hostname
                        logger.debug(f"Extracted Cisco hostname: {hostname}")

            logger.info(f"Parsed Cisco system info: {result}")

        except Exception as e:
            logger.error(f"Error parsing Cisco system info: {str(e)}")

        return result

    def collect_mac_table_cli(
        self,
        switch_ip: str,
        switch_config: Dict,
        templates: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Collect MAC address table via SSH CLI using database templates or built-in fallbacks

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SSH credentials and vendor info
            templates: Optional list of command templates from database

        Returns:
            List of MAC entries: [{mac, port_name, vlan, is_dynamic}, ...]
        """
        connection = None
        try:
            # Decrypt password
            password = decrypt_password(switch_config['password_encrypted'])

            # Decrypt enable password if present
            enable_secret = None
            if switch_config.get('enable_password_encrypted'):
                enable_secret = decrypt_password(switch_config['enable_password_encrypted'])

            # Get vendor, model, and name
            vendor = switch_config.get('vendor', '')
            model = switch_config.get('model', '')
            name = switch_config.get('name', '')

            # Find matching template (with builtin fallback)
            template = self._find_matching_template(vendor, model, name, templates)

            if not template:
                # This should rarely happen now that we have builtin fallback
                logger.error(f"No command template found (even in builtins) for {vendor} {model} (name: {name})")
                return []

            if not template.get('mac_enabled', False) or not template.get('mac_command'):
                logger.info(f"MAC CLI collection not enabled for {vendor} {model}")
                return []

            # Get parser
            parser_type = template.get('mac_parser_type')
            parser = self._get_parser(parser_type, 'mac')
            if not parser:
                logger.warning(f"No MAC parser found for type: {parser_type}")
                return []

            # Create CLI connection (with enable password if available)
            transport = switch_config.get('cli_transport', 'ssh')
            device_type = template.get('device_type')
            connection = self._create_cli_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=device_type,
                port=switch_config.get('ssh_port'),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret,
                transport=transport
            )

            if not connection:
                logger.error(f"Failed to establish CLI connection to {switch_ip}")
                return []

            # Try main command first
            command = template['mac_command']
            logger.info(f"Executing MAC command on {switch_ip}: {command}")

            try:
                output = self._execute_command(
                    connection,
                    command,
                    device_type=device_type,
                    transport=transport,
                    read_timeout=90,
                    delay_factor=4 if self._base_device_type(device_type) == 'dell_force10' else 3,
                    max_loops=200,
                )

                # Debug: Log command output for troubleshooting
                logger.debug(f"MAC command output from {switch_ip} ({len(output)} chars):\n{output[:500]}")

                mac_entries = parser(output)

                if mac_entries:
                    logger.info(f"✅ Collected {len(mac_entries)} MAC entries from {switch_ip} via CLI (main command)")
                    return mac_entries
                else:
                    logger.warning(f"Main MAC command returned 0 entries from {switch_ip} ({vendor} {model}), trying fallback commands...")
                    logger.warning(f"First 2000 chars of output:\n{output[:2000]}")
            except Exception as e:
                logger.warning(f"Main MAC command failed on {switch_ip}: {str(e)}, trying fallback commands...")

            # Try fallback commands if main command failed or returned no data
            fallback_commands = template.get('fallback_commands')
            if fallback_commands:
                try:
                    import json
                    fallback_list = json.loads(fallback_commands)

                    for fallback in fallback_list:
                        fallback_cmd = fallback.get('command')
                        fallback_parser_type = fallback.get('parser')

                        if not fallback_cmd:
                            continue

                        logger.info(f"Trying fallback command on {switch_ip}: {fallback_cmd}")

                        try:
                            output = self._execute_command(
                                connection,
                                fallback_cmd,
                                device_type=device_type,
                                transport=transport,
                                read_timeout=90,
                                delay_factor=3,
                                max_loops=200,
                            )

                            # Try specified parser or use main parser
                            fallback_parser = self._get_parser(fallback_parser_type, 'mac') if fallback_parser_type else parser
                            if fallback_parser:
                                mac_entries = fallback_parser(output)

                                if mac_entries:
                                    logger.info(f"✅ Collected {len(mac_entries)} MAC entries from {switch_ip} via fallback command: {fallback_cmd}")
                                    return mac_entries
                        except Exception as e:
                            logger.debug(f"Fallback command '{fallback_cmd}' failed: {str(e)}")
                            continue

                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in fallback_commands for {switch_ip}")
                except Exception as e:
                    logger.warning(f"Error processing fallback commands: {str(e)}")

            logger.warning(f"All MAC commands failed or returned 0 entries for {switch_ip}")

            # Dell Force10 (FTOS) fallback → retry with OS10 driver
            if device_type == 'dell_force10':
                logger.info(f"Dell Force10 returned 0 MAC entries from {switch_ip}, retrying with OS10 driver...")
                if connection:
                    try:
                        connection.disconnect()
                    except Exception:
                        pass
                    connection = None

                os10_conn = self._create_cli_connection(
                    host=switch_ip,
                    username=switch_config['username'],
                    password=password,
                    device_type='dell_os10',
                    port=switch_config.get('ssh_port'),
                    timeout=switch_config.get('connection_timeout', 30),
                    enable_secret=enable_secret,
                    transport=transport
                )
                if os10_conn:
                    connection = os10_conn  # For cleanup in finally
                    try:
                        os10_output = self._execute_command(
                            os10_conn,
                            command,
                            device_type='dell_os10',
                            transport=transport,
                            read_timeout=90,
                            delay_factor=4,
                            max_loops=200,
                        )
                        os10_parser = self._get_parser('dell_os10', 'mac')
                        if os10_parser:
                            os10_entries = os10_parser(os10_output)
                            if os10_entries:
                                logger.info(
                                    f"✅ Collected {len(os10_entries)} MAC entries from {switch_ip}"
                                    f" via CLI (OS10 fallback)"
                                )
                                return os10_entries
                            else:
                                logger.warning(
                                    f"OS10 MAC fallback parsed 0 entries from {switch_ip}. "
                                    f"Output sample (first 1000 chars):\n{os10_output[:1000]}"
                                )
                    except Exception as os10_err:
                        logger.warning(f"OS10 MAC fallback failed on {switch_ip}: {str(os10_err)[:200]}")

            return []

        except Exception as e:
            logger.error(f"Failed to collect MAC table via CLI from {switch_ip}: {str(e)}")
            return []

        finally:
            if connection:
                try:
                    connection.disconnect()
                    logger.debug(f"CLI connection closed to {switch_ip}")
                except Exception:
                    pass

    def _match_from_template_list(
        self,
        vendor: str,
        model: str,
        name: str,
        template_list: List[Dict]
    ) -> Optional[Dict]:
        """
        Match switch against a list of templates

        Args:
            vendor: Switch vendor
            model: Switch model
            name: Switch name
            template_list: List of template dicts to search

        Returns:
            Matching template dict or None
        """
        vendor_lower = vendor.lower()
        model_lower = model.lower()
        name_lower = name.lower()

        # Sort by priority (descending)
        sorted_templates = sorted(template_list, key=lambda t: t.get('priority', 100), reverse=True)

        for template in sorted_templates:
            if not template.get('enabled', True):
                continue

            # Check vendor match
            if template['vendor'].lower() != vendor_lower:
                continue

            # Check model pattern match
            model_pattern = template['model_pattern'].lower()
            if '*' in model_pattern or '?' in model_pattern:
                if not fnmatch(model_lower, model_pattern) and not fnmatch(name_lower, model_pattern):
                    continue
            else:
                if model_pattern not in model_lower and model_pattern not in name_lower:
                    continue

            # Check name pattern if specified
            name_pattern = template.get('name_pattern')
            if name_pattern:
                name_pattern_lower = name_pattern.lower()
                if '*' in name_pattern_lower or '?' in name_pattern_lower:
                    if not fnmatch(name_lower, name_pattern_lower):
                        continue
                else:
                    if name_pattern_lower not in name_lower:
                        continue

            return template

        return None

    def _find_matching_template(
        self,
        vendor: str,
        model: str,
        name: str,
        templates: Optional[List[Dict]] = None
    ) -> Optional[Dict]:
        """
        Find matching command template for a switch with builtin fallback

        Args:
            vendor: Switch vendor
            model: Switch model
            name: Switch name
            templates: Optional list of templates from database

        Returns:
            Matching template dict or None
        """
        match_details = self.preview_template_match(vendor, model, name, templates)
        if match_details:
            return match_details['template']
        return None

    def preview_template_match(
        self,
        vendor: str,
        model: str,
        name: str = '',
        templates: Optional[List[Dict]] = None
    ) -> Optional[Dict]:
        """
        Explain which template would match a given switch identity.

        Returns:
            {
                'source': 'database' | 'builtin',
                'template': { ...template fields... }
            }
            or None if nothing matches.
        """
        # Try database templates first if provided
        if templates:
            matched_template = self._match_from_template_list(vendor, model, name, templates)
            if matched_template:
                logger.debug(f"Matched database template for {vendor} {model}")
                return {
                    'source': 'database',
                    'template': dict(matched_template),
                }
            logger.debug(f"No match in database templates for {vendor} {model}, trying builtin templates")

        builtin_templates = self._get_builtin_templates()
        matched_template = self._match_from_template_list(vendor, model, name, builtin_templates)

        if matched_template:
            logger.debug(f"Matched builtin template for {vendor} {model}: {matched_template.get('device_type')}")
            return {
                'source': 'builtin',
                'template': dict(matched_template),
            }

        logger.warning(f"No template found (database or builtin) for {vendor} {model}")
        return None

    def _get_builtin_templates(self) -> List[Dict]:
        """
        Get built-in fallback templates

        Returns:
            List of built-in template dicts
        """
        # Import optimized templates from collection_strategy
        try:
            from config.collection_strategy import OPTIMIZED_CLI_TEMPLATES
            return OPTIMIZED_CLI_TEMPLATES
        except ImportError:
            logger.warning("Could not import optimized templates, using fallback")
            try:
                from config.collection_strategy import apply_topology_defaults
            except ImportError:
                apply_topology_defaults = None
            # Fallback to basic templates
            fallback_templates = [
                {
                    'vendor': 'alcatel',
                    'model_pattern': '7220*',
                    'device_type': 'nokia_srl',
                    'arp_command': 'show arpnd arp-entries',
                    'arp_parser_type': 'nokia_7220',
                    'arp_enabled': True,
                    'mac_command': 'show network-instance bridge-table mac-table all',
                    'mac_parser_type': 'nokia_7220',
                    'mac_enabled': True,
                    'priority': 200,
                    'enabled': True
                },
                {
                    'vendor': 'alcatel',
                    'model_pattern': '7250*',
                    'device_type': 'nokia_sros',
                    'arp_command': 'show router arp',
                    'arp_parser_type': 'nokia_7250',
                    'arp_enabled': True,
                    'mac_command': 'show service fdb-mac',
                    'mac_parser_type': 'nokia_7250',
                    'mac_enabled': True,
                    'priority': 200,
                    'enabled': True
                },
                {
                    'vendor': 'dell',
                    'model_pattern': 's*',
                    'device_type': 'dell_force10',
                    'arp_command': 'show arp',
                    'arp_parser_type': 'dell_force10',
                    'arp_enabled': True,
                    'mac_command': 'show mac address-table',
                    'mac_parser_type': 'dell_force10',
                    'mac_enabled': True,
                    'priority': 160,
                    'enabled': True
                },
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
                    'priority': 150,
                    'enabled': True
                },
            ]
            return apply_topology_defaults(fallback_templates) if apply_topology_defaults else fallback_templates

    def collect_arp_table_cli(
        self,
        switch_ip: str,
        switch_config: Dict,
        templates: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Collect ARP table via SSH CLI using database templates or built-in fallbacks

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SSH credentials and vendor info
            templates: Optional list of command templates from database

        Returns:
            List of ARP entries: [{ip_address, mac_address, vlan_id, interface}, ...]
        """
        connection = None
        try:
            # Decrypt password
            password = decrypt_password(switch_config['password_encrypted'])

            # Decrypt enable password if present
            enable_secret = None
            if switch_config.get('enable_password_encrypted'):
                enable_secret = decrypt_password(switch_config['enable_password_encrypted'])

            # Get vendor, model, and name
            vendor = switch_config.get('vendor', '')
            model = switch_config.get('model', '')
            name = switch_config.get('name', '')

            # Find matching template (with builtin fallback)
            template = self._find_matching_template(vendor, model, name, templates)

            if not template:
                # This should rarely happen now that we have builtin fallback
                logger.error(f"No command template found (even in builtins) for {vendor} {model} (name: {name})")
                return []

            if not template.get('arp_enabled', False) or not template.get('arp_command'):
                logger.info(f"ARP CLI collection not enabled for {vendor} {model}")
                return []

            # Get parser
            parser_type = template.get('arp_parser_type')
            parser = self._get_parser(parser_type, 'arp')
            if not parser:
                logger.warning(f"No ARP parser found for type: {parser_type}")
                return []

            # Create CLI connection (with enable password if available)
            transport = switch_config.get('cli_transport', 'ssh')
            device_type = template.get('device_type', '')
            connection = self._create_cli_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=device_type,
                port=switch_config.get('ssh_port'),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret,
                transport=transport
            )

            if not connection:
                logger.error(f"Failed to establish CLI connection to {switch_ip}")
                return []

            # Try main command first
            command = template['arp_command']
            logger.info(f"Executing ARP command on {switch_ip}: {command}")

            try:
                # Clear buffer before sending command to flush any residual data
                # from the SSH handshake / enable-mode sequence
                try:
                    connection.clear_buffer()
                except Exception:
                    pass

                # Dell Force10 (FTOS) devices have prompt-detection timing issues
                # that cause send_command to drop the first character of the command.
                # Use send_command_timing (delay-based) instead to avoid this.
                output = self._execute_command(
                    connection,
                    command,
                    device_type=device_type,
                    transport=transport,
                    read_timeout=90,
                    delay_factor=4 if self._base_device_type(device_type) == 'dell_force10' else 3,
                    max_loops=200,
                )

                arp_entries = parser(output)

                # Debug: Log output if parsing returns 0 results (all vendors)
                if not arp_entries:
                    logger.warning(f"ARP '{command}' parsing returned 0 entries for {switch_ip} ({vendor} {model}). Output sample (first 2000 chars):\n{output[:2000]}")

                if arp_entries:
                    logger.info(f"✅ Collected {len(arp_entries)} ARP entries from {switch_ip} via CLI (main command)")
                    return arp_entries
                else:
                    logger.warning(f"Main ARP command returned 0 entries from {switch_ip}, trying fallback commands...")
            except Exception as e:
                logger.warning(f"Main ARP command failed on {switch_ip}: {str(e)}, trying fallback commands...")

            # Try fallback commands if main command failed or returned no data
            arp_fallback_commands = template.get('arp_fallback_commands')
            if arp_fallback_commands:
                try:
                    import json
                    fallback_list = json.loads(arp_fallback_commands)

                    for fallback in fallback_list:
                        fallback_cmd = fallback.get('command')
                        fallback_parser_type = fallback.get('parser')

                        if not fallback_cmd:
                            continue

                        logger.info(f"Trying ARP fallback command on {switch_ip}: {fallback_cmd}")

                        try:
                            output = self._execute_command(
                                connection,
                                fallback_cmd,
                                device_type=device_type,
                                transport=transport,
                                read_timeout=90,
                                delay_factor=3,
                                max_loops=200,
                            )

                            # Try specified parser or use main parser
                            fallback_parser = self._get_parser(fallback_parser_type, 'arp') if fallback_parser_type else parser
                            if fallback_parser:
                                arp_entries = fallback_parser(output)

                                if arp_entries:
                                    logger.info(f"✅ Collected {len(arp_entries)} ARP entries from {switch_ip} via fallback command: {fallback_cmd}")
                                    return arp_entries
                        except Exception as e:
                            logger.debug(f"ARP fallback command '{fallback_cmd}' failed: {str(e)}")
                            continue

                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in arp_fallback_commands for {switch_ip}")
                except Exception as e:
                    logger.warning(f"Error processing ARP fallback commands: {str(e)}")

            logger.warning(f"All ARP commands failed or returned 0 entries for {switch_ip}")

            # Dell Force10 (FTOS) fallback → retry with OS10 driver
            if device_type == 'dell_force10':
                logger.info(f"Dell Force10 returned 0 ARP entries from {switch_ip}, retrying with OS10 driver...")
                if connection:
                    try:
                        connection.disconnect()
                    except Exception:
                        pass
                    connection = None

                os10_conn = self._create_cli_connection(
                    host=switch_ip,
                    username=switch_config['username'],
                    password=password,
                    device_type='dell_os10',
                    port=switch_config.get('ssh_port'),
                    timeout=switch_config.get('connection_timeout', 30),
                    enable_secret=enable_secret,
                    transport=transport
                )
                if os10_conn:
                    connection = os10_conn  # For cleanup in finally
                    try:
                        os10_output = self._execute_command(
                            os10_conn,
                            command,
                            device_type='dell_os10',
                            transport=transport,
                            read_timeout=90,
                            delay_factor=4,
                            max_loops=200,
                        )
                        os10_parser = self._get_parser('dell_os10', 'arp')
                        if os10_parser:
                            os10_entries = os10_parser(os10_output)
                            if os10_entries:
                                logger.info(
                                    f"✅ Collected {len(os10_entries)} ARP entries from {switch_ip}"
                                    f" via CLI (OS10 fallback)"
                                )
                                return os10_entries
                            else:
                                logger.warning(
                                    f"OS10 ARP fallback parsed 0 entries from {switch_ip}. "
                                    f"Output sample (first 1000 chars):\n{os10_output[:1000]}"
                                )
                    except Exception as os10_err:
                        logger.warning(f"OS10 ARP fallback failed on {switch_ip}: {str(os10_err)[:200]}")

            return []

        except Exception as e:
            logger.error(f"Failed to collect ARP table via CLI from {switch_ip}: {str(e)}")
            return []

        finally:
            if connection:
                try:
                    connection.disconnect()
                    logger.debug(f"CLI connection closed to {switch_ip}")
                except Exception:
                    pass

    def get_device_info_cli(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[Dict[str, str]]:
        """
        Get device information via CLI (hostname, model, version)

        Currently supports:
        - Nokia/Alcatel series (using 'show system information')
        - Juniper switches (using 'show system information')
        - Dell OS10 switches (using 'show version')
        - Cisco IOS switches (using 'show version')

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SSH credentials and vendor info

        Returns:
            Dict with keys: hostname, model, version or None if failed
        """
        connection = None
        try:
            vendor = switch_config.get('vendor', '').lower()
            model = switch_config.get('model', '').lower()

            # Determine command and parser based on vendor/model
            command = None
            parser = None

            # Nokia/Alcatel series (7220, 7250, WBX220, etc)
            if vendor == 'alcatel':
                command = 'show system information'
                parser = self._parse_nokia_7250_system_info

            # Juniper series
            elif vendor == 'juniper':
                command = 'show system information'
                parser = self._parse_juniper_system_info

            # Dell OS10 series
            elif vendor == 'dell':
                command = 'show version'
                parser = self._parse_dell_system_info

            # Cisco IOS series
            elif vendor == 'cisco':
                command = 'show version'
                parser = self._parse_cisco_system_info

            # H3C Comware 系列（不支持 'show version'，必须用 'display version'）
            elif vendor == 'h3c':
                command = 'display version'
                parser = self._parse_h3c_system_info

            if not command or not parser:
                logger.debug(f"No device info CLI command available for {vendor} {model}")
                return None

            # Decrypt password
            password = decrypt_password(switch_config['password_encrypted'])
            transport = switch_config.get('cli_transport', 'ssh')

            # Establish CLI connection
            device_type = switch_config.get('device_type')
            if not device_type:
                device_type = 'hp_comware' if vendor == 'h3c' else 'nokia_sros'
            enable_secret = None
            if switch_config.get('enable_password_encrypted'):
                enable_secret = decrypt_password(switch_config['enable_password_encrypted'])
            connection = self._create_cli_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=device_type,
                port=switch_config.get('ssh_port'),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret,
                transport=transport
            )

            if not connection:
                logger.error(f"Failed to establish CLI connection to {switch_ip}")
                return None

            # Execute command
            logger.info(f"Executing device info command on {switch_ip}: {command}")
            output = self._execute_command(
                connection,
                command,
                device_type=device_type,
                transport=transport,
                read_timeout=60,
                delay_factor=3 if self.normalize_cli_transport(transport) == 'telnet' else 2,
                max_loops=200 if self.normalize_cli_transport(transport) == 'telnet' else 150,
            )

            # Parse output
            device_info = parser(output)

            logger.info(f"Retrieved device info from {switch_ip}: {device_info}")
            return device_info

        except Exception as e:
            logger.error(f"Failed to get device info via CLI from {switch_ip}: {str(e)}")
            return None

        finally:
            if connection:
                try:
                    connection.disconnect()
                    logger.debug(f"CLI connection closed to {switch_ip}")
                except Exception:
                    pass

    def fetch_running_config(
        self,
        switch_ip: str,
        switch_config: Dict,
        device_type: str,
        command: str
    ) -> str:
        """
        只读拉取设备配置文本（供配置备份模块使用）。

        严格只读：只执行调用方给出的 show/display 类命令，绝不调用
        save_config()/config_mode()，也不向设备下发任何写配置命令。
        连接或命令失败时抛出原始异常，由调用方记录失败原因。
        """
        connection = None
        transport = switch_config.get('cli_transport', 'ssh')
        try:
            password = decrypt_password(switch_config['password_encrypted'])
            enable_secret = None
            if switch_config.get('enable_password_encrypted'):
                enable_secret = decrypt_password(switch_config['enable_password_encrypted'])

            connection = self._create_cli_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=device_type,
                port=switch_config.get('ssh_port'),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret,
                transport=transport,
                raise_on_error=True,
                banner_timeout=switch_config.get('handshake_timeout'),
                auth_timeout=switch_config.get('handshake_timeout'),
            )
            if not connection:
                raise RuntimeError('CLI 连接失败')

            output = self._execute_command(
                connection,
                command,
                device_type=device_type,
                transport=transport,
                read_timeout=120,
                delay_factor=3 if self.normalize_cli_transport(transport) == 'telnet' else 2,
                max_loops=400 if self.normalize_cli_transport(transport) == 'telnet' else 300,
            )
            cleaned = self._strip_ansi_codes(output or '')
            # 部分设备（如 Nokia MD-CLI）会把提示符回显在命令回显行里，
            # 使 send_command 误判命令已结束，只拿到 banner/回显（约 160 字节）。
            # 输出明显偏短时清空通道，用 timing 方式重读同一只读命令，取更长者。
            if len(cleaned.strip()) < 1024:
                try:
                    connection.clear_buffer()
                except Exception:
                    pass
                output = connection.send_command_timing(
                    command,
                    read_timeout=120,
                    delay_factor=3 if self.normalize_cli_transport(transport) == 'telnet' else 2,
                    max_loops=400 if self.normalize_cli_transport(transport) == 'telnet' else 300,
                )
                retry_cleaned = self._strip_ansi_codes(output or '')
                if len(retry_cleaned.strip()) > len(cleaned.strip()):
                    cleaned = retry_cleaned
            return cleaned
        finally:
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def get_chassis_serial_cli(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[str]:
        """
        Collect chassis serial number via CLI as a fallback when SNMP ENTITY-MIB
        does not expose it (e.g. Nokia SR Linux).

        Uses 'show version' (or 'show chassis hardware' for Juniper) and extracts
        the serial with vendor-specific patterns.
        """
        connection = None
        try:
            vendor = (switch_config.get('vendor') or '').lower()

            commands = []
            if 'juniper' in vendor:
                commands = ['show chassis hardware']
            elif 'dell' in vendor:
                commands = ['show inventory']
            elif 'alcatel' in vendor or 'nokia' in vendor:
                # Nokia SR OS (TiMOS): 'show version' only prints the banner; the
                # chassis serial lives in 'show chassis detail' -> Chassis -> Hardware
                # Data -> "Serial number". Some Nokia white-box variants (e.g. Nuage
                # 210 WBX) reject 'detail' but expose it under plain 'show chassis'.
                commands = ['show chassis detail', 'show chassis']
            elif 'h3c' in vendor:
                # Comware 不支持 'show version'；整机 SN 在 manuinfo 的
                # DEVICE_SERIAL_NUMBER 字段，'display version' 不含 SN。
                commands = ['display device manuinfo', 'display version']
            else:
                commands = ['show version']

            password = decrypt_password(switch_config['password_encrypted'])
            transport = switch_config.get('cli_transport', 'ssh')
            device_type = switch_config.get('device_type')
            if not device_type:
                device_type = 'hp_comware' if 'h3c' in vendor else 'nokia_sros'
            enable_secret = None
            if switch_config.get('enable_password_encrypted'):
                enable_secret = decrypt_password(switch_config['enable_password_encrypted'])

            connection = self._create_cli_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=device_type,
                port=switch_config.get('ssh_port'),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret,
                transport=transport,
            )
            if not connection:
                return None

            # Dell FTOS (OS6) requires enable mode before 'show inventory' exposes
            # the service tag. The 'dell_os10' driver does not auto-enable.
            if 'dell' in vendor:
                try:
                    connection.send_command_timing('enable', delay_factor=2, max_loops=50)
                    if enable_secret:
                        connection.send_command_timing(enable_secret, delay_factor=2, max_loops=50)
                    connection.send_command_timing('terminal length 0', delay_factor=2, max_loops=50)
                except Exception as enable_err:
                    logger.debug(f"Enable mode for serial collection failed on {switch_ip}: {enable_err}")

            # Use timing-based read: 'show version' on SR Linux/SR OS returns output
            # that netmiko's send_command() may truncate to just the command echo.
            serial = None
            for command in commands:
                try:
                    output = connection.send_command_timing(command, delay_factor=2, max_loops=200)
                except Exception as cmd_err:
                    logger.debug(f"CLI serial command '{command}' failed on {switch_ip}: {cmd_err}")
                    continue
                if not output:
                    continue
                serial = self._extract_chassis_serial(output, vendor)
                if serial:
                    break

            if serial:
                logger.info(f"Chassis serial (CLI) for {switch_ip}: {serial}")
            return serial

        except Exception as e:
            logger.debug(f"CLI serial collection failed for {switch_ip}: {e}")
            return None

        finally:
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def _extract_chassis_serial(self, output: str, vendor: str) -> Optional[str]:
        """Extract chassis serial from 'show version' / 'show chassis hardware' / 'show inventory' output."""
        # Dell FTOS (OS6) 'show inventory': the 'Serial Number' column literally
        # shows 'NA'; the real identifier is the 7-char service tag in the 'Svc
        # Tag' column of the management-unit (star-marked) row.
        if 'dell' in (vendor or '').lower():
            svc_tag = self._extract_dell_ftos_svc_tag(output)
            if svc_tag:
                return svc_tag
            # OS9/OS10 的 'show inventory' 机箱行通常形如
            # "PID: 0P3TGG, VID: 00, SN: 5J0YH32"（不是 "Service Tag:"）。
            # FTOS 行里的 "Serial Number" 列会直接写 NA，由下面的 NA 过滤挡掉。
            m = re.search(r'\bSN\s*[:=]\s*"?([A-Za-z0-9]{5,})"?', output)
            if m:
                val = m.group(1).strip()
                if val and val.lower() not in ('null', 'none', 'n/a', 'na'):
                    return val

        patterns = [
            # H3C Comware 'display device manuinfo'：多槽位的风扇/电源也会输出
            # SERIAL_NUMBER，整机序列号只在 DEVICE_SERIAL_NUMBER 里，必须优先匹配。
            r'DEVICE_SERIAL_NUMBER\s*[:=]\s*"?([A-Za-z0-9]+)"?',
            r'Serial\s+Number\s*[:=]\s*"?([A-Za-z0-9]+)"?',      # Nokia SR Linux / Dell / Junos
            r'serial[-_]?number\s*[:=]\s*"?([A-Za-z0-9]+)"?',    # SR Linux info / Junos table
            r'Processor\s+board\s+ID\s+([A-Za-z0-9]+)',          # Cisco IOS
            r'Service\s+Tag\s*[:=]\s*"?([A-Za-z0-9]+)"?',        # Dell OS10
        ]
        for pat in patterns:
            m = re.search(pat, output, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and val.lower() not in ('null', 'none', 'n/a', 'na'):
                    return val
        return None

    def _extract_dell_ftos_svc_tag(self, output: str) -> Optional[str]:
        """Extract the 7-char Dell service tag from FTOS 'show inventory' output.

        The chassis (management unit) row is the one marked with a leading '*'.
        Dell service tags are exactly 7 alphanumeric characters; part numbers are
        6 chars and the model name contains dashes, so a 7-char token in the star
        row is the service tag.
        """
        if not output:
            return None
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped.startswith('*'):
                continue
            for token in stripped.split():
                if re.fullmatch(r'[A-Za-z0-9]{7}', token) and token.upper() not in ('NA', 'N/A'):
                    return token
        return None

    # ------------------------------------------------------------------
    # 拓扑：LLDP / CDP / 接口清单解析器
    #
    # 输出结构与 SNMP 侧保持完全一致（见 snmp_service.collect_*），
    # 上层 topology_service 不区分数据来源，只消费同一种事实结构。
    # ------------------------------------------------------------------

    # Cisco/NX-OS `show lldp neighbors detail` 的 capability 缩写；
    # 长单词形态（Bridge / Router ...）原样保留，由 topology_service 统一解析。
    _LLDP_CAPABILITY_LETTERS = {
        'p': 'repeater', 'b': 'bridge', 'w': 'wlan', 'r': 'router',
        't': 'phone', 'c': 'docsis', 's': 'station', 'o': 'other',
    }
    # capability 行可能是 `System Capabilities: B,R`，也可能用 `-` 分隔并写
    # `not advertised`（NX-OS），两种都要认。
    _LLDP_CAPABILITY_LINE = re.compile(
        r'^(?:Remote System Capabilities|System Capabilities|Enabled Capabilities)'
        r'\s*(?::|-)\s*(.*)$',
        re.IGNORECASE,
    )
    _CAPABILITY_NON_VALUES = ('not advertised', 'unknown', 'none', '-', '')

    @classmethod
    def _normalize_lldp_capability(cls, value: Optional[str]) -> Optional[str]:
        """把 `P,B,R` 归一成 `repeater,bridge,router`；无信息或未知缩写时返回 None。"""
        raw = (value or '').strip()
        if raw.lower() in cls._CAPABILITY_NON_VALUES:
            return None
        parts = [part.strip() for part in raw.split(',') if part.strip()]
        if not parts:
            return None
        mapped = []
        for part in parts:
            if len(part) == 1:
                word = cls._LLDP_CAPABILITY_LETTERS.get(part.lower())
                if not word:
                    return None
                mapped.append(word)
            else:
                mapped.append(part.lower())
        return ','.join(mapped)

    @classmethod
    def _apply_capability_line(cls, current: Dict, line: str) -> bool:
        """命中 capability 行就写入当前块；Enabled 仅在未拿到 System 时兜底。"""
        match = cls._LLDP_CAPABILITY_LINE.match(line)
        if not match:
            return False
        if line.lower().startswith('enabled') and current.get('capability'):
            return True
        cap = cls._normalize_lldp_capability(match.group(1))
        if cap:
            current['capability'] = cap
        return True

    @staticmethod
    def _build_neighbor_entry(
        protocol: str,
        local_port_id: Optional[str] = None,
        local_if_index: Optional[int] = None,
        remote_chassis_id: Optional[str] = None,
        remote_port_id: Optional[str] = None,
        remote_port_desc: Optional[str] = None,
        remote_sys_name: Optional[str] = None,
        remote_sys_desc: Optional[str] = None,
        remote_mgmt_addr: Optional[str] = None,
        mgmt_type: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> Dict:
        from services.topology_utils import normalize_mac
        return {
            'protocol': protocol,
            'local_if_index': local_if_index,
            'local_port_id': local_port_id,
            'local_port_desc': None,
            'remote_chassis_id': normalize_mac(remote_chassis_id),
            'remote_chassis_id_subtype': None,
            'remote_port_id': remote_port_id,
            'remote_port_id_subtype': None,
            'remote_port_desc': remote_port_desc,
            'remote_sys_name': remote_sys_name,
            'remote_sys_desc': remote_sys_desc,
            'remote_mgmt_addr': remote_mgmt_addr,
            'remote_mgmt_addr_type': mgmt_type,
            'ttl': None,
            'capability': capability,
        }

    def _parse_cisco_lldp_neighbors(self, output: str) -> List[Dict]:
        """Cisco IOS / NX-OS 的 `show lldp neighbors detail`。"""
        entries: List[Dict] = []
        current: Dict = {}

        def flush():
            if current.get('remote_sys_name') or current.get('remote_chassis_id'):
                entries.append(self._build_neighbor_entry('lldp', **current))
            current.clear()

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self._apply_capability_line(current, line):
                continue
            if line.startswith('Local Intf:') or line.startswith('Local Port id:'):
                flush()
                current['local_port_id'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Chassis id:'):
                current['remote_chassis_id'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Port id:'):
                current['remote_port_id'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Port Description:'):
                current['remote_port_desc'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('System Name:'):
                current['remote_sys_name'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('System Description:'):
                current['remote_sys_desc'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('IP:'):
                address = line.split(':', 1)[1].strip()
                current['remote_mgmt_addr'] = address
                current['mgmt_type'] = 'ipv6' if ':' in address else 'ipv4'
        flush()
        return entries

    def _parse_generic_lldp_table(self, output: str) -> List[Dict]:
        """
        通用 LLDP 邻居：

        1. `detail` 块形态（Dell OS10 / FTOS 的 `show lldp neighbors detail`）；
        2. 简述表格形态（`Local Interface / Remote Device ID / Remote Port ID` 等）。

        先判形态再解析，两种输出不会互相误吃。
        """
        from services.topology_utils import looks_like_port

        lowered_all = (output or '').lower()
        if 'remote chassis id:' in lowered_all or 'local port id:' in lowered_all:
            return self._parse_lldp_detail_blocks(output)

        entries: List[Dict] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith(('---', '===', 'lldp', 'neighbor', 'remote system')):
                continue
            if 'chassis id' in lowered or 'system name' in lowered or 'local port' in lowered:
                continue
            parts = [part.strip() for part in re.split(r'\s{2,}|\t+', line) if part.strip()]
            if len(parts) < 3 or not looks_like_port(parts[0]):
                continue
            entries.append(self._build_neighbor_entry(
                'lldp',
                local_port_id=parts[0],
                remote_sys_name=parts[1] or None,
                remote_port_id=parts[2] or None,
            ))
        return entries

    def _parse_lldp_detail_blocks(self, output: str) -> List[Dict]:
        """
        LLDP `detail` 块（Dell OS10 / FTOS、Nokia SR Linux 等）。

        每块以 `Remote Chassis ID:` 开头（FTOS 前面还有 `Local Interface ... has
        N neighbor` 段头），字段统一为 `字段名: 值`；块之间是空行或 `-----` 分隔线。
        只认带 chassis / 系统名的块，表头与统计行一律忽略。
        """
        entries: List[Dict] = []
        current: Dict = {}

        def flush():
            if current.get('remote_chassis_id') or current.get('remote_sys_name'):
                entries.append(self._build_neighbor_entry('lldp', **current))
            current.clear()

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or set(line) <= {'-', '=', '+', '_'}:
                continue
            if self._apply_capability_line(current, line):
                continue
            if line.startswith('Remote Chassis ID:'):
                if current.get('remote_chassis_id'):
                    flush()
                current['remote_chassis_id'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Remote Port ID:'):
                current['remote_port_id'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Remote Port Description:'):
                desc = line.split(':', 1)[1].strip()
                current['remote_port_desc'] = None if desc.lower() == 'not advertised' else (desc or None)
            elif line.startswith('Local Port ID:'):
                current['local_port_id'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Remote System Name:'):
                current['remote_sys_name'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('Remote System Desc:'):
                current['remote_sys_desc'] = line.split(':', 1)[1].strip() or None
        flush()
        return entries

    @staticmethod
    def _parse_pipe_table_rows(output: str) -> List[Dict[str, str]]:
        """
        解析 `|` 框线表（Nokia SR Linux 的 `show system lldp neighbor` /
        `show interface brief`）。

        以第一行 `|` 行为表头、按列名取值，不依赖固定列位，列宽与数量随固件变化
        仍可解析。多张表拼在一起时只认第一张，避免把第二张表头当数据。
        """
        rows: List[Dict[str, str]] = []
        header: Optional[List[str]] = None
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line.startswith('|'):
                continue
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if not any(cells):
                continue
            if header is None:
                header = cells
                continue
            if len(cells) != len(header):
                continue
            rows.append(dict(zip(header, cells)))
        return rows

    def _parse_srlinux_lldp_neighbors(self, output: str) -> List[Dict]:
        """Nokia SR Linux `show system lldp neighbor`（`|` 框线表）。"""
        from services.topology_utils import looks_like_port

        entries: List[Dict] = []
        for row in self._parse_pipe_table_rows(output):
            local_port = row.get('Name') or row.get('Port')
            if not looks_like_port(local_port):
                continue
            entries.append(self._build_neighbor_entry(
                'lldp',
                local_port_id=local_port,
                remote_chassis_id=row.get('Neighbor Chassis ID') or None,
                remote_port_id=row.get('Neighbor Port') or None,
                remote_sys_name=row.get('Neighbor System Name') or row.get('Neighbor') or None,
            ))
        return entries

    @staticmethod
    def _speed_to_mbps(value: Optional[str]) -> Optional[int]:
        """把 `1G` / `10M` / `1000` / `1000Mbps` 统一成 Mbps。"""
        if not value:
            return None
        text = str(value).strip().lower()
        match = re.search(r'(\d+(?:\.\d+)?)\s*([gmt])(?:bit|bps|b)?\b', text)
        if match:
            factor = {'g': 1000, 'm': 1, 't': 1_000_000}[match.group(2)]
            return int(float(match.group(1)) * factor)
        bare = re.search(r'\b(\d{2,6})\b', text)
        return int(bare.group(1)) if bare else None

    def _parse_srlinux_interfaces(self, output: str) -> List[Dict]:
        """Nokia SR Linux `show interface brief`（`|` 框线表）。"""
        from services.topology_utils import (
            looks_like_port, normalize_lag_key, synthetic_if_index
        )

        entries: List[Dict] = []
        for row in self._parse_pipe_table_rows(output):
            if_name = row.get('Port') or row.get('Name')
            if not looks_like_port(if_name):
                continue
            # SR Linux 用 enable/disable，与 SNMP（up/down）及其它厂商解析器统一。
            state_map = {'enable': 'up', 'disable': 'down'}
            oper_raw = (row.get('Oper State') or '').strip().lower()
            admin_raw = (row.get('Admin State') or '').strip().lower()
            oper_raw = state_map.get(oper_raw, oper_raw)
            admin_raw = state_map.get(admin_raw, admin_raw)
            entries.append({
                'if_index': synthetic_if_index(if_name),
                'if_name': if_name,
                'if_descr': None,
                'if_alias': None,
                'if_type': None,
                'admin_status': admin_raw or None,
                'oper_status': oper_raw or None,
                'speed_mbps': self._speed_to_mbps(row.get('Speed')),
                'phys_address': None,
                'lag_key': normalize_lag_key(if_name),
            })
        return entries

    def _parse_cisco_cdp_neighbors(self, output: str) -> List[Dict]:
        """Cisco `show cdp neighbors detail`。"""
        entries: List[Dict] = []
        current: Dict = {}

        def flush():
            if current.get('remote_sys_name'):
                entries.append(self._build_neighbor_entry('cdp', **current))
            current.clear()

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('Device ID:'):
                flush()
                current['remote_sys_name'] = line.split(':', 1)[1].strip() or None
            elif line.startswith('IP address:'):
                address = line.split(':', 1)[1].strip()
                current['remote_mgmt_addr'] = address
                current['mgmt_type'] = 'ipv6' if ':' in address else 'ipv4'
            elif line.startswith('Platform:'):
                platform = line.split(':', 1)[1].split(',')[0].strip()
                current['remote_sys_desc'] = platform or None
            elif line.startswith('Interface:'):
                detail = line.split(':', 1)[1]
                local_part = detail.split(',')[0].strip()
                current['local_port_id'] = local_part or None
                match = re.search(
                    r'Port ID \(outgoing port\)\s*:\s*(.+)$', detail, re.IGNORECASE
                )
                if match:
                    current['remote_port_id'] = match.group(1).strip() or None
        flush()
        return entries

    def _parse_generic_cdp_table(self, output: str) -> List[Dict]:
        """通用 CDP 短表：Device ID / Local Intrfce / Holdtme / Capability / Platform / Port ID。"""
        entries: List[Dict] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith('---'):
                continue
            lowered = line.lower()
            if 'device id' in lowered or 'total cdp entries' in lowered:
                continue
            match = re.match(r'^(\S+)\s+(\S+)\s+(\d+)\s+(.+?)\s+(\S+)$', line)
            if not match:
                continue
            entries.append(self._build_neighbor_entry(
                'cdp',
                remote_sys_name=match.group(1),
                local_port_id=match.group(2),
                capability=match.group(4),
                remote_port_id=match.group(5),
            ))
        return entries

    def _parse_cisco_interfaces(self, output: str) -> List[Dict]:
        """Cisco `show interfaces status`。"""
        from services.topology_utils import (
            looks_like_port, normalize_lag_key, synthetic_if_index
        )

        entries: List[Dict] = []
        in_table = False
        status_map = {
            'connected': 'up', 'up': 'up', 'notconnect': 'down',
            'disabled': 'down', 'err-disabled': 'down', 'down': 'down',
        }
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith('port') and 'status' in lowered:
                in_table = True
                continue
            if not in_table:
                continue
            # Name 列可能为空或含空格，不能依赖固定列位置，
            # 先按已知状态关键字定位 Status，再往后取 Vlan / Duplex / Speed。
            tokens = line.split()
            if len(tokens) < 2 or not looks_like_port(tokens[0]):
                continue
            status_index = None
            for index in range(1, len(tokens)):
                if tokens[index].lower() in status_map:
                    status_index = index
                    break
            if status_index is None:
                continue
            if_name = tokens[0]
            status = tokens[status_index].lower()
            # 列序：Port / Name / Status / Vlan / Duplex / Speed / Type
            name_tokens = tokens[1:status_index]
            speed = None
            speed_index = status_index + 3  # Status 后第 3 个是 Speed
            if speed_index < len(tokens):
                speed_match = re.fullmatch(r'a-?(\d+)', tokens[speed_index].lower())
                if speed_match:
                    speed = int(speed_match.group(1))
            entries.append({
                'if_index': synthetic_if_index(if_name),
                'if_name': if_name,
                'if_descr': ' '.join(name_tokens) or None,
                'if_alias': None,
                'if_type': None,
                'admin_status': None,
                'oper_status': status_map.get(status),
                'speed_mbps': speed,
                'phys_address': None,
                'lag_key': normalize_lag_key(if_name),
            })
        return entries

    def _parse_nokia_interfaces(self, output: str) -> List[Dict]:
        """Nokia SR OS `show port`（列：Port / Admin / Link / SFP / Cfg / LAG / Oper）。"""
        from services.topology_utils import (
            looks_like_port, normalize_lag_key, synthetic_if_index
        )

        entries: List[Dict] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(('---', '===', 'Port ', 'Total')):
                continue
            parts = [part.strip() for part in re.split(r'\s{2,}|\t+', line) if part.strip()]
            if not parts or not looks_like_port(parts[0]):
                continue
            if_name = parts[0]
            # Link 是第 3 列；取不到再看整行（不同固件列数不同）。
            link_text = parts[2].lower() if len(parts) >= 3 else ' '.join(parts[1:]).lower()
            oper_status = None
            if link_text in ('yes', 'up'):
                oper_status = 'up'
            elif link_text in ('no', 'down'):
                oper_status = 'down'
            elif len(parts) >= 3 and parts[-1].lower() in ('up', 'down'):
                oper_status = parts[-1].lower()
            entries.append({
                'if_index': synthetic_if_index(if_name),
                'if_name': if_name,
                'if_descr': None,
                'if_alias': None,
                'if_type': None,
                'admin_status': None,
                'oper_status': oper_status,
                'speed_mbps': None,
                'phys_address': None,
                'lag_key': normalize_lag_key(if_name),
            })
        return entries

    def _parse_generic_interfaces(self, output: str) -> List[Dict]:
        """
        通用接口清单：每行「接口名 + 状态 + 速率」。

        无法识别状态时仍保留接口，oper_status 为 None（UI 显示未知，
        不用猜测的 "up" 骗自己）。
        """
        from services.topology_utils import (
            looks_like_port, normalize_lag_key, synthetic_if_index
        )

        entries: List[Dict] = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(('---', '===', 'Total')):
                continue
            parts = [part.strip() for part in re.split(r'\s{2,}|\t+', line) if part.strip()]
            if not parts:
                continue
            if_name = parts[0]
            # Dell FTOS 的 `show interfaces status` 把接口名写成 "Gi 1/1"（单空格），
            # 按列切分后仍是同一个 token，含空格会被 looks_like_port 整行丢弃。
            spaced_name = re.fullmatch(r'([A-Za-z][A-Za-z\-]{0,15})\s+(\d+(?:/\d+)+)', if_name)
            if spaced_name and len(parts) > 1:
                if_name = f'{spaced_name.group(1)}{spaced_name.group(2)}'
            elif (
                len(parts) > 1
                and re.fullmatch(r'[A-Za-z][A-Za-z\-]{0,15}', parts[0])
                and re.fullmatch(r'\d+(?:/\d+)+', parts[1])
            ):
                if_name = f'{parts[0]}{parts[1]}'
                parts = [if_name, *parts[2:]]
            if not looks_like_port(if_name):
                continue
            joined = ' '.join(parts[1:]).lower()
            oper_status = None
            if re.search(r'\bup\b|\bconnected\b', joined):
                oper_status = 'up'
            elif re.search(r'\bdown\b|\bnotconnect\b|\bdisabled\b', joined):
                oper_status = 'down'
            speed = None
            # 优先识别带单位的速率（1000M / 1000 Mbit / a-1000 / Comware 1G(a) 10G(a)），
            # 裸数字可能撞上 VLAN 列，只在找不到单位时才退回。
            # 注意单位是 G 时要换算：1G(a) = 1000 Mbps，10G(a) = 10000 Mbps。
            unit_match = re.search(r'(\d+)\s*(gbit|gb|g|mbit|mbps|mb)\b', joined)
            if unit_match:
                speed = int(unit_match.group(1))
                if unit_match.group(2).startswith('g'):
                    speed *= 1000
            else:
                for token in parts[1:]:
                    speed_match = re.fullmatch(r'a-?(\d+)', token.lower())
                    if speed_match:
                        speed = int(speed_match.group(1))
                        break
            if speed is None:
                bare_match = re.search(r'\b(\d{3,5})\b', ' '.join(parts[2:]))
                if bare_match:
                    speed = int(bare_match.group(1))
            entries.append({
                'if_index': synthetic_if_index(if_name),
                'if_name': if_name,
                'if_descr': None,
                'if_alias': None,
                'if_type': None,
                'admin_status': None,
                'oper_status': oper_status,
                'speed_mbps': speed,
                'phys_address': None,
                'lag_key': normalize_lag_key(if_name),
            })
        return entries

    def _collect_topology_facts_cli(
        self,
        switch_ip: str,
        switch_config: Dict,
        templates: Optional[List[Dict]],
        data_type: str,
    ) -> Dict:
        """
        采集一类拓扑事实（lldp / cdp / interfaces）。

        命令与解析器全部来自模板（数据库优先，其次内置模板），不在代码里硬编码设备命令。
        """
        connection = None
        try:
            password = decrypt_password(switch_config['password_encrypted'])
            enable_secret = None
            if switch_config.get('enable_password_encrypted'):
                enable_secret = decrypt_password(switch_config['enable_password_encrypted'])

            vendor = switch_config.get('vendor', '')
            model = switch_config.get('model', '')
            name = switch_config.get('name', '')
            template = self._find_matching_template(vendor, model, name, templates)
            if not template:
                return {
                    'status': 'unsupported',
                    'entries': [],
                    'message': 'no command template matched for this device',
                }

            # 数据库模板优先；模板里没有配置拓扑命令（None/空）时，按 device_type 取内置默认命令。
            from config.collection_strategy import TOPOLOGY_CLI_DEFAULTS
            effective = dict(template)
            for key, value in (TOPOLOGY_CLI_DEFAULTS.get(template.get('device_type') or '') or {}).items():
                if effective.get(key) is None:
                    effective[key] = value

            command = effective.get(f'{data_type}_command')
            enabled = effective.get(f'{data_type}_enabled', True)
            if not enabled or not command:
                return {
                    'status': 'unsupported',
                    'entries': [],
                    'message': f'{data_type} CLI collection is not enabled for this template',
                }

            parser_type = effective.get(f'{data_type}_parser_type')
            parser = self._get_parser(parser_type, data_type)
            if not parser:
                return {
                    'status': 'error',
                    'entries': [],
                    'message': f'no {data_type} parser registered for type {parser_type!r}',
                }

            transport = switch_config.get('cli_transport', 'ssh')
            device_type = template.get('device_type')
            try:
                connection = self._create_cli_connection(
                    host=switch_ip,
                    username=switch_config['username'],
                    password=password,
                    device_type=device_type,
                    port=switch_config.get('ssh_port'),
                    timeout=switch_config.get('connection_timeout', 30),
                    enable_secret=enable_secret,
                    transport=transport,
                    raise_on_error=True,
                )
            except Exception as connect_error:
                # netmiko 异常是多行带排查建议的大段文本，压成一行便于在告警页阅读。
                reason = ' '.join(str(connect_error).split())[:300]
                return {
                    'status': 'error',
                    'entries': [],
                    'message': f'CLI connection failed: {reason}',
                }
            if not connection:
                return {'status': 'error', 'entries': [], 'message': 'CLI connection failed'}

            try:
                output = self._execute_command(
                    connection,
                    command,
                    device_type=device_type,
                    transport=transport,
                    read_timeout=90,
                    delay_factor=3,
                    max_loops=200,
                )
            except Exception as e:
                return {'status': 'error', 'entries': [], 'message': str(e)}

            logger.debug(
                f"{data_type.upper()} CLI output from {switch_ip} "
                f"({len(output or '')} chars):\n{(output or '')[:500]}"
            )
            entries = parser(output or '')
            if not entries:
                # 设备真实输出格式可能与登记的厂商/型号不符（例如登记为 cisco，实际输出 Dell 表格）。
                # 通用表格解析器覆盖多数厂商的 detail/table 输出；命中条目即采用，避免误报解析失败。
                fallback_parser = self._get_parser('generic', data_type)
                if fallback_parser and fallback_parser is not parser:
                    fallback_entries = fallback_parser(output or '')
                    if fallback_entries:
                        logger.warning(
                            f"{data_type.upper()} parser {parser_type!r} found 0 entries from "
                            f"{switch_ip}; generic parser matched {len(fallback_entries)} entries"
                        )
                        entries = fallback_entries
            if not entries:
                lowered = (output or '').lower()
                if any(marker in lowered for marker in (
                    'invalid input', 'unrecognized command', 'incomplete command',
                    'syntax error', 'unknown command', "doesn't exist",
                    # NX-OS 在 feature 未开启时回显 "% Invalid command at '^' marker."
                    '% invalid command',
                    # H3C Comware 的错误回显
                    '% wrong parameter', '% ambiguous command', '% too many parameters',
                    '% unrecognized command', '% incomplete command',
                    # Comware 未开启 LLDP
                    'lldp is not enabled',
                )):
                    return {
                        'status': 'unsupported',
                        'entries': [],
                        'message': 'device rejected the command',
                    }
                if not (output or '').strip():
                    return {'status': 'error', 'entries': [], 'message': 'empty CLI output'}
                # 设备明确表示没有邻居 = 支持协议但无邻居，属于成功；
                # 其余「解析出 0 条」说明输出格式没被识别，不能报成功（假 success 会误导覆盖率）。
                # Cisco 实际输出是 "Total cdp entries displayed : 0"（冒号前有空格），
                # 固定子串匹配不到，必须按空白宽松匹配。
                if any(marker in lowered for marker in (
                    'no neighbors', 'no lldp neighbors', 'no cdp neighbors',
                    'neighbor table is empty', 'no remote system',
                )) or re.search(
                    r'total\s+(?:cdp\s+|lldp\s+)?entries\s+displayed\s*:\s*0\b', lowered
                ) or re.search(
                    r'total\s+number\s+of\s+neighbors\s*:\s*0\b', lowered
                ):
                    return {
                        'status': 'ok',
                        'entries': [],
                        'message': 'device reports no neighbors',
                    }
                return {
                    'status': 'error',
                    'entries': [],
                    'message': 'unable to parse CLI output; command or output format may be unsupported',
                }
            logger.info(f"Collected {len(entries)} {data_type} facts from {switch_ip} via CLI")
            return {'status': 'ok', 'entries': entries}

        except Exception as e:
            logger.error(f"Failed to collect {data_type} via CLI from {switch_ip}: {str(e)}")
            return {'status': 'error', 'entries': [], 'message': str(e)}

        finally:
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    pass

    def collect_lldp_neighbors_cli(
        self,
        switch_ip: str,
        switch_config: Dict,
        templates: Optional[List[Dict]] = None
    ) -> Dict:
        return self._collect_topology_facts_cli(switch_ip, switch_config, templates, 'lldp')

    def collect_cdp_neighbors_cli(
        self,
        switch_ip: str,
        switch_config: Dict,
        templates: Optional[List[Dict]] = None
    ) -> Dict:
        return self._collect_topology_facts_cli(switch_ip, switch_config, templates, 'cdp')

    def collect_interfaces_cli(
        self,
        switch_ip: str,
        switch_config: Dict,
        templates: Optional[List[Dict]] = None
    ) -> Dict:
        return self._collect_topology_facts_cli(switch_ip, switch_config, templates, 'interfaces')

    def topology_dataset_supported(
        self,
        switch_config: Dict,
        templates: Optional[List[Dict]],
        data_type: str,
    ) -> Optional[bool]:
        """
        该设备类型是否应采集某类拓扑事实。

        返回 None 表示无法判断（模板或 device_type 未定义），调用方按原逻辑
        SNMP 优先 + CLI 回退实际探测；True/False 表示模板已明确支持/不适用
        （例如 Dell / Nokia 没有 CDP），此时不应再尝试 SNMP，避免把
        「协议不适用」误记成采集失败。
        """
        template = self._find_matching_template(
            switch_config.get('vendor', ''),
            switch_config.get('model', ''),
            switch_config.get('name', ''),
            templates,
        )
        if not template:
            return None
        from config.collection_strategy import TOPOLOGY_CLI_DEFAULTS
        defaults = TOPOLOGY_CLI_DEFAULTS.get(template.get('device_type') or '')
        if not defaults:
            return None
        # 与 _collect_topology_facts_cli 相同的「模板优先、内置默认补齐」规则。
        effective = dict(template)
        for key, value in defaults.items():
            if effective.get(key) is None:
                effective[key] = value
        enabled = effective.get(f'{data_type}_enabled', True)
        command = effective.get(f'{data_type}_command')
        return bool(enabled and command)

    def _get_parser(self, parser_type: Optional[str], data_type: str):
        """
        Get parser function by type

        Args:
            parser_type: Parser type name (e.g., 'nokia_7220', 'dell_os10')
            data_type: 'arp' / 'mac' / 'lldp' / 'cdp' / 'interfaces'

        Returns:
            Parser function or None
        """
        if not parser_type:
            return None

        parser_map = {
            'nokia_7220': {
                'arp': self._parse_nokia_7220_arp_table,
                'mac': self._parse_nokia_7220_mac_table,
                'lldp': self._parse_srlinux_lldp_neighbors,
                'interfaces': self._parse_srlinux_interfaces,
            },
            'nokia_7250': {
                'arp': self._parse_nokia_7250_arp_table,
                'mac': self._parse_nokia_7250_mac_table,
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_nokia_interfaces,
            },
            # 别名：命令模板页可选 nokia_sros，但此前未注册会导致「解析器不存在」。
            'nokia_sros': {
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_nokia_interfaces,
            },
            # 别名：未知厂商/通用表格，与命令模板页的 generic 选项保持一致。
            'generic': {
                'lldp': self._parse_generic_lldp_table,
                'cdp': self._parse_generic_lldp_table,
                'interfaces': self._parse_generic_interfaces,
            },
            'dell_os10': {
                'arp': self._parse_dell_os10_arp_table,
                'mac': self._parse_dell_os10_mac_table,
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_generic_interfaces,
            },
            'dell_force10': {
                'arp': self._parse_dell_force10_arp_table,
                'mac': self._parse_dell_force10_mac_table,
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_generic_interfaces,
            },
            'cisco_ios': {
                'arp': self._parse_cisco_ios_arp_table,
                'mac': self._parse_cisco_ios_mac_table,
                'lldp': self._parse_cisco_lldp_neighbors,
                'cdp': self._parse_cisco_cdp_neighbors,
                'interfaces': self._parse_cisco_interfaces,
            },
            'cisco_nxos': {
                'arp': self._parse_cisco_nxos_arp_table,
                'mac': self._parse_cisco_nxos_mac_table,
                'lldp': self._parse_cisco_lldp_neighbors,
                'cdp': self._parse_cisco_cdp_neighbors,
                'interfaces': self._parse_cisco_interfaces,
            },
            'juniper': {
                'arp': self._parse_juniper_arp_table,
                'mac': self._parse_juniper_mac_table,
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_generic_interfaces,
            },
            'arista_eos': {
                'arp': self._parse_arista_eos_arp_table,
                'mac': self._parse_arista_eos_mac_table,
                'lldp': self._parse_cisco_lldp_neighbors,
                'cdp': self._parse_cisco_cdp_neighbors,
                'interfaces': self._parse_cisco_interfaces,
            },
            'hpe_procurve': {
                'arp': self._parse_hpe_procurve_arp_table,
                'mac': self._parse_hpe_procurve_mac_table,
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_generic_interfaces,
            },
            'huawei_vrp': {
                'arp': self._parse_huawei_vrp_arp_table,
                'mac': self._parse_huawei_vrp_mac_table,
                'lldp': self._parse_generic_lldp_table,
                'interfaces': self._parse_generic_interfaces,
            },
            'h3c_comware': {
                'arp': self._parse_h3c_comware_arp_table,
                'mac': self._parse_h3c_comware_mac_table,
                'lldp': self._parse_h3c_comware_lldp,
                'interfaces': self._parse_generic_interfaces,
            }
        }

        return parser_map.get(parser_type, {}).get(data_type)

    def _resolve_device_type(
        self,
        vendor: str,
        model: str,
        name: str = '',
        configured_device_type: Optional[str] = None
    ) -> str:
        """Resolve the CLI device type from templates, falling back to the provided config."""
        template = self._find_matching_template(vendor, model, name)
        if template and template.get('device_type'):
            resolved_device_type = template['device_type']
            if configured_device_type and configured_device_type != resolved_device_type:
                logger.info(
                    f"Overriding device_type for {vendor} {model} from "
                    f"{configured_device_type} to {resolved_device_type}"
                )
            return resolved_device_type

        return configured_device_type or (
            'hp_comware' if (vendor or '').lower() == 'h3c' else 'cisco_ios'
        )

    def collect_optical_modules_cli(
        self,
        switch_ip: str,
        cli_config: Dict,
        vendor: str,
        model: str
    ) -> List[Dict]:
        """
        Collect optical module information via CLI
        
        Args:
            switch_ip: IP address of the switch
            cli_config: CLI configuration (username, password, etc.)
            vendor: Vendor name (cisco, dell, alcatel, etc.)
            model: Model name
            
        Returns:
            List of optical module dictionaries with keys:
            - port_name: Interface name
            - module_type: SFP/SFP+/QSFP/QSFP+/QSFP28
            - model: Model number
            - serial_number: Serial number
            - vendor: Manufacturer name
            - speed_gbps: Port speed in Gbps
        """
        logger.info(f"Collecting optical modules from {switch_ip} via CLI (vendor: {vendor}, model: {model})")
        
        try:
            # Create CLI connection
            from core.security import decrypt_password
            device_type = self._resolve_device_type(
                vendor,
                model,
                cli_config.get('name', ''),
                cli_config.get('device_type')
            )

            connection = self._create_cli_connection(
                switch_ip,
                cli_config['username'],
                decrypt_password(cli_config['password_encrypted']),
                device_type,
                cli_config.get('ssh_port'),
                cli_config.get('connection_timeout', 30),
                decrypt_password(cli_config.get('enable_password_encrypted')) if cli_config.get('enable_password_encrypted') else None,
                cli_config.get('cli_transport', 'ssh')
            )
            
            if not connection:
                logger.error(f"Failed to establish CLI connection to {switch_ip}")
                return []
            
            modules = []
            vendor_lower = vendor.lower() if vendor else ''
            model_upper = model.upper() if model else ''
            
            # Dell: OS10 与 OS9(FTOS) 的光模块命令不一样，而且同一型号可能跑不同 NOS
            # （本环境的 S4048-ON 就跑 FTOS，而不是 OS10）。以前按型号后缀猜单一命令，
            # 猜错就只能拿到一条报错回显、0 个模块。改成按候选命令依次尝试，解析到模块即停。
            if vendor_lower == 'dell':
                candidates = (
                    ('show inventory media', self._parse_dell_inventory_media),
                    ('show interfaces transceiver', self._parse_dell_transceiver),
                    ('show interface transceiver', self._parse_dell_transceiver),
                )
                for command, parser in candidates:
                    logger.info(f"Trying '{command}' for Dell {model}")
                    output = connection.send_command_timing(command, delay_factor=2)
                    logger.debug(f"Command output length: {len(output)} bytes")
                    modules = parser(output)
                    if modules:
                        logger.info(
                            f"Parsed {len(modules)} optical module(s) from '{command}' on {switch_ip}"
                        )
                        break
            # Cisco: show inventory and show interface transceiver
            elif vendor_lower == 'cisco':
                # Detect if this is NX-OS device
                is_nxos = model and ('N9K' in model.upper() or 'NX' in model.upper() or 'NEXUS' in model.upper())

                logger.info(f"Using 'show inventory' for Cisco {model} (NX-OS: {is_nxos})")
                command = 'show inventory'
                output = connection.send_command_timing(command, delay_factor=2)
                logger.debug(f"Command output length: {len(output)} bytes")
                modules = self._parse_cisco_inventory(output)

                if not modules:
                    logger.info(f"No transceivers parsed from Cisco inventory on {switch_ip}, trying 'show interface transceiver'")
                    command = 'show interface transceiver'
                    output = connection.send_command_timing(command, delay_factor=2)
                    logger.debug(f"Fallback command output length: {len(output)} bytes")

                    # Choose parser based on device type
                    if is_nxos:
                        logger.info(f"Using NX-OS transceiver parser for {model}")
                        modules = self._parse_cisco_nxos_transceiver(output)
                    else:
                        logger.info(f"Using IOS transceiver parser for {model}")
                        modules = self._parse_cisco_transceiver(output)
            
            # Alcatel/Nokia: per-port query
            elif vendor_lower in ['alcatel', 'nokia', 'alcatel-lucent']:
                logger.info(f"Using per-port transceiver query for Alcatel/Nokia {model}")
                modules = self._collect_alcatel_transceivers(connection)
            
            # Juniper: show interfaces diagnostics optics
            elif vendor_lower == 'juniper':
                logger.info(f"Using 'show interfaces diagnostics optics' for Juniper {model}")
                command = 'show interfaces diagnostics optics'
                output = connection.send_command_timing(command, delay_factor=2)
                logger.debug(f"Command output length: {len(output)} bytes")
                modules = self._parse_juniper_optics(output)

            # H3C Comware: 'display transceiver interface' 在老版本/部分平台不输出
            # 厂商型号，回退到 manuinfo 视图；两者解析格式一致。
            elif vendor_lower == 'h3c':
                for command in ('display transceiver interface', 'display transceiver manuinfo interface'):
                    logger.info(f"Trying '{command}' for H3C {model}")
                    output = connection.send_command_timing(command, delay_factor=2)
                    logger.debug(f"Command output length: {len(output)} bytes")
                    modules = self._parse_h3c_transceiver(output)
                    if modules:
                        logger.info(
                            f"Parsed {len(modules)} optical module(s) from '{command}' on {switch_ip}"
                        )
                        break

            else:
                logger.warning(f"Unsupported vendor/model for optical module CLI collection: {vendor} {model}")
            
            connection.disconnect()
            logger.info(f"Collected {len(modules)} optical modules from {switch_ip} via CLI")
            return modules
            
        except Exception as e:
            logger.error(f"Failed to collect optical modules via CLI from {switch_ip}: {str(e)}", exc_info=True)
            return []
    
    def _parse_dell_inventory_media(self, output: str) -> List[Dict]:
        """Parse Dell 'show inventory media' output (table format)

        Example output:
        Slot   Port     Type        Media                   Serial Number        Dell Qualified
        ------------------------------------------------------------------------------------
           1      1     SFP+        10GBASE-LR                FR204937045          No
           1      2              Media not present or accessible
        """
        modules = []
        try:
            lines = output.strip().split('\n')

            for line in lines:
                # Skip empty lines, headers, separators, and --More--
                if not line.strip() or '---' in line or 'Slot' in line and 'Port' in line:
                    continue
                if 'More' in line or not line.strip():
                    continue

                # Skip lines without media present
                if 'not present' in line.lower() or 'accessible' in line.lower():
                    continue

                # Parse table row - split by multiple spaces
                import re
                parts = re.split(r'\s{2,}', line.strip())

                if len(parts) < 2:
                    continue

                try:
                    # OS10 format:
                    # [Node/Slot/Port, Form-Factor, Media, Serial-Number, Qualified]
                    if '/' in parts[0]:
                        port_name = parts[0].strip()
                        form_factor = parts[1].strip() if len(parts) > 1 else ''
                        media = parts[2].strip() if len(parts) > 2 else ''
                        serial = parts[3].strip() if len(parts) > 3 else None

                        if not media or 'not present' in media.lower():
                            continue

                        module = {
                            'port_name': port_name,
                            'module_type': self._identify_module_type(form_factor or media),
                            'model': media or form_factor,
                            'serial_number': serial,
                            'vendor': None,
                            'speed_gbps': self._extract_speed_gbps(media or form_factor)
                        }

                        modules.append(module)
                        logger.debug(f"Parsed Dell OS10 module: {port_name} = {form_factor} / {media} / {serial}")
                        continue

                    # Legacy table format:
                    # [Slot, Port, Type, Media, Serial_Number, Dell_Qualified]
                    if len(parts) >= 5:
                        slot = parts[0].strip()
                        port = parts[1].strip()
                        module_type_str = parts[2].strip()
                        media = parts[3].strip()
                        serial = parts[4].strip() if len(parts) > 4 else None

                        port_name = f"Port {port}"

                        module = {
                            'port_name': port_name,
                            'module_type': self._identify_module_type(module_type_str),
                            'model': media if media else module_type_str,
                            'serial_number': serial,
                            'vendor': None,
                            'speed_gbps': self._extract_speed_gbps(media if media else module_type_str)
                        }

                        modules.append(module)
                        logger.debug(f"Parsed Dell module: {port_name} = {module_type_str} / {media} / {serial}")

                except Exception as e:
                    logger.debug(f"Error parsing Dell media line '{line}': {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing Dell inventory media output: {str(e)}")

        return modules
    
    def _parse_dell_transceiver(self, output: str) -> List[Dict]:
        """Parse Dell 'show interface transceiver' output.

        Force10/OS9 platforms return a per-interface block with serial-id and
        diagnostics sections. The old line-by-line parser treated every
        diagnostic line as a separate module record, producing hundreds of fake
        rows like "RX1 / Power". Parse the output block-wise instead.
        """
        modules = []
        try:
            blocks: List[tuple[str, List[str]]] = []
            current_interface = None
            current_lines: List[str] = []

            for raw_line in output.splitlines():
                line = raw_line.rstrip()
                interface_match = re.match(r'^\s*Interface Name\s*:\s*(.+?)\s*$', line)
                if interface_match:
                    if current_interface is not None:
                        blocks.append((current_interface, current_lines))
                    current_interface = interface_match.group(1).strip()
                    current_lines = []
                    continue

                if current_interface is not None:
                    current_lines.append(line)

            if current_interface is not None:
                blocks.append((current_interface, current_lines))

            for interface_name, block_lines in blocks:
                block_text = '\n'.join(block_lines)
                if 'pluggable optics cannot be read or is not present' in block_text.lower():
                    continue

                # FTOS 不同版本的行格式不一致：有的带模块类型前缀（"SFP+ 0 Vendor SN = ..."），
                # 有的就是裸的 "Vendor SN = ..."。前缀设为可选，分隔符同时接受 '=' 和 ':'。
                _opt_prefix = r'(?:(?:QSFP28|QSFP\+|QSFP|SFP\+|SFP)\s+\S+\s+)?'
                serial_match = re.search(
                    _opt_prefix + r'Vendor SN\s*[:=]\s*(.+?)\s*$',
                    block_text,
                    re.MULTILINE
                )
                vendor_match = re.search(
                    _opt_prefix + r'Vendor Name\s*[:=]\s*(.+?)\s*$',
                    block_text,
                    re.MULTILINE
                )
                part_match = re.search(
                    _opt_prefix + r'Vendor (?:PN|Part Number|Part)\s*[:=]\s*(.+?)\s*$',
                    block_text,
                    re.MULTILINE
                )
                family_match = re.search(
                    r'^\s*((?:QSFP28|QSFP\+|QSFP|SFP\+|SFP))(?:\s+\S+)?\s+Serial ID Base Fields',
                    block_text,
                    re.MULTILINE
                )

                media_model = None
                for candidate in reversed(block_lines):
                    candidate = candidate.strip()
                    if (
                        not candidate or
                        '=' in candidate or
                        candidate.startswith('Interface Name') or
                        set(candidate) == {'='}
                    ):
                        continue
                    if re.search(r'(BASE|AOC|DAC|SFP|QSFP)', candidate, re.IGNORECASE):
                        media_model = candidate
                        break

                vendor = vendor_match.group(1).strip() if vendor_match else None
                part_number = part_match.group(1).strip() if part_match else None
                serial_number = serial_match.group(1).strip() if serial_match else None
                module_family = family_match.group(1).strip() if family_match else None
                port_name = self._normalize_optical_port_name(interface_name)

                model_hint = ' '.join(
                    value for value in [module_family, media_model, part_number, interface_name] if value
                )
                module_type = self._identify_module_type(model_hint)
                if module_type == 'Transceiver':
                    module_type = self._infer_module_type_from_port_name(interface_name)

                speed_gbps = self._extract_speed_gbps(model_hint)

                # Only keep interface blocks that expose real identity data.
                if not any([serial_number, vendor, part_number, media_model]):
                    continue

                modules.append({
                    'port_name': port_name,
                    'model': part_number or media_model,
                    'vendor': vendor,
                    'serial_number': serial_number,
                    'module_type': module_type,
                    'speed_gbps': speed_gbps
                })
        
        except Exception as e:
            logger.error(f"Error parsing Dell transceiver output: {str(e)}")
        
        return modules
    
    def _parse_cisco_transceiver(self, output: str) -> List[Dict]:
        """Parse Cisco 'show interfaces transceiver' output"""
        modules = []
        try:
            # Catalyst IOS often returns DOM telemetry rather than module identity.
            # In that format the output contains temperatures/voltages/currents, not
            # vendor/model/serial data. Returning fake records is worse than returning none.
            if (
                'Temperature' in output and
                'Voltage' in output and
                'Current' in output and
                'Tx Power' in output and
                'Rx Power' in output
            ):
                logger.warning("Cisco transceiver output is telemetry-only; skipping parser to avoid fake module records")
                return []

            lines = output.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line or 'Interface' in line or '---' in line:
                    continue
                
                # Example: Gi1/0/1    SFP-10GBase-SR    CISCO-FINISAR    FTLX8571D3BCL    ABC123456
                parts = line.split()
                if len(parts) >= 3:
                    module = {
                        'port_name': parts[0],
                        'model': parts[1] if len(parts) > 1 else None,
                        'vendor': parts[2] if len(parts) > 2 else None,
                        'serial_number': parts[3] if len(parts) > 3 else None,
                        'module_type': self._identify_module_type(parts[1] if len(parts) > 1 else ''),
                        'speed_gbps': None
                    }
                    modules.append(module)
        
        except Exception as e:
            logger.error(f"Error parsing Cisco transceiver output: {str(e)}")
        
        return modules

    def _parse_cisco_inventory(self, output: str) -> List[Dict]:
        """Parse Cisco 'show inventory' output for pluggable optics."""
        modules = []
        try:
            blocks = [block.strip() for block in re.split(r'\n\s*\n', output) if block.strip()]

            for block in blocks:
                name_match = re.search(r'NAME:\s+"([^"]+)",\s*DESCR:\s+"([^"]*)"', block)
                pid_match = re.search(r'PID:\s*([^,]*),\s*VID:\s*([^,]*),\s*SN:\s*(.+)', block)

                if not name_match:
                    continue

                port_name = name_match.group(1).strip()
                description = name_match.group(2).strip()

                # Keep only interface-like inventory entries, not chassis/PSU/stack items.
                if not re.match(r'^(Te|Gi|Fa|Fo|Hu|Twe|Eth|Ethernet|FortyGig|TwentyFiveGig|HundredGig)', port_name, re.IGNORECASE):
                    continue

                identity_text = description.lower()
                pid = pid_match.group(1).strip() if pid_match else ''
                serial = pid_match.group(3).strip() if pid_match else ''
                unsupported_identity = description.lower() in {'unsupported', 'unknown', 'not supported'}

                if not any(keyword in identity_text for keyword in ['sfp', 'qsfp', 'gbic', 'transceiver', '1000base', '10gbase', '40gbase', '100g']):
                    # Older Catalyst platforms sometimes expose pluggables as
                    # interface inventory entries with DESCR "unsupported" but
                    # still provide a real serial number.
                    if not (unsupported_identity and serial):
                        continue

                model = pid or (None if unsupported_identity else description) or None
                module_hint = f"{description} {pid} {port_name}".strip()
                module_type = self._identify_module_type(module_hint)
                if module_type == 'Transceiver':
                    module_type = self._infer_module_type_from_port_name(port_name)

                modules.append({
                    'port_name': port_name,
                    'model': model if model else None,
                    'vendor': 'Cisco',
                    'serial_number': serial if serial else None,
                    'module_type': module_type,
                    'speed_gbps': self._extract_speed_gbps(module_hint)
                })

        except Exception as e:
            logger.error(f"Error parsing Cisco inventory output: {str(e)}")

        return modules

    def _parse_cisco_nxos_transceiver(self, output: str) -> List[Dict]:
        """Parse Cisco NX-OS 'show interface transceiver' output

        NX-OS format is block-based, one block per interface:
        Ethernet1/1
            transceiver is present
            type is 10Gbase-LR
            name is WTD
            part number is RTXM228-402-C40
            serial number is FR210410162
            nominal bitrate is 10300 MBit/sec
        """
        modules = []
        try:
            # Split by interface blocks (lines starting with Ethernet/Eth without leading spaces)
            blocks = re.split(r'\n(?=\S)', output)

            for block in blocks:
                lines = block.strip().split('\n')
                if not lines:
                    continue

                # First line should be interface name
                port_name = lines[0].strip()
                if not re.match(r'^(Ethernet|Eth)\d+/\d+', port_name, re.IGNORECASE):
                    continue

                # Check if transceiver is present
                if 'transceiver is not present' in block.lower():
                    continue

                # Extract fields
                module_type_match = re.search(r'type is\s+(.+)', block, re.IGNORECASE)
                vendor_match = re.search(r'name is\s+(.+)', block, re.IGNORECASE)
                part_number_match = re.search(r'part number is\s+(.+)', block, re.IGNORECASE)
                serial_match = re.search(r'serial number is\s+(.+)', block, re.IGNORECASE)

                module_type_str = module_type_match.group(1).strip() if module_type_match else ''
                vendor = vendor_match.group(1).strip() if vendor_match else None
                part_number = part_number_match.group(1).strip() if part_number_match else None
                serial_number = serial_match.group(1).strip() if serial_match else None

                # Identify module type from "type is" field
                module_type = self._identify_module_type(module_type_str)
                if module_type == 'Transceiver':
                    module_type = self._infer_module_type_from_port_name(port_name)

                # Extract speed
                speed_gbps = self._extract_speed_gbps(module_type_str)

                modules.append({
                    'port_name': port_name,
                    'model': part_number,
                    'vendor': vendor,
                    'serial_number': serial_number,
                    'module_type': module_type,
                    'speed_gbps': speed_gbps
                })

        except Exception as e:
            logger.error(f"Error parsing Cisco NX-OS transceiver output: {str(e)}")

        return modules

    def _collect_alcatel_transceivers(self, connection) -> List[Dict]:
        """Collect Alcatel/Nokia transceivers by querying each port individually

        Uses: info from state interface ethernet-1/X transceiver

        Note: Only queries first 24 ports to avoid timeout (typical switches have
        optical modules on front ports only, with rear ports being copper RJ45)
        """
        modules = []
        try:
            # For Alcatel/Nokia SR Linux, query all ports but use faster timeout
            # Strategy: Query high-speed uplink ports (49-52) first, then regular ports
            # Most optical modules are on uplink ports (last few ports) or scattered throughout
            logger.info(f"Querying Alcatel/Nokia ports ethernet-1/1 to ethernet-1/52")

            # First check uplink ports (49-52) where optical modules are most common
            uplink_ports = list(range(49, 53))  # 49, 50, 51, 52
            # Then check regular ports
            regular_ports = list(range(1, 49))   # 1-48

            all_ports = uplink_ports + regular_ports

            for port_num in all_ports:
                port = f'ethernet-1/{port_num}'
                try:
                    # Use the exact command format provided by user
                    cmd = f'info from state interface {port} transceiver'
                    # Use very short timeout to fail fast on empty/copper ports
                    port_output = connection.send_command_timing(cmd, delay_factor=0.3)

                    # Log first port with optical module for debugging (full output)
                    if len(modules) < 2 and 'form-factor' in port_output.lower():
                        logger.debug(f"Alcatel port {port} FULL output:\n{port_output}")

                    # Parse transceiver info
                    module_info = self._parse_alcatel_transceiver_info(port, port_output)
                    if module_info:
                        modules.append(module_info)
                        logger.info(f"✅ Found optical module on {port}: {module_info}")

                except Exception as e:
                    # Port doesn't exist or has no transceiver - skip silently
                    if port_num in [1, 2, 3, 49, 50, 51, 52]:
                        logger.debug(f"Port {port} error: {str(e)}")
                    continue

            logger.info(f"Collected {len(modules)} optical modules from Alcatel switch")

        except Exception as e:
            logger.error(f"Error collecting Alcatel transceivers: {str(e)}")

        return modules
    
    def _parse_alcatel_transceiver_info(self, port_name: str, output: str) -> Optional[Dict]:
        """Parse Alcatel transceiver info for a single port"""
        try:
            # Check if port has no transceiver
            if 'not equipped' in output.lower() or 'no transceiver' in output.lower() or 'not-present' in output.lower():
                return None

            module = {'port_name': port_name}

            # Extract vendor - SR Linux format: "vendor WTD" (no quotes, no -name suffix)
            # Try vendor-name first (quoted format), then vendor (unquoted format)
            vendor_match = re.search(r'vendor-name\s+"?([^"\n]+)"?', output)
            if not vendor_match:
                vendor_match = re.search(r'^\s*vendor\s+(\S+)', output, re.MULTILINE)
            if vendor_match:
                module['vendor'] = vendor_match.group(1).strip().strip('"')

            # Extract part number (model)
            model_match = re.search(r'vendor-part-number\s+(\S+)', output)
            if model_match:
                module['model'] = model_match.group(1).strip().strip('"')

            # Extract serial number - SR Linux format: "serial-number FR213902505" (no vendor- prefix)
            serial_match = re.search(r'serial-number\s+(\S+)', output)
            if serial_match:
                module['serial_number'] = serial_match.group(1).strip().strip('"')

            # Extract module type from form-factor (SFP/SFPplus/QSFP/etc)
            if 'form-factor' in output:
                form_match = re.search(r'form-factor\s+(\S+)', output)
                if form_match:
                    form_factor = form_match.group(1).strip()
                    module['module_type'] = self._identify_module_type(form_factor)
                    if not module.get('model'):
                        module['model'] = form_factor

            # Extract module type from type field (fallback)
            elif 'type' in output and 'module_type' not in module:
                type_match = re.search(r'type\s+(\S+)', output)
                if type_match:
                    module['module_type'] = self._identify_module_type(type_match.group(1))

            module['speed_gbps'] = None

            # Only keep modules that carry at least one real identifying attribute.
            # A generic "Transceiver" placeholder without vendor/model/serial pollutes the search page.
            has_identity = any(module.get(key) for key in ['vendor', 'model', 'serial_number'])
            if has_identity:
                return module
            return None

        except Exception as e:
            logger.error(f"Error parsing Alcatel transceiver info for {port_name}: {str(e)}", exc_info=True)
            return None
    
    def _parse_juniper_optics(self, output: str) -> List[Dict]:
        """Parse Juniper 'show interfaces diagnostics optics' output."""
        modules = []
        if not output:
            return modules

        blocks = re.split(r'^Physical interface:', output, flags=re.MULTILINE)
        for block in blocks:
            if not block.strip():
                continue

            lines = block.strip().split('\n')
            port_name_raw = lines[0].strip() if lines else ''
            port_name = self._normalize_optical_port_name(port_name_raw)

            vendor = None
            part_number = None
            serial_number = None

            for line in lines[1:]:
                line_lower = line.lower().strip()
                if 'vendor name' in line_lower:
                    vendor = line.split(':', 1)[-1].strip()
                elif 'vendor part number' in line_lower or 'part number' in line_lower:
                    part_number = line.split(':', 1)[-1].strip()
                elif 'vendor serial number' in line_lower or 'serial number' in line_lower:
                    serial_number = line.split(':', 1)[-1].strip()

            module_type = self._infer_module_type_from_port_name(port_name_raw)
            speed = self._extract_speed_gbps(port_name_raw)

            has_identity = any([vendor, part_number, serial_number])
            if has_identity:
                modules.append({
                    'port_name': port_name,
                    'module_type': module_type,
                    'vendor': vendor,
                    'model': part_number,
                    'serial_number': serial_number,
                    'speed_gbps': speed,
                })

        logger.info(f"Parsed {len(modules)} optical modules from Juniper optics output")
        return modules

    def _identify_module_type(self, type_str: str) -> str:
        """Identify module type from description string"""
        if not type_str:
            return 'Unknown'

        type_lower = type_str.lower()

        if 'qsfp28' in type_lower or '100g' in type_lower:
            return 'QSFP28'
        elif 'qsfp+' in type_lower or 'qsfp-plus' in type_lower or 'qsfpplus' in type_lower or '40g' in type_lower:
            return 'QSFP+'
        elif 'qsfp' in type_lower:
            return 'QSFP'
        elif 'sfp+' in type_lower or 'sfp-plus' in type_lower or 'sfpplus' in type_lower or '10g' in type_lower:
            return 'SFP+'
        elif 'sfp' in type_lower:
            return 'SFP'
        else:
            return 'Transceiver'

    def _infer_module_type_from_port_name(self, port_name: str) -> str:
        """Infer a generic optical module type when the platform hides the PID."""
        port_lower = (port_name or '').lower()

        if port_lower.startswith(('hundredgige', 'hundredgig', 'hu')):
            return 'QSFP28'
        if port_lower.startswith(('fortygige', 'fortygig', 'fo')):
            return 'QSFP+'
        if port_lower.startswith(('tengigabitethernet', 'tengige', 'te', 'twentyfivegig', 'twe')):
            return 'SFP+'
        if port_lower.startswith(('gigabitethernet', 'gi', 'fastethernet', 'fa', 'ethernet')):
            return 'SFP'
        return 'Transceiver'

    def _normalize_optical_port_name(self, interface_name: str) -> str:
        """Normalize vendor-specific interface labels to the canonical port token."""
        if not interface_name:
            return interface_name

        cleaned = interface_name.strip()
        match = re.search(r'(\d+(?:/\d+){1,2})$', cleaned)
        if match:
            return match.group(1)
        return cleaned

    def _extract_speed_gbps(self, speed_str: str) -> Optional[int]:
        """Extract speed in Gbps from speed string"""
        try:
            if not speed_str:
                return None
            
            speed_lower = speed_str.lower()
            
            if '100g' in speed_lower or '100000' in speed_lower:
                return 100
            elif '40g' in speed_lower or '40000' in speed_lower:
                return 40
            elif '10g' in speed_lower or '10000' in speed_lower:
                return 10
            elif '1g' in speed_lower or '1000' in speed_lower:
                return 1
            
            return None
        except Exception:
            return None


# Singleton instance
cli_service = CLIService()
