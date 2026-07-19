"""Config-entry-level baseline and data-contract tests."""

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
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
    CONF_WARNING_CITY_ID,
    CONF_WARNING_CITY_NAME,
    CONF_WARNING_COUNTRY,
    CONF_WARNING_LOCATION_COORDINATES,
    CONF_WARNING_LOCATION_ID,
    CONF_WARNING_LOCATION_NAME,
    DOMAIN,
    PLATFORMS,
)
from custom_components.qweather_pro.entity_identity import PUBLIC_ENTITY_IDS

from .fakes import FakeNationwideWarningClient, FakeQWeatherClient


class MutableClock:
    """A controllable coordinator clock for refresh-contract tests."""

    def __init__(self, initial: datetime) -> None:
        self.value = initial

    def now(self) -> datetime:
        return self.value

    def advance(self, duration: timedelta) -> None:
        self.value += duration


def _advance_provider_timestamps(
    qweather: FakeQWeatherClient,
    *,
    excluded: str | None = None,
) -> None:
    """Give successful fake datasets a newly published provider timestamp."""
    timestamp = "2026-07-14T09:00+08:00"
    if excluded != "now":
        qweather.responses["now"]["now"]["obsTime"] = timestamp
    if excluded != "daily":
        qweather.responses["daily"]["updateTime"] = timestamp
    if excluded != "hourly":
        qweather.responses["hourly"]["updateTime"] = timestamp
    if excluded != "air":
        qweather.responses["air"]["indexes"][0]["pubTime"] = timestamp


def _warning(
    warning_id: str,
    *,
    headline: str = "Synthetic rain warning",
    severity: str = "moderate",
    hazard_code: str = "rain",
    hazard_name: str = "暴雨",
    status: str = "active",
    scope: str = "city",
    expire_time: str = "2026-07-14T09:00+08:00",
) -> dict[str, object]:
    """Create a synthetic active QWeather warning response item."""
    location = (
        {
            "id": "synthetic-city",
            "name": "Synthetic City",
            "country": "Synthetic Country",
        }
        if scope == "city"
        else {
            "id": "synthetic-district",
            "name": "Synthetic District",
            "cityId": "synthetic-city",
            "cityName": "Synthetic City",
            "country": "Synthetic Country",
        }
    )
    return {
        "id": warning_id,
        "eventType": {"id": hazard_code, "name": hazard_name},
        "severity": severity,
        "headline": headline,
        "description": f"{headline} details",
        "instruction": "Stay indoors",
        "senderName": "Synthetic Meteorological Service",
        "issuedTime": "2026-07-14T08:00+08:00",
        "effectiveTime": "2026-07-14T08:00+08:00",
        "expireTime": expire_time,
        "status": status,
        "scope": scope,
        "location": location,
    }


def _warning_response(
    alerts: list[dict[str, object]], *, update_time: str = "2026-07-14T08:00+08:00"
) -> dict[str, object]:
    return {"metadata": {"updateTime": update_time}, "alerts": alerts}


def _set_warning_source_responses(
    qweather: FakeQWeatherClient,
    *,
    city_alerts: list[dict[str, object]],
    district_alerts: list[dict[str, object]],
    update_time: str = "2026-07-14T08:00+08:00",
) -> None:
    """Program the city and district requests independently at the public seam."""
    qweather.warning_responses = {
        ("30.00", "120.00"): _warning_response(city_alerts, update_time=update_time),
        ("30.10", "120.10"): _warning_response(
            district_alerts,
            update_time=update_time,
        ),
    }


