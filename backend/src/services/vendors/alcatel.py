from services.vendors.base import VendorHandler
from typing import Optional, Dict, List
import re


class AlcatelHandler(VendorHandler):
    """Alcatel-Lucent (Nokia) switch command handler"""

    def __init__(self):
        super().__init__()
        self.vendor_name = "alcatel"

    def get_arp_command(self, ip_address: str) -> str:
        """Get command to query ARP table for specific IP"""
        return f"show arp"

    def get_arp_command_fallback(self, ip_address: str) -> str:
        """Fallback command - Alcatel uses 'show arp' primarily"""
        return None

    def get_mac_table_command(self, mac_address: str) -> str:
        """Get command to query MAC address table"""
        formatted_mac = self.format_mac_for_query(mac_address)
        # Alcatel uses show mac-address or show mac-learning
        return f"show mac-address {formatted_mac}"

    def get_mac_table_all_command(self) -> str:
        """Get command to retrieve entire MAC address table"""
        return "show mac-address"

    def normalize_mac(self, mac_address: str) -> str:
        """
        Normalize MAC address to aa:bb:cc:dd:ee:ff format
        Alcatel format: aa:bb:cc:dd:ee:ff (standard format)
        """
        # Remove all non-hex characters
        mac_clean = re.sub(r'[^0-9a-fA-F]', '', mac_address)

        if len(mac_clean) != 12:
            raise ValueError(f"Invalid MAC address: {mac_address}")

        # Convert to standard format with colons
        return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)]).lower()

    def format_mac_for_query(self, mac_address: str) -> str:
        """
        Format MAC address for Alcatel commands (aa:bb:cc:dd:ee:ff)
        Alcatel uses standard colon-separated format
        """
        return self.normalize_mac(mac_address)

    def parse_arp_output(self, output: str, target_ip: str) -> Optional[str]:
        """
        Parse Alcatel ARP table output
        Example output:
        IP Address       Physical Address  Type       Age (sec) VLAN  Port
        ---------------------------------------------------------------------------
        192.168.1.100    00:50:56:c0:00:01 dynamic    3600      1     1/1/1
        """
        lines = output.strip().split('\n')

        for line in lines:
            if target_ip in line:
                # Alcatel ARP format: IP_Address Physical_Address Type Age VLAN Port
                parts = line.split()
                if len(parts) >= 2:
                    # Try different positions for MAC address
                    for part in parts:
                        # Look for MAC address pattern (contains colons or dots)
                        if (':' in part or '.' in part) and part != target_ip:
                            # Check if it looks like a MAC (12 hex chars)
                            mac_clean = part.replace(':', '').replace('.', '').replace('-', '')
                            if len(mac_clean) == 12 and all(c in '0123456789abcdefABCDEF' for c in mac_clean):
                                try:
                                    return self.normalize_mac(part)
                                except ValueError:
                                    continue

        return None

    def parse_mac_table_output(self, output: str, mac_address: str) -> List[Dict[str, any]]:
        """
        Parse Alcatel MAC address table output
        Example output from 'show mac-address':
        MAC Address         VLAN    Port           Type
        ---------------------------------------------------
        00:50:56:c0:00:01   1       1/1/1          learned

        Or from 'show mac-learning':
        vlan   mac                 port      age
        -----------------------------------------------
        1      00:50:56:c0:00:01   1/1/1     0
        """
        results = []
        lines = output.strip().split('\n')

        # Skip header lines
        data_started = False
        for line in lines:
            # Skip header separator lines
            if '---' in line or 'MAC' in line and ('Address' in line or 'VLAN' in line):
                data_started = True
                continue

            if not data_started or not line.strip():
                continue

            # Parse data line
            parts = line.split()
            if len(parts) >= 3:
                # Try different column orders (Alcatel has variations)
                # Format 1: MAC VLAN Port Type
                # Format 2: VLAN MAC Port Age

                mac = None
                vlan = None
                port = None

                for i, part in enumerate(parts):
                    # Identify MAC address (contains : or . and is 12 hex chars)
                    if ':' in part or '.' in part:
                        mac_clean = part.replace(':', '').replace('.', '').replace('-', '')
                        if len(mac_clean) == 12 and all(c in '0123456789abcdefABCDEF' for c in mac_clean):
                            mac = part
                    # Identify VLAN (should be numeric and reasonable)
                    elif part.isdigit() and int(part) < 4096 and vlan is None:
                        vlan = int(part)
                    # Identify port (contains /)
                    elif '/' in part and port is None:
                        port = part

                if not mac or not port:
                    continue

                # Validate and normalize MAC
                try:
                    normalized_mac = self.normalize_mac(mac)
                    target_normalized = self.normalize_mac(mac_address)

                    if normalized_mac == target_normalized:
                        results.append({
                            'port': port,
                            'vlan': vlan if vlan else 1,  # Default to VLAN 1
                            'mac': normalized_mac
                        })
                except ValueError:
                    continue

        return results
