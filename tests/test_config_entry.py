"""Config-entry-level baseline and data-contract tests."""

import asyncio
import importlib
from datetime import datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.exceptions import ConfigEntryNotReady

import custom_components.qweather_pro as integration
from custom_components.qweather_pro.clients import ProviderClients
from custom_components.qweather_pro.const import (
    CONF_CUSTOM_UI,
    CONF_DAILYSTEPS,
    CONF_GIRD,
    CONF_HOURLYSTEPS,
    CONF_KEY_ID,
    CONF_LOCATION_ID,
    CONF_PRIVATE_KEY,
    CONF_PROJECT_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USE_TOKEN,
    DOMAIN,
    PLATFORMS,
)

from .fakes import FakeNationwideWarningClient, FakeQWeatherClient


class MutableClock:
    """A controllable coordinator clock for refresh-contract tests."""

    def __init__(self, initial: datetime) -> None:
        self.value = initial

    def now(self) -> datetime:
        return self.value

    def advance(self, duration: timedelta) -> None:
        self.value += duration


def _config_entry() -> ConfigEntry:
    return ConfigEntry(
        data={
            CONF_HOST: "weather-api.example.invalid",
            CONF_LOCATION_ID: "121.4737,31.2304",
            CONF_USE_TOKEN: True,
            CONF_PROJECT_ID: "synthetic-project",
            CONF_KEY_ID: "synthetic-key-id",
        },
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={
            CONF_UPDATE_INTERVAL: 10,
            CONF_DAILYSTEPS: "7",
            CONF_HOURLYSTEPS: "24",
            CONF_GIRD: True,
            CONF_CUSTOM_UI: True,
        },
        source="user",
        state=ConfigEntryState.SETUP_IN_PROGRESS,
        subentries_data=(),
        title="Synthetic Shanghai",
        unique_id="qw_121.47_31.23",
        version=1,
    )


def _patch_provider_clients(monkeypatch, clients: ProviderClients) -> None:
    monkeypatch.setattr(
        integration,
        "create_provider_clients",
        lambda _hass, _entry: clients,
    )
    monkeypatch.setattr(
        integration,
        "async_get_integration",
        AsyncMock(return_value=SimpleNamespace(version="1.1.6-yx.0")),
    )


async def test_full_config_entry_uses_programmable_offline_clients(
    hass,
    monkeypatch,
) -> None:
    """Load all platforms through the public setup and first-refresh path."""
    qweather = FakeQWeatherClient()
    nationwide_snapshot = {
        "source": "China Weather",
        "warnings": [{"id": "synthetic-warning"}],
    }
    nationwide = FakeNationwideWarningClient(nationwide_snapshot)
    clients = ProviderClients(qweather=qweather, nationwide_warnings=nationwide)
    entities = []

    async def forward_entry_setups(entry, platforms) -> None:
        for platform in platforms:
            module = importlib.import_module(
                f"custom_components.qweather_pro.{platform.value}"
            )
            await module.async_setup_entry(hass, entry, entities.extend)

    hass.config_entries.async_forward_entry_setups.side_effect = forward_entry_setups
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()
    assert CONF_PRIVATE_KEY not in entry.data

    assert await integration.async_setup_entry(hass, entry)

    assert qweather.calls == [
        "location",
        "now",
        "daily",
        "hourly",
        "warning",
        "air",
        "indices",
    ]
    assert qweather.location_calls == [("121.45,31.25", "zh")]
    assert nationwide.calls == 1
    assert entry.runtime_data.data["now"]["temp"] == 24.0
    assert entry.runtime_data.data["nationwide_warnings"] == nationwide_snapshot
    assert len(entities) == 6
    assert {entity.unique_id for entity in entities} == {
        f"{entry.entry_id}_aqi",
        f"{entry.entry_id}_today_temp_range",
        f"{entry.entry_id}_warning_info",
        f"{entry.entry_id}_precipitation_summary",
        f"{entry.entry_id}_weather_summary",
        f"{entry.entry_id}_weather",
    }
    weather = next(
        entity for entity in entities if entity.unique_id == f"{entry.entry_id}_weather"
    )
    aqi = next(
        entity for entity in entities if entity.unique_id == f"{entry.entry_id}_aqi"
    )
    precipitation = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_precipitation_summary"
    )
    assert "custom_ui_more_info" not in weather.extra_state_attributes
    assert weather.extra_state_attributes["dataset_status"]["now"]["state"] == "fresh"
    assert aqi.extra_state_attributes["dataset_status"]["air"]["state"] == "fresh"
    assert precipitation.native_value is None
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )
    assert f"{DOMAIN}_assets" not in hass.data


