"""Provider client construction for QWeather Pro."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
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
    """Interface reserved for the isolated China Weather warning provider."""

    async def async_fetch_active_warnings(self) -> dict[str, Any]:
        """Return one provider snapshot."""


class QWeatherClient(Protocol):
    """QWeather endpoints consumed by the first fork version."""

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
    """Represent the nationwide feed before its provider is implemented."""

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


def create_provider_clients(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ProviderClients:
    """Create production provider clients without exposing credentials."""
    return ProviderClients(
        qweather=QWeatherAPI(
            session=async_get_clientsession(hass),
            api_key=entry.data.get(CONF_API_KEY),
            use_token=entry.data.get(CONF_USE_TOKEN),
            project_id=entry.data.get(CONF_PROJECT_ID),
            key_id=entry.data.get(CONF_KEY_ID),
            private_key=entry.data.get(CONF_PRIVATE_KEY),
            host=entry.data.get("host"),
        ),
        nationwide_warnings=DisabledNationwideWarningClient(),
    )
