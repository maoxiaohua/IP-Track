from services.vendors.base import VendorHandler
from typing import Optional, Dict, List
import re


class CiscoHandler(VendorHandler):
    """Cisco IOS/IOS-XE switch command handler"""

    def __init__(self):
        super().__init__()
        self.vendor_name = "cisco"

    def get_arp_command(self, ip_address: str) -> str:
        """Get command to query ARP table for specific IP"""
        return f"show ip arp | include {ip_address}"

    def get_mac_table_command(self, mac_address: str) -> str:
        """Get command to query MAC address table"""
        formatted_mac = self.format_mac_for_query(mac_address)
        return f"show mac address-table address {formatted_mac}"

    def get_mac_table_all_command(self) -> str:
        """Get command to retrieve entire MAC address table"""
        return "show mac address-table"

    def get_enable_command(self) -> Optional[str]:
        """Cisco requires enable mode for privileged commands"""
        return "enable"

    def normalize_mac(self, mac_address: str) -> str:
        """
        Normalize MAC address to aa:bb:cc:dd:ee:ff format
        Cisco format: aaaa.bbbb.cccc
        """
        # Remove all non-hex characters
        mac_clean = re.sub(r'[^0-9a-fA-F]', '', mac_address)

        if len(mac_clean) != 12:
            raise ValueError(f"Invalid MAC address: {mac_address}")

        # Convert to standard format with colons
        return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)]).lower()

    def format_mac_for_query(self, mac_address: str) -> str:
        """
        Format MAC address for Cisco commands (aaaa.bbbb.cccc)
        Input: aa:bb:cc:dd:ee:ff or any format
        """
        # Normalize first, then convert to Cisco format
        normalized = self.normalize_mac(mac_address)
        mac_clean = normalized.replace(':', '')

        # Convert to Cisco dotted format: aaaa.bbbb.cccc
        return f"{mac_clean[0:4]}.{mac_clean[4:8]}.{mac_clean[8:12]}"

    def parse_arp_output(self, output: str, target_ip: str) -> Optional[str]:
        """
        Parse Cisco ARP table output
        Example output:
        Internet  192.168.1.100   12   0050.56c0.0001  ARPA   Vlan1
        """
        lines = output.strip().split('\n')

        for line in lines:
            if target_ip in line:
                # Cisco ARP format: Protocol Address Age(min) Hardware_Addr Type Interface
                parts = line.split()
                if len(parts) >= 4:
                    # MAC address is typically the 4th field
                    mac = parts[3]
                    # Validate it looks like a MAC (contains dots for Cisco)
                    if '.' in mac and len(mac.replace('.', '')) == 12:
                        return self.normalize_mac(mac)

        return None

    def parse_mac_table_output(self, output: str, mac_address: str) -> List[Dict[str, any]]:
        """
        Parse Cisco MAC address table output
        Example output:
        Vlan    Mac Address       Type        Ports
        ----    -----------       --------    -----
          1     0050.56c0.0001    DYNAMIC     Gi1/0/1
        """
        results = []
        lines = output.strip().split('\n')

        # Skip header lines
        data_started = False
        for line in lines:
            # Skip until we find the data section
            if '----' in line or 'Vlan' in line and 'Mac Address' in line:
                data_started = True
                continue

            if not data_started or not line.strip():
                continue

            # Parse data line
            parts = line.split()
            if len(parts) >= 4:
                vlan = parts[0]
                mac = parts[1]
                port = parts[3]

                # Validate VLAN is numeric
                try:
                    vlan_id = int(vlan)
                except ValueError:
                    continue

                # Normalize MAC and check if it matches
                try:
                    normalized_mac = self.normalize_mac(mac)
                    target_normalized = self.normalize_mac(mac_address)

                    if normalized_mac == target_normalized:
                        results.append({
                            'port': port,
                            'vlan': vlan_id,
                            'mac': normalized_mac
                        })
                except ValueError:
                    continue

        return results