async def test_existing_non_shanghai_entry_fails_before_weather_requests(
    hass,
    monkeypatch,
) -> None:
    """Preserve entry identity but reject an unexpected runtime jurisdiction."""
    qweather = FakeQWeatherClient()
    qweather.responses["location"] = {
        "code": "200",
        "location": [
            {
                "country": "中国",
                "adm1": "江苏省",
                "adm2": "苏州市",
            }
        ],
    }
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, entry)

    assert entry.unique_id == "qw_121.47_31.23"
    assert qweather.location_calls == [("121.45,31.25", "zh")]
    assert qweather.calls == ["location"]


async def test_weather_datasets_keep_independent_stale_and_recovery_states(
    hass,
    monkeypatch,
) -> None:
    """A failed current-weather refresh cannot make other datasets look failed."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_status = coordinator.data["dataset_status"]
    initial_now_success = initial_status["now"]["last_success_time"]
    assert coordinator.data["now"]["obsTime"] == "2026-07-14T08:00+08:00"
    assert initial_status["daily"]["provider_time"] == "2026-07-14T08:00+08:00"
    assert initial_status["hourly"]["provider_time"] == "2026-07-14T08:00+08:00"
    assert initial_status["air"]["provider_time"] == "2026-07-14T08:00+08:00"
    assert all(
        initial_status[name]["state"] == "fresh"
        for name in ("now", "daily", "hourly", "air")
    )

    clock = MutableClock(datetime.fromisoformat(initial_now_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["now"] = asyncio.TimeoutError()
    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()

    stale_now = coordinator.data["dataset_status"]["now"]
    assert stale_now == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": initial_now_success,
        "last_update_result": "failed",
        "state": "stale",
    }
    assert coordinator.data["now"]["temp"] == 24.0
    assert coordinator.data["dataset_status"]["daily"]["state"] == "fresh"

    qweather.responses["now"] = {
        "code": "200",
        "now": {
            **qweather.responses["daily"].get("now", {}),
            "temp": "25",
            "text": "晴",
            "icon": "100",
            "humidity": "60",
            "windSpeed": "10",
            "wind360": "90",
            "windDir": "东风",
            "feelsLike": "25",
            "obsTime": "2026-07-14T08:20+08:00",
        },
    }
    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()

    recovered_now = coordinator.data["dataset_status"]["now"]
    assert recovered_now["state"] == "fresh"
    assert recovered_now["last_update_result"] == "success"
    assert recovered_now["last_success_time"] != initial_now_success
    assert coordinator.data["now"]["temp"] == 25.0


async def test_refresh_schedule_uses_fixed_10_and_60_minute_contract(
    hass,
    monkeypatch,
) -> None:
    """The public refresh path requests 24 hours and 7 days on the fixed cadence."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_now_success = coordinator.data["dataset_status"]["now"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_now_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    assert coordinator.update_interval == timedelta(minutes=10)
    assert qweather.forecast_calls == ["7d"]
    assert qweather.hourly_calls == ["24h"]

    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()
    assert qweather.forecast_calls == ["7d"]
    assert qweather.hourly_calls == ["24h"]

    clock.advance(timedelta(minutes=50))
    await coordinator.async_refresh()
    assert qweather.forecast_calls == ["7d", "7d"]
    assert qweather.hourly_calls == ["24h", "24h"]


async def test_all_core_endpoint_failures_without_snapshots_block_entry_setup(
    hass,
    monkeypatch,
) -> None:
    """A cold entry cannot claim fresh weather when every core request fails."""
    qweather = FakeQWeatherClient()
    for category in ("now", "daily", "hourly", "air"):
        qweather.responses[category] = {"code": "401"}
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)

    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, _config_entry())


