"""Contract tests for the isolated China Weather nationwide-warning feed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.qweather_pro.clients import ChinaWeatherWarningClient
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


class FakeHTTPResponse:
    """Async response context for concrete China Weather client tests."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    async def __aenter__(self) -> "FakeHTTPResponse":
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        return None

    async def json(self, *, content_type: object) -> object:
        """Return one synthetic provider JSON payload."""
        assert content_type is None
        return self._payload


class FakeHTTPSession:
    """Capture the no-network request contract for the production client."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.requests: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> FakeHTTPResponse:
        """Record one HTTP request and return a synthetic async response."""
        self.requests.append({"url": url, **kwargs})
        return FakeHTTPResponse(self._payload)


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


async def test_concrete_client_decodes_legacy_feed_without_network(
    hass,
    monkeypatch,
) -> None:
    """The public positional feed reaches the coordinator's named contract."""
    session = FakeHTTPSession(
        {
            "count": "1",
            "data": [
                [
                    "10101010020260714080000001",
                    "北京市气象台发布暴雨蓝色预警[IV/一般]",
                    "2026-07-14 08:00:00",
                    "北京市气象台",
                    "暴雨",
                    "蓝色",
                    "北京市",
                ]
            ],
        }
    )
    coordinator = NationwideWarningCoordinator(
        hass,
        _config_entry(),
        ChinaWeatherWarningClient(session),
    )
    clock = MutableClock(datetime(2026, 7, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(coordinator, "_now", clock.now)

    await coordinator.async_refresh()

    assert session.requests == [
        {
            "url": "https://product.weather.com.cn/alarm/newalarmlist.shtml",
            "params": {"count": -1},
            "headers": {"Referer": "https://www.weather.com.cn/"},
            "raise_for_status": True,
        }
    ]
    assert coordinator.data["warnings"] == [
        {
            "id": "10101010020260714080000001",
            "region": "北京市",
            "type": "暴雨",
            "level": "blue",
            "title": "北京市气象台发布暴雨蓝色预警[IV/一般]",
            "issued": "2026-07-14 08:00:00",
            "effective": None,
            "expires": None,
            "source": "China Weather",
        }
    ]
    assert coordinator.data["dataset_status"]["provider_time"] is None
    assert coordinator.data["dataset_status"]["last_update_result"] == "success"


async def test_concrete_client_rejects_malformed_legacy_records() -> None:
    """An unknown provider shape is an explicit isolated failure, not truncation."""
    client = ChinaWeatherWarningClient(FakeHTTPSession({"data": [["too", "short"]]}))

    with pytest.raises(ValueError, match="unknown shape"):
        await client.async_fetch_active_warnings()


async def test_concrete_client_decodes_a_top_level_legacy_list() -> None:
    """A list envelope uses the same positional decoder as the nested feed."""
    client = ChinaWeatherWarningClient(
        FakeHTTPSession(
            [
                [
                    "10101010020260714080000002",
                    "北京市气象台发布大风黄色预警",
                    "2026-07-14 08:00:00",
                    "北京市气象台",
                    "大风",
                    "黄色",
                    "北京市",
                ]
            ]
        )
    )

    snapshot = await client.async_fetch_active_warnings()

    assert snapshot == {
        "warnings": [
            {
                "alarmId": "10101010020260714080000002",
                "title": "北京市气象台发布大风黄色预警",
                "issueTime": "2026-07-14 08:00:00",
                "senderName": "北京市气象台",
                "signaltype": "大风",
                "signallevel": "黄色",
                "provinceName": "北京市",
            }
        ]
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