def _config_entry(*, include_warning_jurisdiction: bool = True) -> ConfigEntry:
    data = {
            CONF_HOST: "weather-api.example.invalid",
            CONF_LOCATION_ID: "120.004,30.004",
            CONF_USE_TOKEN: True,
            CONF_PROJECT_ID: "synthetic-project",
            CONF_KEY_ID: "synthetic-key-id",
    }
    if include_warning_jurisdiction:
        data.update(
            {
            CONF_WARNING_LOCATION_ID: "synthetic-district",
            CONF_WARNING_LOCATION_NAME: "Synthetic District",
            CONF_WARNING_CITY_ID: "synthetic-city",
            CONF_WARNING_CITY_NAME: "Synthetic City",
            CONF_WARNING_COUNTRY: "Synthetic Country",
            CONF_WARNING_LOCATION_COORDINATES: "120.10,30.10",
            }
        )
    return ConfigEntry(
        data=data,
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
        title="Synthetic City",
        unique_id="qw_120.00_30.00",
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
    monkeypatch.setattr(
        integration.QWeatherUpdateCoordinator,
        "_now",
        lambda _self: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )


def _capture_platform_entities(hass):
    """Forward platform setup and retain the public entities it creates."""
    entities = []

    async def forward_entry_setups(entry, platforms) -> None:
        for platform in platforms:
            module = importlib.import_module(
                f"custom_components.qweather_pro.{platform.value}"
            )
            await module.async_setup_entry(hass, entry, entities.extend)

    hass.config_entries.async_forward_entry_setups.side_effect = forward_entry_setups
    return entities


async def test_full_config_entry_uses_programmable_offline_clients(
    hass,
    monkeypatch,
) -> None:
    """Load all platforms through the public setup and first-refresh path."""
    qweather = FakeQWeatherClient()
    nationwide_snapshot = {
        "source": "China Weather",
        "warnings": [
            {
                "alarmId": "synthetic-warning",
                "provinceName": "合成地区",
                "signaltype": "暴雨",
                "signallevel": "orange",
                "title": "合成地区暴雨橙色预警",
                "issueTime": "2026-07-14T08:00+08:00",
                "startTime": "2026-07-14T08:00+08:00",
                "endTime": "2026-07-14T12:00+08:00",
            }
        ],
    }
    nationwide = FakeNationwideWarningClient(nationwide_snapshot)
    clients = ProviderClients(qweather=qweather, nationwide_warnings=nationwide)
    entities = _capture_platform_entities(hass)
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()
    assert CONF_PRIVATE_KEY not in entry.data

    assert await integration.async_setup_entry(hass, entry)

    assert qweather.weather_now_calls == [("30.00", "120.00", "zh")]
    assert qweather.warning_calls == [
        ("30.00", "120.00", "zh"),
        ("30.10", "120.10", "zh"),
    ]
    assert qweather.calls == [
        "location",
        "now",
        "daily",
        "hourly",
        "air",
        "indices",
        "location",
        "warning",
        "warning",
    ]
    assert qweather.location_calls == [
        ("120.00,30.00", "zh"),
        ("synthetic-city", "zh"),
    ]
    assert nationwide.calls == 1
    assert entry.runtime_data.data["now"]["temp"] == 24.0
    assert "nationwide_warnings" not in entry.runtime_data.data
    assert entry.runtime_data.nationwide_warning_coordinator.data["summary"] == {
        "warning_count": 1,
        "orange_red_count": 1,
        "highest_level": "orange",
    }
    assert entry.runtime_data.nationwide_warning_coordinator.data["dataset_status"][
        "state"
    ] == "unavailable"
    assert len(entities) == 9
    assert {entity.unique_id for entity in entities} == {
        f"{entry.entry_id}_aqi",
        f"{entry.entry_id}_today_temp_range",
        f"{entry.entry_id}_warning_info",
        f"{entry.entry_id}_daily_rain_guidance",
        f"{entry.entry_id}_nationwide_warning_summary",
        f"{entry.entry_id}_nationwide_warning_details",
        f"{entry.entry_id}_precipitation_summary",
        f"{entry.entry_id}_weather_summary",
        f"{entry.entry_id}_weather",
    }
    assert {entity.entity_id for entity in entities} == set(PUBLIC_ENTITY_IDS.values())
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
    nationwide_summary = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_nationwide_warning_summary"
    )
    nationwide_details = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_nationwide_warning_details"
    )
    rain_guidance = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_daily_rain_guidance"
    )
    assert "custom_ui_more_info" not in weather.extra_state_attributes
    assert weather.extra_state_attributes["dataset_status"]["now"]["state"] == "fresh"
    assert aqi.extra_state_attributes["dataset_status"]["air"]["state"] == "fresh"
    assert aqi.extra_state_attributes["primary_pollutant"] == "unknown"
    assert precipitation.native_value is None
    assert nationwide_summary.native_value == "orange"
    assert nationwide_summary.extra_state_attributes["orange_red_count"] == 1
    assert nationwide_details.native_value == 1
    assert nationwide_details.extra_state_attributes["transport"] == "entity_attribute"
    assert nationwide_details.extra_state_attributes["warnings"][0]["source"] == "China Weather"
    assert rain_guidance.native_value == "unconfirmed"
    assert rain_guidance.extra_state_attributes["hourly_status"]["state"] == "fresh"
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )
    assert f"{DOMAIN}_assets" not in hass.data


