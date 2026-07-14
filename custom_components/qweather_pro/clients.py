"""Provider client construction for QWeather Pro."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import QWeatherAPI
from .const import (
    CONF_API_KEY,
    CONF_KEY_ID,
    CONF_PRIVATE_KEY,
    CONF_PROJECT_ID,
    CONF_USE_TOKEN,
)


class NationwideWarningClient(Protocol):
    """Baseline seam for the required isolated China Weather provider client."""

    async def async_fetch_active_warnings(self) -> dict[str, Any]:
        """Return one provider snapshot."""


class QWeatherClient(Protocol):
    """QWeather endpoints consumed by the first fork version."""

    async def city_lookup(self, location: str, lang: str) -> dict[str, Any]: ...

    async def get_weather_now(self, lat: str, lon: str, lang: str) -> dict[str, Any]: ...

    async def get_forecast(
        self, lat: str, lon: str, days: str, lang: str
    ) -> dict[str, Any]: ...

    async def get_hourly(
        self, lat: str, lon: str, hours: str, lang: str
    ) -> dict[str, Any]: ...

    async def get_warning_v1(self, lat: str, lon: str, lang: str) -> dict[str, Any]: ...

    async def get_air_v1(self, lat: str, lon: str, lang: str) -> dict[str, Any]: ...

    async def get_indices(self, lat: str, lon: str, lang: str) -> dict[str, Any]: ...


class DisabledNationwideWarningClient:
    """Keep refresh offline until the nationwide provider task is implemented."""

    async def async_fetch_active_warnings(self) -> dict[str, Any]:
        """Return an explicit disabled snapshot without making network calls."""
        return {
            "source": "China Weather",
            "status": "not_configured",
            "warnings": [],
        }


@dataclass(frozen=True, slots=True)
class ProviderClients:
    """All provider clients owned by one qweather_pro config entry."""

    qweather: QWeatherClient
    nationwide_warnings: NationwideWarningClient


def create_qweather_client(
    hass: HomeAssistant,
    config_data: Mapping[str, Any],
) -> QWeatherAPI:
    """Create one QWeather client from private Home Assistant config data."""
    configured_host = config_data.get(CONF_HOST)
    return QWeatherAPI(
        session=async_get_clientsession(hass),
        api_key=config_data.get(CONF_API_KEY),
        use_token=config_data.get(CONF_USE_TOKEN),
        project_id=config_data.get(CONF_PROJECT_ID),
        key_id=config_data.get(CONF_KEY_ID),
        private_key=config_data.get(CONF_PRIVATE_KEY),
        host=str(configured_host).strip() if configured_host is not None else None,
    )


def create_provider_clients(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ProviderClients:
    """Create production provider clients without exposing credentials."""
    return ProviderClients(
        qweather=create_qweather_client(hass, entry.data),
        nationwide_warnings=DisabledNationwideWarningClient(),
    )
