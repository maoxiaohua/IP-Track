from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List
import json


class Settings(BaseSettings):
    """Application settings from environment variables"""

    # Application
    APP_NAME: str = "IP-Track Network Monitor"
    APP_VERSION: str = "2.2.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8100
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: str = '["http://localhost:8001","http://localhost:3000"]'

    # Database
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "iptrack"
    DATABASE_POOL_SIZE: int = 40
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_ECHO_SQL: bool = False

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_CACHE_TTL: int = 300
    REDIS_ENABLED: bool = True

    @property
    def REDIS_URL(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # Security
    ENCRYPTION_KEY: str  # Required - generate with Fernet

    # Collection Scheduler
    COLLECTION_ENABLED: bool = True
    COLLECTION_INTERVAL_MINUTES: int = 120
    IPAM_SCAN_INTERVAL_MINUTES: int = 30
    OPTICAL_MODULE_INTERVAL_MINUTES: int = 720
    ALARM_CLEANUP_HOUR: int = 3
    ALARM_RETENTION_DAYS: int = 30
    COLLECTION_JOB_RETENTION_DAYS: int = 30
    COLLECTION_JOB_CLEANUP_BATCH_SIZE: int = 10000
    COLLECTION_JOB_HARD_TIMEOUT_SECONDS: int = 360  # Per-job hard deadline (6 min)
    STALE_JOB_RECLAIM_MINUTES: int = 15  # Reclaim RUNNING jobs older than this
    CONSECUTIVE_FAILURE_AUTO_RESOLVE: int = 10  # Auto-resolve alarm after N failures

    # IPAM Settings
    IPAM_OFFLINE_THRESHOLD_HOURS: int = 6  # Hours without response before marking as offline
    IP_SCAN_HISTORY_RETENTION_DAYS: int = 14
    IP_SCAN_HISTORY_CLEANUP_BATCH_SIZE: int = 50000
    IPAM_DEFAULT_SCAN_INTERVAL: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Default scan interval in seconds for imported subnets without explicit interval"
    )
    IPAM_STARTUP_CATCHUP_DELAY_SECONDS: int = Field(
        default=300,
        ge=0,
        le=86400,
        description="Delay before the IPAM service runs its startup catch-up scan"
    )
    IPAM_STARTUP_CATCHUP_MAX_SUBNETS: int = Field(
        default=50,
        ge=0,
        le=500,
        description="Maximum overdue subnets to scan during startup catch-up; 0 disables startup catch-up"
    )

    # IPAM Scale Configuration (1000+ subnets)
    IPAM_CONCURRENT_SUBNETS: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum subnets scanned concurrently in a single auto-scan pass"
    )
    IPAM_MAX_SUBNETS_PER_PASS: int = Field(
        default=200,
        ge=0,
        le=2000,
        description="Cap on subnets per auto-scan pass; 0 = unlimited"
    )
    IPAM_CONCURRENT_IPS_PER_SUBNET: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Concurrent ping/scan operations within a single subnet scan"
    )
    IPAM_SCAN_HARD_TIMEOUT_SECONDS: int = Field(
        default=7200,
        ge=600,
        le=14400,
        description="Hard timeout for the entire auto-scan pass"
    )
    IPAM_ENRICHMENT_INTERVAL_MINUTES: int = Field(
        default=240,
        ge=60,
        le=1440,
        description="Interval between automatic enrichment passes (hostname/DNS/SNMP)"
    )
    IPAM_ENRICHMENT_MAX_SUBNETS: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Maximum subnets per enrichment pass"
    )
    IPAM_ENRICHMENT_HARD_TIMEOUT_SECONDS: int = Field(
        default=3600,
        ge=600,
        le=14400,
        description="Hard timeout for a single enrichment pass"
    )
    IP_SCAN_HISTORY_RECORD_ALL: bool = Field(
        default=True,
        description="Record history for all IPs (True) or only changed IPs (False)"
    )
    IP_SCAN_HISTORY_BULK_INSERT_BATCH: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Number of history rows per bulk INSERT statement"
    )

    # IP Scan Timeouts (seconds)
    IP_SCAN_DNS_TIMEOUT: int = Field(
        default=5,
        ge=1,
        le=30,
        description="DNS PTR lookup timeout in seconds"
    )
    IP_SCAN_NETBIOS_TIMEOUT: float = Field(
        default=1.5,
        ge=0.5,
        le=10.0,
        description="NetBIOS node status query timeout in seconds"
    )
    IP_SCAN_MDNS_TIMEOUT: float = Field(
        default=1.5,
        ge=0.5,
        le=10.0,
        description="mDNS unicast query timeout in seconds (UDP 5353)"
    )
    IP_SCAN_ARP_TIMEOUT: int = Field(
        default=2,
        ge=1,
        le=10,
        description="ARP cache lookup subprocess timeout in seconds"
    )

    # SSE Progress
    IPAM_SSE_THROTTLE_MS: int = Field(
        default=250,
        ge=50,
        le=2000,
        description="Min interval between SSE progress broadcasts (milliseconds)"
    )

    # IP Lookup Settings
    IP_LOOKUP_CACHE_HOURS: int = Field(
        default=24,
        ge=1,
        le=168,  # Maximum 7 days (aligned with data retention period)
        description="IP Lookup cache mode query window in hours"
    )

    # OS Detection Settings
    OS_DETECTION_PREFER_SNMP: bool = True  # Prefer SNMP over Nmap when both available
    NMAP_OS_TIMEOUT: int = 30  # Timeout for nmap OS detection (seconds)

    # MAC OUI Vendor Lookup
    OUI_DOWNLOAD_URL: str = 'https://standards-oui.ieee.org/oui/oui.txt'
    OUI_CACHE_TTL_DAYS: int = 7

    # Worker Pools
    COLLECTION_WORKERS: int = 10
    IP_LOOKUP_WORKERS: int = 50
    DISCOVERY_WORKERS: int = 20
    IPAM_SCAN_WORKERS: int = 20

    # Batch Processing
    COLLECTION_BATCH_SIZE: int = 5
    OPTICAL_BATCH_SIZE: int = 3
    COLLECTION_MAX_RETRIES: int = 3
    COLLECTION_RETRY_BACKOFF: int = 2

    # Timeouts (seconds)
    DEFAULT_SSH_TIMEOUT: int = 30
    CLI_COMMAND_TIMEOUT: int = 60
    SNMP_TIMEOUT: int = 10
    CONNECTION_TIMEOUT: int = 30
    COLLECTION_JOB_TIMEOUT: int = 300

    # BMC Reset
    BMC_RESET_TIMEOUT_SECONDS: int = 30

    # Port Analysis Thresholds
    PORT_SINGLE_MAC_CONFIDENCE: int = 95
    PORT_TRUNK_THRESHOLD: int = 10
    PORT_UPLINK_THRESHOLD: int = 50
    PORT_MAX_MAC_ACCESS: int = 10

    # IP Location Confidence
    IP_LOCATION_BASE_SCORE: int = 50
    IP_LOCATION_SINGLE_MAC_BONUS: int = 30
    IP_LOCATION_ACCESS_PORT_BONUS: int = 25
    IP_LOCATION_TRUNK_PENALTY: int = 35

    # SNMP
    SNMP_VERSION: int = 3
    SNMP_PORT: int = 161
    SNMP_RETRIES: int = 3
    SNMP_COMMUNITY: str = ""  # Optional fallback for discovery

    # Feature Toggles
    FEATURE_IPAM: bool = True
    FEATURE_ALARMS: bool = True
    FEATURE_OPTICAL_MODULES: bool = True
    FEATURE_PORT_ANALYSIS: bool = True
    FEATURE_STATUS_CHECKER: bool = True
    FEATURE_QUERY_HISTORY: bool = True

    # Lightweight switch reachability checker
    STATUS_CHECK_INTERVAL_SECONDS: int = 300
    STATUS_CHECK_PING_TIMEOUT_SECONDS: int = 2
    STATUS_CHECK_CONCURRENCY: int = 50

    # Hybrid Collection Strategy (vendor-specific)
    CISCO_PRIMARY_METHOD: str = "cli"
    CISCO_FALLBACK_METHOD: str = "snmp"
    CISCO_ENABLE_REQUIRED: bool = True

    DELL_PRIMARY_METHOD: str = "cli"
    DELL_FALLBACK_METHOD: str = "snmp"
    DELL_ENABLE_REQUIRED: bool = True

    ALCATEL_PRIMARY_METHOD: str = "cli"
    ALCATEL_FALLBACK_METHOD: str = ""
    ALCATEL_ENABLE_REQUIRED: bool = False

    JUNIPER_PRIMARY_METHOD: str = "cli"
    JUNIPER_FALLBACK_METHOD: str = "snmp"
    JUNIPER_ENABLE_REQUIRED: bool = False

    # Logging
    LOG_FILE_ENABLED: bool = True
    LOG_FILE_PATH: str = "logs/iptrack.log"
    LOG_FILE_MAX_BYTES: int = 10485760  # 10MB
    LOG_FILE_BACKUP_COUNT: int = 5

    # Parse JSON strings for CORS origins
    @property
    def CORS_ORIGINS(self) -> List[str]:
        if isinstance(self.BACKEND_CORS_ORIGINS, str):
            try:
                return json.loads(self.BACKEND_CORS_ORIGINS)
            except Exception:
                return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(',')]
        return self.BACKEND_CORS_ORIGINS

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
