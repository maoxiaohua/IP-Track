"""配置备份模块的请求/响应模型"""

from typing import Optional

from pydantic import BaseModel, Field


class BackupSwitchSettingsUpdate(BaseModel):
    """每台交换机的备份设置（部分更新，显式 null 表示清除覆盖）"""

    backup_enabled: Optional[bool] = None
    backup_interval_minutes: Optional[int] = Field(None, ge=5, le=43200)
    backup_device_type: Optional[str] = Field(None, max_length=50)
    backup_config_command: Optional[str] = Field(None, max_length=200)


class BackupGlobalSettingsUpdate(BaseModel):
    """全局默认间隔与保留版本数"""

    interval_minutes: int = Field(..., ge=5, le=43200)
    retention_versions: int = Field(..., ge=1, le=200)
