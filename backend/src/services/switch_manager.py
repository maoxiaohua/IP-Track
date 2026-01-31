from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
from typing import Optional, Dict
from utils.logger import logger
from core.security import credential_encryption
from services.vendors.base import VendorHandler
from services.vendors.cisco import CiscoHandler
from services.vendors.dell import DellHandler
from services.vendors.alcatel import AlcatelHandler
from models.switch import Switch


class SwitchConnectionError(Exception):
    """Custom exception for switch connection errors"""
    pass


class SwitchManager:
    """Manages SSH connections to network switches"""

    def __init__(self):
        self.vendor_handlers: Dict[str, VendorHandler] = {
            'cisco': CiscoHandler(),
            'dell': DellHandler(),
            'alcatel': AlcatelHandler(),
        }

    def get_vendor_handler(self, vendor: str) -> VendorHandler:
        """Get the appropriate vendor handler"""
        handler = self.vendor_handlers.get(vendor.lower())
        if not handler:
            raise ValueError(f"Unsupported vendor: {vendor}")
        return handler

    def _get_device_params(self, switch: Switch) -> Dict:
        """Prepare device parameters for netmiko connection"""
        # Decrypt credentials
        password = credential_encryption.decrypt(switch.password_encrypted)
        enable_password = None
        if switch.enable_password_encrypted:
            enable_password = credential_encryption.decrypt(switch.enable_password_encrypted)

        # Map vendor to netmiko device type
        device_type_map = {
            'cisco': 'cisco_ios',
            'dell': 'dell_os10',
            'alcatel': 'alcatel_aos',
        }

        device_type = device_type_map.get(switch.vendor.lower(), 'cisco_ios')

        device_params = {
            'device_type': device_type,
            'host': str(switch.ip_address),
            'username': switch.username,
            'password': password,
            'port': switch.ssh_port,
            'timeout': switch.connection_timeout,
            'session_timeout': switch.connection_timeout,
            'blocking_timeout': switch.connection_timeout,
        }

        # Add enable password for Cisco devices
        if switch.vendor.lower() == 'cisco' and enable_password:
            device_params['secret'] = enable_password

        return device_params

    def test_connection(self, switch: Switch) -> Dict[str, any]:
        """
        Test connection to a switch
        Returns dict with success status and details
        """
        try:
            logger.info(f"Testing connection to switch {switch.name} ({switch.ip_address})")

            device_params = self._get_device_params(switch)

            with ConnectHandler(**device_params) as connection:
                # Try to get hostname as a simple test
                output = connection.send_command("show version", read_timeout=10)

                logger.info(f"Successfully connected to switch {switch.name}")
                return {
                    'success': True,
                    'message': 'Connection successful',
                    'details': {
                        'connected': True,
                        'output_length': len(output)
                    }
                }

        except NetmikoAuthenticationException as e:
            logger.error(f"Authentication failed for switch {switch.name}: {str(e)}")
            return {
                'success': False,
                'message': 'Authentication failed',
                'details': {'error': str(e)}
            }

        except NetmikoTimeoutException as e:
            logger.error(f"Connection timeout for switch {switch.name}: {str(e)}")
            return {
                'success': False,
                'message': 'Connection timeout',
                'details': {'error': str(e)}
            }

        except Exception as e:
            logger.error(f"Connection error for switch {switch.name}: {str(e)}")
            return {
                'success': False,
                'message': f'Connection error: {str(e)}',
                'details': {'error': str(e)}
            }

    def execute_command(self, switch: Switch, command: str) -> str:
        """
        Execute a command on a switch and return the output
        Raises SwitchConnectionError on failure
        """
        try:
            logger.debug(f"Executing command on {switch.name}: {command}")

            device_params = self._get_device_params(switch)

            with ConnectHandler(**device_params) as connection:
                # Enter enable mode for Cisco if needed
                if switch.vendor.lower() == 'cisco':
                    if not connection.check_enable_mode():
                        connection.enable()

                output = connection.send_command(command, read_timeout=30)
                logger.debug(f"Command output length: {len(output)} characters")
                return output

        except NetmikoAuthenticationException as e:
            error_msg = f"Authentication failed for switch {switch.name}"
            logger.error(f"{error_msg}: {str(e)}")
            raise SwitchConnectionError(error_msg)

        except NetmikoTimeoutException as e:
            error_msg = f"Connection timeout for switch {switch.name}"
            logger.error(f"{error_msg}: {str(e)}")
            raise SwitchConnectionError(error_msg)

        except Exception as e:
            error_msg = f"Error executing command on switch {switch.name}"
            logger.error(f"{error_msg}: {str(e)}")
            raise SwitchConnectionError(f"{error_msg}: {str(e)}")

    def query_arp_table(self, switch: Switch, target_ip: str) -> Optional[str]:
        """
        Query ARP table on a switch for a specific IP
        Returns MAC address if found, None otherwise
        """
        try:
            handler = self.get_vendor_handler(switch.vendor)
            command = handler.get_arp_command(target_ip)

            output = self.execute_command(switch, command)
            mac_address = handler.parse_arp_output(output, target_ip)

            if mac_address:
                logger.info(f"Found MAC {mac_address} for IP {target_ip} on switch {switch.name}")
            else:
                logger.debug(f"No ARP entry found for IP {target_ip} on switch {switch.name}")

            return mac_address

        except SwitchConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error querying ARP table on {switch.name}: {str(e)}")
            return None

    def query_mac_table(self, switch: Switch, mac_address: str) -> list:
        """
        Query MAC address table on a switch for a specific MAC
        Returns list of port information dicts
        """
        try:
            handler = self.get_vendor_handler(switch.vendor)
            command = handler.get_mac_table_command(mac_address)

            output = self.execute_command(switch, command)
            results = handler.parse_mac_table_output(output, mac_address)

            if results:
                logger.info(f"Found {len(results)} port(s) for MAC {mac_address} on switch {switch.name}")
            else:
                logger.debug(f"No MAC table entry found for {mac_address} on switch {switch.name}")

            return results

        except SwitchConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error querying MAC table on {switch.name}: {str(e)}")
            return []


# Singleton instance
switch_manager = SwitchManager()