async def test_warning_info_exposes_one_atomic_household_contract(
    hass,
    monkeypatch,
) -> None:
    """Consumers get an effective list and explicit unhealthy machine states."""
    qweather = FakeQWeatherClient()
    city_warning = _warning("city-rain", severity="yellow", scope="city")
    district_warning = _warning("district-rain", severity="red", scope="district")
    for warning in (city_warning, district_warning):
        warning.pop("scope")
        warning.pop("location")
    _set_warning_source_responses(
        qweather,
        city_alerts=[city_warning],
        district_alerts=[district_warning],
    )
    entities = _capture_platform_entities(hass)
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    warning_sensor = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_warning_info"
    )

    assert warning_sensor.native_value == "active"
    contract = warning_sensor.extra_state_attributes["warning_contract"]
    assert contract["effective_warnings"][0]["source_level"] == "district"
    assert contract["effective_warnings"][0]["level"] == "red"
    assert {event["source_level"] for event in contract["history"]} == {
        "city",
        "district",
    }
    assert {event["action"] for event in contract["history"]} == {"issued"}

    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.warning_responses = {
        ("30.00", "120.00"): {"code": "429"},
        ("30.10", "120.10"): {"code": "429"},
    }
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()

    assert warning_sensor.native_value == "failed"
    assert warning_sensor.extra_state_attributes["warnings"] == []
    assert warning_sensor.extra_state_attributes["warning_contract"]["history"] == []

    _set_warning_source_responses(
        qweather,
        city_alerts=[
            {
                **_warning(
                    "invalid-level",
                    scope="city",
                    headline="暴雨预警",
                    expire_time="2026-07-14T12:00:00+08:00",
                ),
                "severity": None,
            }
        ],
        district_alerts=[],
        update_time="2026-07-14T09:00+08:00",
    )
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()

    assert warning_sensor.native_value == "contract_error"
    assert warning_sensor.extra_state_attributes["warnings"] == []

    _set_warning_source_responses(
        qweather,
        city_alerts=[],
        district_alerts=[],
        update_time="2026-07-14T09:30+08:00",
    )
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()

    assert warning_sensor.native_value == "clear"
    assert warning_sensor.extra_state_attributes["warnings"] == []
    assert [
        event["action"]
        for event in warning_sensor.extra_state_attributes["warning_contract"]["history"][:2]
    ] == ["cleared", "cleared"]


async def test_missing_warning_jurisdiction_is_distinct_from_a_successful_clear(
    hass,
    monkeypatch,
) -> None:
    """Old entries stay operational but expose an explicit uninitialized contract."""
    qweather = FakeQWeatherClient()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry(include_warning_jurisdiction=False)

    assert await integration.async_setup_entry(hass, entry)

    coordinator = entry.runtime_data
    assert coordinator.data["household_warning"] == {
        "state": "uninitialized",
        "jurisdiction": None,
        "effective_warnings": [],
        "sources": {},
        "recent_changes": {},
        "history": [],
        "published_at": "2026-07-14T00:00:00+00:00",
    }
    assert qweather.warning_calls == []
    assert qweather.weather_now_calls == [("30.00", "120.00", "zh")]


async def test_mismatched_city_and_district_source_times_are_an_atomic_contract_error(
    hass,
    monkeypatch,
) -> None:
    """Consumers never see a hybrid result assembled from two provider batches."""
    qweather = FakeQWeatherClient()
    qweather.warning_responses = {
        ("30.00", "120.00"): _warning_response(
            [_warning("city-rain")],
            update_time="2026-07-14T08:00+08:00",
        ),
        ("30.10", "120.10"): _warning_response(
            [_warning("district-rain", scope="district")],
            update_time="2026-07-14T08:01+08:00",
        ),
    }
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["household_warning"]["state"] == "contract_error"
    assert entry.runtime_data.data["warning"] == []


