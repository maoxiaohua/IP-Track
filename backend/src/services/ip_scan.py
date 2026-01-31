from typing import Optional, Dict, List
import asyncio
import subprocess
import socket
import re
import time
from concurrent.futures import ThreadPoolExecutor
from utils.logger import logger


class IPScanService:
    """Service for scanning IP addresses"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=20)

    def _ping_ip(self, ip: str, timeout: int = 2) -> tuple[bool, Optional[int]]:
        """
        Ping an IP address to check reachability
        Returns: (is_reachable, response_time_ms)
        """
        try:
            # Use ping command
            cmd = ['ping', '-c', '1', '-W', str(timeout), ip]
            start_time = time.time()
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 1
            )
            elapsed = int((time.time() - start_time) * 1000)

            if result.returncode == 0:
                # Parse response time from output
                output = result.stdout.decode()
                match = re.search(r'time[=<](\d+\.?\d*)\s*ms', output)
                if match:
                    response_time = int(float(match.group(1)))
                else:
                    response_time = elapsed
                return (True, response_time)
            else:
                return (False, None)

        except Exception as e:
            logger.debug(f"Ping failed for {ip}: {str(e)}")
            return (False, None)

    def _resolve_hostname(self, ip: str) -> Optional[str]:
        """
        Reverse DNS lookup to get hostname
        """
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except Exception:
            return None

    def _get_mac_address(self, ip: str) -> Optional[str]:
        """
        Get MAC address using ARP table
        """
        try:
            # Try to read from ARP cache
            result = subprocess.run(
                ['arp', '-n', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2
            )

            if result.returncode == 0:
                output = result.stdout.decode()
                # Parse MAC address from ARP output
                # Format: 192.168.1.1 ether 00:11:22:33:44:55 C eth0
                match = re.search(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})', output)
                if match:
                    mac = match.group(0).replace('-', ':').lower()
                    return mac

            return None

        except Exception as e:
            logger.debug(f"MAC lookup failed for {ip}: {str(e)}")
            return None

    def _detect_os(self, ip: str) -> Dict[str, Optional[str]]:
        """
        Detect operating system using nmap
        Returns: {os_type, os_name, os_version, os_vendor}
        """
        try:
            # Check if nmap is available
            result = subprocess.run(
                ['which', 'nmap'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            if result.returncode != 0:
                logger.debug("nmap not available, skipping OS detection")
                return self._detect_os_simple(ip)

            # Run nmap OS detection
            result = subprocess.run(
                ['nmap', '-O', '--osscan-guess', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )

            if result.returncode == 0:
                output = result.stdout.decode()
                return self._parse_nmap_output(output)

            return self._detect_os_simple(ip)

        except Exception as e:
            logger.debug(f"OS detection failed for {ip}: {str(e)}")
            return self._detect_os_simple(ip)

    def _detect_os_simple(self, ip: str) -> Dict[str, Optional[str]]:
        """
        Simple OS detection using TTL values
        """
        try:
            result = subprocess.run(
                ['ping', '-c', '1', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3
            )

            if result.returncode == 0:
                output = result.stdout.decode()
                # Parse TTL value
                match = re.search(r'ttl[=<](\d+)', output, re.IGNORECASE)
                if match:
                    ttl = int(match.group(1))

                    # Guess OS based on TTL
                    if ttl <= 64:
                        return {
                            'os_type': 'linux',
                            'os_name': 'Linux/Unix',
                            'os_version': None,
                            'os_vendor': None
                        }
                    elif ttl <= 128:
                        return {
                            'os_type': 'windows',
                            'os_name': 'Windows',
                            'os_version': None,
                            'os_vendor': 'Microsoft'
                        }
                    elif ttl <= 255:
                        return {
                            'os_type': 'network',
                            'os_name': 'Network Device',
                            'os_version': None,
                            'os_vendor': None
                        }

            return {
                'os_type': None,
                'os_name': None,
                'os_version': None,
                'os_vendor': None
            }

        except Exception:
            return {
                'os_type': None,
                'os_name': None,
                'os_version': None,
                'os_vendor': None
            }

    def _parse_nmap_output(self, output: str) -> Dict[str, Optional[str]]:
        """
        Parse nmap output to extract OS information
        """
        os_info = {
            'os_type': None,
            'os_name': None,
            'os_version': None,
            'os_vendor': None
        }

        try:
            # Look for OS details line
            for line in output.split('\n'):
                if 'OS details:' in line:
                    os_details = line.split('OS details:')[1].strip()
                    os_info['os_name'] = os_details

                    # Detect OS type
                    os_lower = os_details.lower()
                    if 'windows' in os_lower:
                        os_info['os_type'] = 'windows'
                        os_info['os_vendor'] = 'Microsoft'

                        # Extract version
                        if 'windows 11' in os_lower:
                            os_info['os_version'] = '11'
                        elif 'windows 10' in os_lower:
                            os_info['os_version'] = '10'
                        elif 'windows server 2022' in os_lower:
                            os_info['os_version'] = 'Server 2022'
                        elif 'windows server 2019' in os_lower:
                            os_info['os_version'] = 'Server 2019'

                    elif 'linux' in os_lower or 'ubuntu' in os_lower or 'centos' in os_lower or 'redhat' in os_lower or 'debian' in os_lower:
                        os_info['os_type'] = 'linux'

                        # Extract distribution
                        if 'ubuntu' in os_lower:
                            os_info['os_vendor'] = 'Canonical'
                            match = re.search(r'ubuntu\s+(\d+\.\d+)', os_lower)
                            if match:
                                os_info['os_version'] = match.group(1)
                        elif 'centos' in os_lower:
                            os_info['os_vendor'] = 'CentOS'
                            match = re.search(r'centos\s+(\d+)', os_lower)
                            if match:
                                os_info['os_version'] = match.group(1)
                        elif 'red hat' in os_lower or 'redhat' in os_lower or 'rhel' in os_lower:
                            os_info['os_vendor'] = 'Red Hat'
                            match = re.search(r'(\d+\.\d+)', os_lower)
                            if match:
                                os_info['os_version'] = match.group(1)
                        elif 'debian' in os_lower:
                            os_info['os_vendor'] = 'Debian'
                            match = re.search(r'debian\s+(\d+)', os_lower)
                            if match:
                                os_info['os_version'] = match.group(1)

                    elif 'macos' in os_lower or 'mac os' in os_lower:
                        os_info['os_type'] = 'macos'
                        os_info['os_vendor'] = 'Apple'

                    break

        except Exception as e:
            logger.debug(f"Error parsing nmap output: {str(e)}")

        return os_info

    def _scan_single_ip(self, ip: str, scan_type: str = "full") -> Dict:
        """
        Scan a single IP address
        scan_type: 'quick' (ping only) or 'full' (ping + hostname + MAC + OS)
        """
        result = {
            'ip_address': ip,
            'is_reachable': False,
            'response_time': None,
            'hostname': None,
            'mac_address': None,
            'os_type': None,
            'os_name': None,
            'os_version': None,
            'os_vendor': None
        }

        # Step 1: Ping check
        is_reachable, response_time = self._ping_ip(ip)
        result['is_reachable'] = is_reachable
        result['response_time'] = response_time

        if not is_reachable:
            return result

        # Step 2: Quick scan stops here
        if scan_type == "quick":
            return result

        # Step 3: Full scan - get hostname
        hostname = self._resolve_hostname(ip)
        if hostname:
            result['hostname'] = hostname

        # Step 4: Get MAC address
        mac = self._get_mac_address(ip)
        if mac:
            result['mac_address'] = mac

        # Step 5: OS detection
        os_info = self._detect_os(ip)
        result.update(os_info)

        return result

    async def scan_ip_async(self, ip: str, scan_type: str = "full") -> Dict:
        """
        Async wrapper for scanning a single IP
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._scan_single_ip,
            ip,
            scan_type
        )

    async def scan_multiple_ips(
        self,
        ip_list: List[str],
        scan_type: str = "full"
    ) -> List[Dict]:
        """
        Scan multiple IPs concurrently
        """
        logger.info(f"Starting scan of {len(ip_list)} IPs (type: {scan_type})")
        start_time = time.time()

        # Create tasks for all IPs
        tasks = [
            self.scan_ip_async(ip, scan_type)
            for ip in ip_list
        ]

        # Wait for all scans to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, dict):
                valid_results.append(result)
            else:
                logger.error(f"Scan error: {result}")

        elapsed = time.time() - start_time
        logger.info(f"Scan completed in {elapsed:.2f}s: {len(valid_results)} results")

        return valid_results


# Singleton instance
ip_scan_service = IPScanService()
