from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # Application
    APP_NAME: str = "IP Track System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # API
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8001"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://iptrack:iptrack123@localhost:5432/iptrack"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 300  # 5 minutes

    # Security
    ENCRYPTION_KEY: str  # Must be 32 bytes base64 encoded

    # Switch Connection
    DEFAULT_SSH_TIMEOUT: int = 30
    MAX_CONCURRENT_CONNECTIONS: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