async def test_existing_entry_with_a_mismatched_structured_location_fails_before_weather_requests(
    hass,
    monkeypatch,
) -> None:
    """Reject a wrong weather area even when an older entry has no warning config."""
    qweather = FakeQWeatherClient()
    qweather.responses["location"] = {
        "code": "200",
        "location": [
            {
                "id": "synthetic-other-district",
                "name": "Synthetic Other District",
                "country": "Synthetic Country",
                "adm1": "Synthetic Province",
                "adm2": "Synthetic City",
                "lon": "120.10",
                "lat": "30.10",
            }
        ],
    }
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry(include_warning_jurisdiction=False)

    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, entry)

    assert entry.unique_id == "qw_120.00_30.00"
    assert qweather.location_calls == [("120.00,30.00", "zh")]
    assert qweather.calls == ["location"]


async def test_nationwide_warning_failure_does_not_degrade_qweather_data(
    hass,
    monkeypatch,
) -> None:
    """China Weather can be unavailable while every QWeather dataset remains fresh."""
    qweather = FakeQWeatherClient()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient(
                RuntimeError("synthetic nationwide failure")
            ),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["dataset_status"]["now"]["state"] == "fresh"
    nationwide_data = entry.runtime_data.nationwide_warning_coordinator.data
    assert nationwide_data["dataset_status"]["state"] == "unavailable"
    assert nationwide_data["warnings"] == []
    assert qweather.calls == [
        "location",
        "now",
        "daily",
        "hourly",
        "air",
        "indices",
        "location",
        "warning",
        "warning",
    ]


async def test_qweather_refresh_does_not_drive_the_nationwide_warning_client(
    hass,
    monkeypatch,
) -> None:
    """The separate 30-minute coordinator is not called on a 10-minute refresh."""
    qweather = FakeQWeatherClient()
    nationwide = FakeNationwideWarningClient({"warnings": []})
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(qweather=qweather, nationwide_warnings=nationwide),
    )
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["now"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)

    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()

    assert nationwide.calls == 1
    assert qweather.calls.count("now") == 2


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


async def test_unchanged_hourly_provider_observation_stays_fresh_until_expiry(
    hass,
    monkeypatch,
) -> None:
    """A provider's hourly observation remains usable between refresh polls."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_status = coordinator.data["dataset_status"]["now"]
    clock = MutableClock(datetime.fromisoformat(initial_status["last_success_time"]))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    clock.advance(timedelta(minutes=10))

    await coordinator.async_refresh()

    assert coordinator.data["dataset_status"]["now"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": clock.now().isoformat(),
        "last_update_result": "success",
        "state": "fresh",
    }


async def test_unchanged_hourly_observation_expires_after_one_hour(
    hass,
    monkeypatch,
) -> None:
    """Repeated current weather still fails closed after its source-age window."""
    qweather = FakeQWeatherClient()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_status = coordinator.data["dataset_status"]["now"]
    clock = MutableClock(datetime.fromisoformat(initial_status["last_success_time"]))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    clock.advance(timedelta(minutes=60))

    await coordinator.async_refresh()

    assert coordinator.data["dataset_status"]["now"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": initial_status["last_success_time"],
        "last_update_result": "unchanged",
        "state": "stale",
    }


async def test_air_snapshot_without_provider_time_remains_unavailable(
    hass,
    monkeypatch,
) -> None:
    """AQI without source time fails closed rather than using local receipt time."""
    qweather = FakeQWeatherClient()
    qweather.responses["air"]["indexes"][0].pop("pubTime")
    entities = _capture_platform_entities(hass)
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    aqi_sensor = next(
        entity for entity in entities if entity.unique_id == f"{entry.entry_id}_aqi"
    )
    air_status = aqi_sensor.extra_state_attributes["dataset_status"]["air"]
    assert air_status["provider_time"] is None
    assert air_status["last_update_result"] == "unavailable"
    assert air_status["state"] == "unavailable"


async def test_regressing_provider_observation_remains_stale(
    hass,
    monkeypatch,
) -> None:
    """A provider clock moving backward cannot create a newer weather snapshot."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_status = coordinator.data["dataset_status"]["now"]
    clock = MutableClock(datetime.fromisoformat(initial_status["last_success_time"]))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["now"]["now"]["obsTime"] = "2026-07-14T07:50+08:00"
    clock.advance(timedelta(minutes=10))

    await coordinator.async_refresh()

    assert coordinator.data["dataset_status"]["now"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": initial_status["last_success_time"],
        "last_update_result": "unchanged",
        "state": "stale",
    }


