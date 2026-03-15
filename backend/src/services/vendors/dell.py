from services.vendors.base import VendorHandler
from typing import Optional, Dict, List
import re


class DellHandler(VendorHandler):
    """Dell Networking OS switch command handler"""

    def __init__(self):
        super().__init__()
        self.vendor_name = "dell"

    def get_arp_command(self, ip_address: str) -> str:
        """Get command to query ARP table for specific IP"""
        # Dell uses 'show arp' primarily
        return f"show arp {ip_address}"

    def get_arp_command_fallback(self, ip_address: str) -> str:
        """Fallback command for Dell switches"""
        return f"show ip arp {ip_address}"

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
        Dell format: aa:bb:cc:dd:ee:ff (already standard)
        """
        # Remove all non-hex characters
        mac_clean = re.sub(r'[^0-9a-fA-F]', '', mac_address)

        if len(mac_clean) != 12:
            raise ValueError(f"Invalid MAC address: {mac_address}")

        # Convert to standard format with colons
        return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)]).lower()

    def format_mac_for_query(self, mac_address: str) -> str:
        """
        Format MAC address for Dell commands (aa:bb:cc:dd:ee:ff)
        Dell uses standard colon-separated format
        """
        return self.normalize_mac(mac_address)

    def parse_arp_output(self, output: str, target_ip: str) -> Optional[str]:
        """
        Parse Dell ARP table output and extract MAC address

        Example output (S5232):
        Address        Hardware address    Interface                     Egress Interface
        ------------------------------------------------------------------------------------------
        10.71.193.15   50:e0:ef:73:8f:f2   ethernet1/1/2                 ethernet1/1/2

        Example output (older Dell):
        192.168.1.100   00:50:56:c0:00:01   Vlan 1          Dynamic
        """
        lines = output.strip().split('\n')

        for line in lines:
            if target_ip in line:
                parts = line.split()
                if len(parts) >= 2:
                    # MAC address is typically the 2nd field
                    mac = parts[1]
                    # Validate it looks like a MAC (contains colons)
                    if ':' in mac and len(mac.replace(':', '')) == 12:
                        return self.normalize_mac(mac)

        return None

    def parse_arp_output_with_port(self, output: str, target_ip: str) -> Optional[Dict[str, str]]:
        """
        Parse Dell ARP output and extract both MAC and port information
        Returns dict with 'mac', 'port', and 'vlan' if available

        For Dell S5232 and similar models that show port in ARP output
        """
        lines = output.strip().split('\n')

        for line in lines:
            if target_ip in line:
                parts = line.split()
                if len(parts) >= 4:
                    # S5232 format: Address Hardware_address Interface Egress_Interface
                    # parts[0] = IP, parts[1] = MAC, parts[2] = Interface, parts[3] = Egress Interface
                    mac = parts[1]

                    # Validate MAC format
                    if ':' in mac and len(mac.replace(':', '')) == 12:
                        # Use Egress Interface if available, otherwise Interface
                        port = parts[3] if len(parts) >= 4 else parts[2]

                        return {
                            'mac': self.normalize_mac(mac),
                            'port': port,
                            'vlan': None  # Dell S5232 doesn't show VLAN in ARP output
                        }

        return None

    def parse_mac_table_output(self, output: str, mac_address: str) -> List[Dict[str, any]]:
        """
        Parse Dell MAC address table output
        Example output:
        VlanId  Mac Address         Type      Interface
        ------  -----------------   -------   ---------
        1       00:50:56:c0:00:01   Dynamic   ethernet 1/g1

        Or:
        Vlan ID    MAC Address         Interface              Type
        -------    -----------------   ---------------------  ------
        10         00:11:22:33:44:55   GigabitEthernet 1/0/1  Dynamic
        """
        results = []
        lines = output.strip().split('\n')

        # Skip header lines
        data_started = False
        for line in lines:
            # Skip until we find the data section
            if '------' in line or '-------' in line:
                data_started = True
                continue

            if 'VlanId' in line or 'Vlan ID' in line or 'Mac Address' in line:
                continue

            if not data_started or not line.strip():
                continue

            # Parse data line
            parts = line.split()
            if len(parts) >= 4:
                vlan = parts[0]
                mac = parts[1]
                # Port could be parts[3] or combination of parts[3] and parts[4]
                # Example: "ethernet 1/g1" or "GigabitEthernet 1/0/1" or just "Gi1/0/1"
                if len(parts) >= 4:
                    if '/' in parts[3]:
                        port = parts[3]
                    elif len(parts) >= 5 and '/' in parts[4]:
                        port = parts[4]  # Skip "ethernet" or "GigabitEthernet" prefix
                    else:
                        port = parts[3]
                else:
                    continue

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