async def test_all_core_failures_keep_each_existing_snapshot_stale(
    hass,
    monkeypatch,
) -> None:
    """A complete provider outage cannot turn cached data into a fresh update."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_status = coordinator.data["dataset_status"]
    clock = MutableClock(
        datetime.fromisoformat(initial_status["now"]["last_success_time"])
    )
    monkeypatch.setattr(coordinator, "_now", clock.now)
    for category in ("now", "daily", "hourly", "air"):
        qweather.responses[category] = asyncio.TimeoutError()
    clock.advance(timedelta(minutes=60))

    await coordinator.async_refresh()

    statuses = coordinator.data["dataset_status"]
    assert coordinator.data["now"]["temp"] == 24.0
    for category in ("now", "daily", "hourly", "air"):
        assert statuses[category]["state"] == "stale"
        assert statuses[category]["last_update_result"] == "failed"
        assert (
            statuses[category]["last_success_time"]
            == initial_status[category]["last_success_time"]
        )


async def test_missing_air_snapshot_is_unavailable_without_a_default_aqi(
    hass,
    monkeypatch,
) -> None:
    """A failed first air request cannot become a zero or favourable AQI."""
    qweather = FakeQWeatherClient()
    qweather.responses["air"] = {"code": "429"}
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["aqi"] == {}
    assert entry.runtime_data.data["dataset_status"]["air"] == {
        "provider_time": None,
        "last_success_time": None,
        "last_update_result": "failed",
        "state": "unavailable",
    }


async def test_missing_aqi_field_is_fresh_unknown_not_an_endpoint_failure(
    hass,
    monkeypatch,
) -> None:
    """A successful response without AQI is distinct from a failed response."""
    qweather = FakeQWeatherClient()
    qweather.responses["air"]["indexes"] = [
        {"pubTime": "2026-07-14T08:00+08:00"}
    ]
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["aqi"] == {
        "aqi": None,
        "category": None,
        "level": None,
        "primary": None,
        "health_effect": None,
        "health_advice": None,
    }
    assert entry.runtime_data.data["dataset_status"]["air"]["state"] == "fresh"


@pytest.mark.parametrize(
    ("category", "elapsed"),
    [
        ("now", timedelta(minutes=10)),
        ("daily", timedelta(minutes=60)),
        ("hourly", timedelta(minutes=60)),
        ("air", timedelta(minutes=60)),
    ],
)
async def test_one_endpoint_failure_does_not_mask_other_dataset_states(
    hass,
    monkeypatch,
    category: str,
    elapsed: timedelta,
) -> None:
    """A provider error only makes its own cached dataset stale."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_status = coordinator.data["dataset_status"]
    clock = MutableClock(
        datetime.fromisoformat(initial_status[category]["last_success_time"])
    )
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses[category] = {"code": "429"}
    clock.advance(elapsed)

    await coordinator.async_refresh()

    statuses = coordinator.data["dataset_status"]
    assert statuses[category]["state"] == "stale"
    assert statuses[category]["last_update_result"] == "failed"
    assert statuses[category]["last_success_time"] == initial_status[category]["last_success_time"]
    for other in set(("now", "daily", "hourly", "air")) - {category}:
        assert statuses[other]["state"] == "fresh"


async def test_forecast_fields_remain_unknown_when_the_provider_omits_them(
    hass,
    monkeypatch,
) -> None:
    """Missing forecast values are not turned into zero or a weather condition."""
    qweather = FakeQWeatherClient()
    qweather.responses["daily"]["daily"] = [{"fxDate": "2026-07-14"}]
    qweather.responses["hourly"]["hourly"] = [
        {"fxTime": "2026-07-14T09:00+08:00"}
    ]
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    daily = entry.runtime_data.data["daily"][0]
    hourly = entry.runtime_data.data["hourly"][0]
    assert daily["native_temperature"] is None
    assert daily["native_templow"] is None
    assert daily["native_precipitation"] is None
    assert daily["condition"] is None
    assert hourly["native_temperature"] is None
    assert hourly["native_precipitation"] is None
    assert hourly["precipitation_probability"] is None
    assert hourly["condition"] is None


@pytest.mark.parametrize("aqi", [42, 100, 101])
async def test_aqi_values_preserve_provider_thresholds(
    hass,
    monkeypatch,
    aqi: int,
) -> None:
    """Normal, boundary, and polluted AQI values remain distinguishable."""
    qweather = FakeQWeatherClient()
    qweather.responses["air"]["indexes"][0].update(
        {
            "aqi": aqi,
            "primaryPollutant": {"name": "PM2.5"},
            "health": {
                "effect": "synthetic effect",
                "advice": {"generalPopulation": "synthetic advice"},
            },
        }
    )
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    data = entry.runtime_data.data["aqi"]
    assert data["aqi"] == aqi
    assert data["primary"] == "PM2.5"
    assert data["health_effect"] == "synthetic effect"
    assert data["health_advice"] == "synthetic advice"
