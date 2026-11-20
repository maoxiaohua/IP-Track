from services.vendors.base import VendorHandler
from services.cli_service import cli_service
from typing import Optional, Dict, List
import re


class H3CHandler(VendorHandler):
    """H3C Comware (V5/V7) switch command handler"""

    def __init__(self):
        super().__init__()
        self.vendor_name = "h3c"

    def get_arp_command(self, ip_address: str) -> str:
        """Get command to query ARP table for specific IP"""
        return f"display arp {ip_address}"

    def get_arp_command_fallback(self, ip_address: str) -> str:
        """Fallback: dump the whole ARP table when per-IP query is unavailable"""
        return "display arp all"

    def get_mac_table_command(self, mac_address: str) -> str:
        """Get command to query MAC address table for one MAC"""
        return f"display mac-address {self.format_mac_for_query(mac_address)}"

    def get_mac_table_all_command(self) -> str:
        """Get command to retrieve entire MAC address table"""
        return "display mac-address"

    def normalize_mac(self, mac_address: str) -> str:
        """Normalize to aa:bb:cc:dd:ee:ff (Comware uses aabb-ccdd-eeff)"""
        mac_clean = re.sub(r'[^0-9a-fA-F]', '', mac_address or '')
        if len(mac_clean) != 12:
            raise ValueError(f"Invalid MAC address: {mac_address}")
        return ':'.join(mac_clean[i:i + 2] for i in range(0, 12, 2)).lower()

    def format_mac_for_query(self, mac_address: str) -> str:
        """Format MAC for Comware commands: H-H-H in 4-hex groups"""
        compact = self.normalize_mac(mac_address).replace(':', '')
        return f"{compact[0:4]}-{compact[4:8]}-{compact[8:12]}"

    def parse_arp_output(self, output: str, target_ip: str) -> Optional[str]:
        data = self.parse_arp_output_with_port(output, target_ip)
        return data['mac'] if data else None

    def parse_arp_output_with_port(self, output: str, target_ip: str) -> Optional[Dict[str, str]]:
        """Reuse the shared h3c_comware parser so CLI batch and live lookup stay in sync"""
        for entry in cli_service._parse_h3c_comware_arp_table(output):
            if entry.get('ip_address') == target_ip:
                return {
                    'mac': entry['mac_address'],
                    'port': entry.get('interface') or None,
                    'vlan': entry.get('vlan_id'),
                }
        return None

    def parse_mac_table_output(self, output: str, mac_address: str) -> List[Dict[str, any]]:
        """Reuse the shared h3c_comware parser"""
        try:
            target = self.normalize_mac(mac_address)
        except ValueError:
            return []

        results = []
        for entry in cli_service._parse_h3c_comware_mac_table(output):
            if entry.get('mac_address') == target:
                results.append({
                    'port': entry['port_name'],
                    'vlan': entry.get('vlan_id'),
                    'mac': entry['mac_address'],
                })
        return results