async def test_ancient_provider_observation_is_stale_on_first_refresh(
    hass,
    monkeypatch,
) -> None:
    """An old-but-present source timestamp cannot begin life as fresh data."""
    qweather = FakeQWeatherClient()
    qweather.responses["now"]["now"]["obsTime"] = "2026-07-13T08:00+08:00"
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["dataset_status"]["now"] == {
        "provider_time": "2026-07-13T08:00+08:00",
        "last_success_time": None,
        "last_update_result": "stale",
        "state": "stale",
    }


async def test_future_provider_observation_is_stale_on_first_refresh(
    hass,
    monkeypatch,
) -> None:
    """A timezone-offset timestamp from the future cannot be fresh source data."""
    qweather = FakeQWeatherClient()
    qweather.responses["now"]["now"]["obsTime"] = "2026-07-14T08:01+08:00"
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["dataset_status"]["now"] == {
        "provider_time": "2026-07-14T08:01+08:00",
        "last_success_time": None,
        "last_update_result": "stale",
        "state": "stale",
    }


async def test_valid_observation_recovers_after_a_rejected_future_timestamp(
    hass,
    monkeypatch,
) -> None:
    """A rejected future timestamp cannot block a later valid provider update."""
    qweather = FakeQWeatherClient()
    qweather.responses["now"]["now"]["obsTime"] = "2026-07-14T08:01+08:00"
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    clock = MutableClock(datetime(2026, 7, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["now"]["now"]["obsTime"] = "2026-07-14T08:10+08:00"
    clock.advance(timedelta(minutes=10))

    await coordinator.async_refresh()

    assert coordinator.data["dataset_status"]["now"]["state"] == "fresh"
    assert coordinator.data["dataset_status"]["now"]["last_update_result"] == "success"


async def test_future_observation_preserves_last_snapshot_then_recovers(
    hass,
    monkeypatch,
) -> None:
    """A bad future response neither replaces nor blocks the good observation."""
    qweather = FakeQWeatherClient()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    clock = MutableClock(datetime(2026, 7, 14, tzinfo=timezone.utc))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["now"]["now"]["obsTime"] = "2026-07-14T08:11+08:00"
    clock.advance(timedelta(minutes=10))

    await coordinator.async_refresh()

    assert coordinator.data["now"]["obsTime"] == "2026-07-14T08:00+08:00"
    assert coordinator.data["dataset_status"]["now"]["state"] == "stale"

    qweather.responses["now"]["now"]["obsTime"] = "2026-07-14T08:20+08:00"
    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()

    assert coordinator.data["now"]["obsTime"] == "2026-07-14T08:20+08:00"
    assert coordinator.data["dataset_status"]["now"]["state"] == "fresh"


@pytest.mark.parametrize("category", ["daily", "hourly", "air"])
async def test_dataset_freshness_expires_with_provider_time(
    hass,
    monkeypatch,
    category: str,
) -> None:
    """A source timestamp near expiry becomes stale without a coordinator grace."""
    qweather = FakeQWeatherClient()
    near_expiry = "2026-07-14T07:01+08:00"
    if category == "air":
        qweather.responses[category]["indexes"][0]["pubTime"] = near_expiry
    else:
        qweather.responses[category]["updateTime"] = near_expiry
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"][category]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    clock.advance(timedelta(minutes=10))

    await coordinator.async_refresh()

    assert coordinator.data["dataset_status"][category]["state"] == "stale"


async def test_current_weather_is_not_requested_before_its_10_minute_due_time(
    hass,
    monkeypatch,
) -> None:
    """An early manual coordinator refresh does not increase provider calls."""
    qweather = FakeQWeatherClient()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["now"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    clock.advance(timedelta(minutes=5))

    await coordinator.async_refresh()

    assert qweather.calls.count("now") == 1


async def test_local_warning_contract_preserves_all_active_warning_fields(
    hass,
    monkeypatch,
) -> None:
    """One successful response keeps every active warning separately."""
    qweather = FakeQWeatherClient()
    _set_warning_source_responses(
        qweather,
        city_alerts=[
            _warning("rain-1"),
            _warning(
            "wind-2",
            headline="Synthetic wind warning",
            severity="severe",
            hazard_code="wind",
            hazard_name="大风",
            ),
        ],
        district_alerts=[],
    )
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    warnings = entry.runtime_data.data["warning"]
    assert [warning["hazard_id"] for warning in warnings] == ["rain", "wind"]
    assert {key: warnings[0][key] for key in (
        "hazard_id",
        "hazard_name",
        "level",
        "source_level",
        "title",
        "text",
        "instruction",
        "sender",
        "issued",
        "effective",
        "expires",
        "source",
    )} == {
        "hazard_id": "rain",
        "hazard_name": "暴雨",
        "level": "yellow",
        "source_level": "city",
        "title": "Synthetic rain warning",
        "text": "Synthetic rain warning details",
        "instruction": "Stay indoors",
        "sender": "Synthetic Meteorological Service",
        "issued": "2026-07-14T08:00+08:00",
        "effective": "2026-07-14T08:00+08:00",
        "expires": "2026-07-14T09:00+08:00",
        "source": "QWeather",
    }
    assert entry.runtime_data.data["dataset_status"]["warning"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": "2026-07-14T00:00:00+00:00",
        "last_update_result": "success",
        "state": "fresh",
    }


async def test_warning_failure_without_snapshot_is_unconfirmed(
    hass,
    monkeypatch,
) -> None:
    """An initial provider failure is not the same as a confirmed empty list."""
    qweather = FakeQWeatherClient()
    qweather.responses["warning"] = {"code": "429"}
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["warning"] == []
    assert entry.runtime_data.data["dataset_status"]["warning"] == {
        "provider_time": None,
        "last_success_time": None,
        "last_update_result": "failed",
        "state": "unavailable",
    }


async def test_warning_success_without_provider_timestamp_is_fresh(
    hass,
    monkeypatch,
) -> None:
    """A successful warning query is fresh even when the API omits snapshot time."""
    qweather = FakeQWeatherClient()
    qweather.warning_responses = {
        ("30.00", "120.00"): {"code": "200", "alerts": [_warning("rain-city")]},
        ("30.10", "120.10"): {"code": "200", "alerts": []},
    }
    entities = _capture_platform_entities(hass)
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )

    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    warning_sensor = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_warning_info"
    )

    assert warning_sensor.native_value == "active"
    attributes = warning_sensor.extra_state_attributes
    status = attributes["warning_status"]
    assert status["provider_time"] is None
    assert status["last_success_time"] is not None
    assert status["last_update_result"] == "success"
    assert status["state"] == "fresh"
    assert attributes["warning_contract"]["state"] == "active"


async def test_warning_failure_retains_snapshot_until_successful_clear(
    hass,
    monkeypatch,
) -> None:
    """A provider error hides the effective list but remains a distinct state."""
    qweather = FakeQWeatherClient()
    qweather.responses["warning"]["metadata"]["updateTime"] = (
        "2026-07-14T08:00+08:00"
    )
    qweather.responses["warning"]["alerts"] = [_warning("rain-1")]
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["warning"] = {"code": "401"}
    clock.advance(timedelta(minutes=30))

    await coordinator.async_refresh()

    assert coordinator.data["warning"] == []
    assert coordinator.data["household_warning"]["state"] == "failed"
    assert coordinator.data["dataset_status"]["warning"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": initial_success,
        "last_update_result": "failed",
        "state": "stale",
    }


async def test_warning_successful_empty_and_expired_items_clear_active_state(
    hass,
    monkeypatch,
) -> None:
    """Only a success-empty response or explicit expiry clears active warnings."""
    qweather = FakeQWeatherClient()
    qweather.responses["warning"]["alerts"] = [_warning("rain-1")]
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["warning"] = {
        "metadata": {"updateTime": "2026-07-14T08:30+08:00"},
        "alerts": [],
    }
    clock.advance(timedelta(minutes=30))

    await coordinator.async_refresh()

    assert coordinator.data["warning"] == []
    assert coordinator.data["dataset_status"]["warning"]["state"] == "fresh"

    qweather.responses["warning"] = {
        "metadata": {"updateTime": "2026-07-14T09:00+08:00"},
        "alerts": [
            _warning(
                "expired-1",
                expire_time="2026-07-14T09:00+08:00",
            )
        ],
    }
    clock.advance(timedelta(minutes=30))
    await coordinator.async_refresh()

    assert coordinator.data["warning"] == []


async def test_warning_successful_empty_without_provider_time_is_confirmed_clear(
    hass,
    monkeypatch,
) -> None:
    """A provider success can confirm a clear even without a source timestamp."""
    qweather = FakeQWeatherClient()
    qweather.responses["warning"]["alerts"] = [_warning("rain-1")]
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    entities = _capture_platform_entities(hass)
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    warning_sensor = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_warning_info"
    )
    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["warning"] = {"code": "200", "alerts": []}
    clock.advance(timedelta(minutes=30))

    await coordinator.async_refresh()

    status = coordinator.data["dataset_status"]["warning"]
    assert coordinator.data["warning"] == []
    assert status["provider_time"] is None
    assert status["last_update_result"] == "success"
    assert warning_sensor.native_value == "clear"
    assert warning_sensor.extra_state_attributes["warning_status"] == status


