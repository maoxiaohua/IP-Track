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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from utils.logger import logger
from core.security import decrypt_password
from fnmatch import fnmatch


class CLIService:
    """Service for collecting data from switches via SSH CLI"""

    def __init__(self):
        logger.info("CLI service initialized")

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

    def _create_ssh_connection(
        self,
        host: str,
        username: str,
        password: str,
        device_type: str = 'dell_os10',
        port: int = 22,
        timeout: int = 30,
        enable_secret: str = None
    ) -> Optional[ConnectHandler]:
        """
        Create SSH connection to network device

        Args:
            host: Device IP address
            username: SSH username
            password: SSH password
            device_type: Device type (dell_os10, cisco_ios, etc.)
            port: SSH port (default 22)
            timeout: Connection timeout in seconds
            enable_secret: Enable password (for Cisco/Dell Force10)

        Returns:
            ConnectHandler object or None if connection fails
        """
        try:
            device = {
                'device_type': device_type,
                'host': host,
                'username': username,
                'password': password,
                'port': port,
                'timeout': timeout,
                'session_timeout': timeout,
                'conn_timeout': timeout,
            }

            # Add enable secret if provided (for Cisco and Dell Force10)
            if enable_secret and device_type in ['cisco_ios', 'cisco_xe', 'dell_force10']:
                device['secret'] = enable_secret
                logger.debug(f"Enable password provided for {device_type} on {host}")
            elif device_type in ['cisco_ios', 'cisco_xe', 'dell_force10']:
                logger.warning(f"No enable password provided for {device_type} on {host} - commands may fail")

            logger.debug(f"Connecting to {host} via SSH as {username}")
            connection = ConnectHandler(**device)
            logger.info(f"✅ SSH connection established to {host}")

            # Enable privileged mode for devices that require it
            if device_type in ['cisco_ios', 'cisco_xe', 'dell_force10']:
                try:
                    # For Dell Force10, use send_command_timing throughout to avoid prompt issues
                    if device_type == 'dell_force10':
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

            return connection

        except Exception as e:
            logger.error(f"❌ SSH connection failed to {host}: {str(e)}")
            return None

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

    def _parse_nokia_7220_arp_table(self, output: str) -> List[Dict]:
        """
        Parse Nokia 7220 'show arpnd arp-entries' output

        Example output format:
        +-------------------+---------------+----------------+--------+---------------------+
        | Interface         | Subinterface  | Neighbor       | Origin | Link layer address  |
        +===================+===============+================+========+=====================+
        | ethernet-1/51     | 0             | 10.71.194.130  | dynamic| 8C:47:BE:B1:50:91   |
        | irb4              | 0             | 10.71.207.25   | dynamic| A8:1E:84:F3:C8:43   |

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
                ip_address = parts[2]          # 10.71.194.130
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
        10.71.197.1     4c:62:cd:37:f4:3d Dynamic  ies-vlan235       0d 00:00:23
        10.71.197.2     c8:f7:50:5c:96:c1 Dynamic  ies-vlan235       0d 00:00:13
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

                # Match OS Version - e.g., "OS Version: 10.5.1.0"
                version_match = re.search(r'OS\s+Version\s*[:=]\s*(.+)', line, re.IGNORECASE)
                if version_match:
                    version = version_match.group(1).strip()
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

            # Find matching template
            template = self._find_matching_template(vendor, model, name, templates)

            if not template:
                logger.warning(f"No command template found for {vendor} {model} (name: {name})")
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

            # Create SSH connection (with enable password if available)
            connection = self._create_ssh_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=template['device_type'],
                port=switch_config.get('ssh_port', 22),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret
            )

            if not connection:
                logger.error(f"Failed to establish SSH connection to {switch_ip}")
                return []

            # Try main command first
            command = template['mac_command']
            logger.info(f"Executing MAC command on {switch_ip}: {command}")

            try:
                # For Dell Force10, always use send_command_timing to avoid prompt issues
                if template.get('device_type') == 'dell_force10':
                    output = connection.send_command_timing(command, delay_factor=4, max_loops=200)
                else:
                    # Use send_command_timing for devices with problematic prompts
                    try:
                        output = connection.send_command(command, read_timeout=90)
                    except Exception as cmd_error:
                        # Fallback to send_command_timing if send_command fails
                        logger.debug(f"send_command failed, trying send_command_timing: {str(cmd_error)[:100]}")
                        output = connection.send_command_timing(command, delay_factor=2, max_loops=150)

                # Debug: Log command output for troubleshooting
                logger.debug(f"MAC command output from {switch_ip} ({len(output)} chars):\n{output[:500]}")

                mac_entries = parser(output)

                if mac_entries:
                    logger.info(f"✅ Collected {len(mac_entries)} MAC entries from {switch_ip} via CLI (main command)")
                    return mac_entries
                else:
                    logger.warning(f"Main MAC command returned 0 entries from {switch_ip}, trying fallback commands...")
                    logger.warning(f"First 500 chars of output:\n{output[:500]}")
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
                            # Remove expect_string to let Netmiko auto-detect the prompt
                            output = connection.send_command(fallback_cmd, read_timeout=90)

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
            return []

        except Exception as e:
            logger.error(f"Failed to collect MAC table via CLI from {switch_ip}: {str(e)}")
            return []

        finally:
            if connection:
                try:
                    connection.disconnect()
                    logger.debug(f"SSH connection closed to {switch_ip}")
                except:
                    pass

    def _find_matching_template(
        self,
        vendor: str,
        model: str,
        name: str,
        templates: Optional[List[Dict]] = None
    ) -> Optional[Dict]:
        """
        Find matching command template for a switch

        Args:
            vendor: Switch vendor
            model: Switch model
            name: Switch name
            templates: Optional list of templates from database

        Returns:
            Matching template dict or None
        """
        if not templates:
            # Fallback to hardcoded templates
            templates = self._get_builtin_templates()

        vendor_lower = vendor.lower()
        model_lower = model.lower()
        name_lower = name.lower()

        # Sort by priority (descending)
        sorted_templates = sorted(templates, key=lambda t: t.get('priority', 100), reverse=True)

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
            # Fallback to basic templates
            return [
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
                    'arp_parser_type': 'cisco_ios',
                    'arp_enabled': True,
                    'mac_command': 'show mac address-table',
                    'mac_parser_type': 'cisco_ios',
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

            # Find matching template
            template = self._find_matching_template(vendor, model, name, templates)

            if not template:
                logger.warning(f"No command template found for {vendor} {model} (name: {name})")
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

            # Create SSH connection (with enable password if available)
            connection = self._create_ssh_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=template['device_type'],
                port=switch_config.get('ssh_port', 22),
                timeout=switch_config.get('connection_timeout', 30),
                enable_secret=enable_secret
            )

            if not connection:
                logger.error(f"Failed to establish SSH connection to {switch_ip}")
                return []

            # Try main command first
            command = template['arp_command']
            logger.info(f"Executing ARP command on {switch_ip}: {command}")

            try:
                # Use send_command_timing for devices with problematic prompts
                # This uses delays instead of pattern matching
                try:
                    output = connection.send_command(command, read_timeout=90)
                except Exception as cmd_error:
                    # Fallback to send_command_timing if send_command fails
                    logger.debug(f"send_command failed, trying send_command_timing: {str(cmd_error)[:100]}")
                    output = connection.send_command_timing(command, delay_factor=2, max_loops=150)

                arp_entries = parser(output)

                # Debug: Log first 1000 chars of output if parsing returns 0 results for Dell Force10
                if not arp_entries and template.get('device_type') == 'dell_force10':
                    logger.warning(f"Dell Force10 '{command}' parsing returned 0 entries. Output sample (first 1000 chars):\n{output[:1000]}")

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
                            # Remove expect_string to let Netmiko auto-detect the prompt
                            output = connection.send_command(fallback_cmd, read_timeout=90)

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
            return []

        except Exception as e:
            logger.error(f"Failed to collect ARP table via CLI from {switch_ip}: {str(e)}")
            return []

        finally:
            if connection:
                try:
                    connection.disconnect()
                    logger.debug(f"SSH connection closed to {switch_ip}")
                except:
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

            if not command or not parser:
                logger.debug(f"No device info CLI command available for {vendor} {model}")
                return None

            # Decrypt password
            password = decrypt_password(switch_config['password_encrypted'])

            # Establish SSH connection
            device_type = switch_config.get('device_type', 'nokia_sros')
            connection = self._create_ssh_connection(
                host=switch_ip,
                username=switch_config['username'],
                password=password,
                device_type=device_type,
                port=switch_config.get('ssh_port', 22),
                timeout=switch_config.get('connection_timeout', 30)
            )

            if not connection:
                logger.error(f"Failed to establish SSH connection to {switch_ip}")
                return None

            # Execute command
            logger.info(f"Executing device info command on {switch_ip}: {command}")
            # Remove expect_string to let Netmiko auto-detect the prompt
            output = connection.send_command(command, read_timeout=60)

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
                    logger.debug(f"SSH connection closed to {switch_ip}")
                except:
                    pass

    def _get_parser(self, parser_type: Optional[str], data_type: str):
        """
        Get parser function by type

        Args:
            parser_type: Parser type name (e.g., 'nokia_7220', 'dell_os10')
            data_type: 'arp' or 'mac'

        Returns:
            Parser function or None
        """
        if not parser_type:
            return None

        parser_map = {
            'nokia_7220': {
                'arp': self._parse_nokia_7220_arp_table,
                'mac': self._parse_nokia_7220_mac_table
            },
            'nokia_7250': {
                'arp': self._parse_nokia_7250_arp_table,
                'mac': self._parse_nokia_7250_mac_table
            },
            'dell_os10': {
                'arp': self._parse_dell_os10_arp_table,
                'mac': self._parse_dell_os10_mac_table
            },
            'cisco_ios': {
                'arp': self._parse_cisco_ios_arp_table,
                'mac': self._parse_cisco_ios_mac_table
            },
            'juniper': {
                'arp': self._parse_juniper_arp_table,
                'mac': self._parse_juniper_mac_table
            }
        }

        return parser_map.get(parser_type, {}).get(data_type)

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
            # Create SSH connection
            from core.security import decrypt_password

            connection = self._create_ssh_connection(
                switch_ip,
                cli_config['username'],
                decrypt_password(cli_config['password_encrypted']),
                cli_config.get('device_type', 'cisco_ios'),
                cli_config.get('ssh_port', 22),
                cli_config.get('connection_timeout', 30),
                decrypt_password(cli_config.get('enable_password_encrypted')) if cli_config.get('enable_password_encrypted') else None
            )
            
            if not connection:
                logger.error(f"Failed to establish SSH connection to {switch_ip}")
                return []
            
            modules = []
            vendor_lower = vendor.lower() if vendor else ''
            model_upper = model.upper() if model else ''
            
            # Dell S3048/S4048: show inventory media
            if vendor_lower == 'dell' and ('3048' in model_upper or '4048' in model_upper or 's3048' in model_upper or 's4048' in model_upper):
                logger.info(f"Using 'show inventory media' for Dell {model}")
                command = 'show inventory media'
                output = connection.send_command_timing(command, delay_factor=2)
                logger.debug(f"Command output length: {len(output)} bytes")
                logger.debug(f"Dell inventory media output:\n{output}")
                modules = self._parse_dell_inventory_media(output)
            
            # Dell S9100: show interface transceiver
            elif vendor_lower == 'dell' and ('9100' in model_upper or 's9100' in model_upper):
                logger.info(f"Using 'show interface transceiver' for Dell {model}")
                command = 'show interface transceiver'
                output = connection.send_command_timing(command, delay_factor=2)
                logger.debug(f"Command output length: {len(output)} bytes")
                modules = self._parse_dell_transceiver(output)
            
            # Cisco: show interfaces transceiver
            elif vendor_lower == 'cisco':
                logger.info(f"Using 'show interfaces transceiver' for Cisco {model}")
                command = 'show interfaces transceiver'
                output = connection.send_command_timing(command, delay_factor=2)
                logger.debug(f"Command output length: {len(output)} bytes")
                modules = self._parse_cisco_transceiver(output)
            
            # Alcatel/Nokia: per-port query
            elif vendor_lower in ['alcatel', 'nokia', 'alcatel-lucent']:
                logger.info(f"Using per-port transceiver query for Alcatel/Nokia {model}")
                modules = self._collect_alcatel_transceivers(connection)
            
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

                # Expected format: [Slot, Port, Type, Media, Serial_Number, Dell_Qualified]
                # Sometimes Type column might be empty, so we need flexible parsing
                if len(parts) < 4:
                    continue

                try:
                    slot = parts[0].strip()
                    port = parts[1].strip()

                    # Check if we have module type/media info
                    if len(parts) >= 5:
                        module_type_str = parts[2].strip()
                        media = parts[3].strip()
                        serial = parts[4].strip() if len(parts) > 4 else None

                        # Build port name as "Port {port}"
                        port_name = f"Port {port}"

                        module = {
                            'port_name': port_name,
                            'module_type': self._identify_module_type(module_type_str),
                            'model': media if media else module_type_str,
                            'serial_number': serial,
                            'vendor': None,  # Not available in this output format
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
        """Parse Dell 'show interface transceiver' output"""
        modules = []
        try:
            lines = output.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('Port') or line.startswith('---'):
                    continue
                
                # Example: Gi 1/1    SFP-10GBase-SR    FINISAR CORP.    FTLX8571D3BCL-FC    1234567
                parts = line.split()
                if len(parts) >= 4:
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
            logger.error(f"Error parsing Dell transceiver output: {str(e)}")
        
        return modules
    
    def _parse_cisco_transceiver(self, output: str) -> List[Dict]:
        """Parse Cisco 'show interfaces transceiver' output"""
        modules = []
        try:
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
                module['vendor'] = vendor_match.group(1).strip()

            # Extract part number (model)
            model_match = re.search(r'vendor-part-number\s+(\S+)', output)
            if model_match:
                module['model'] = model_match.group(1).strip()

            # Extract serial number - SR Linux format: "serial-number FR213902505" (no vendor- prefix)
            serial_match = re.search(r'serial-number\s+(\S+)', output)
            if serial_match:
                module['serial_number'] = serial_match.group(1).strip()

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

            # Return module only if we have at least one identifying field
            if 'vendor' in module or 'model' in module or 'serial_number' in module or 'module_type' in module:
                return module
            return None

        except Exception as e:
            logger.error(f"Error parsing Alcatel transceiver info for {port_name}: {str(e)}", exc_info=True)
            return None
    
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
        except:
            return None


# Singleton instance
cli_service = CLIService()
