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
        return f"show ip arp | match {ip_address}"

    def get_mac_table_command(self, mac_address: str) -> str:
        """Get command to query MAC address table"""
        formatted_mac = self.format_mac_for_query(mac_address)
        return f"show mac-address-table address {formatted_mac}"

    def get_mac_table_all_command(self) -> str:
        """Get command to retrieve entire MAC address table"""
        return "show mac-address-table"

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
        192.168.1.100   00:50:56:c0:00:01   1       Dynamic   Vlan1
        """
        lines = output.strip().split('\n')

        for line in lines:
            if target_ip in line:
                # Alcatel ARP format varies, but MAC is typically recognizable by colons
                parts = line.split()
                for part in parts:
                    # Look for MAC address pattern (contains colons and is right length)
                    if ':' in part and len(part.replace(':', '')) == 12:
                        try:
                            return self.normalize_mac(part)
                        except ValueError:
                            continue

        return None

    def parse_mac_table_output(self, output: str, mac_address: str) -> List[Dict[str, any]]:
        """
        Parse Alcatel MAC address table output
        Example output:
        Vlan  Mac Address         Type      Port
        ----  -----------------   -------   ----
        1     00:50:56:c0:00:01   Learned   1/1/1
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
