from typing import List, Dict, Optional, Tuple
from models.switch import Switch
from services.switch_manager import switch_manager
from core.security import credential_encryption
from utils.logger import logger
import ipaddress
import asyncio
from concurrent.futures import ThreadPoolExecutor


class SwitchDiscoveryService:
    """Service for discovering and batch adding switches"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=20)

    def _detect_vendor(self, output: str) -> Optional[str]:
        """Detect switch vendor from command output"""
        output_lower = output.lower()

        if 'cisco' in output_lower or 'ios' in output_lower:
            return 'cisco'
        elif 'dell' in output_lower:
            return 'dell'
        elif 'alcatel' in output_lower or 'nokia' in output_lower:
            return 'alcatel'

        return None

    def _detect_role(self, model: str, hostname: str) -> str:
        """Detect switch role based on model and hostname"""
        model_lower = model.lower() if model else ''
        hostname_lower = hostname.lower() if hostname else ''

        # Core switch indicators
        core_keywords = ['core', 'nexus', '6500', '6800', '9000', 'catalyst 6']
        if any(keyword in model_lower or keyword in hostname_lower for keyword in core_keywords):
            return 'core'

        # Aggregation switch indicators
        agg_keywords = ['aggregation', 'agg', 'distribution', '4500', '3850', 'catalyst 4']
        if any(keyword in model_lower or keyword in hostname_lower for keyword in agg_keywords):
            return 'aggregation'

        # Default to access
        return 'access'

    def _get_priority_by_role(self, role: str) -> int:
        """Get default priority based on role"""
        priority_map = {
            'core': 10,
            'aggregation': 30,
            'access': 50
        }
        return priority_map.get(role, 50)

    def _try_connect(self, ip: str, username: str, password: str,
                     enable_password: Optional[str], port: int) -> Optional[Dict]:
        """Try to connect to a switch and gather information"""
        try:
            from netmiko import ConnectHandler

            # Try different device types
            device_types = ['cisco_ios', 'dell_os10', 'alcatel_aos']

            for device_type in device_types:
                try:
                    device_params = {
                        'device_type': device_type,
                        'host': ip,
                        'username': username,
                        'password': password,
                        'port': port,
                        'timeout': 10,
                    }

                    if enable_password and device_type == 'cisco_ios':
                        device_params['secret'] = enable_password

                    with ConnectHandler(**device_params) as conn:
                        # Get device info
                        if device_type == 'cisco_ios':
                            if enable_password:
                                conn.enable()
                            output = conn.send_command('show version')
                            hostname_output = conn.send_command('show running-config | include hostname')
                        else:
                            output = conn.send_command('show version')
                            hostname_output = conn.send_command('show running-config')

                        # Parse hostname
                        hostname = ip  # Default to IP
                        for line in hostname_output.split('\n'):
                            if 'hostname' in line.lower():
                                parts = line.split()
                                if len(parts) >= 2:
                                    hostname = parts[1]
                                    break

                        # Parse model
                        model = 'Unknown'
                        for line in output.split('\n'):
                            if 'model' in line.lower() or 'cisco' in line.lower():
                                model = line.strip()
                                break

                        # Detect vendor
                        vendor = self._detect_vendor(output)
                        if not vendor:
                            if device_type == 'cisco_ios':
                                vendor = 'cisco'
                            elif device_type == 'dell_os10':
                                vendor = 'dell'
                            elif device_type == 'alcatel_aos':
                                vendor = 'alcatel'

                        # Detect role
                        role = self._detect_role(model, hostname)
                        priority = self._get_priority_by_role(role)

                        logger.info(f"Successfully discovered switch at {ip}: {hostname} ({vendor}, {role})")

                        return {
                            'ip_address': ip,
                            'name': hostname,
                            'vendor': vendor,
                            'model': model,
                            'role': role,
                            'priority': priority,
                            'ssh_port': port,
                            'username': username,
                            'password': password,
                            'enable_password': enable_password,
                            'success': True
                        }

                except Exception as e:
                    continue  # Try next device type

            logger.warning(f"Could not connect to {ip} with any device type")
            return None

        except Exception as e:
            logger.error(f"Error connecting to {ip}: {str(e)}")
            return None

    async def discover_switches(
        self,
        ip_range: str,
        credentials: List[Dict[str, str]]
    ) -> List[Dict]:
        """
        Discover switches in an IP range using multiple credentials

        Args:
            ip_range: IP range in format "10.0.0.1-10.0.0.254" or "10.0.0.0/24"
            credentials: List of dicts with keys: username, password, enable_password (optional), port (optional)

        Returns:
            List of discovered switch information
        """
        logger.info(f"Starting switch discovery for range: {ip_range}")

        # Parse IP range
        ip_list = self._parse_ip_range(ip_range)
        logger.info(f"Scanning {len(ip_list)} IP addresses")

        # Create tasks for all IP/credential combinations
        loop = asyncio.get_event_loop()
        tasks = []

        for ip in ip_list:
            for cred in credentials:
                username = cred.get('username')
                password = cred.get('password')
                enable_password = cred.get('enable_password')
                port = cred.get('port', 22)

                if not username or not password:
                    continue

                task = loop.run_in_executor(
                    self.executor,
                    self._try_connect,
                    ip, username, password, enable_password, port
                )
                tasks.append(task)

        # Wait for all discovery attempts
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful discoveries
        discovered = []
        seen_ips = set()

        for result in results:
            if isinstance(result, dict) and result and result.get('success'):
                ip = result['ip_address']
                if ip not in seen_ips:
                    seen_ips.add(ip)
                    discovered.append(result)

        logger.info(f"Discovery complete: found {len(discovered)} switches")
        return discovered

    def _parse_ip_range(self, ip_range: str) -> List[str]:
        """Parse IP range string into list of IPs"""
        try:
            # Check if it's CIDR notation
            if '/' in ip_range:
                network = ipaddress.ip_network(ip_range, strict=False)
                return [str(ip) for ip in network.hosts()]

            # Check if it's range notation (10.0.0.1-10.0.0.254)
            elif '-' in ip_range:
                start_ip, end_ip = ip_range.split('-')
                start_ip = start_ip.strip()
                end_ip = end_ip.strip()

                # If end is just a number, use start's prefix
                if '.' not in end_ip:
                    prefix = '.'.join(start_ip.split('.')[:-1])
                    end_ip = f"{prefix}.{end_ip}"

                start = ipaddress.ip_address(start_ip)
                end = ipaddress.ip_address(end_ip)

                ip_list = []
                current = start
                while current <= end:
                    ip_list.append(str(current))
                    current = ipaddress.ip_address(int(current) + 1)

                return ip_list

            # Single IP
            else:
                return [ip_range.strip()]

        except Exception as e:
            logger.error(f"Error parsing IP range {ip_range}: {str(e)}")
            return []


# Singleton instance
switch_discovery_service = SwitchDiscoveryService()
