from abc import ABC, abstractmethod
from typing import Optional, Dict, List


class VendorHandler(ABC):
    """Base class for vendor-specific switch command handlers"""

    def __init__(self):
        self.vendor_name = "unknown"

    @abstractmethod
    def get_arp_command(self, ip_address: str) -> str:
        """Get the command to query ARP table for a specific IP"""
        pass

    @abstractmethod
    def get_mac_table_command(self, mac_address: str) -> str:
        """Get the command to query MAC address table for a specific MAC"""
        pass

    @abstractmethod
    def get_mac_table_all_command(self) -> str:
        """Get the command to retrieve the entire MAC address table"""
        pass

    @abstractmethod
    def parse_arp_output(self, output: str, target_ip: str) -> Optional[str]:
        """
        Parse ARP table output and extract MAC address for target IP
        Returns MAC address in normalized format (aa:bb:cc:dd:ee:ff) or None
        """
        pass

    @abstractmethod
    def parse_mac_table_output(self, output: str, mac_address: str) -> List[Dict[str, any]]:
        """
        Parse MAC address table output and extract port information
        Returns list of dicts with keys: port, vlan, mac
        """
        pass

    @abstractmethod
    def normalize_mac(self, mac_address: str) -> str:
        """
        Normalize MAC address to standard format (aa:bb:cc:dd:ee:ff)
        """
        pass

    @abstractmethod
    def format_mac_for_query(self, mac_address: str) -> str:
        """
        Format MAC address for use in vendor-specific commands
        """
        pass

    def get_enable_command(self) -> Optional[str]:
        """Get the command to enter privileged mode (if needed)"""
        return None
