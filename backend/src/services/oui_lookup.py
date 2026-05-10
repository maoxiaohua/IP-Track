import logging
import os
import re
import time
from typing import Optional, Dict
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)

# Lazy-loaded in-memory OUI cache
_OUI_CACHE: Optional[Dict[str, str]] = None

# Default paths and URLs
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
_CACHE_FILE = os.path.join(_CACHE_DIR, 'oui_cache.txt')
_DOWNLOAD_URL = 'https://standards-oui.ieee.org/oui/oui.txt'
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _get_cache_age() -> Optional[float]:
    """Return age of cache file in seconds, or None if missing."""
    if not os.path.exists(_CACHE_FILE):
        return None
    return time.time() - os.path.getmtime(_CACHE_FILE)


def _download_oui_file() -> str:
    """Download IEEE OUI text file. Returns the raw text content."""
    url = os.environ.get('OUI_DOWNLOAD_URL', _DOWNLOAD_URL)
    logger.info(f"Downloading OUI database from {url}")
    req = Request(url, headers={'User-Agent': 'IP-Track/1.0'})
    with urlopen(req, timeout=30) as resp:
        text = resp.read().decode('utf-8', errors='replace')
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
        f.write(text)
    logger.info(f"OUI database cached to {_CACHE_FILE} ({len(text)} bytes)")
    return text


def _parse_oui_text(text: str) -> Dict[str, str]:
    """Parse IEEE OUI text into a dict mapping prefix -> vendor name.

    Format:  FC-5C-EE   (hex)\t\tDell Inc.
    """
    oui_map: Dict[str, str] = {}
    pattern = re.compile(r'^([0-9A-F]{2})-([0-9A-F]{2})-([0-9A-F]{2})\s+\(hex\)\s+(.+)', re.IGNORECASE)
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            prefix = f"{m.group(1).lower()}:{m.group(2).lower()}:{m.group(3).lower()}"
            vendor = m.group(4).strip()
            # Take only the first vendor mapping (some prefixes have multiple lines)
            if prefix not in oui_map:
                oui_map[prefix] = vendor
    logger.info(f"Parsed {len(oui_map)} OUI entries")
    return oui_map


def _load_oui_cache() -> Dict[str, str]:
    """Load OUI cache from file or download fresh."""
    age = _get_cache_age()
    if age is not None and age < _CACHE_TTL_SECONDS:
        logger.debug(f"Loading OUI cache from file (age: {age / 3600:.1f} hours)")
        with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
            return _parse_oui_text(f.read())

    try:
        text = _download_oui_file()
        return _parse_oui_text(text)
    except Exception as e:
        logger.warning(f"Failed to download OUI database: {e}")
        if os.path.exists(_CACHE_FILE):
            logger.info("Using stale OUI cache file")
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                return _parse_oui_text(f.read())
        raise


def lookup_vendor(mac_address: str) -> Optional[str]:
    """Look up vendor name from MAC address OUI prefix.

    Returns the vendor name (e.g. "Dell Inc.") or None if not found.
    """
    global _OUI_CACHE

    if _OUI_CACHE is None:
        _OUI_CACHE = _load_oui_cache()

    # Normalize MAC: strip separators, take first 6 hex chars (3 octets)
    mac_clean = re.sub(r'[^0-9a-fA-F]', '', mac_address)
    if len(mac_clean) < 6:
        return None

    oui_prefix = ':'.join([mac_clean[i:i+2].lower() for i in range(0, 6, 2)])
    return _OUI_CACHE.get(oui_prefix)


def refresh_oui_cache() -> bool:
    """Force refresh of OUI cache. Returns True on success."""
    global _OUI_CACHE
    try:
        text = _download_oui_file()
        _OUI_CACHE = _parse_oui_text(text)
        return True
    except Exception as e:
        logger.error(f"OUI cache refresh failed: {e}")
        return False
