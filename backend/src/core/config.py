from pydantic_settings import BaseSettings, SettingsConfigDict
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
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
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
    IPAM_SCAN_INTERVAL_MINUTES: int = 60
    OPTICAL_MODULE_INTERVAL_MINUTES: int = 720
    ALARM_CLEANUP_HOUR: int = 3
    ALARM_RETENTION_DAYS: int = 30

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
            except:
                return [origin.strip() for origin in self.BACKEND_CORS_ORIGINS.split(',')]
        return self.BACKEND_CORS_ORIGINS

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
