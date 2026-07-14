"""Config-entry-level baseline tests."""

import importlib
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST

import custom_components.qweather_pro as integration
from custom_components.qweather_pro.clients import ProviderClients
from custom_components.qweather_pro.const import (
    CONF_CUSTOM_UI,
    CONF_DAILYSTEPS,
    CONF_GIRD,
    CONF_HOURLYSTEPS,
    CONF_KEY_ID,
    CONF_LOCATION_ID,
    CONF_PROJECT_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USE_TOKEN,
    DOMAIN,
    PLATFORMS,
)

from .fakes import FakeNationwideWarningClient, FakeQWeatherClient


def _config_entry() -> ConfigEntry:
    return ConfigEntry(
        data={
            CONF_HOST: "weather-api.example.invalid",
            CONF_LOCATION_ID: "121.45,31.25",
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
        unique_id="qw_121.45_31.25",
        version=1,
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
    entry = _config_entry()

    assert await integration.async_setup_entry(hass, entry)

    assert qweather.calls == ["now", "daily", "hourly", "warning", "air", "indices"]
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
    precipitation = next(
        entity
        for entity in entities
        if entity.unique_id == f"{entry.entry_id}_precipitation_summary"
    )
    assert "custom_ui_more_info" not in weather.extra_state_attributes
    assert precipitation.native_value is None
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )
    assert f"{DOMAIN}_assets" not in hass.data