async def test_successful_warning_snapshot_replaces_disappeared_hazards(
    hass,
    monkeypatch,
) -> None:
    """A success response is a complete atomic snapshot, not a raw-alert merge."""
    qweather = FakeQWeatherClient()
    _set_warning_source_responses(
        qweather,
        city_alerts=[_warning("rain-1", expire_time="2026-07-14T12:00+08:00")],
        district_alerts=[
            _warning(
            "wind-2",
            hazard_code="wind",
            hazard_name="大风",
            headline="Synthetic wind warning",
            scope="district",
            expire_time="2026-07-14T12:00+08:00",
            )
        ],
    )
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    _set_warning_source_responses(
        qweather,
        city_alerts=[
            _warning(
                "rain-1",
                headline="Synthetic rain warning revised",
                expire_time="2026-07-14T12:00+08:00",
            ),
        ],
        district_alerts=[],
        update_time="2026-07-14T08:30+08:00",
    )
    clock.advance(timedelta(minutes=30))

    await coordinator.async_refresh()

    assert coordinator.data["warning"] == [
        {
            "hazard_id": "rain",
            "hazard_name": "暴雨",
            "level": "yellow",
            "source_level": "city",
            "jurisdiction": "Synthetic City · Synthetic Country",
            "issued": "2026-07-14T08:00+08:00",
            "effective": "2026-07-14T08:00+08:00",
            "expires": "2026-07-14T12:00+08:00",
            "title": "Synthetic rain warning revised",
            "text": "Synthetic rain warning revised details",
            "instruction": "Stay indoors",
            "sender": "Synthetic Meteorological Service",
            "source": "QWeather",
            "source_count": 1,
        }
    ]
    assert coordinator.data["household_warning"]["sources"]["district"] == {
        "state": "clear",
        "warnings": [],
    }


