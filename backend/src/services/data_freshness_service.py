from datetime import datetime, timedelta, timezone
from typing import Optional

from core.config import settings
from models.switch import Switch


def latest_collection_attempt_at(switch: Switch) -> Optional[datetime]:
    timestamps = [
        ts for ts in [switch.last_arp_collection_at, switch.last_mac_collection_at]
        if ts is not None
    ]
    return max(timestamps) if timestamps else None


def latest_optical_collection_attempt_at(switch: Switch) -> Optional[datetime]:
    timestamps = [
        ts for ts in [switch.last_optical_collection_at, switch.last_optical_success_at]
        if ts is not None
    ]
    return max(timestamps) if timestamps else None


def _optical_snapshot_stale_threshold() -> timedelta:
    interval_minutes = max(settings.OPTICAL_MODULE_INTERVAL_MINUTES, 60)
    return timedelta(minutes=interval_minutes * 2)


def build_port_analysis_freshness(
    switch: Switch,
    latest_analyzed_at: Optional[datetime]
) -> dict:
    last_attempt_at = latest_collection_attempt_at(switch)
    collection_message = switch.last_collection_message or ""
    message_lower = collection_message.lower()

    freshness_status = "fresh"
    reason = "fresh"
    warning = None

    if switch.last_collection_status == "failed":
        freshness_status = "stale"
        reason = "latest_collection_failed"
        warning = (
            "最新一次采集失败，当前展示的是历史端口分析结果。"
            "请结合最近成功分析时间与失败原因判断是否仍可参考。"
        )
    elif switch.last_collection_status == "partial":
        freshness_status = "stale"
        reason = "latest_collection_partial"
        warning = "最新一次采集不完整，当前端口分析可能已经过期。"
    elif "mac: 0" in message_lower or "mac result: mac: 0" in message_lower:
        freshness_status = "stale"
        reason = "latest_collection_missing_mac"
        warning = "最新一次采集未获得有效 MAC 数据，当前端口分析沿用的是历史成功快照。"
    elif switch.is_reachable is False:
        reason = "reachability_check_failed"
        warning = "状态探测显示设备离线，但最近一次 ARP/MAC 采集成功，以下结果仍按最近一次成功快照展示。"

    return {
        "status": freshness_status,
        "reason": reason,
        "warning": warning,
        "last_analyzed_at": latest_analyzed_at.isoformat() if latest_analyzed_at else None,
        "last_collection_attempt_at": last_attempt_at.isoformat() if last_attempt_at else None,
        "last_collection_status": switch.last_collection_status,
        "last_collection_message": switch.last_collection_message,
        "is_reachable": switch.is_reachable,
    }


def build_lookup_result_freshness(
    switch: Switch,
    data_age_seconds: Optional[int] = None,
    last_seen_at: Optional[datetime] = None
) -> dict:
    last_attempt_at = latest_collection_attempt_at(switch)

    freshness_status = "fresh"
    reason = "fresh"
    warning = None

    if switch.last_collection_status == "failed":
        freshness_status = "stale"
        reason = "latest_collection_failed"
        warning = "交换机最近一次采集失败，当前定位结果基于历史缓存，端口位置可能已经失效。"
    elif switch.last_collection_status == "partial":
        freshness_status = "stale"
        reason = "latest_collection_partial"
        warning = "交换机最近一次采集不完整，当前定位结果可能不完整或已过期。"
    elif switch.is_reachable is False:
        freshness_status = "stale"
        reason = "switch_offline"
        warning = "交换机当前离线，当前定位结果基于失联前的历史缓存，仅供排障参考。"

    return {
        "status": freshness_status,
        "reason": reason,
        "warning": warning,
        "switch_last_collection_status": switch.last_collection_status,
        "switch_last_collection_message": switch.last_collection_message,
        "switch_is_reachable": switch.is_reachable,
        "last_collection_attempt_at": last_attempt_at.isoformat() if last_attempt_at else None,
        "data_age_seconds": data_age_seconds,
        "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
    }


def build_optical_inventory_freshness(switch: Switch) -> dict:
    last_attempt_at = latest_optical_collection_attempt_at(switch)
    last_success_at = switch.last_optical_success_at

    freshness_status = "fresh"
    reason = "fresh"
    warning = None

    if switch.last_optical_collection_status == "failed":
        freshness_status = "stale"
        reason = "latest_optical_collection_failed"
        warning = "最近一次光模块采集失败，当前展示的是历史缓存，需要结合最后一次成功时间判断是否仍可参考。"
    elif switch.is_reachable is False:
        freshness_status = "stale"
        reason = "switch_offline"
        warning = "交换机当前离线，光模块信息基于失联前的历史缓存，仅供排障参考。"
    elif last_success_at and (datetime.now(timezone.utc) - last_success_at) > _optical_snapshot_stale_threshold():
        freshness_status = "stale"
        reason = "optical_snapshot_old"
        warning = "最近一次成功光模块采集时间较久，当前库存信息可能已经过期。"
    elif switch.last_optical_collection_status == "empty":
        reason = "latest_collection_empty"
        warning = "最近一次光模块采集已确认当前未检测到模块；如仍显示记录，则这些记录属于历史缓存。"

    return {
        "status": freshness_status,
        "reason": reason,
        "warning": warning,
        "last_optical_collection_at": last_attempt_at.isoformat() if last_attempt_at else None,
        "last_optical_success_at": last_success_at.isoformat() if last_success_at else None,
        "last_optical_collection_status": switch.last_optical_collection_status,
        "last_optical_collection_message": switch.last_optical_collection_message,
        "last_optical_modules_count": switch.last_optical_modules_count,
        "is_reachable": switch.is_reachable,
    }


def build_optical_module_freshness(
    switch: Switch,
    last_seen_at: Optional[datetime]
) -> dict:
    inventory_freshness = build_optical_inventory_freshness(switch)
    last_success_at = switch.last_optical_success_at

    is_present = bool(last_seen_at and last_success_at and last_seen_at >= last_success_at)
    presence_status = "present" if is_present else "historical"

    freshness_status = inventory_freshness["status"]
    reason = inventory_freshness["reason"]
    warning = inventory_freshness["warning"]

    if not is_present:
        freshness_status = "stale"
        reason = "not_seen_in_latest_successful_snapshot"
        warning = "该光模块记录来自历史快照，最近一次成功光模块采集中未再次发现。"

        if switch.last_optical_collection_status == "failed":
            warning += " 最近一次采集失败，因此系统无法确认它是否仍然存在。"
        elif switch.is_reachable is False:
            warning += " 当前交换机离线，因此系统无法重新确认。"
        elif switch.last_optical_collection_status == "empty":
            warning += " 最近一次成功采集明确返回 0 个模块。"

    return {
        "status": freshness_status,
        "reason": reason,
        "warning": warning,
        "presence_status": presence_status,
        "is_present": is_present,
        "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
        "last_optical_collection_at": inventory_freshness["last_optical_collection_at"],
        "last_optical_success_at": inventory_freshness["last_optical_success_at"],
        "last_optical_collection_status": inventory_freshness["last_optical_collection_status"],
        "last_optical_collection_message": inventory_freshness["last_optical_collection_message"],
        "switch_is_reachable": switch.is_reachable,
    }
