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
    # Swagger/ReDoc are closed by default; enable explicitly for local debugging.
    API_DOCS_ENABLED: bool = False

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

    # Authentication (write operations require login; browsing stays read-only)
    AUTH_ALGORITHM: str = "HS256"
    AUTH_TOKEN_EXPIRE_MINUTES: int = 720
    AUTH_PASSWORD_MIN_LENGTH: int = 8
    # Roles allowed to perform write operations (comma separated).
    AUTH_WRITE_ROLES: str = "admin"
    # Optional explicit JWT secret. When empty it is derived from ENCRYPTION_KEY,
    # so existing deployments work without touching .env.
    AUTH_SECRET_KEY: str = ""
    INITIAL_ADMIN_USERNAME: str = "admin"
    # Used only when the users table is empty. Leave empty to auto-generate a
    # one-time password printed once in the core service log.
    INITIAL_ADMIN_PASSWORD: str = ""

    @property
    def JWT_SECRET(self) -> str:
        if self.AUTH_SECRET_KEY:
            return self.AUTH_SECRET_KEY
        import hashlib
        return hashlib.sha256(f"iptrack-auth:{self.ENCRYPTION_KEY}".encode()).hexdigest()

    # Collection Scheduler
    COLLECTION_ENABLED: bool = True
    COLLECTION_INTERVAL_MINUTES: int = 120
    IPAM_SCAN_INTERVAL_MINUTES: int = 30
    OPTICAL_MODULE_INTERVAL_MINUTES: int = 720
    TOPOLOGY_COLLECTION_INTERVAL_MINUTES: int = 360
    TOPOLOGY_MAX_COLLECT_CONCURRENCY: int = 5  # 1000 台同时 SNMP 会打爆网络，需限流
    # 配置备份（只读）：每 CONFIG_BACKUP_TICK_MINUTES 扫描一次到期设备
    CONFIG_BACKUP_ENABLED: bool = True
    CONFIG_BACKUP_TICK_MINUTES: int = 5
    CONFIG_BACKUP_MAX_CONCURRENCY: int = 3  # 同时 SSH 备份的设备数上限
    CONFIG_BACKUP_DIR: str = "/app/data/config_backups"
    # 拥堵/慢速链路上 SSH banner 与认证响应可能远超 Netmiko 默认 15s，
    # 放宽握手超时，避免把“网络慢”误判成“认证失败”。
    CONFIG_BACKUP_HANDSHAKE_TIMEOUT_SECONDS: int = 90
    # 登录耗时达到该秒数仍失败，判为“网络慢”而非凭据错误
    CONFIG_BACKUP_SLOW_CONNECT_SECONDS: int = 10
    # 备份失败后到下次重试的最小间隔（分钟），与成功后的备份间隔独立
    CONFIG_BACKUP_RETRY_MINUTES: int = 15
    ALARM_CLEANUP_HOUR: int = 3
    ALARM_RETENTION_DAYS: int = 30
    COLLECTION_JOB_RETENTION_DAYS: int = 30
    COLLECTION_JOB_CLEANUP_BATCH_SIZE: int = 10000
    COLLECTION_JOB_HARD_TIMEOUT_SECONDS: int = 360  # Per-job hard deadline (6 min)
    STALE_JOB_RECLAIM_MINUTES: int = 15  # Reclaim RUNNING jobs older than this
    CONSECUTIVE_FAILURE_AUTO_RESOLVE: int = 10  # Auto-resolve alarm after N failures
    # Netmiko banner/auth 握手超时。慢链路或并发登录时远超默认 15s，
    # 不放宽会把"网络慢"误判成"认证失败"（与 CONFIG_BACKUP_HANDSHAKE_TIMEOUT_SECONDS 同因）。
    CLI_HANDSHAKE_TIMEOUT_SECONDS: int = Field(default=90, ge=5, le=600)

    # IPAM Settings
    IPAM_OFFLINE_THRESHOLD_HOURS: int = 6  # Hours without response before marking as offline
    IPAM_FRESHNESS_STALE_DAYS: int = 7  # Devices unseen longer than this are excluded from distribution charts
    IPAM_BLIND_ROUND_MIN_PREVIOUS: int = 10  # Minimum previously reachable hosts before a round can be flagged blind
    IPAM_BLIND_ROUND_MAX_REACHABLE_RATIO: float = 0.2  # Reachable ratio below this (vs previous round) = collector blind
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
    HARDWARE_WMI_SWEEP_INTERVAL_MINUTES: int = Field(
        default=360,
        ge=60,
        le=1440,
        description="Interval between Windows WMI hardware inventory sweeps"
    )
    # Windows WinRM 硬件采集（WMI 兜底通路），默认值对应 Windows 默认配置
    WINRM_PORT: int = Field(
        default=5985,
        ge=1,
        le=65535,
        description="WinRM (WSMan) port; 5985 for HTTP, 5986 for HTTPS"
    )
    WINRM_USE_SSL: bool = Field(
        default=False,
        description="Connect to WinRM over HTTPS (required for port 5986)"
    )
    WINRM_TRANSPORT: str = Field(
        default='ntlm',
        description="pywinrm transport: ntlm, basic, kerberos, credssp, plaintext, ssl"
    )
    WINRM_TIMEOUT_SECONDS: int = Field(
        default=30,
        ge=5,
        le=300,
        description="WinRM read timeout in seconds per host"
    )
    WINRM_SERVER_CERT_VALIDATION: bool = Field(
        default=False,
        description="Validate WinRM HTTPS server certificate (disable for self-signed)"
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

    # Subnet Probe Tool (temporary one-off "is this /24 still used?" sweeper, independent from IPAM)
    SUBNET_PROBE_MAX_SUBNETS: int = Field(
        default=5000,
        ge=1,
        le=20000,
        description="Maximum number of subnets accepted in a single subnet probe run"
    )
    SUBNET_PROBE_MAX_TOTAL_HOSTS: int = Field(
        default=300000,
        ge=256,
        le=2000000,
        description="Maximum total expanded host addresses accepted in a single subnet probe run"
    )
    SUBNET_PROBE_MIN_PREFIX: int = Field(
        default=16,
        ge=8,
        le=30,
        description="Reject subnets broader than this (smaller prefix = bigger subnet), e.g. 16 rejects 10.0.0.0/8"
    )
    SUBNET_PROBE_DEFAULT_CONCURRENCY: int = Field(
        default=200,
        ge=1,
        le=500,
        description="Default number of in-flight pings for a subnet probe run"
    )
    SUBNET_PROBE_MAX_CONCURRENCY: int = Field(
        default=500,
        ge=1,
        le=2000,
        description="Upper bound for the concurrency the UI may request"
    )
    SUBNET_PROBE_DEFAULT_TIMEOUT: float = Field(
        default=1.0,
        ge=0.2,
        le=10.0,
        description="Default per-ping timeout in seconds for a subnet probe run"
    )
    SUBNET_PROBE_CHUNK_SIZE: int = Field(
        default=32,
        ge=1,
        le=256,
        description="Hosts probed per batch inside a subnet; enables early exit once a live host is found"
    )
    SUBNET_PROBE_MAX_TASKS: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Number of finished subnet probe tasks kept in memory for the UI"
    )

    # Visio (.vsdx) read-only viewer limits
    VSDX_MAX_FILE_MB: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum accepted .vsdx upload size in MB"
    )
    VSDX_MAX_TOTAL_MB: int = Field(
        default=80,
        ge=1,
        le=500,
        description="Maximum total uncompressed size of all zip entries in an .vsdx file, in MB"
    )
    VSDX_MAX_ENTRIES: int = Field(
        default=5000,
        ge=10,
        le=50000,
        description="Maximum number of zip entries accepted in an .vsdx file"
    )
    VSDX_MAX_PAGES: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of pages parsed from an .vsdx file"
    )
    VSDX_MAX_SHAPES_PER_PAGE: int = Field(
        default=5000,
        ge=10,
        le=50000,
        description="Maximum number of shapes rendered per Visio page"
    )
    VSDX_MAX_IMAGE_MB: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum size of a single embedded image in an .vsdx file, in MB"
    )
    VSDX_MAX_SVG_MB: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Maximum generated SVG size per Visio page, in MB"
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

    # BMC IPMI info probing (fru / mc info). Probes run in subprocesses and can
    # take ~60s each, so cap how many run at once. Without a cap a periodic
    # sweep over hundreds of servers exhausts the DB connection pool and takes
    # the whole API down (switches / IP lookup included).
    BMC_IPMI_CONCURRENCY: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Maximum concurrent IPMI info probes across all BMC servers"
    )

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
    FEATURE_TOPOLOGY: bool = True

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
    # Absolute path inside the backend container (./backend/logs is mounted there).
    LOG_FILE_PATH: str = "/app/logs/iptrack.log"
    LOG_FILE_MAX_BYTES: int = 10485760  # 10MB
    LOG_FILE_BACKUP_COUNT: int = 5

    # Parse JSON strings for CORS origins
    @property
    def WRITE_ROLES(self) -> List[str]:
        return [role.strip() for role in self.AUTH_WRITE_ROLES.split(",") if role.strip()]

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