async def test_unchanged_success_is_stale_not_a_request_failure(
    hass,
    monkeypatch,
) -> None:
    """An unadvanced provider timestamp remains distinct from a failed request."""
    qweather = FakeQWeatherClient()
    qweather.responses["warning"] = {
        "metadata": {"updateTime": "2026-07-14T08:00+08:00"},
        "alerts": [_warning("rain-1", expire_time="2026-07-14T12:00+08:00")],
    }
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    clock.advance(timedelta(minutes=30))

    await coordinator.async_refresh()

    assert coordinator.data["household_warning"]["state"] == "stale"
    assert coordinator.data["dataset_status"]["warning"]["last_update_result"] == "unchanged"
    assert coordinator.data["dataset_status"]["warning"]["state"] == "stale"


async def test_successful_disappearance_records_the_hazard_change_time(
    hass,
    monkeypatch,
) -> None:
    """A successful empty snapshot keeps the just-cleared hazard's change time."""
    qweather = FakeQWeatherClient()
    _set_warning_source_responses(
        qweather,
        city_alerts=[_warning("rain-1", expire_time="2026-07-14T12:00+08:00")],
        district_alerts=[],
    )
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["warning"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    _set_warning_source_responses(
        qweather,
        city_alerts=[],
        district_alerts=[],
        update_time="2026-07-14T08:30+08:00",
    )
    clock.advance(timedelta(minutes=30))

    await coordinator.async_refresh()

    contract = coordinator.data["household_warning"]
    assert contract["state"] == "clear"
    assert contract["recent_changes"] == {"rain": clock.now().isoformat()}


async def test_warning_sensor_marks_initial_failure_as_unconfirmed(
    hass,
    monkeypatch,
) -> None:
    """The public warning sensor does not translate an initial failure to clear."""
    qweather = FakeQWeatherClient()
    qweather.responses["warning"] = {"code": "429"}
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    entities = _capture_platform_entities(hass)
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)

    warning_sensor = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_warning_info"
    )
    assert warning_sensor.native_value == "failed"
    assert warning_sensor.extra_state_attributes["warnings"] == []
    assert warning_sensor.extra_state_attributes["warning_status"]["state"] == "unavailable"


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


