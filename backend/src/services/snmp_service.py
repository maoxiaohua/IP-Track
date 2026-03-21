"""
SNMP Service for collecting ARP and MAC tables from network switches

This service uses SNMPv3 to query switches for:
1. ARP tables (IP-MAC mappings)
2. MAC address tables (MAC-Port mappings)
3. Interface names and VLAN information

Standard SNMP OIDs used:
- IP-MIB::ipNetToMediaPhysAddress (1.3.6.1.2.1.4.22.1.2) - ARP MAC addresses
- IP-MIB::ipNetToMediaNetAddress (1.3.6.1.2.1.4.22.1.3) - ARP IP addresses
- BRIDGE-MIB::dot1dTpFdbAddress (1.3.6.1.2.1.17.4.3.1.1) - MAC addresses
- BRIDGE-MIB::dot1dTpFdbPort (1.3.6.1.2.1.17.4.3.1.2) - Port indexes
- IF-MIB::ifName (1.3.6.1.2.1.31.1.1.1.1) - Interface names
"""

from typing import Dict, List, Optional, Tuple
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd, next_cmd, CommunityData,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol, usmHMAC128SHA224AuthProtocol,
    usmDESPrivProtocol, usmAesCfb128Protocol, usmAesCfb192Protocol, usmAesCfb256Protocol
)
from pysnmp.proto.rfc1902 import OctetString
import asyncio
from utils.logger import logger
from core.security import decrypt_password


