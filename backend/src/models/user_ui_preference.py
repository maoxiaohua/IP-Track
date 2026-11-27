"""Per-account UI preferences (e.g. which table columns are visible).

Kept in its own table rather than ``system_settings`` because these are
per-user, not global.  Guests have no account, so the frontend falls back to
browser-local storage for them.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from core.database import Base
# 显式导入被引用的表，保证只加载本模块的服务（如 backend-ipam）也能解析 users 外键
from models.user import User  # noqa: F401


class UserUIPreference(Base):
    """One JSONB value per (user, preference key)."""

    __tablename__ = "user_ui_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "pref_key", name="uq_user_ui_preferences_user_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pref_key = Column(String(80), nullable=False)
    value = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<UserUIPreference(user_id={self.user_id}, key='{self.pref_key}')>"