async def test_warning_refreshes_on_its_own_30_minute_cadence(
    hass,
    monkeypatch,
) -> None:
    """Warning requests are independent from the 10- and 60-minute endpoints."""
    qweather = FakeQWeatherClient()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )
    entry = _config_entry()
    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["now"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)

    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()
    assert qweather.calls.count("warning") == 2
    assert qweather.forecast_calls == ["7d"]

    clock.advance(timedelta(minutes=20))
    await coordinator.async_refresh()
    assert qweather.calls.count("warning") == 4
    assert qweather.forecast_calls == ["7d"]


async def test_failed_60_minute_dataset_waits_for_its_next_scheduled_attempt(
    hass,
    monkeypatch,
) -> None:
    """A failed daily refresh remains stale without a 10-minute retry loop."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["daily"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["daily"] = {"code": "429"}

    clock.advance(timedelta(minutes=60))
    await coordinator.async_refresh()
    assert qweather.forecast_calls == ["7d", "7d"]
    assert coordinator.data["dataset_status"]["daily"]["state"] == "stale"

    clock.advance(timedelta(minutes=10))
    await coordinator.async_refresh()
    assert qweather.forecast_calls == ["7d", "7d"]
    assert coordinator.data["dataset_status"]["daily"]["state"] == "stale"


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


async def test_timeout_without_snapshots_blocks_entry_setup(
    hass,
    monkeypatch,
) -> None:
    """A cold network timeout has no usable snapshot to expose."""
    qweather = FakeQWeatherClient()
    for category in ("now", "daily", "hourly", "air"):
        qweather.responses[category] = asyncio.TimeoutError()
    _patch_provider_clients(
        monkeypatch,
        ProviderClients(
            qweather=qweather,
            nationwide_warnings=FakeNationwideWarningClient({}),
        ),
    )

    with pytest.raises(ConfigEntryNotReady):
        await integration.async_setup_entry(hass, _config_entry())


async def test_cached_auth_error_marks_only_the_current_dataset_stale(
    hass,
    monkeypatch,
) -> None:
    """An authentication response retains the last observation as stale data."""
    qweather = FakeQWeatherClient()
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    initial_success = coordinator.data["dataset_status"]["now"]["last_success_time"]
    clock = MutableClock(datetime.fromisoformat(initial_success))
    monkeypatch.setattr(coordinator, "_now", clock.now)
    qweather.responses["now"] = {"code": "401"}
    clock.advance(timedelta(minutes=10))

    await coordinator.async_refresh()

    assert coordinator.data["dataset_status"]["now"] == {
        "provider_time": "2026-07-14T08:00+08:00",
        "last_success_time": initial_success,
        "last_update_result": "failed",
        "state": "stale",
    }


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
    _advance_provider_timestamps(qweather, excluded=category)
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


async def test_incomplete_forecast_payload_is_unavailable_not_fresh(
    hass,
    monkeypatch,
) -> None:
    """A successful envelope cannot stand in for the required 24h/7d coverage."""
    qweather = FakeQWeatherClient()
    qweather.responses["daily"]["daily"] = qweather.responses["daily"]["daily"][:6]
    qweather.responses["hourly"]["hourly"] = qweather.responses["hourly"]["hourly"][:23]
    clients = ProviderClients(
        qweather=qweather,
        nationwide_warnings=FakeNationwideWarningClient({}),
    )
    _patch_provider_clients(monkeypatch, clients)
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert entry.runtime_data.data["daily"] == []
    assert entry.runtime_data.data["hourly"] == []
    assert entry.runtime_data.data["dataset_status"]["daily"]["state"] == "unavailable"
    assert entry.runtime_data.data["dataset_status"]["hourly"]["state"] == "unavailable"


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
