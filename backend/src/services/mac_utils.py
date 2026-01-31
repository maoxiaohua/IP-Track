import re
from typing import Optional


def normalize_mac_address(mac_address: str) -> str:
    """
    Normalize MAC address to standard format (aa:bb:cc:dd:ee:ff)
    Handles various input formats:
    - Cisco: aaaa.bbbb.cccc
    - Standard: aa:bb:cc:dd:ee:ff
    - Compact: aabbccddeeff
    - Hyphenated: aa-bb-cc-dd-ee-ff
    """
    if not mac_address:
        raise ValueError("MAC address cannot be empty")

    # Remove all non-hex characters
    mac_clean = re.sub(r'[^0-9a-fA-F]', '', mac_address)

    if len(mac_clean) != 12:
        raise ValueError(f"Invalid MAC address length: {mac_address}")

    # Validate all characters are hex
    try:
        int(mac_clean, 16)
    except ValueError:
        raise ValueError(f"Invalid MAC address format: {mac_address}")

    # Convert to standard format with colons
    return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)]).lower()


def is_valid_mac_address(mac_address: str) -> bool:
    """Check if a string is a valid MAC address"""
    try:
        normalize_mac_address(mac_address)
        return True
    except ValueError:
        return False


def mac_to_cisco_format(mac_address: str) -> str:
    """
    Convert MAC address to Cisco format (aaaa.bbbb.cccc)
    Input: aa:bb:cc:dd:ee:ff or any valid format
    """
    normalized = normalize_mac_address(mac_address)
    mac_clean = normalized.replace(':', '')
    return f"{mac_clean[0:4]}.{mac_clean[4:8]}.{mac_clean[8:12]}"


def mac_to_standard_format(mac_address: str) -> str:
    """
    Convert MAC address to standard format (aa:bb:cc:dd:ee:ff)
    Alias for normalize_mac_address for clarity
    """
    return normalize_mac_address(mac_address)
