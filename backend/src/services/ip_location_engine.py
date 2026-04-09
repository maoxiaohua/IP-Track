"""
IP Location Matching Engine

Matches IP addresses to switch ports using:
1. ARP table data (IP -> MAC mappings)
2. MAC table data (MAC -> Port mappings)
3. Port analysis (to filter out trunk ports)

Implements confidence scoring to handle conflicts when a MAC appears
on multiple switches.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from utils.logger import logger
from services.port_lookup_policy_service import resolve_lookup_policy


class IPLocationEngine:
    """Engine for matching IP addresses to switch ports with confidence scoring"""

    def calculate_confidence(
        self,
        mac_count_on_port: int,
        port_type: str,
        appears_on_switches: int,
        arp_age_seconds: Optional[int] = None
    ) -> float:
        """
        Calculate confidence score for IP location match

        Args:
            mac_count_on_port: Number of MACs on the port
            port_type: Port type ('access', 'trunk', 'uplink')
            appears_on_switches: How many switches see this MAC
            arp_age_seconds: Age of ARP entry (fresher is better)

        Returns:
            Confidence score (0-100)
        """
        score = 50.0  # Start neutral

        # === Factor 1: MAC Count (Your Core Algorithm) ===
        if mac_count_on_port == 1:
            score += 30  # Perfect - single MAC on port
        elif mac_count_on_port == 2:
            score += 25  # Very good - likely IP phone + PC
        elif mac_count_on_port <= 5:
            score += 15  # OK - might be AP or VM host
        elif mac_count_on_port <= 10:
            score += 5  # Low - probably trunk but could be valid
        else:
            score -= 30  # Very unlikely - definitely trunk

        # === Factor 2: Port Type ===
        if port_type == 'access':
            score += 25  # Strong indicator
        elif port_type == 'trunk':
            score -= 35  # Should not match trunk ports
        elif port_type == 'uplink':
            score -= 40  # Definitely wrong
        # 'unknown' has no adjustment

        # === Factor 3: MAC Appearances ===
        if appears_on_switches == 1:
            score += 20  # Excellent - unique location
        elif appears_on_switches == 2:
            score += 5  # OK - might be legitimate
        elif appears_on_switches >= 3:
            score -= 15  # Problematic - likely L3 MAC

        # === Factor 4: ARP Freshness ===
        if arp_age_seconds is not None:
            if arp_age_seconds < 300:  # Less than 5 minutes
                score += 10
            elif arp_age_seconds < 1800:  # Less than 30 minutes
                score += 5
            elif arp_age_seconds > 7200:  # Over 2 hours
                score -= 5

        # Clamp to 0-100 range
        return max(0.0, min(100.0, score))

    def match_ip_to_location(
        self,
        ip_address: str,
        arp_records: List[Dict],
        mac_records: List[Dict],
        port_analysis: Dict[Tuple[int, str], Dict]  # (switch_id, port) -> analysis
    ) -> Optional[Dict]:
        """
        Match an IP address to a switch port

        Args:
            ip_address: IP to locate
            arp_records: ARP table records [{ip, mac, switch_id, ...}, ...]
            mac_records: MAC table records [{mac, port, switch_id, ...}, ...]
            port_analysis: Port analysis results {(switch_id, port): {port_type, mac_count, ...}}

        Returns:
            Best match: {
                ip_address, mac_address, switch_id, port_name, vlan_id,
                confidence_score, detection_method, port_mac_count,
                appears_on_switches, reasoning
            }
            or None if no valid match found
        """
        # Step 1: Find MAC address(es) for this IP
        ip_mac_mappings = [
            r for r in arp_records
            if r['ip_address'] == ip_address
        ]

        if not ip_mac_mappings:
            logger.debug(f"No ARP entry found for {ip_address}")
            return None

        # Get all MACs associated with this IP (usually just one)
        mac_addresses = list(set([r['mac_address'] for r in ip_mac_mappings]))

        if len(mac_addresses) > 1:
            logger.warning(f"IP {ip_address} has multiple MACs: {mac_addresses}")
            # Use most recent ARP entry
            ip_mac_mappings.sort(key=lambda x: x.get('collected_at', datetime.min), reverse=True)

        # Use the primary MAC (most recent)
        primary_mac = ip_mac_mappings[0]['mac_address']

        # Step 2: Find all ports where this MAC appears
        mac_locations = [
            r for r in mac_records
            if r['mac_address'] == primary_mac
        ]

        if not mac_locations:
            logger.debug(f"MAC {primary_mac} for IP {ip_address} not found in MAC tables")
            return None

        # Count how many switches see this MAC
        unique_switches = len(set([r['switch_id'] for r in mac_locations]))

        # Step 3: Score each candidate location
        candidates = []

        for mac_loc in mac_locations:
            switch_id = mac_loc['switch_id']
            port_name = mac_loc['port_name']
            vlan_id = mac_loc.get('vlan_id')

            # Get port analysis data
            port_key = (switch_id, port_name)
            port_info = port_analysis.get(port_key, {})
            port_type = port_info.get('port_type', 'unknown')
            mac_count = port_info.get('mac_count', 0)
            resolved_lookup_policy = resolve_lookup_policy(
                port_type=port_info.get('port_type'),
                lookup_policy_override=port_info.get('lookup_policy_override'),
                has_analysis=bool(port_info)
            )

            if not resolved_lookup_policy['included']:
                logger.debug(
                    f"Skipping port {port_name} on switch {switch_id} "
                    f"for MAC {primary_mac} ({resolved_lookup_policy['reason']})"
                )
                continue

            # Also filter out ports with excessive MAC count (>10) as safety net
            if mac_count > 10:
                logger.debug(
                    f"Skipping port {port_name} on switch {switch_id} with excessive MACs "
                    f"({mac_count} MACs) for {primary_mac}"
                )
                continue

            # Get ARP age if available
            arp_age = ip_mac_mappings[0].get('age_seconds')

            # Calculate confidence
            confidence = self.calculate_confidence(
                mac_count_on_port=mac_count,
                port_type=port_type,
                appears_on_switches=unique_switches,
                arp_age_seconds=arp_age
            )

            candidates.append({
                'ip_address': ip_address,
                'mac_address': primary_mac,
                'switch_id': switch_id,
                'port_name': port_name,
                'vlan_id': vlan_id,
                'confidence_score': confidence,
                'detection_method': 'snmp_arp_mac',
                'port_mac_count': mac_count,
                'appears_on_switches': unique_switches,
                'port_type': port_type,
                'reasoning': (
                    f"MAC on {unique_switches} switch(es), port has {mac_count} MACs, "
                    f"type={port_type}, policy={resolved_lookup_policy['reason']}"
                )
            })

        # Step 4: Select best candidate
        if not candidates:
            return None

        # Sort by confidence (highest first)
        candidates.sort(key=lambda x: x['confidence_score'], reverse=True)

        best_match = candidates[0]

        # Only return if confidence is reasonable (>30)
        if best_match['confidence_score'] < 30:
            logger.debug(f"Low confidence ({best_match['confidence_score']:.1f}) for {ip_address}")
            return None

        # Log if there are conflicts
        if len(candidates) > 1:
            logger.debug(f"IP {ip_address} has {len(candidates)} candidate locations, "
                        f"chose switch_id={best_match['switch_id']} port={best_match['port_name']} "
                        f"with confidence {best_match['confidence_score']:.1f}")

        return best_match

    def match_all_ips(
        self,
        arp_records: List[Dict],
        mac_records: List[Dict],
        port_analysis: Dict[Tuple[int, str], Dict]
    ) -> List[Dict]:
        """
        Match all IPs from ARP table to switch ports

        Args:
            arp_records: All ARP table records
            mac_records: All MAC table records
            port_analysis: All port analysis results

        Returns:
            List of IP location matches
        """
        # Get unique IPs
        unique_ips = list(set([r['ip_address'] for r in arp_records]))

        logger.info(f"Matching {len(unique_ips)} unique IPs to switch ports")

        results = []
        matched_count = 0
        high_confidence_count = 0

        for ip in unique_ips:
            match = self.match_ip_to_location(
                ip,
                arp_records,
                mac_records,
                port_analysis
            )

            if match:
                results.append(match)
                matched_count += 1

                if match['confidence_score'] >= 70:
                    high_confidence_count += 1

        logger.info(f"Matched {matched_count}/{len(unique_ips)} IPs "
                   f"({high_confidence_count} with high confidence >=70)")

        return results


# Singleton instance
ip_location_engine = IPLocationEngine()
