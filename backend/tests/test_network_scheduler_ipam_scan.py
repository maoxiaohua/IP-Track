import inspect
from unittest.mock import AsyncMock

import pytest

from services.ipam_service import IPAMService
from services.network_scheduler import NetworkCollectionScheduler


class _FakeSession:
    def __init__(self) -> None:
        self.rollback = AsyncMock()


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_auto_ipam_scan_uses_quick_mode(monkeypatch):
    scheduler = NetworkCollectionScheduler()
    fake_db = _FakeSession()

    start_scan = AsyncMock(return_value="session-1")
    complete_scan = AsyncMock()
    fail_scan = AsyncMock()
    scan_all_auto_subnets = AsyncMock(
        return_value={
            "total_subnets": 1,
            "scanned_subnets": 1,
            "total_ips_scanned": 42,
        }
    )

    monkeypatch.setattr(
        "services.network_scheduler.AsyncSessionLocal",
        lambda: _FakeSessionFactory(fake_db),
    )
    monkeypatch.setattr(
        "services.network_scheduler.ipam_scan_status_service.start_scan",
        start_scan,
    )
    monkeypatch.setattr(
        "services.network_scheduler.ipam_scan_status_service.complete_scan",
        complete_scan,
    )
    monkeypatch.setattr(
        "services.network_scheduler.ipam_scan_status_service.fail_scan",
        fail_scan,
    )
    monkeypatch.setattr(
        "services.ipam_service.ipam_service.scan_all_auto_subnets",
        scan_all_auto_subnets,
    )

    await scheduler._run_ipam_scan()

    start_scan.assert_awaited_once()
    assert start_scan.await_args.kwargs["source"] == "auto"
    assert start_scan.await_args.kwargs["scan_type"] == "quick"

    scan_all_auto_subnets.assert_awaited_once()
    assert scan_all_auto_subnets.await_args.kwargs["scan_type"] == "quick"
    assert scan_all_auto_subnets.await_args.kwargs["max_subnets"] is None

    complete_scan.assert_awaited_once()
    fail_scan.assert_not_awaited()
    fake_db.rollback.assert_not_awaited()
    assert not scheduler.is_ipam_scan_running()


def test_scan_all_auto_subnets_defaults_to_quick():
    signature = inspect.signature(IPAMService.scan_all_auto_subnets)
    assert signature.parameters["scan_type"].default == "quick"


@pytest.mark.asyncio
async def test_startup_ipam_scan_uses_limited_batch(monkeypatch):
    scheduler = NetworkCollectionScheduler()
    fake_db = _FakeSession()

    start_scan = AsyncMock(return_value="session-2")
    complete_scan = AsyncMock()
    fail_scan = AsyncMock()
    scan_all_auto_subnets = AsyncMock(
        return_value={
            "total_subnets": 5,
            "total_due_subnets": 12,
            "deferred_subnets": 7,
            "scanned_subnets": 5,
            "total_ips_scanned": 1270,
        }
    )

    monkeypatch.setattr(
        "services.network_scheduler.AsyncSessionLocal",
        lambda: _FakeSessionFactory(fake_db),
    )
    monkeypatch.setattr(
        "services.network_scheduler.ipam_scan_status_service.start_scan",
        start_scan,
    )
    monkeypatch.setattr(
        "services.network_scheduler.ipam_scan_status_service.complete_scan",
        complete_scan,
    )
    monkeypatch.setattr(
        "services.network_scheduler.ipam_scan_status_service.fail_scan",
        fail_scan,
    )
    monkeypatch.setattr(
        "services.ipam_service.ipam_service.scan_all_auto_subnets",
        scan_all_auto_subnets,
    )

    await scheduler._run_ipam_scan(startup_catchup=True, max_subnets=5)

    start_scan.assert_awaited_once()
    assert start_scan.await_args.kwargs["scan_type"] == "quick"
    assert "启动补扫" in start_scan.await_args.kwargs["message"]

    scan_all_auto_subnets.assert_awaited_once()
    assert scan_all_auto_subnets.await_args.kwargs["max_subnets"] == 5

    complete_scan.assert_awaited_once()
    assert "剩余 7 个子网留待后续定时任务处理" in complete_scan.await_args.kwargs["message"]
    fail_scan.assert_not_awaited()


@pytest.mark.asyncio
async def test_delayed_startup_catchup_waits_and_runs_limited_scan(monkeypatch):
    scheduler = NetworkCollectionScheduler()
    fake_db = _FakeSession()

    sleep_mock = AsyncMock()
    should_run = AsyncMock(return_value=True)
    run_ipam_scan = AsyncMock()

    monkeypatch.setattr("services.network_scheduler.asyncio.sleep", sleep_mock)
    monkeypatch.setattr("services.network_scheduler.settings.IPAM_STARTUP_CATCHUP_DELAY_SECONDS", 90)
    monkeypatch.setattr("services.network_scheduler.settings.IPAM_STARTUP_CATCHUP_MAX_SUBNETS", 4)
    monkeypatch.setattr("services.network_scheduler.AsyncSessionLocal", lambda: _FakeSessionFactory(fake_db))
    monkeypatch.setattr(scheduler, "_should_run_ipam_catchup", should_run)
    monkeypatch.setattr(scheduler, "_run_ipam_scan", run_ipam_scan)

    await scheduler._run_ipam_startup_catchup_after_delay(delay_seconds=90, max_subnets=4)

    sleep_mock.assert_awaited_once_with(90)
    should_run.assert_awaited_once_with(fake_db)
    run_ipam_scan.assert_awaited_once_with(startup_catchup=True, max_subnets=4)


def test_schedule_ipam_startup_catchup_creates_single_task(monkeypatch):
    scheduler = NetworkCollectionScheduler()
    created_tasks = []

    class _TaskStub:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            return None

        def add_done_callback(self, callback) -> None:
            self._callback = callback

    monkeypatch.setattr("services.network_scheduler.settings.IPAM_STARTUP_CATCHUP_DELAY_SECONDS", 45)
    monkeypatch.setattr("services.network_scheduler.settings.IPAM_STARTUP_CATCHUP_MAX_SUBNETS", 3)

    def fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()
        return _TaskStub()

    monkeypatch.setattr("services.network_scheduler.asyncio.create_task", fake_create_task)

    scheduler.schedule_ipam_startup_catchup()
    scheduler.schedule_ipam_startup_catchup()

    assert len(created_tasks) == 1
