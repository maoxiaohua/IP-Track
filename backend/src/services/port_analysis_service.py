"""
Port Analysis Service

Analyzes switch ports to determine their type (access/trunk/uplink)
based on the number of MAC addresses learned and port naming conventions.

USER REQUIREMENT: Only 1 MAC = access port, >1 MAC = trunk port
"""

import re
from typing import Dict, List
from enum import Enum
from utils.logger import logger


class PortType(str, Enum):
    """Port type classifications"""
    ACCESS = "access"  # End device connected (single MAC only)
    TRUNK = "trunk"  # Multiple MACs (cascaded switch, AP, etc)
    UPLINK = "uplink"  # Very high MAC count (50+)
    UNKNOWN = "unknown"  # Cannot determine


class PortAnalysisService:
    """Service for analyzing port types based on MAC count"""

    _PORT_NAME_PATTERNS = (
        (r'^(?:tengigabitethernet|te)\s*(?P<suffix>\d.+)$', 'Te'),
        (r'^(?:fortygigabitethernet|fortygige|fo)\s*(?P<suffix>\d.+)$', 'Fo'),
        (r'^(?:gigabitethernet|gi)\s*(?P<suffix>\d.+)$', 'Gi'),
        (r'^(?:fastethernet|fa)\s*(?P<suffix>\d.+)$', 'Fa'),
        (r'^(?:hundredgigabitethernet|hundredgige|hu)\s*(?P<suffix>\d.+)$', 'Hu'),
        (r'^(?:twentyfivegigabitethernet|twentyfivegige|twe)\s*(?P<suffix>\d.+)$', 'Twe'),
    )

    def normalize_port_name(self, port_name: str) -> str:
        """Normalize equivalent interface names to a single canonical form."""
        cleaned = re.sub(r'\s+', ' ', str(port_name or '').strip())
        if not cleaned:
            return ''

        for pattern, canonical_prefix in self._PORT_NAME_PATTERNS:
            match = re.match(pattern, cleaned, re.IGNORECASE)
            if match:
                suffix = re.sub(r'\s+', '', match.group('suffix').strip())
                return f"{canonical_prefix} {suffix}"

        return cleaned

    def classify_port(
        self,
        port_name: str,
        mac_count: int,
        unique_vlans: int = 1
    ) -> Dict:
        """
        Classify a port based on MAC count (STRICT: Only 1 MAC = access)

        Args:
            port_name: Interface name
            mac_count: Number of unique MAC addresses learned on this port
            unique_vlans: Number of unique VLANs seen on this port

        Returns:
            Dict with {port_type, confidence_score, reasoning}
        """
        port_lower = port_name.lower()
        confidence = 50.0
        port_type = PortType.UNKNOWN
        reasoning = []

        # === Rule 1: MAC Count Analysis (STRICT: Only 1 MAC = Access) ===
        # USER REQUIREMENT: Only single MAC address ports are true access ports
        # Any port with >1 MAC (including 2 MACs like IP phone+PC) is trunk/cascaded

        if mac_count == 0:
            port_type = PortType.UNKNOWN
            confidence = 0
            reasoning.append("No MACs learned")

        elif mac_count == 1:
            # ONLY single MAC = true access port (direct device connection)
            port_type = PortType.ACCESS
            confidence = 95
            reasoning.append(f"Single MAC - true access port")

        elif mac_count == 2:
            # 2 MACs = trunk (could be IP phone+PC, small hub, cascaded switch)
            port_type = PortType.TRUNK
            confidence = 70
            reasoning.append(f"2 MACs - trunk/cascaded device")

        elif 3 <= mac_count <= 10:
            # Multiple MACs = trunk (wireless AP, small switch, hub)
            port_type = PortType.TRUNK
            confidence = 80
            reasoning.append(f"{mac_count} MACs - trunk/cascaded switch")

        elif 11 <= mac_count < 50:
            # Many MACs = trunk
            port_type = PortType.TRUNK
            confidence = 90
            reasoning.append(f"{mac_count} MACs - clear trunk")

        else:  # mac_count >= 50
            # Very many MACs = uplink
            port_type = PortType.UPLINK
            confidence = 95
            reasoning.append(f"{mac_count} MACs - uplink port")

        # === Rule 2: VLAN Count Adjustment ===
        # Note: For service-based switches (e.g., Nokia 7250), same MAC can appear in
        # multiple VLANs/services. Only use VLAN count as weak indicator, not absolute rule.

        if unique_vlans > 1:
            # Multiple VLANs - only weak indicator, don't override mac_count classification
            if port_type == PortType.ACCESS and mac_count == 1:
                # Single MAC in multiple VLANs - keep as ACCESS
                # This is common for service-based switches or voice+data VLAN configs
                confidence = max(confidence - 15, 50)  # Reduce confidence slightly
                reasoning.append(f"Single MAC in {unique_vlans} VLANs - likely service-based config or voice VLAN")
            elif port_type == PortType.ACCESS and mac_count > 1:
                # Multiple MACs in multiple VLANs - likely trunk
                port_type = PortType.TRUNK
                confidence = max(confidence, 80)
                reasoning.append(f"{mac_count} MACs in {unique_vlans} VLANs - trunk")
            else:
                # Already classified as trunk/uplink, VLANs confirm
                confidence = min(confidence + 10, 100)
                reasoning.append(f"Multiple VLANs ({unique_vlans}) confirms classification")

        return {
            'port_type': port_type.value,
            'confidence_score': round(confidence, 2),
            'is_trunk_by_name': 0,
            'is_access_by_name': 0,
            'reasoning': ' | '.join(reasoning),
            'mac_count': mac_count,
            'unique_vlans': unique_vlans
        }

    def analyze_port_statistics(
        self,
        mac_table_entries: List[Dict]
    ) -> Dict[str, Dict]:
        """
        Analyze all ports from MAC table entries

        Args:
            mac_table_entries: List of MAC table records for a switch

        Returns:
            Dict mapping port_name -> analysis_result
        """
        # Group MACs by port
        port_stats = {}

        for entry in mac_table_entries:
            port = self.normalize_port_name(entry['port_name'])
            if not port:
                continue
            vlan = entry.get('vlan_id')
            mac_address = str(entry.get('mac_address') or '').lower()
            if not mac_address:
                continue

            if port not in port_stats:
                port_stats[port] = {
                    'macs': set(),
                    'vlans': set()
                }

            port_stats[port]['macs'].add(mac_address)
            if vlan:
                port_stats[port]['vlans'].add(vlan)

        # Classify each port
        results = {}
        for port, stats in port_stats.items():
            mac_count = len(stats['macs'])
            vlan_count = len(stats['vlans'])

            analysis = self.classify_port(port, mac_count, vlan_count)
            results[port] = analysis

        logger.info(f"Analyzed {len(results)} ports: "
                   f"{sum(1 for r in results.values() if r['port_type'] == 'access')} access, "
                   f"{sum(1 for r in results.values() if r['port_type'] == 'trunk')} trunk")

        return results


# Singleton instance
port_analysis_service = PortAnalysisService()
