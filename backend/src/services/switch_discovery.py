from typing import List, Dict, Optional, Tuple, Callable
from models.switch import Switch
from services.switch_manager import switch_manager
from core.security import credential_encryption
from core.config import settings
from utils.logger import logger
import ipaddress
import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import time


class SwitchDiscoveryService:
    """Service for discovering and batch adding switches"""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=settings.DISCOVERY_WORKERS)
        self.progress_queues = {}  # session_id -> asyncio.Queue
        self.event_loops = {}  # session_id -> event loop

    # SNMP Enterprise OID prefixes for vendor identification
    # Source: IANA Private Enterprise Numbers
    VENDOR_OIDS = {
        '1.3.6.1.4.1.9':    'cisco',   # Cisco Systems
        '1.3.6.1.4.1.2636': 'juniper', # Juniper Networks
        '1.3.6.1.4.1.6527': 'alcatel', # Nokia (TiMetra/SROS)
        '1.3.6.1.4.1.637':  'alcatel', # Alcatel-Lucent (legacy)
        '1.3.6.1.4.1.6486': 'alcatel', # Alcatel-Lucent Enterprise (AOS OmniSwitch)
        '1.3.6.1.4.1.6027': 'dell',    # Force10 Networks (now Dell EMC)
        '1.3.6.1.4.1.674':  'dell',    # Dell Inc.
        '1.3.6.1.4.1.7050': 'alcatel', # Nokia SR Linux
    }

    def _detect_vendor_from_oid(self, sys_object_id: str) -> Optional[str]:
        """
        Detect vendor from SNMP sysObjectID (most reliable method).
        Uses IANA Private Enterprise Numbers.
        Handles both dotted form (1.3.6.1.4.1.6527.x.x) and
        named form (SNMPv2-SMI::enterprises.6527.x.x) returned by pysnmp.
        """
        if not sys_object_id:
            return None
        # Dotted numeric form: "1.3.6.1.4.1.ENTERPRISE..."
        for oid_prefix, vendor in self.VENDOR_OIDS.items():
            if sys_object_id.startswith(oid_prefix):
                logger.debug(f"Vendor '{vendor}' detected from sysObjectID: {sys_object_id}")
                return vendor
        # Named form: "SNMPv2-SMI::enterprises.6527.1.3.3"
        import re
        m = re.search(r'enterprises\.(\d+)', sys_object_id)
        if m:
            enterprise_num = m.group(1)
            for oid_prefix, vendor in self.VENDOR_OIDS.items():
                if oid_prefix.split('.')[-1] == enterprise_num:
                    logger.debug(
                        f"Vendor '{vendor}' detected from named-form sysObjectID: {sys_object_id}"
                    )
                    return vendor
        return None

    def _detect_vendor_from_descr(self, sys_descr: str) -> Optional[str]:
        """
        Detect vendor from SNMP sysDescr or SSH 'show version' output.
        Checks Nokia/Alcatel FIRST to avoid false positives.
        sysDescr examples:
          Nokia SROS:     "TiMOS-B-20.10.R1 ..."
          Nokia SR Linux: "Nokia SR Linux ..." / "srlinux ..."
          Dell OS10:      "Dell EMC Networking OS10 ..."
          Juniper:        "Juniper Networks, Inc. ..."
          Cisco IOS:      "Cisco IOS Software, ..."
          Cisco NX-OS:    "Cisco Nexus Operating System ..."
        """
        if not sys_descr:
            return None
        d = sys_descr.lower()

        # Nokia / Alcatel-Lucent (check BEFORE Dell and Cisco)
        if any(k in d for k in ('timos', 'nokia', 'alcatel', 'sr linux', 'srlinux', 'sros')):
            return 'alcatel'

        # Dell EMC / Force10 / OS10
        if any(k in d for k in ('dell emc', 'dell networking', 'force10', 'os10', 'powerconnect')):
            return 'dell'

        # Dell fallback - only if no Nokia keyword matched above
        if 'dell' in d:
            return 'dell'

        # Juniper
        if any(k in d for k in ('juniper', 'junos', 'ex series', 'qfx', 'srx')):
            return 'juniper'

        # Cisco - use specific phrases, NOT bare 'ios' to avoid false positives
        if any(k in d for k in ('cisco ios', 'cisco nexus', 'ios-xe', 'ios xe',
                                 'nx-os', 'ios version', 'cisco adaptive')):
            return 'cisco'

        # Bare 'cisco' as a fallback
        if 'cisco' in d:
            return 'cisco'

        return None

    def _detect_vendor(self, output: str) -> Optional[str]:
        """Detect vendor from SSH show version output (backwards compat wrapper)."""
        return self._detect_vendor_from_descr(output)

    def _extract_model_from_sysdescr(self, sys_descr: str, vendor: str) -> str:
        """
        Extract hardware model from SNMP sysDescr (single-line string).

        sysDescr examples:
          Cisco NX-OS:  "Cisco NX-OS(tm) n9000, Software (n9000-dk9), ..."
          Cisco IOS:    "Cisco IOS Software, C3900 Software (C3900-UNIVERSALK9-M), ..."
          Nokia SROS:   "TiMOS-B-20.10.R1 both/x86_64 Nokia 7750 SR-12 Copyright ..."
          Nokia SRLinux:"Nokia SR Linux version : 21.3.1-113-gd8b52fb"
          Dell OS10:    "Dell EMC Networking OS10 Enterprise 10.5.2.3"
          Alcatel AOS:  "Alcatel-Lucent OS6860E-48 6.7.2.R02 Service Release ..."
          Nokia AOS:    "Nokia OmniSwitch-OS6360-P10 AOS-8.7.15.R01"
          Juniper:      "Juniper Networks, Inc. ex4200-48t internet router, kernel JUNOS 12.3R12.4 ..."

        Only returns a value when the hardware model can be confidently identified.
        Returns 'Unknown' when sysDescr only contains OS/version info (very common
        for Cisco IOS where sysDescr has no hardware model).
        """
        import re
        if not sys_descr:
            return 'Unknown'

        d = sys_descr.strip()

        if vendor == 'cisco':
            # NX-OS: "Cisco NX-OS(tm) n9000, Software ..."
            m = re.search(r'Cisco NX-OS\(tm\)\s+(\S+)', d, re.IGNORECASE)
            if m:
                return m.group(1)

            # IOS with embedded platform identifier:
            #   "C3900 Software (C3900-UNIVERSALK9-M), ..."  → C3900
            #   "WS-C3750X-48P", "ASR1001-X", "ISR4321"
            m = re.search(
                r'\b(WS-C[A-Z0-9\-]+|N[0-9]K-C[0-9][A-Z0-9\-]+|C[0-9]{4}[A-Z][A-Z0-9\-]+'
                r'|ASR[0-9][A-Z0-9\-]*|ISR[0-9][A-Z0-9\-]*)',
                d
            )
            if m:
                return m.group(1)

            # Generic Cisco IOS sysDescr has no hardware model — don't guess
            return 'Unknown'

        elif vendor == 'alcatel':
            # Nokia SROS: "TiMOS-B-20.10.R1 both/x86_64 Nokia 7750 SR-12 Copyright..."
            # Covers: SR, IXR, SXR, SAS, ESS, PSS, XRS, FX, MG product lines
            m = re.search(
                r'Nokia\s+(\d{3,4}\s+(?:SR|IXR|SXR|SAS|ESS|PSS|XRS|FX|MG)[A-Z0-9\-][A-Z0-9\-]*)',
                d, re.IGNORECASE
            )
            if m:
                return m.group(1)

            # Nokia SR Linux: "Nokia SR Linux version : 21.3.1-..."
            if 'sr linux' in d.lower() or 'srlinux' in d.lower():
                return 'SR Linux'

            # Alcatel/Nokia OmniSwitch AOS: model always starts with OS + 4 digits
            # Handles ALL of:
            #   "Alcatel-Lucent OS6860E-48 6.7.2.R02..."
            #   "Alcatel-Lucent Enterprise OS6570-P48 AOS-8.9.7..."
            #   "Alcatel-Lucent OmniSwitch-OS6450-48 6.7.2.R02"
            #   "Nokia OmniSwitch-OS6360-P10 AOS-8.7.15.R01"
            m = re.search(r'\b(OS[0-9]{4}[A-Z0-9\-]+)', d, re.IGNORECASE)
            if m:
                return m.group(1)

            # Bare Nokia hardware platform without "Nokia" prefix
            # Handles ENTITY-MIB entPhysicalDescr like "7220 IXR-D2" or "7750 SR-12 Chassis"
            m = re.search(
                r'\b(\d{4}\s+(?:SR|IXR|SXR|SAS|ESS|PSS|XRS|FX|MG)[A-Z0-9\-][A-Z0-9\-]*)',
                d, re.IGNORECASE
            )
            if m:
                return m.group(1)

            return 'Unknown'

        elif vendor == 'dell':
            # Dell specific model numbers: S5248F-ON, Z9264F-ON, N3048P-ON
            m = re.search(r'\b([SZN][0-9]{4}[A-Z0-9]*-ON)\b', d)
            if m:
                return m.group(1)

            # Dell PowerConnect: "PowerConnect 5524"
            m = re.search(r'PowerConnect\s+(\S+)', d, re.IGNORECASE)
            if m:
                return f'PowerConnect {m.group(1)}'

            # OS10 as fallback product line identifier
            if 'os10' in d.lower():
                return 'OS10'

            return 'Unknown'

        elif vendor == 'juniper':
            # Juniper model numbers: EX4200-48T, QFX5100-48S, SRX300, etc.
            # Pattern: EX, QFX, SRX, MX followed by digits and optional suffix
            m = re.search(r'\b((?:EX|QFX|SRX|MX|ACX|PTX)[0-9]{3,4}[A-Z0-9\-]*)\b', d, re.IGNORECASE)
            if m:
                return m.group(1).upper()

            return 'Unknown'

        # Generic fallback: "Model: X"
        m = re.search(r'model[:\s]+(\S+)', d, re.IGNORECASE)
        if m:
            return m.group(1)

        return 'Unknown'

    def _extract_model(self, show_version_output: str, vendor: str) -> str:
        """
        Extract model string from 'show version' output.
        Each vendor has a different output format.
        """
        lines = show_version_output.split('\n')
        model = 'Unknown'

        if vendor == 'cisco':
            # Cisco IOS: "Model number  : WS-C3750X-48P"  or  "cisco WS-C3750X ..."
            # Cisco NX-OS: "  cisco Nexus9000 ..."
            for line in lines:
                ll = line.lower()
                if 'model number' in ll or 'pid:' in ll:
                    model = line.strip()
                    break
                if ll.strip().startswith('cisco ') and len(line.split()) >= 2:
                    # e.g. "cisco WS-C3750X-48P-S (PowerPC405) ..."
                    model = line.split()[1].strip()
                    break

        elif vendor == 'dell':
            # Dell OS10: "System Type: S4048-ON" or "Model: S5248F-ON"
            # Dell FTOS: "Dell Application Software Version ..."
            for line in lines:
                ll = line.lower()
                if 'system type' in ll or ('model' in ll and ':' in line):
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        model = parts[1].strip()
                        break

        elif vendor == 'alcatel':
            # Priority order:
            # 1. "Chassis Type : OS6860E-48"  (Alcatel AOS OmniSwitch)
            # 2. "System Type  : 7750 SR-12"  (Nokia SROS)
            # 3. "Product Name : OS6860E-48"  (AOS fallback)
            # 4. Bare model line "    7750 SR-12" (SROS fallback)
            for line in lines:
                ll = line.lower()
                if ('chassis type' in ll or 'system type' in ll) and ':' in line:
                    parts = line.split(':', 1)
                    if len(parts) == 2 and parts[1].strip():
                        model = parts[1].strip()
                        break
                if 'product name' in ll or 'product type' in ll:
                    parts = line.split(':', 1)
                    if len(parts) == 2 and parts[1].strip():
                        model = parts[1].strip()
                        break
                # Nokia SROS: bare line like "    7750 SR-12  ..."
                if ll.strip().startswith('7') and any(
                        kw in ll for kw in ('sr-', 'ixr', 'fx', 'mg', 'sas', 'ess')):
                    model = ' '.join(line.strip().split()[0:2])
                    break

        elif vendor == 'juniper':
            # Juniper: "Model: ex4200-48t" or "Model                 EX4200-48T"
            for line in lines:
                ll = line.lower()
                if 'model' in ll:
                    # Try colon separator first
                    if ':' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2 and parts[1].strip():
                            model = parts[1].strip()
                            break
                    # Try whitespace-separated format
                    else:
                        parts = line.split()
                        if len(parts) >= 2:
                            model = parts[-1].strip()
                            break

        # Generic fallback
        if model == 'Unknown':
            for line in lines:
                if 'model:' in line.lower():
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        model = parts[1].strip()
                        break

        return model[:100] if len(model) > 100 else model

    def _try_connect_with_retry(self, ip: str, username: str, password: str,
                                  enable_password: Optional[str], port: int,
                                  session_id: str = None,
                                  max_retries: int = 2,
                                  progress_queue = None,
                                  loop = None) -> Optional[Dict]:
        """
        Try to connect to a switch with retry mechanism
        Returns dict with success status and details
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if progress_queue and loop:
                    status = "重试中" if attempt > 0 else "连接中"
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            progress_queue.put({
                                'type': 'attempt',
                                'ip': ip,
                                'attempt': attempt + 1,
                                'max_attempts': max_retries + 1,
                                'status': status
                            }),
                            loop
                        )
                        future.result(timeout=5)  # Wait for the put to complete
                    except Exception as e:
                        logger.warning(f"Failed to send attempt event for {ip}: {e}")
                
                result = self._try_connect(ip, username, password, enable_password, port)
                
                if result and result.get('success'):
                    if progress_queue and loop:
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                progress_queue.put({
                                    'type': 'success',
                                    'ip': ip,
                                    'name': result.get('name'),
                                    'vendor': result.get('vendor')
                                }),
                                loop
                            )
                            future.result(timeout=5)
                        except Exception as e:
                            logger.warning(f"Failed to send success event for {ip}: {e}")
                    return result
                
                # Connection failed, try next attempt
                last_error = "连接失败"
                if attempt < max_retries:
                    time.sleep(1)  # Wait 1 second before retry
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1}/{max_retries + 1} failed for {ip}: {str(e)}")
                if attempt < max_retries:
                    time.sleep(1)
        
        # All attempts failed
        if progress_queue and loop:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    progress_queue.put({
                        'type': 'failed',
                        'ip': ip,
                        'error': last_error or '连接失败',
                        'attempts': max_retries + 1
                    }),
                    loop
                )
                future.result(timeout=5)
            except Exception as e:
                logger.warning(f"Failed to send failed event for {ip}: {e}")
        
        logger.info(f"Failed to connect to {ip} after {max_retries + 1} attempts")
        return None

    def _extract_hostname(self, hostname_output: str, device_type: str, conn) -> str:
        """
        Extract hostname from command output based on device type

        Different vendors have different hostname formats:
        - Cisco: hostname SWITCHNAME
        - Dell: hostname SWITCHNAME
        - Alcatel: system name SWITCHNAME
        """
        try:
            # Try different methods to extract hostname
            lines = hostname_output.split('\n')

            for line in lines:
                line_lower = line.lower().strip()

                # Cisco/Dell format: "hostname SWITCHNAME"
                if line_lower.startswith('hostname '):
                    parts = line.split()
                    if len(parts) >= 2:
                        hostname = parts[1].strip()
                        # Remove quotes if present
                        hostname = hostname.strip('"').strip("'")
                        if hostname and hostname != 'hostname':
                            logger.info(f"Found hostname via 'hostname' keyword: {hostname}")
                            return hostname

                # Alcatel format: "system name SWITCHNAME"
                if 'system name' in line_lower:
                    parts = line.split()
                    if len(parts) >= 3:
                        hostname = parts[2].strip()
                        hostname = hostname.strip('"').strip("'")
                        if hostname:
                            logger.info(f"Found hostname via 'system name': {hostname}")
                            return hostname

            # If not found in config, try to get from prompt
            try:
                # Get the prompt (often includes hostname)
                if hasattr(conn, 'find_prompt'):
                    prompt = conn.find_prompt()
                    # Remove common prompt characters
                    hostname = prompt.strip().rstrip('#>$').strip()
                    if hostname and len(hostname) > 0 and len(hostname) < 64:
                        logger.info(f"Found hostname from prompt: {hostname}")
                        return hostname
            except Exception as e:
                logger.debug(f"Could not get hostname from prompt: {e}")

            logger.warning("Could not extract hostname from output")
            return None

        except Exception as e:
            logger.error(f"Error extracting hostname: {str(e)}")
            return None

    def _try_connect(self, ip: str, username: str, password: str,
                     enable_password: Optional[str], port: int) -> Optional[Dict]:
        """Try to connect to a switch and gather information via SSH."""
        try:
            from netmiko import ConnectHandler
            from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException

            # Try device types in order.
            # Nokia types are tried BEFORE cisco_ios to avoid misidentification,
            # since Nokia SROS/SRLinux CLI can look similar to IOS.
            device_types = [
                ('nokia_sros',    'alcatel'),  # Nokia SROS (7250, 7750, etc.)
                ('nokia_srlinux', 'alcatel'),  # Nokia SR Linux (7220, etc.)
                ('dell_os10',     'dell'),      # Dell EMC OS10
                ('juniper_junos', 'juniper'),   # Juniper JunOS
                ('cisco_ios',     'cisco'),     # Cisco IOS / IOS-XE
                ('alcatel_aos',   'alcatel'),   # Alcatel AOS (OmniSwitch)
            ]

            for device_type, default_vendor in device_types:
                try:
                    device_params = {
                        'device_type': device_type,
                        'host': ip,
                        'username': username,
                        'password': password,
                        'port': port,
                        'timeout': 10,
                        'conn_timeout': 10,
                        'global_delay_factor': 1.5,
                        'allow_agent': False,
                        'use_keys': False,
                        'ssh_strict': False,
                        'allow_auto_change': False,
                    }

                    if enable_password and device_type == 'cisco_ios':
                        device_params['secret'] = enable_password

                    with ConnectHandler(**device_params) as conn:
                        # Step 1: Get show version output (vendor-independent command)
                        try:
                            if device_type == 'cisco_ios' and enable_password:
                                conn.enable()
                            output = conn.send_command('show version', read_timeout=15)
                        except Exception:
                            output = ''

                        # Step 2: Detect vendor from actual output (PRIMARY method)
                        vendor = self._detect_vendor_from_descr(output)

                        # Step 3: Fall back to the device_type's default vendor
                        if not vendor:
                            vendor = default_vendor
                            logger.debug(
                                f"{ip}: vendor not found in 'show version', "
                                f"using device_type default: {vendor}"
                            )

                        # Step 4: Get hostname
                        try:
                            if device_type in ('nokia_sros', 'nokia_srlinux'):
                                hostname_output = conn.send_command(
                                    'show system information | match Name', read_timeout=15)
                            elif device_type == 'dell_os10':
                                hostname_output = conn.send_command(
                                    'show running-configuration | grep hostname', read_timeout=15)
                            elif device_type == 'cisco_ios':
                                hostname_output = conn.send_command(
                                    'show running-config | include hostname', read_timeout=15)
                            else:
                                hostname_output = conn.send_command(
                                    'show running-directory', read_timeout=15)
                        except Exception:
                            hostname_output = ''

                        hostname = self._extract_hostname(hostname_output, device_type, conn)
                        if not hostname:
                            hostname = ip

                        # Step 5: Extract model from show version output
                        model = self._extract_model(output, vendor)

                        logger.info(
                            f"Discovered {ip}: {hostname} vendor={vendor} "
                            f"model={model} via device_type={device_type}"
                        )

                        return {
                            'ip_address': ip,
                            'name': hostname,
                            'vendor': vendor,
                            'model': model,
                            'ssh_port': port,
                            'username': username,
                            'password': password,
                            'enable_password': enable_password,
                            'success': True
                        }

                except (NetmikoTimeoutException, NetmikoAuthenticationException):
                    continue  # Try next device type
                except Exception as e:
                    logger.debug(f"Device type {device_type} failed for {ip}: {str(e)}")
                    continue  # Try next device type

            return None

        except Exception as e:
            logger.error(f"Error connecting to {ip}: {str(e)}")
            return None

    async def _discover_via_snmp(
        self,
        ip: str,
        snmp_config: Dict
    ) -> Optional[Dict]:
        """
        Try to discover device identity via SNMP.
        Uses sysObjectID → vendor, sysDescr → model, sysName → hostname.
        This is more reliable than SSH-based detection for vendor/model info.

        Returns dict with name/vendor/model or None if SNMP fails.
        """
        try:
            from pysnmp.hlapi.v3arch.asyncio import (
                SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
                ObjectType, ObjectIdentity, get_cmd, CommunityData,
                usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmHMAC128SHA224AuthProtocol,
                usmDESPrivProtocol, usmAesCfb128Protocol, usmAesCfb192Protocol, usmAesCfb256Protocol
            )

            port = snmp_config.get('snmp_port', 161)
            version = snmp_config.get('snmp_version', '3')

            engine = SnmpEngine()

            if version == '3':
                username = snmp_config.get('snmp_username', '')
                auth_password = snmp_config.get('snmp_auth_password', '')
                priv_password = snmp_config.get('snmp_priv_password', '')
                auth_protocol = snmp_config.get('snmp_auth_protocol', 'SHA').upper()
                priv_protocol = snmp_config.get('snmp_priv_protocol', 'AES128').upper()

                if not username or not auth_password or not priv_password:
                    logger.debug(f"{ip}: SNMP v3 config incomplete, skipping SNMP discovery")
                    return None

                auth_map = {
                    'MD5': usmHMACMD5AuthProtocol,
                    'SHA': usmHMACSHAAuthProtocol,
                    'SHA256': usmHMAC128SHA224AuthProtocol,
                }
                priv_map = {
                    'DES': usmDESPrivProtocol,
                    'AES': usmAesCfb128Protocol,
                    'AES128': usmAesCfb128Protocol,
                    'AES192': usmAesCfb192Protocol,
                    'AES256': usmAesCfb256Protocol,
                }
                auth_data = UsmUserData(
                    username,
                    authKey=auth_password,
                    privKey=priv_password,
                    authProtocol=auth_map.get(auth_protocol, usmHMACSHAAuthProtocol),
                    privProtocol=priv_map.get(priv_protocol, usmAesCfb128Protocol)
                )
            else:
                community = snmp_config.get('snmp_community', 'public')
                auth_data = CommunityData(community)

            transport = await UdpTransportTarget.create((ip, port), timeout=5, retries=1)

            OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'
            OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'
            OID_SYS_OBJECT_ID = '1.3.6.1.2.1.1.2.0'

            sys_name = None
            sys_descr = None
            sys_object_id = None

            for oid, label in [
                (OID_SYS_NAME, 'sysName'),
                (OID_SYS_DESCR, 'sysDescr'),
                (OID_SYS_OBJECT_ID, 'sysObjectID'),
            ]:
                try:
                    err_ind, err_status, _, var_binds = await get_cmd(
                        engine, auth_data, transport, ContextData(),
                        ObjectType(ObjectIdentity(oid))
                    )
                    if not err_ind and not err_status and var_binds:
                        value = str(var_binds[0][1]).strip()
                        if label == 'sysName':
                            sys_name = ''.join(c for c in value if c.isprintable())
                        elif label == 'sysDescr':
                            sys_descr = value
                        elif label == 'sysObjectID':
                            sys_object_id = value
                except Exception as e:
                    logger.debug(f"{ip}: SNMP GET {label} failed: {e}")

            if not sys_name and not sys_descr:
                logger.debug(f"{ip}: SNMP discovery returned no usable data")
                return None

            # Determine vendor: OID is most reliable, fallback to sysDescr
            vendor = self._detect_vendor_from_oid(sys_object_id)
            if not vendor and sys_descr:
                vendor = self._detect_vendor_from_descr(sys_descr)
            if not vendor:
                vendor = 'unknown'

            # Extract model from sysDescr
            model = 'Unknown'
            if sys_descr:
                model = self._extract_model_from_sysdescr(sys_descr, vendor)

            hostname = sys_name if sys_name else ip

            logger.info(
                f"SNMP discovered {ip}: hostname={hostname} vendor={vendor} "
                f"model={model} (OID={sys_object_id})"
            )
            return {
                'hostname': hostname,
                'vendor': vendor,
                'model': model,
                'snmp_success': True
            }

        except Exception as e:
            logger.debug(f"{ip}: SNMP discovery failed: {e}")
            return None

    async def discover_switches(
        self,
        ip_range: str,
        credentials: List[Dict[str, str]],
        session_id: str = None,
        progress_queue = None,
        snmp_config: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Discover switches in an IP range using multiple credentials

        Args:
            ip_range: IP range in format "10.0.0.1-10.0.0.254" or "10.0.0.0/24"
            credentials: List of dicts with keys: username, password, enable_password (optional), port (optional)
            session_id: Optional session ID for progress tracking
            progress_queue: Optional asyncio.Queue for progress updates

        Returns:
            List of discovered switch information
        """
        loop = None
        if session_id and progress_queue:
            self.progress_queues[session_id] = progress_queue
            loop = asyncio.get_event_loop()
            self.event_loops[session_id] = loop
        
        try:
            logger.info(f"Starting switch discovery for range: {ip_range}")

            # Parse IP range
            ip_list = self._parse_ip_range(ip_range)
            
            if not ip_list:
                logger.error("No valid IPs to scan")
                raise ValueError("无法解析 IP 范围，请检查输入格式")
            
            logger.info(f"Scanning {len(ip_list)} IP addresses")
            
            if progress_queue:
                await progress_queue.put({
                    'type': 'start',
                    'total_ips': len(ip_list),
                    'total_credentials': len(credentials)
                })

            # Create tasks for all IP/credential combinations
            loop = asyncio.get_event_loop()
            tasks = []
            
            # Group by IP to try different credentials sequentially per IP
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
                        self._try_connect_with_retry,
                        ip, username, password, enable_password, port, session_id, 2,
                        progress_queue, loop
                    )
                    tasks.append(task)

            # Wait for all discovery attempts
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Filter successful discoveries (one per IP)
            discovered = []
            seen_ips = set()

            for result in results:
                if isinstance(result, dict) and result and result.get('success'):
                    ip = result['ip_address']
                    if ip not in seen_ips:
                        seen_ips.add(ip)
                        discovered.append(result)

            # Enrich discovered switches with SNMP identity data (hostname/vendor/model)
            # SNMP is more reliable for vendor/model than SSH show version parsing
            if snmp_config and discovered:
                logger.info(f"Enriching {len(discovered)} switches with SNMP identity data")
                snmp_tasks = [
                    self._discover_via_snmp(sw['ip_address'], snmp_config)
                    for sw in discovered
                ]
                snmp_results = await asyncio.gather(*snmp_tasks, return_exceptions=True)

                for sw, snmp_info in zip(discovered, snmp_results):
                    if isinstance(snmp_info, dict) and snmp_info and snmp_info.get('snmp_success'):
                        # Prefer SNMP hostname over SSH-derived hostname
                        if snmp_info.get('hostname') and snmp_info['hostname'] != sw['ip_address']:
                            sw['name'] = snmp_info['hostname']
                        # Prefer SNMP vendor over SSH-derived vendor
                        if snmp_info.get('vendor') and snmp_info['vendor'] != 'unknown':
                            sw['vendor'] = snmp_info['vendor']
                        # Prefer SNMP model over SSH-derived model
                        if snmp_info.get('model') and snmp_info['model'] != 'Unknown':
                            sw['model'] = snmp_info['model']
                        logger.info(
                            f"SNMP enriched {sw['ip_address']}: "
                            f"name={sw['name']} vendor={sw['vendor']} model={sw['model']}"
                        )
                    else:
                        logger.debug(
                            f"{sw['ip_address']}: SNMP enrichment unavailable, "
                            f"keeping SSH-discovered values (vendor={sw['vendor']})"
                        )

            logger.info(f"Discovery complete: found {len(discovered)} switches out of {len(ip_list)} IPs")

            return discovered
            
        finally:
            # Cleanup
            if session_id:
                if session_id in self.progress_queues:
                    del self.progress_queues[session_id]
                if session_id in self.event_loops:
                    del self.event_loops[session_id]

    def _parse_ip_range(self, ip_range: str) -> List[str]:
        """Parse IP range string into list of IPs"""
        try:
            ip_range = ip_range.strip()
            
            # Validate input is not empty
            if not ip_range:
                logger.error("IP range is empty")
                raise ValueError("IP 范围不能为空")
            
            # Check if it's CIDR notation
            if '/' in ip_range:
                try:
                    network = ipaddress.ip_network(ip_range, strict=False)
                    ip_list = [str(ip) for ip in network.hosts()]
                    if not ip_list:  # Empty network (like /32 or /31)
                        ip_list = [str(network.network_address)]
                    return ip_list
                except ValueError as e:
                    logger.error(f"Invalid CIDR notation '{ip_range}': {str(e)}")
                    raise ValueError(f"无效的 CIDR 格式: {ip_range}. 示例: 10.0.0.0/24")

            # Check if it's range notation (10.0.0.1-10.0.0.254)
            elif '-' in ip_range:
                try:
                    parts = ip_range.split('-', 1)
                    if len(parts) != 2:
                        raise ValueError("IP 范围格式错误")
                    
                    start_ip = parts[0].strip()
                    end_ip = parts[1].strip()

                    # If end is just a number, use start's prefix
                    if '.' not in end_ip:
                        start_parts = start_ip.split('.')
                        if len(start_parts) != 4:
                            raise ValueError("起始 IP 地址格式错误")
                        prefix = '.'.join(start_parts[:-1])
                        end_ip = f"{prefix}.{end_ip}"

                    start = ipaddress.ip_address(start_ip)
                    end = ipaddress.ip_address(end_ip)
                    
                    if start > end:
                        logger.error(f"Start IP {start_ip} is greater than end IP {end_ip}")
                        raise ValueError(f"起始 IP {start_ip} 不能大于结束 IP {end_ip}")

                    # Prevent huge ranges
                    ip_count = int(end) - int(start) + 1
                    max_ips = 1024
                    if ip_count > max_ips:
                        logger.warning(f"IP range too large ({ip_count} IPs), limiting to {max_ips}")
                        end = ipaddress.ip_address(int(start) + max_ips - 1)

                    ip_list = []
                    current = start
                    while current <= end:
                        ip_list.append(str(current))
                        current = ipaddress.ip_address(int(current) + 1)

                    return ip_list
                    
                except ValueError as e:
                    if "起始 IP" in str(e) or "IP 范围" in str(e):
                        raise
                    logger.error(f"Invalid IP range '{ip_range}': {str(e)}")
                    raise ValueError(f"无效的 IP 范围格式: {ip_range}. 示例: 10.0.0.1-10.0.0.50 或 10.0.0.1-50")

            # Single IP
            else:
                try:
                    ip = ipaddress.ip_address(ip_range)
                    return [str(ip)]
                except ValueError as e:
                    logger.error(f"Invalid IP address '{ip_range}': {str(e)}")
                    raise ValueError(f"无效的 IP 地址: {ip_range}. 示例: 10.0.0.1")

        except ValueError:
            # Re-raise ValueError for API to catch
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing IP range {ip_range}: {str(e)}")
            raise ValueError(f"解析 IP 范围时发生错误: {str(e)}")


# Singleton instance
switch_discovery_service = SwitchDiscoveryService()
