from typing import Optional, Dict, List, Tuple, Callable, Awaitable, Any
import asyncio
import inspect
import subprocess
import socket
import re
import time
import shutil
import struct
import random
from concurrent.futures import ThreadPoolExecutor
from core.config import settings
from utils.logger import logger

# Try to import dnspython, but make it optional
try:
    import dns.resolver
    import dns.reversename
    DNS_AVAILABLE = True
except ImportError:
    DNS_AVAILABLE = False
    logger.warning("dnspython not available - DNS PTR lookups will be disabled")


class IPScanService:
    """Service for scanning IP addresses"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=settings.IPAM_SCAN_WORKERS)
        # Semaphore to limit concurrent scan operations (prevent resource exhaustion)
        # Limit to 20 concurrent scans to prevent ping failures due to network congestion
        self.semaphore = asyncio.Semaphore(20)
        # Find ping command path at initialization
        # Always use absolute paths to avoid PATH issues
        import os
        self.ping_cmd = '/usr/bin/ping' if os.path.exists('/usr/bin/ping') else '/bin/ping'
        self.arp_cmd = '/usr/sbin/arp' if os.path.exists('/usr/sbin/arp') else '/sbin/arp'
        self.nmap_cmd = shutil.which('nmap')

        logger.info(f"IP scan service initialized: ping={self.ping_cmd}, arp={self.arp_cmd}, nmap={self.nmap_cmd}, concurrency_limit=20")

    @staticmethod
    def _build_result(ip: str) -> Dict[str, Any]:
        return {
            'ip_address': ip,
            'is_reachable': False,
            'response_time': None,
            'hostname': None,
            'hostname_source': None,  # SNMP, DNS, NETBIOS, ARP, or None
            'dns_name': None,  # DNS PTR lookup result
            'system_name': None,  # SNMP sysName
            'contact': None,  # SNMP sysContact
            'location': None,  # SNMP sysLocation
            'machine_type': None,  # SNMP sysDescr parsed
            'vendor': None,  # SNMP sysDescr parsed
            'last_boot_time': None,  # SNMP sysUpTime converted
            'mac_address': None,
            'os_type': None,
            'os_name': None,
            'os_version': None,
            'os_vendor': None,
            'switch_name': None,
            'switch_port': None,
            'vlan_id': None
        }

    def _ping_ip(self, ip: str, timeout: int = 5) -> tuple[bool, Optional[int]]:
        """
        Ping an IP address to check reachability
        Returns: (is_reachable, response_time_ms)

        Note: Default timeout increased to 5 seconds to handle network congestion
        during mass scanning (Windows hosts, hosts waking from sleep, network delays)
        """
        try:
            # Use ping command with full path
            cmd = [self.ping_cmd, '-c', '1', '-W', str(timeout), ip]
            start_time = time.time()

            # Create environment without proxy settings for local network commands
            import os
            env = {k: v for k, v in os.environ.items()
                   if not k.lower().endswith('_proxy')}

            # Ensure PATH is set
            if 'PATH' not in env:
                env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 1,
                env=env
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
            logger.error(f"Ping failed for {ip}: {str(e)} (cmd: {self.ping_cmd})")
            return (False, None)

    def _resolve_hostname(self, ip: str) -> Optional[str]:
        """
        Reverse DNS lookup to get hostname (basic method using socket)
        """
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except Exception:
            return None

    def _encode_netbios_name(self, name: str = '*') -> bytes:
        """
        Encode a NetBIOS name for NBSTAT queries (RFC 1002 first-level encoding).
        """
        if name == '*':
            raw_name = b'*' + b'\x00' * 15
        else:
            raw_name = name.upper().encode('ascii', 'ignore')[:15].ljust(15, b' ') + b'\x00'

        encoded = bytearray()
        for byte in raw_name:
            encoded.append(ord('A') + ((byte >> 4) & 0x0F))
            encoded.append(ord('A') + (byte & 0x0F))

        return bytes([32]) + bytes(encoded) + b'\x00'

    def _skip_dns_name(self, data: bytes, offset: int) -> int:
        """
        Skip a DNS-style encoded name in an NBNS packet.
        """
        while offset < len(data):
            length = data[offset]
            if length == 0:
                return offset + 1
            if (length & 0xC0) == 0xC0:
                return offset + 2
            offset += 1 + length
        return offset

    def _normalize_hostname_candidate(self, value: Optional[str]) -> Optional[str]:
        """
        Clean and validate hostname-like values before storing them.
        """
        if not value:
            return None

        cleaned = ''.join(ch for ch in value.strip() if ch.isprintable()).strip(" .\x00")
        if not cleaned:
            return None

        if cleaned in {'*', '__MSBROWSE__'}:
            return None

        return cleaned

    def _get_netbios_hostname(self, ip: str, timeout: float = 1.5) -> Optional[str]:
        """
        Query Windows NetBIOS node status (UDP/137) and return the best hostname.

        This helps identify Windows endpoints that do not expose SNMP and do not
        have a reverse DNS PTR record.
        """
        sock = None
        try:
            transaction_id = random.randint(0, 0xFFFF)
            header = struct.pack('>HHHHHH', transaction_id, 0x0000, 1, 0, 0, 0)
            question = self._encode_netbios_name('*') + struct.pack('>HH', 0x0021, 0x0001)
            packet = header + question

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(packet, (ip, 137))
            data, _ = sock.recvfrom(4096)

            if len(data) < 12:
                return None

            qdcount = struct.unpack('>H', data[4:6])[0]
            ancount = struct.unpack('>H', data[6:8])[0]
            offset = 12

            for _ in range(qdcount):
                offset = self._skip_dns_name(data, offset)
                offset += 4

            candidates: List[Tuple[int, str]] = []

            for _ in range(ancount):
                offset = self._skip_dns_name(data, offset)
                if offset + 10 > len(data):
                    break

                rrtype, rrclass, _ttl, rdlength = struct.unpack('>HHIH', data[offset:offset + 10])
                offset += 10
                rdata = data[offset:offset + rdlength]
                offset += rdlength

                if rrtype != 0x0021 or rrclass != 0x0001 or not rdata:
                    continue

                name_count = rdata[0]
                pos = 1
                for _ in range(name_count):
                    if pos + 18 > len(rdata):
                        break

                    raw_name = rdata[pos:pos + 15].decode('ascii', 'ignore')
                    suffix = rdata[pos + 15]
                    flags = struct.unpack('>H', rdata[pos + 16:pos + 18])[0]
                    is_group = bool(flags & 0x8000)
                    pos += 18

                    if is_group:
                        continue

                    hostname = self._normalize_hostname_candidate(raw_name)
                    if not hostname:
                        continue

                    priority = {
                        0x20: 1,  # File server service
                        0x00: 2,  # Workstation service
                        0x03: 3,  # Messenger service
                    }.get(suffix, 99)
                    candidates.append((priority, hostname))

            if not candidates:
                return None

            candidates.sort(key=lambda item: item[0])
            best_hostname = candidates[0][1]
            logger.debug(f"NetBIOS hostname for {ip}: {best_hostname}")
            return best_hostname

        except Exception as e:
            logger.debug(f"NetBIOS lookup failed for {ip}: {str(e)}")
            return None
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

    def _dns_ptr_lookup(self, ip: str, timeout: int = 5, dns_servers: Optional[List[str]] = None) -> Optional[str]:
        """
        DNS PTR (reverse DNS) lookup to get hostname
        Uses dnspython for more reliable PTR lookups

        Args:
            ip: IP address to lookup
            timeout: Query timeout in seconds
            dns_servers: List of DNS server IPs to use (if None, uses system default)

        Returns: DNS hostname from PTR record or None
        """
        if not DNS_AVAILABLE:
            logger.debug("DNS PTR lookup skipped - dnspython not available")
            return None

        try:
            # Create reverse DNS name (e.g., 1.0.168.192.in-addr.arpa)
            rev_name = dns.reversename.from_address(ip)

            # Configure resolver with timeout
            resolver = dns.resolver.Resolver()
            resolver.timeout = timeout
            resolver.lifetime = timeout

            # Use custom DNS servers if provided
            if dns_servers:
                resolver.nameservers = dns_servers
                logger.debug(f"Using DNS servers: {dns_servers}")

            # Perform PTR query
            answers = resolver.resolve(rev_name, "PTR")

            # Get first PTR record
            if answers:
                ptr_record = str(answers[0])
                # Remove trailing dot if present
                if ptr_record.endswith('.'):
                    ptr_record = ptr_record[:-1]
                logger.debug(f"DNS PTR lookup for {ip}: {ptr_record}")
                return ptr_record

            return None

        except dns.resolver.NXDOMAIN:
            # No PTR record exists
            logger.debug(f"No PTR record for {ip}")
            return None
        except dns.resolver.Timeout:
            logger.debug(f"DNS PTR lookup timeout for {ip}")
            return None
        except Exception as e:
            logger.debug(f"DNS PTR lookup failed for {ip}: {str(e)}")
            return None

    def _get_mac_address(self, ip: str) -> Optional[str]:
        """
        Get MAC address using ARP table
        """
        try:
            # Create environment without proxy settings
            import os
            env = {k: v for k, v in os.environ.items()
                   if not k.lower().endswith('_proxy')}

            # Try to read from ARP cache
            result = subprocess.run(
                [self.arp_cmd, '-n', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
                env=env
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
            if not self.nmap_cmd:
                logger.debug("nmap not available, skipping OS detection")
                return self._detect_os_simple(ip)

            # Create environment without proxy settings
            import os
            env = {k: v for k, v in os.environ.items()
                   if not k.lower().endswith('_proxy')}

            # Run nmap OS detection
            result = subprocess.run(
                [self.nmap_cmd, '-O', '--osscan-guess', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                env=env
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
        TTL values typically used by different OS:
        - Linux/Unix: 64
        - Windows: 128
        - Network devices (routers/switches): 255
        """
        try:
            # Create environment without proxy settings
            import os
            env = {k: v for k, v in os.environ.items()
                   if not k.lower().endswith('_proxy')}

            result = subprocess.run(
                [self.ping_cmd, '-c', '1', ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=3,
                env=env
            )

            if result.returncode == 0:
                output = result.stdout.decode()
                # Parse TTL value
                match = re.search(r'ttl[=<](\d+)', output, re.IGNORECASE)
                if match:
                    ttl = int(match.group(1))

                    # Guess OS based on TTL
                    # TTL decreases by 1 for each hop, so we check ranges
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
                        # Network devices typically use TTL 255
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
        Parse nmap output to extract OS information and device type
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

                        # Extract version using regex
                        match = re.search(r'Windows\s+(Server\s+)?([0-9]+(?:\.[0-9]+)?|\d{4})', os_lower, re.IGNORECASE)
                        if match:
                            if match.group(1):  # "Server" exists
                                os_info['os_version'] = f"Server {match.group(2)}"
                                os_info['os_name'] = f"Windows Server {match.group(2)}"
                            else:
                                os_info['os_version'] = match.group(2)
                                os_info['os_name'] = f"Windows {match.group(2)}"

                    elif 'linux' in os_lower or 'ubuntu' in os_lower or 'centos' in os_lower or 'redhat' in os_lower or 'debian' in os_lower:
                        os_info['os_type'] = 'linux'

                        # Extract kernel version first (more generic)
                        kernel_match = re.search(r'Linux\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)', os_lower, re.IGNORECASE)
                        if kernel_match:
                            os_info['os_version'] = kernel_match.group(1)

                        # Extract distribution (may override os_version)
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

                    # Detect network devices
                    # Cisco devices
                    elif any(keyword in os_lower for keyword in ['cisco', 'ios', 'catalyst', 'nexus']):
                        os_info['os_type'] = 'network'
                        os_info['os_vendor'] = 'Cisco'

                        # Extract IOS version
                        version_match = re.search(r'IOS\s+([0-9]+\.[0-9]+)', os_lower, re.IGNORECASE)
                        if version_match:
                            os_info['os_version'] = version_match.group(1)
                            os_info['os_name'] = f"Cisco IOS {os_info['os_version']}"
                        else:
                            os_info['os_name'] = 'Cisco Network Device'

                    # Juniper devices
                    elif any(keyword in os_lower for keyword in ['juniper', 'junos']):
                        os_info['os_type'] = 'network'
                        os_info['os_vendor'] = 'Juniper'

                        # Extract JUNOS version
                        version_match = re.search(r'JUNOS\s+([0-9]+\.[0-9]+)', os_lower, re.IGNORECASE)
                        if version_match:
                            os_info['os_version'] = version_match.group(1)
                            os_info['os_name'] = f"Juniper JUNOS {os_info['os_version']}"
                        else:
                            os_info['os_name'] = 'Juniper Network Device'
                    elif any(keyword in os_lower for keyword in ['hp', 'aruba', 'procurve']):
                        os_info['os_type'] = 'network'
                        os_info['os_vendor'] = 'HP/Aruba'
                        os_info['os_name'] = 'HP/Aruba Network Device'
                    elif any(keyword in os_lower for keyword in ['nokia', 'alcatel']):
                        os_info['os_type'] = 'network'
                        os_info['os_vendor'] = 'Nokia'
                        os_info['os_name'] = 'Nokia Network Device'
                    elif any(keyword in os_lower for keyword in ['dell', 'force10']):
                        os_info['os_type'] = 'network'
                        os_info['os_vendor'] = 'Dell'
                        os_info['os_name'] = 'Dell Network Device'
                    elif 'printer' in os_lower:
                        os_info['os_type'] = 'printer'
                        os_info['os_name'] = 'Network Printer'
                    elif any(keyword in os_lower for keyword in ['camera', 'ipc', 'surveillance']):
                        os_info['os_type'] = 'camera'
                        os_info['os_name'] = 'IP Camera'

                    break

        except Exception as e:
            logger.debug(f"Error parsing nmap output: {str(e)}")

        return os_info

    def _scan_single_ip(
        self,
        ip: str,
        scan_type: str = "full",
        snmp_profile: Optional[Dict] = None,
        dns_servers: Optional[List[str]] = None
    ) -> Dict:
        """
        Scan a single IP address with integrated Ping+DNS+SNMP workflow

        Args:
            ip: IP address to scan
            scan_type: 'quick' (ping only) or 'full' (ping + DNS + SNMP + MAC + OS)
            snmp_profile: Optional SNMP profile for device identification
                          Dict with keys: username, auth_protocol, auth_password_encrypted,
                          priv_protocol, priv_password_encrypted, port, timeout
            dns_servers: Optional list of DNS server IPs for PTR lookups

        Returns:
            Dict with scan results including:
            - is_reachable, response_time
            - hostname (best available from SNMP/DNS/ARP priority)
            - hostname_source (SNMP, DNS, NETBIOS, ARP)
            - dns_name (from DNS PTR)
            - system_name (from SNMP sysName)
            - contact, location, machine_type, vendor (from SNMP)
            - last_boot_time (from SNMP sysUpTime)
            - mac_address, os_type, os_name, etc.
        """
        result = self._build_result(ip)

        if scan_type == "enrich":
            result['is_reachable'] = True
            return self._enrich_single_ip(
                result=result,
                ip=ip,
                snmp_profile=snmp_profile,
                dns_servers=dns_servers
            )

        # Step 1: Ping check
        ping_timeout = max(1, settings.STATUS_CHECK_PING_TIMEOUT_SECONDS)
        is_reachable, response_time = self._ping_ip(ip, timeout=ping_timeout)
        result['is_reachable'] = is_reachable
        result['response_time'] = response_time

        if not is_reachable:
            return result

        # Step 2: Quick scan stops here
        if scan_type == "quick":
            return result

        return self._enrich_single_ip(
            result=result,
            ip=ip,
            snmp_profile=snmp_profile,
            dns_servers=dns_servers
        )

    def _enrich_single_ip(
        self,
        *,
        result: Dict[str, Any],
        ip: str,
        snmp_profile: Optional[Dict] = None,
        dns_servers: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        # Step 3: OS detection baseline
        # Keep the baseline lightweight for subnet sweeps. Running nmap against
        # every reachable host turns a /24 scan into a multi-minute operation,
        # so use TTL-based detection here and let SNMP refine network devices.
        baseline_os_info = self._detect_os_simple(ip)
        result.update(baseline_os_info)

        # Step 4: DNS PTR lookup
        if not result['hostname']:
            dns_name = self._dns_ptr_lookup(ip, dns_servers=dns_servers)
            if dns_name:
                result['dns_name'] = dns_name
                result['hostname'] = dns_name
                result['hostname_source'] = 'DNS'
                logger.debug(f"Hostname from DNS for {ip}: {dns_name}")

        # Step 4b: System resolver reverse lookup (same source classification as DNS)
        if not result['hostname']:
            reverse_name = self._normalize_hostname_candidate(self._resolve_hostname(ip))
            if reverse_name:
                result['dns_name'] = reverse_name
                result['hostname'] = reverse_name
                result['hostname_source'] = 'DNS'
                logger.debug(f"Hostname from system resolver for {ip}: {reverse_name}")

        # Step 5: Windows hostname fallback via NetBIOS
        if not result['hostname'] and result.get('os_type') == 'windows':
            netbios_name = self._get_netbios_hostname(ip)
            if netbios_name:
                result['hostname'] = netbios_name
                result['hostname_source'] = 'NETBIOS'
                logger.debug(f"Hostname from NetBIOS for {ip}: {netbios_name}")

        # Step 6: SNMP device identification (highest priority for network devices)
        # Restrict SNMP to likely network devices or hosts we still cannot name.
        # Applying SNMP to every reachable endpoint in a /24 causes large timeout
        # amplification on subnets dominated by PCs and printers.
        snmp_os_data = None  # Track SNMP OS info separately
        should_try_snmp = bool(snmp_profile) and (
            result.get('os_type') == 'network'
            or not result.get('hostname')
        )
        if should_try_snmp:
            try:
                from services.snmp_service import snmp_service

                snmp_data = asyncio.run(
                    snmp_service.get_device_identification(ip, snmp_profile)
                )
                if snmp_data:
                    result['system_name'] = snmp_data.get('system_name')
                    result['contact'] = snmp_data.get('contact')
                    result['location'] = snmp_data.get('location')
                    result['last_boot_time'] = snmp_data.get('last_boot_time')
                    result['machine_type'] = snmp_data.get('machine_type')
                    result['vendor'] = snmp_data.get('vendor')

                    snmp_os_data = {
                        'os_type': snmp_data.get('os_type'),
                        'os_name': snmp_data.get('os_name'),
                        'os_version': snmp_data.get('os_version')
                    }

                    if snmp_os_data['os_type']:
                        result['os_type'] = snmp_os_data['os_type']
                    if snmp_os_data['os_name']:
                        result['os_name'] = snmp_os_data['os_name']
                    if snmp_os_data['os_version']:
                        result['os_version'] = snmp_os_data['os_version']

                    # SNMP sysName remains the highest priority hostname when available.
                    if result['system_name']:
                        result['hostname'] = result['system_name']
                        result['hostname_source'] = 'SNMP'
                        logger.debug(f"Hostname from SNMP for {ip}: {result['system_name']}")

            except Exception as e:
                logger.debug(f"SNMP device identification failed for {ip}: {str(e)}")

        # Step 7: Get MAC address (can be used for ARP-based hostname later)
        mac = self._get_mac_address(ip)
        if mac:
            result['mac_address'] = mac

        # Step 8: OS detection merge
        nmap_os_info = baseline_os_info
        if snmp_os_data and any(snmp_os_data.values()):
            logger.debug(f"Using SNMP OS data for {ip} (highest priority)")

            if not result.get('os_type') and nmap_os_info.get('os_type'):
                result['os_type'] = nmap_os_info['os_type']
                logger.debug(f"Filled os_type from Nmap: {nmap_os_info['os_type']}")

            if not result.get('os_name') and nmap_os_info.get('os_name'):
                result['os_name'] = nmap_os_info['os_name']
                logger.debug(f"Filled os_name from Nmap: {nmap_os_info['os_name']}")

            if not result.get('os_version') and nmap_os_info.get('os_version'):
                result['os_version'] = nmap_os_info['os_version']
                logger.debug(f"Filled os_version from Nmap: {nmap_os_info['os_version']}")

            # os_vendor: prefer SNMP vendor over Nmap os_vendor
            if not result.get('os_vendor') and nmap_os_info.get('os_vendor'):
                result['os_vendor'] = nmap_os_info['os_vendor']
        else:
            logger.debug(f"Using Nmap OS data for {ip} (SNMP unavailable)")
            result.update(nmap_os_info)

        return result

    async def scan_ip_async(
        self,
        ip: str,
        scan_type: str = "full",
        snmp_profile: Optional[Dict] = None,
        dns_servers: Optional[List[str]] = None
    ) -> Dict:
        """
        Async wrapper for scanning a single IP with optional SNMP profile

        Args:
            ip: IP address to scan
            scan_type: 'quick' or 'full'
            snmp_profile: Optional SNMP profile for device identification
            dns_servers: Optional list of DNS server IPs for PTR lookups

        Note: Uses semaphore to limit concurrency and prevent resource exhaustion
        """
        # Acquire semaphore to limit concurrent scans
        async with self.semaphore:
            loop = asyncio.get_event_loop()
            from functools import partial
            scan_func = partial(
                self._scan_single_ip,
                ip=ip,
                scan_type=scan_type,
                snmp_profile=snmp_profile,
                dns_servers=dns_servers
            )
            return await loop.run_in_executor(self.executor, scan_func)

    async def scan_multiple_ips(
        self,
        ip_list: List[str],
        scan_type: str = "full",
        snmp_profile: Optional[Dict] = None,
        dns_servers: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[Dict, int, int], Awaitable[None] | None]] = None
    ) -> List[Dict]:
        """
        Scan multiple IPs concurrently with optional SNMP profile

        Args:
            ip_list: List of IP addresses to scan
            scan_type: 'quick' or 'full'
            snmp_profile: Optional SNMP profile for all IPs
            dns_servers: Optional list of DNS server IPs for PTR lookups
        """
        logger.info(f"Starting scan of {len(ip_list)} IPs (type: {scan_type}, SNMP: {'enabled' if snmp_profile else 'disabled'})")
        start_time = time.time()

        valid_results = []
        total = len(ip_list)

        if total == 0:
            return valid_results

        tasks = [
            asyncio.create_task(
                self.scan_ip_async(ip, scan_type, snmp_profile, dns_servers)
            )
            for ip in ip_list
        ]

        completed = 0
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
            except Exception as exc:
                logger.error(f"Scan error: {exc}")
                continue

            if not isinstance(result, dict):
                logger.error(f"Unexpected scan result: {result}")
                continue

            valid_results.append(result)
            completed += 1

            if progress_callback:
                callback_result = progress_callback(result, completed, total)
                if inspect.isawaitable(callback_result):
                    await callback_result

        elapsed = time.time() - start_time
        logger.info(f"Scan completed in {elapsed:.2f}s: {len(valid_results)} results")

        return valid_results

    async def enrich_multiple_ips(
        self,
        ip_list: List[str],
        snmp_profile: Optional[Dict] = None,
        dns_servers: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[Dict, int, int], Awaitable[None] | None]] = None
    ) -> List[Dict]:
        """Enrich already-reachable IPs without repeating the full subnet sweep."""
        return await self.scan_multiple_ips(
            ip_list=ip_list,
            scan_type="enrich",
            snmp_profile=snmp_profile,
            dns_servers=dns_servers,
            progress_callback=progress_callback
        )


# Singleton instance
ip_scan_service = IPScanService()
