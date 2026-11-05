from loguru import logger
import sys
from pathlib import Path
from core.config import settings

# Remove default handler
logger.remove()

# Add console handler
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG" if settings.DEBUG else "INFO",
    colorize=True,
)

_FMT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"

if settings.LOG_FILE_ENABLED:
    try:
        _log_path = Path(settings.LOG_FILE_PATH)
        _log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"⚠️ 日志目录不可写，已跳过文件日志: {exc}")
    else:
        # All logs
        logger.add(
            str(_log_path),
            rotation=settings.LOG_FILE_MAX_BYTES,
            retention=settings.LOG_FILE_BACKUP_COUNT,
            compression="zip",
            format=_FMT,
            level="DEBUG",
        )
        # Errors only
        logger.add(
            str(_log_path.with_name("error.log")),
            rotation=settings.LOG_FILE_MAX_BYTES,
            retention=settings.LOG_FILE_BACKUP_COUNT,
            compression="zip",
            format=_FMT,
            level="ERROR",
        )

