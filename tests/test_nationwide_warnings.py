"""Contract tests for the isolated China Weather nationwide-warning feed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from custom_components.qweather_pro.nationwide_warnings import (
    NationwideWarningCoordinator,
)

from .fakes import FakeNationwideWarningClient
from .test_config_entry import _config_entry


class MutableClock:
    """A controllable provider-refresh clock."""

    def __init__(self, initial: datetime) -> None:
        self.value = initial

    def now(self) -> datetime:
        """Return the current synthetic time."""
        return self.value

    def advance(self, duration: timedelta) -> None:
        """Move the synthetic time forward."""
        self.value += duration


def _warning(
    warning_id: str,
    level: str,
    *,
    region: str = "北京市",
    headline: str | None = None,
) -> dict[str, str]:
    """Build a provider-shaped active nationwide warning."""
    return {
        "alarmId": warning_id,
        "provinceName": region,
        "signaltype": "暴雨",
        "signallevel": level,
        "title": headline or f"{region}暴雨{level}预警",
        "issueTime": "2026-07-14T08:00+08:00",
        "startTime": "2026-07-14T08:00+08:00",
        "endTime": "2026-07-14T12:00+08:00",
    }


def _snapshot(
    warnings: list[dict[str, str]],
    provider_time: str = "2026-07-14T08:00+08:00",
) -> dict[str, object]:
    """Wrap warning records in the narrow provider-client contract."""
    return {
        "source": "China Weather",
        "updateTime": provider_time,
        "warnings": warnings,
    }


async def test_nationwide_contract_keeps_all_levels_and_summary(hass, monkeypatch) -> None:
    """Blue/yellow warnings remain in the full list while summary prioritizes risk."""
    client = FakeNationwideWarningClient(
        _snapshot(
            [
                _warning("blue-1", "blue"),
                _warning("yellow-2", "yellow"),
                _warning("orange-3", "orange"),
                _warning("red-4", "red"),
            ]
        )
    )
    coordinator = NationwideWarningCoordinator(hass, _config_entry(), client)
    clock = MutableClock(datetime(2026, 7, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(coordinator, "_now", clock.now)

    await coordinator.async_refresh()

    assert coordinator.update_interval == timedelta(minutes=30)
    assert [warning["id"] for warning in coordinator.data["warnings"]] == [
        "blue-1",
        "yellow-2",
        "orange-3",
        "red-4",
    ]
    assert coordinator.data["summary"] == {
        "warning_count": 4,
        "orange_red_count": 2,
        "highest_level": "red",
    }
    assert coordinator.data["warnings"][0] == {
        "id": "blue-1",
        "region": "北京市",
        "type": "暴雨",
        "level": "blue",
        "title": "北京市暴雨blue预警",
        "issued": "2026-07-14T08:00+08:00",
        "effective": "2026-07-14T08:00+08:00",
        "expires": "2026-07-14T12:00+08:00",
        "source": "China Weather",
    }
    assert coordinator.data["dataset_status"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": "2026-07-14T00:00:00+00:00",
        "last_update_result": "success",
        "state": "fresh",
    }


async def test_nationwide_failure_isolated_and_recovers_from_stale_snapshot(
    hass,
    monkeypatch,
) -> None:
    """A China Weather failure only affects the independently retained snapshot."""
    client = FakeNationwideWarningClient(RuntimeError("synthetic failure"))
    coordinator = NationwideWarningCoordinator(hass, _config_entry(), client)
    clock = MutableClock(datetime(2026, 7, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(coordinator, "_now", clock.now)

    await coordinator.async_refresh()
    assert coordinator.data["warnings"] == []
    assert coordinator.data["dataset_status"]["state"] == "unavailable"
    assert coordinator.data["dataset_status"]["last_update_result"] == "failed"

    client.response = _snapshot([_warning("orange-1", "orange")], "2026-07-14T08:30+08:00")
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()
    first_success = coordinator.data["dataset_status"]["last_success_time"]
    assert coordinator.data["dataset_status"]["state"] == "fresh"

    client.response = RuntimeError("synthetic failure")
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()
    assert [warning["id"] for warning in coordinator.data["warnings"]] == ["orange-1"]
    assert coordinator.data["dataset_status"] == {
        "provider_time": "2026-07-14T08:30+08:00",
        "last_success_time": first_success,
        "last_update_result": "failed",
        "state": "stale",
    }

    client.response = _snapshot([_warning("red-2", "red")], "2026-07-14T09:30+08:00")
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()
    assert [warning["id"] for warning in coordinator.data["warnings"]] == ["red-2"]
    assert coordinator.data["dataset_status"]["state"] == "fresh"


async def test_nationwide_peak_detail_contract_never_silently_truncates(
    hass,
    monkeypatch,
) -> None:
    """A fixed high-volume fixture remains fully available to the detail entity."""
    warnings = [
        _warning(
            f"peak-{index}",
            ("blue", "yellow", "orange", "red")[index % 4],
            region=f"合成地区{index}",
            headline=f"合成峰值预警 {index}",
        )
        for index in range(160)
    ]
    client = FakeNationwideWarningClient(_snapshot(warnings))
    coordinator = NationwideWarningCoordinator(hass, _config_entry(), client)
    clock = MutableClock(datetime(2026, 7, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(coordinator, "_now", clock.now)

    await coordinator.async_refresh()

    detail_contract = coordinator.detail_contract
    assert detail_contract["transport"] == "entity_attribute"
    assert detail_contract["warning_count"] == 160
    assert [warning["id"] for warning in detail_contract["warnings"]] == [
        f"peak-{index}" for index in range(160)
    ]
    assert len(json.dumps(detail_contract, ensure_ascii=False).encode()) > 16_000
