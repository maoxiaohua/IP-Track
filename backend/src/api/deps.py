from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal, get_db
from models.ipam import SNMPProfile

__all__ = ['get_db', 'load_snmp_profile_or_400']


async def load_snmp_profile_or_400(
    db: AsyncSession,
    profile_id: int | None,
) -> SNMPProfile | None:
    """
    按 ID 取 SNMP 凭据模板，取不到就抛 400。profile_id 为 None 时直接返回 None。

    放在这里而不是某个路由模块里，是因为新增、编辑、批量配置、批量发现导入四条写库
    路径都要做同一件事：把「引用了不存在的模板」挡在写库之前。若放行，交换机会带着
    一个悬空引用存进去，之后采集端 build_switch_snmp_config 取不到模板、退化成用
    交换机自己那份空凭据 —— 采集静默什么都不采，而界面上什么错都看不到。
    """
    if profile_id is None:
        return None
    result = await db.execute(select(SNMPProfile).where(SNMPProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SNMP profile {profile_id} not found",
        )
    return profile