class SNMPService:
    """Service for collecting data from switches via SNMP"""

    # Standard SNMP OIDs
    OID_SYS_NAME = '1.3.6.1.2.1.1.5.0'       # sysName (hostname)
    OID_SYS_DESCR = '1.3.6.1.2.1.1.1.0'      # sysDescr (system description)
    OID_SYS_OBJECT_ID = '1.3.6.1.2.1.1.2.0'  # sysObjectID (vendor enterprise OID)
    OID_SYS_CONTACT = '1.3.6.1.2.1.1.4.0'    # sysContact (contact info)
    OID_SYS_LOCATION = '1.3.6.1.2.1.1.6.0'   # sysLocation (location)
    OID_SYS_UPTIME = '1.3.6.1.2.1.1.3.0'     # sysUpTime (time ticks since boot)
    # ENTITY-MIB: physical chassis description (index 1 = chassis)
    # Returns hardware platform string, e.g. "Nokia 7220 IXR-D2" on SR Linux
    OID_ENTITY_PHYS_DESCR = '1.3.6.1.2.1.47.1.1.1.1.2.1'
    OID_ARP_MAC = '1.3.6.1.2.1.4.22.1.2'     # ipNetToMediaPhysAddress
    OID_ARP_IP = '1.3.6.1.2.1.4.22.1.3'  # ipNetToMediaNetAddress
    OID_MAC_ADDRESS = '1.3.6.1.2.1.17.4.3.1.1'  # dot1dTpFdbAddress
    OID_MAC_PORT = '1.3.6.1.2.1.17.4.3.1.2'  # dot1dTpFdbPort
    OID_IF_NAME = '1.3.6.1.2.1.31.1.1.1.1'  # ifName
    OID_IF_INDEX = '1.3.6.1.2.1.2.2.1.1'  # ifIndex
    OID_BRIDGE_PORT_MAP = '1.3.6.1.2.1.17.1.4.1.2'  # dot1dBasePortIfIndex

    # ENTITY-MIB OIDs for optical module information
    OID_ENTITY_PHYS_DESCR_TABLE = '1.3.6.1.2.1.47.1.1.1.1.2'  # entPhysicalDescr
    OID_ENTITY_PHYS_NAME = '1.3.6.1.2.1.47.1.1.1.1.7'  # entPhysicalName
    OID_ENTITY_PHYS_MODEL = '1.3.6.1.2.1.47.1.1.1.1.13'  # entPhysicalModelName
    OID_ENTITY_PHYS_SERIAL = '1.3.6.1.2.1.47.1.1.1.1.11'  # entPhysicalSerialNum
    OID_ENTITY_PHYS_MFG = '1.3.6.1.2.1.47.1.1.1.1.12'  # entPhysicalMfgName
    OID_ENTITY_PHYS_CONTAINED_IN = '1.3.6.1.2.1.47.1.1.1.1.4'  # entPhysicalContainedIn
    OID_ENTITY_PHYS_CLASS = '1.3.6.1.2.1.47.1.1.1.1.5'  # entPhysicalClass
    OID_IF_HIGH_SPEED = '1.3.6.1.2.1.31.1.1.1.15'  # ifHighSpeed (in Mbps)

    def __init__(self):
        # Don't create a singleton engine - create per-request to avoid event loop issues
        logger.info("SNMP service initialized with asyncio")

    def _create_snmp_auth(
        self,
        username: str,
        auth_protocol: str,
        auth_password: str,
        priv_protocol: str,
        priv_password: str
    ) -> UsmUserData:
        """
        Create SNMPv3 authentication credentials

        Args:
            username: SNMPv3 username
            auth_protocol: 'MD5', 'SHA', 'SHA256'
            auth_password: Authentication password
            priv_protocol: 'DES', 'AES', 'AES128', 'AES192', 'AES256'
            priv_password: Privacy password
        """
        # Map protocol names to pysnmp protocol objects
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

        auth_proto = auth_map.get(auth_protocol.upper(), usmHMACSHAAuthProtocol)
        priv_proto = priv_map.get(priv_protocol.upper(), usmAesCfb128Protocol)

        return UsmUserData(
            username,
            authKey=auth_password,
            privKey=priv_password,
            authProtocol=auth_proto,
            privProtocol=priv_proto
        )

    async def _walk_oid(
        self,
        target_ip: str,
        oid: str,
        auth_data: UsmUserData,
        port: int = 161,
        timeout: int = 5,
        retries: int = 2
    ) -> List[Tuple[str, any]]:
        """
        Perform SNMP WALK on a specific OID using asyncio

        Returns:
            List of (OID, value) tuples
        """
        try:
            results = []
            # Create a new SnmpEngine for each request to avoid event loop issues
            engine = SnmpEngine()

            # Create transport target using .create() method for pysnmp 7.x
            transport = await UdpTransportTarget.create((target_ip, port), timeout=timeout, retries=retries)

            # In pysnmp 7.x asyncio, we need to manually loop for WALK operations
            # Start with the base OID
            varBinds = [ObjectType(ObjectIdentity(oid))]

            while True:
                errorIndication, errorStatus, errorIndex, varBinds = await next_cmd(
                    engine,
                    auth_data,
                    transport,
                    ContextData(),
                    *varBinds,
                    lexicographicMode=False
                )

                if errorIndication:
                    logger.debug(f"SNMP walk ended on {target_ip}: {errorIndication}")
                    break
                elif errorStatus:
                    logger.error(f"SNMP error on {target_ip}: {errorStatus.prettyPrint()}")
                    break
                else:
                    for varBind in varBinds:
                        oid_str = str(varBind[0])
                        value = varBind[1]
                        # Stop if we've walked past our OID tree
                        if not oid_str.startswith(oid):
                            return results
                        results.append((oid_str, value))

            return results

        except Exception as e:
            logger.error(f"SNMP walk failed for {target_ip} OID {oid}: {str(e)}")
            return []

    async def _get_oid(
        self,
        target_ip: str,
        oid: str,
        auth_data: UsmUserData,
        port: int = 161,
        timeout: int = 10  # Increased timeout from 5 to 10 seconds for slow devices
    ) -> Optional[any]:
        """
        Perform SNMP GET on a specific OID using asyncio
        """
        try:
            logger.debug(f"Starting SNMP GET on {target_ip} OID {oid} with timeout={timeout}s")

            # Create a new SnmpEngine for each request to avoid event loop issues
            engine = SnmpEngine()

            # Create transport target using .create() method for pysnmp 7.x
            transport = await UdpTransportTarget.create((target_ip, port), timeout=timeout, retries=2)
            logger.debug(f"Transport created for {target_ip}:{port}")

            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                engine,
                auth_data,
                transport,
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )

            if errorIndication:
                logger.error(f"❌ SNMP GET errorIndication on {target_ip} OID {oid}: {errorIndication} (type: {type(errorIndication).__name__})")
                return None
            elif errorStatus:
                logger.error(f"❌ SNMP GET errorStatus on {target_ip} OID {oid}: {errorStatus.prettyPrint()} at index {errorIndex}")
                return None
            else:
                for varBind in varBinds:
                    value = varBind[1]
                    logger.info(f"✅ SNMP GET success on {target_ip} OID {oid}: {value}")
                    return value

                # If we get here, varBinds was empty
                logger.warning(f"⚠️ SNMP GET returned empty varBinds for {target_ip} OID {oid}")
                return None

        except Exception as e:
            logger.error(f"❌ SNMP GET exception for {target_ip} OID {oid}: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _format_mac_address(self, mac_bytes) -> str:
        """
        Convert SNMP MAC address bytes to standard format

        Args:
            mac_bytes: Can be OctetString or bytes

        Returns:
            MAC address in format 'aa:bb:cc:dd:ee:ff'
        """
        try:
            if isinstance(mac_bytes, OctetString):
                mac_bytes = mac_bytes.asOctets()

            if isinstance(mac_bytes, bytes):
                # Convert bytes to hex string with colons
                mac_hex = ':'.join([f'{b:02x}' for b in mac_bytes])
                return mac_hex.lower()
            else:
                # Try to convert to string and parse
                mac_str = str(mac_bytes)
                # Handle hex string format
                if len(mac_str) == 12:
                    return ':'.join([mac_str[i:i+2] for i in range(0, 12, 2)]).lower()
                return mac_str.lower()

        except Exception as e:
            logger.debug(f"MAC format error: {str(e)}")
            return str(mac_bytes)

    def _format_ip_address(self, ip_bytes) -> Optional[str]:
        """
        Convert SNMP IP address bytes to dotted decimal format

        Args:
            ip_bytes: IP address in bytes or OctetString

        Returns:
            IP address in format '192.168.1.1' or None if invalid
        """
        try:
            if isinstance(ip_bytes, OctetString):
                ip_bytes = ip_bytes.asOctets()

            if isinstance(ip_bytes, bytes) and len(ip_bytes) == 4:
                return '.'.join([str(b) for b in ip_bytes])
            else:
                # Try to parse from string
                ip_str = str(ip_bytes)
                return ip_str

        except Exception as e:
            logger.debug(f"IP format error: {str(e)}")
            return None

    async def collect_arp_table(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> List[Dict]:
        """
        Collect ARP table from a switch using asyncio

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SNMP credentials

        Returns:
            List of ARP entries: [{ip, mac, vlan, interface}, ...]
        """
        try:
            # Decrypt SNMP passwords
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = decrypt_password(switch_config['snmp_priv_password_encrypted'])

            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config['snmp_priv_protocol'],
                priv_password=priv_password
            )

            port = switch_config.get('snmp_port', 161)

            # Walk ARP table
            arp_entries = []
            arp_data = {}

            # Get IP addresses from ARP table
            ip_results = await self._walk_oid(switch_ip, self.OID_ARP_IP, auth_data, port)
            for oid, value in ip_results:
                # OID format: 1.3.6.1.2.1.4.22.1.3.ifIndex.ipAddress
                # Extract index (last part of OID)
                index = oid.split('.')[-5:]  # Get last 5 parts (ifIndex + IP)
                index_key = '.'.join(index)

                ip_addr = self._format_ip_address(value)
                if ip_addr:
                    arp_data[index_key] = {'ip': ip_addr}

            # Get MAC addresses from ARP table
            mac_results = await self._walk_oid(switch_ip, self.OID_ARP_MAC, auth_data, port)
            for oid, value in mac_results:
                index = oid.split('.')[-5:]
                index_key = '.'.join(index)

                mac_addr = self._format_mac_address(value)
                if index_key in arp_data:
                    arp_data[index_key]['mac'] = mac_addr
                else:
                    arp_data[index_key] = {'mac': mac_addr}

            # Convert to list and filter complete entries
            for index, data in arp_data.items():
                if 'ip' in data and 'mac' in data:
                    arp_entries.append({
                        'ip_address': data['ip'],
                        'mac_address': data['mac'],
                        'vlan_id': None,  # VLAN can be extracted from index if needed
                        'interface': None,
                        'age_seconds': None
                    })

            logger.info(f"Collected {len(arp_entries)} ARP entries from {switch_ip}")
            return arp_entries

        except Exception as e:
            logger.error(f"Failed to collect ARP table from {switch_ip}: {str(e)}")
            return []

    async def collect_mac_table(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> List[Dict]:
        """
        Collect MAC address table from a switch using asyncio

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SNMP credentials

        Returns:
            List of MAC entries: [{mac, port_name, vlan, is_dynamic}, ...]
        """
        try:
            # Decrypt SNMP passwords
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = decrypt_password(switch_config['snmp_priv_password_encrypted'])

            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config['snmp_priv_protocol'],
                priv_password=priv_password
            )

            port = switch_config.get('snmp_port', 161)

            # Step 1: Get bridge port to ifIndex mapping
            port_map = {}  # bridge_port -> ifIndex
            bridge_results = await self._walk_oid(switch_ip, self.OID_BRIDGE_PORT_MAP, auth_data, port)
            for oid, value in bridge_results:
                bridge_port = int(oid.split('.')[-1])
                if_index = int(value)
                port_map[bridge_port] = if_index

            # Step 2: Get interface names
            if_names = {}  # ifIndex -> interface name
            name_results = await self._walk_oid(switch_ip, self.OID_IF_NAME, auth_data, port)
            for oid, value in name_results:
                if_index = int(oid.split('.')[-1])
                if_name = str(value)
                if_names[if_index] = if_name

            # Step 3: Get MAC addresses and their ports
            mac_entries = []
            mac_data = {}

            # Get MAC addresses
            mac_results = await self._walk_oid(switch_ip, self.OID_MAC_ADDRESS, auth_data, port)
            for oid, value in mac_results:
                # OID format: 1.3.6.1.2.1.17.4.3.1.1.vlan.mac
                mac_addr = self._format_mac_address(value)
                # Extract VLAN from OID if present
                vlan_id = None
                try:
                    vlan_id = int(oid.split('.')[-7])
                except:
                    pass

                mac_data[oid] = {
                    'mac': mac_addr,
                    'vlan': vlan_id
                }

            # Get port assignments
            port_results = await self._walk_oid(switch_ip, self.OID_MAC_PORT, auth_data, port)
            for oid, value in port_results:
                # Match OID with MAC data
                mac_oid = oid.replace(self.OID_MAC_PORT, self.OID_MAC_ADDRESS)

                if mac_oid in mac_data:
                    bridge_port = int(value)

                    # Map bridge port to interface name
                    if_index = port_map.get(bridge_port, bridge_port)
                    port_name = if_names.get(if_index, f"Port{bridge_port}")

                    mac_entries.append({
                        'mac_address': mac_data[mac_oid]['mac'],
                        'port_name': port_name,
                        'vlan_id': mac_data[mac_oid]['vlan'],
                        'is_dynamic': 1
                    })

            logger.info(f"Collected {len(mac_entries)} MAC entries from {switch_ip}")
            return mac_entries

        except Exception as e:
            logger.error(f"Failed to collect MAC table from {switch_ip}: {str(e)}")
            return []

    async def get_hostname(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[str]:
        """
        Get hostname from switch via SNMP sysName OID

        Args:
            switch_ip: IP address of the switch
            switch_config: Dictionary with SNMP credentials

        Returns:
            Hostname string or None if failed
        """
        try:
            logger.info(f"Starting SNMP GET for hostname on {switch_ip}")

            # Decrypt SNMP passwords
            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = decrypt_password(switch_config['snmp_priv_password_encrypted'])

            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config['snmp_priv_protocol'],
                priv_password=priv_password
            )

            port = switch_config.get('snmp_port', 161)

            # Get hostname via SNMP
            result = await self._get_oid(switch_ip, self.OID_SYS_NAME, auth_data, port)

            if result:
                hostname = str(result).strip()
                # Clean up hostname - remove any non-printable characters
                hostname = ''.join(char for char in hostname if char.isprintable())
                logger.info(f"✅ Got hostname from {switch_ip} via SNMP: {hostname}")
                return hostname
            else:
                logger.error(f"❌ No hostname returned from {switch_ip} - SNMP GET returned None")
                return None

        except Exception as e:
            logger.error(f"❌ Failed to get hostname from {switch_ip}: {str(e)}")
            return None

    async def get_device_info(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> Optional[Dict]:
        """
        Get device identity info (hostname, vendor, model) via SNMP.
        Queries sysName, sysDescr, sysObjectID, and (optionally) ENTITY-MIB
        entPhysicalDescr for chassis hardware identification.

        Returns dict with keys: hostname, sys_descr, sys_object_id, entity_phys_descr
        or None if SNMP fails.
        """
        try:
            logger.info(f"Getting device info from {switch_ip} via SNMP")

            auth_password = decrypt_password(switch_config['snmp_auth_password_encrypted'])
            priv_password = decrypt_password(switch_config['snmp_priv_password_encrypted'])

            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config['snmp_auth_protocol'],
                auth_password=auth_password,
                priv_protocol=switch_config['snmp_priv_protocol'],
                priv_password=priv_password
            )

            port = switch_config.get('snmp_port', 161)

            hostname = None
            sys_descr = None
            sys_object_id = None

            for oid, label in [
                (self.OID_SYS_NAME, 'sysName'),
                (self.OID_SYS_DESCR, 'sysDescr'),
                (self.OID_SYS_OBJECT_ID, 'sysObjectID'),
            ]:
                value = await self._get_oid(switch_ip, oid, auth_data, port, timeout=8)
                if value is not None:
                    value_str = str(value).strip()
                    if label == 'sysName':
                        hostname = ''.join(c for c in value_str if c.isprintable())
                    elif label == 'sysDescr':
                        sys_descr = value_str
                    elif label == 'sysObjectID':
                        sys_object_id = value_str

            if not hostname and not sys_descr:
                logger.warning(f"No usable SNMP data from {switch_ip}")
                return None

            # Query ENTITY-MIB chassis description — optional, not all devices support it.
            # Useful for Nokia SR Linux where sysDescr only contains OS version, not hardware model.
            entity_phys_descr = None
            try:
                value = await self._get_oid(
                    switch_ip, self.OID_ENTITY_PHYS_DESCR, auth_data, port, timeout=5
                )
                if value is not None:
                    entity_phys_descr = str(value).strip()
                    logger.debug(f"ENTITY-MIB chassis descr from {switch_ip}: {entity_phys_descr}")
            except Exception:
                pass  # ENTITY-MIB is optional

            logger.info(
                f"Got device info from {switch_ip}: hostname={hostname} "
                f"OID={sys_object_id}"
            )
            return {
                'hostname': hostname,
                'sys_descr': sys_descr,
                'sys_object_id': sys_object_id,
                'entity_phys_descr': entity_phys_descr,
            }

        except Exception as e:
            logger.error(f"Failed to get device info from {switch_ip}: {str(e)}")
            return None

    async def get_device_identification(
        self,
        target_ip: str,
        snmp_profile: Dict
    ) -> Optional[Dict]:
        """
        Get device identification info for IPAM (SolarWinds-style)

        Queries the following SNMP OIDs:
        - sysName (1.3.6.1.2.1.1.5.0): System hostname
        - sysContact (1.3.6.1.2.1.1.4.0): Contact information
        - sysLocation (1.3.6.1.2.1.1.6.0): Physical location
        - sysUpTime (1.3.6.1.2.1.1.3.0): Time since boot
        - sysDescr (1.3.6.1.2.1.1.1.0): System description (for machine_type/vendor)

        Args:
            target_ip: IP address of the device to query
            snmp_profile: SNMP profile dictionary with credentials

        Returns:
            Dictionary with keys:
            - system_name: SNMP sysName (hostname)
            - contact: SNMP sysContact
            - location: SNMP sysLocation
            - last_boot_time: Calculated datetime from sysUpTime
            - machine_type: Extracted from sysDescr
            - vendor: Extracted from sysDescr
            Or None if SNMP query fails
        """
        try:
            logger.debug(f"Getting device identification from {target_ip} via SNMP")

            # Decrypt SNMP passwords
            auth_password = decrypt_password(snmp_profile['auth_password_encrypted'])
            priv_password = decrypt_password(snmp_profile['priv_password_encrypted'])

            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=snmp_profile['username'],
                auth_protocol=snmp_profile.get('auth_protocol', 'SHA'),
                auth_password=auth_password,
                priv_protocol=snmp_profile.get('priv_protocol', 'AES'),
                priv_password=priv_password
            )

            port = snmp_profile.get('port', 161)
            timeout = snmp_profile.get('timeout', 5)

            # Query all OIDs
            result = {
                'system_name': None,
                'contact': None,
                'location': None,
                'last_boot_time': None,
                'machine_type': None,
                'vendor': None
            }

            # sysName (hostname)
            sys_name = await self._get_oid(target_ip, self.OID_SYS_NAME, auth_data, port, timeout)
            if sys_name:
                result['system_name'] = ''.join(c for c in str(sys_name) if c.isprintable()).strip()

            # sysContact
            sys_contact = await self._get_oid(target_ip, self.OID_SYS_CONTACT, auth_data, port, timeout)
            if sys_contact:
                result['contact'] = str(sys_contact).strip()

            # sysLocation
            sys_location = await self._get_oid(target_ip, self.OID_SYS_LOCATION, auth_data, port, timeout)
            if sys_location:
                result['location'] = str(sys_location).strip()

            # sysDescr (for machine_type and vendor extraction)
            sys_descr = await self._get_oid(target_ip, self.OID_SYS_DESCR, auth_data, port, timeout)
            if sys_descr:
                descr = str(sys_descr).strip()
                # Try to extract vendor and machine type from sysDescr
                descr_lower = descr.lower()

                # Enhanced vendor detection
                if 'cisco' in descr_lower:
                    result['vendor'] = 'Cisco'
                elif 'dell' in descr_lower:
                    result['vendor'] = 'Dell'
                elif 'hp' in descr_lower or 'hewlett' in descr_lower or 'hewlett-packard' in descr_lower:
                    result['vendor'] = 'HP'
                elif 'juniper' in descr_lower:
                    result['vendor'] = 'Juniper'
                elif 'nokia' in descr_lower or 'alcatel' in descr_lower:
                    result['vendor'] = 'Nokia'
                elif 'huawei' in descr_lower:
                    result['vendor'] = 'Huawei'
                elif 'zte' in descr_lower:
                    result['vendor'] = 'ZTE'
                elif 'aruba' in descr_lower:
                    result['vendor'] = 'Aruba'
                elif 'fortinet' in descr_lower or 'fortigate' in descr_lower:
                    result['vendor'] = 'Fortinet'

                # Enhanced device type detection
                machine_type = descr.split('\n')[0][:200] if descr else None

                # Categorize device types based on sysDescr patterns
                if 'switch' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Switch"
                elif 'router' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Router"
                elif 'firewall' in descr_lower or 'fortigate' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Firewall"
                elif 'access point' in descr_lower or 'wireless' in descr_lower or 'ap' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Access Point"
                elif 'base station' in descr_lower or 'bts' in descr_lower or 'enodeb' in descr_lower or 'gnodeb' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Nokia')} Base Station"
                elif 'server' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Server"
                elif 'workstation' in descr_lower or 'pc' in descr_lower or 'desktop' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} PC"
                elif 'laptop' in descr_lower or 'notebook' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Laptop"
                elif 'printer' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} Printer"
                elif 'camera' in descr_lower or 'ipc' in descr_lower:
                    result['machine_type'] = f"{result.get('vendor', 'Unknown')} IP Camera"
                else:
                    # Use raw sysDescr as fallback
                    result['machine_type'] = machine_type

            # sysUpTime (time ticks since boot, convert to last_boot_time)
            sys_uptime = await self._get_oid(target_ip, self.OID_SYS_UPTIME, auth_data, port, timeout)
            if sys_uptime:
                try:
                    # sysUpTime is in hundredths of seconds
                    uptime_ticks = int(sys_uptime)
                    uptime_seconds = uptime_ticks / 100

                    # Calculate last boot time
                    from datetime import datetime, timedelta, timezone
                    now = datetime.now(timezone.utc)
                    last_boot = now - timedelta(seconds=uptime_seconds)
                    result['last_boot_time'] = last_boot.isoformat()

                    logger.debug(f"Device {target_ip} uptime: {uptime_seconds}s, last boot: {last_boot}")
                except Exception as e:
                    logger.warning(f"Failed to parse sysUpTime for {target_ip}: {str(e)}")

            # Return result if we got at least one field
            if result['system_name'] or result['contact'] or result['location']:
                logger.info(
                    f"Got device identification from {target_ip}: "
                    f"sysName={result['system_name']}, "
                    f"location={result['location']}, "
                    f"vendor={result['vendor']}"
                )
                return result
            else:
                logger.warning(f"No device identification data retrieved from {target_ip}")
                return None

        except Exception as e:
            logger.error(f"Failed to get device identification from {target_ip}: {str(e)}")
            return None

    # Keep compatibility with async wrappers
    async def collect_arp_table_async(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> List[Dict]:
        """Async wrapper for ARP table collection - now just calls the async method"""
        return await self.collect_arp_table(switch_ip, switch_config)

    async def collect_mac_table_async(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> List[Dict]:
        """Async wrapper for MAC table collection - now just calls the async method"""
        return await self.collect_mac_table(switch_ip, switch_config)

    async def collect_optical_modules(
        self,
        switch_ip: str,
        switch_config: Dict
    ) -> List[Dict]:
        """
        Collect optical transceiver (SFP/QSFP) information from switch via SNMP

        Uses ENTITY-MIB to retrieve:
        - Module type (SFP, SFP+, QSFP, etc.)
        - Model number
        - Serial number
        - Vendor/manufacturer
        - Port mapping

        Args:
            switch_ip: IP address of the switch
            switch_config: SNMP configuration dictionary

        Returns:
            List of optical module dictionaries with keys:
            - port_name: Interface name
            - module_type: SFP/SFP+/QSFP/QSFP+/QSFP28
            - model: Model number
            - serial_number: Serial number
            - vendor: Manufacturer name
            - speed_gbps: Port speed in Gbps
        """
        logger.info(f"Collecting optical modules from {switch_ip} via SNMP")

        try:
            # Create SNMP authentication
            auth_data = self._create_snmp_auth(
                username=switch_config['snmp_username'],
                auth_protocol=switch_config.get('snmp_auth_protocol', 'SHA'),
                auth_password=decrypt_password(switch_config['snmp_auth_password_encrypted']),
                priv_protocol=switch_config.get('snmp_priv_protocol', 'AES'),
                priv_password=decrypt_password(switch_config['snmp_priv_password_encrypted'])
            )

            # Step 1: Walk entPhysicalDescr and entPhysicalClass to find optical modules
            logger.debug(f"Walking entPhysicalDescr and entPhysicalClass on {switch_ip}")
            phys_descr = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_DESCR_TABLE, auth_data)
            phys_class = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_CLASS, auth_data)

            if not phys_descr:
                logger.warning(f"No entPhysicalDescr entries found on {switch_ip}")
                return []

            # Convert entPhysicalClass to dictionary
            # RFC 2737: 1=other, 2=unknown, 3=chassis, 4=backplane, 5=container,
            #           6=powerSupply, 7=fan, 8=sensor, 9=module, 10=port
            class_dict = {str(oid).split('.')[-1]: int(val) for oid, val in phys_class}

            # Filter entries that are optical modules
            optical_keywords = ['sfp', 'qsfp', 'transceiver', 'gbic', 'optic']
            exclude_keywords = [
                'fan', 'power supply', 'sensor', 'temperature', 'cpu', 'memory', 'stack',
                'container', 'slot', 'backplane', 'chassis', 'board',
                'motherboard', 'supervisor', 'linecard', 'switch system',
                # Exclude entire interface boards/modules (these contain multiple ports)
                ' x ', 'network module', 'routing module'
            ]

            module_indices = []
            for oid, value in phys_descr:
                # Extract index from OID (last component)
                index = str(oid).split('.')[-1]
                desc_lower = str(value).lower()

                # Get entPhysicalClass for this entity
                entity_class = class_dict.get(index, 0)

                # Check if this is an optical module
                is_optical = any(keyword in desc_lower for keyword in optical_keywords)
                is_excluded = any(keyword in desc_lower for keyword in exclude_keywords)

                if is_optical and not is_excluded:
                    module_indices.append((index, str(value)))
                    logger.debug(f"Found optical module at index {index} (class={entity_class}): {value}")
                elif is_optical and is_excluded:
                    logger.debug(f"Excluded at index {index} (class={entity_class}): {value[:80]}")

            if not module_indices:
                logger.info(f"No optical modules found on {switch_ip}")
                # Log first 10 physical entities for debugging
                logger.debug("First 10 entPhysicalDescr entries:")
                for i, (oid, value) in enumerate(phys_descr[:10]):
                    index = str(oid).split('.')[-1]
                    entity_class = class_dict.get(index, 0)
                    logger.debug(f"  [{index}] class={entity_class}: {str(value)[:80]}")
                return []

            logger.info(f"Found {len(module_indices)} optical modules on {switch_ip}")

            # Step 2: Collect additional info for each module
            modules = []

            # Walk all needed OIDs once
            logger.debug(f"Collecting model names, serials, vendors, names, and containment info")
            phys_model = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_MODEL, auth_data)
            phys_serial = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_SERIAL, auth_data)
            phys_vendor = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_MFG, auth_data)
            phys_name = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_NAME, auth_data)
            phys_contained = await self._walk_oid(switch_ip, self.OID_ENTITY_PHYS_CONTAINED_IN, auth_data)
            if_names = await self._walk_oid(switch_ip, self.OID_IF_NAME, auth_data)
            if_speeds = await self._walk_oid(switch_ip, self.OID_IF_HIGH_SPEED, auth_data)

            # Convert to dictionaries for easy lookup
            model_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_model}
            serial_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_serial}
            vendor_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_vendor}
            phys_name_dict = {str(oid).split('.')[-1]: str(val) for oid, val in phys_name}
            contained_dict = {str(oid).split('.')[-1]: int(val) for oid, val in phys_contained}
            ifname_dict = {str(oid).split('.')[-1]: str(val) for oid, val in if_names}
            ifspeed_dict = {str(oid).split('.')[-1]: int(val) for oid, val in if_speeds}

            # Step 3: Map modules to ports and collect info
            for index, description in module_indices:
                try:
                    # Determine module type from description
                    desc_lower = description.lower()
                    if 'qsfp28' in desc_lower or '100g' in desc_lower:
                        module_type = 'QSFP28'
                    elif 'qsfp+' in desc_lower or '40g' in desc_lower:
                        module_type = 'QSFP+'
                    elif 'qsfp' in desc_lower:
                        module_type = 'QSFP'
                    elif 'sfp+' in desc_lower or '10g' in desc_lower:
                        module_type = 'SFP+'
                    elif 'sfp' in desc_lower:
                        module_type = 'SFP'
                    else:
                        module_type = 'Transceiver'

                    # Get additional info
                    model = model_dict.get(index, '').strip()
                    serial = serial_dict.get(index, '').strip()
                    vendor = vendor_dict.get(index, '').strip()

                    # Find parent port (walk up containment hierarchy)
                    port_name = None
                    parent_index = contained_dict.get(index)

                    # Strategy 1: Try entPhysicalName directly (many vendors use this for port names)
                    entity_name = phys_name_dict.get(index, '').strip()
                    if entity_name and ('ethernet' in entity_name.lower() or
                                        'gigabit' in entity_name.lower() or
                                        'tengigabit' in entity_name.lower() or
                                        '/' in entity_name):  # Port names often have format like "1/0/1"
                        port_name = entity_name
                        logger.debug(f"Found port name from entPhysicalName: {port_name}")

                    # Strategy 2: Walk up containment hierarchy to find ifName
                    if not port_name and parent_index:
                        # Try up to 5 levels of parents
                        current_index = str(parent_index)
                        for level in range(5):
                            # Check if current parent has ifName
                            if_name = ifname_dict.get(current_index)
                            if if_name:
                                port_name = if_name
                                logger.debug(f"Found port name at level {level+1}: {port_name}")
                                break

                            # Check if current parent has entPhysicalName that looks like a port
                            parent_name = phys_name_dict.get(current_index, '').strip()
                            if parent_name and ('ethernet' in parent_name.lower() or
                                                'gigabit' in parent_name.lower() or
                                                '/' in parent_name):
                                port_name = parent_name
                                logger.debug(f"Found port name from parent entPhysicalName at level {level+1}: {port_name}")
                                break

                            # Go up one more level
                            if current_index not in contained_dict:
                                break
                            current_index = str(contained_dict[current_index])

                    # Strategy 3: Fallback - try using the module index directly as ifIndex
                    if not port_name:
                        port_name = ifname_dict.get(index)
                        if port_name:
                            logger.debug(f"Found port name from direct ifIndex mapping: {port_name}")

                    # Get port speed (in Mbps, convert to Gbps)
                    speed_mbps = None
                    if parent_index:
                        speed_mbps = ifspeed_dict.get(str(parent_index))
                    if not speed_mbps:
                        speed_mbps = ifspeed_dict.get(index)

                    speed_gbps = None
                    if speed_mbps and speed_mbps > 0:
                        speed_gbps = speed_mbps // 1000  # Convert Mbps to Gbps

                    # Only include if we successfully mapped to a port
                    if port_name:
                        modules.append({
                            'port_name': port_name,
                            'module_type': module_type,
                            'model': model if model else None,
                            'serial_number': serial if serial else None,
                            'vendor': vendor if vendor else None,
                            'speed_gbps': speed_gbps
                        })
                        logger.debug(
                            f"Mapped {module_type} to port {port_name} "
                            f"(model: {model}, SN: {serial}, vendor: {vendor})"
                        )
                    else:
                        logger.warning(
                            f"Could not map module at index {index} to port - "
                            f"parent: {parent_index}, desc: {description[:50]}"
                        )

                except Exception as e:
                    logger.error(f"Error processing module at index {index}: {str(e)}")
                    continue

            logger.info(f"Successfully collected {len(modules)} optical modules from {switch_ip}")
            return modules

        except Exception as e:
            logger.error(f"Failed to collect optical modules from {switch_ip}: {str(e)}")
            return []


# Singleton instance
snmp_service = SNMPService()
