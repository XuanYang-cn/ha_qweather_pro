"""Provider client construction for QWeather Pro."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any, Protocol

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import QWeatherAPI
from .const import (
    CONF_KEY_ID,
    CONF_PRIVATE_KEY,
    CONF_PROJECT_ID,
    CONF_USE_TOKEN,
)


class JWTConfigurationError(ValueError):
    """Raised when an entry cannot use the fork's JWT-only provider path."""


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


class ChinaWeatherWarningClient:
    """Read the public China Weather nationwide active-warning feed."""

    _URL = "https://product.weather.com.cn/alarm/newalarmlist.shtml"

    def __init__(self, session: ClientSession) -> None:
        """Use Home Assistant's shared client session without QWeather credentials."""
        self._session = session

    @staticmethod
    def _decode_warning(record: object) -> dict[str, Any]:
        """Decode the legacy positional China Weather feed into named fields."""
        if isinstance(record, Mapping):
            return dict(record)
        if not isinstance(record, list) or len(record) < 7:
            raise ValueError("China Weather warning record had an unknown shape")
        return {
            "alarmId": record[0],
            "title": record[1],
            "issueTime": record[2],
            "senderName": record[3],
            "signaltype": record[4],
            "signallevel": record[5],
            "provinceName": record[6],
        }

    async def async_fetch_active_warnings(self) -> dict[str, Any]:
        """Return a narrow snapshot for the isolated nationwide coordinator."""
        async with asyncio.timeout(15):
            async with self._session.get(
                self._URL,
                params={"count": -1},
                headers={"Referer": "https://www.weather.com.cn/"},
                raise_for_status=True,
            ) as response:
                payload = await response.json(content_type=None)
        if isinstance(payload, list):
            return {"warnings": [self._decode_warning(record) for record in payload]}
        if not isinstance(payload, Mapping):
            raise ValueError("China Weather returned a non-object warning feed")
        raw_warnings = payload.get(
            "warnings",
            payload.get("alerts", payload.get("data", [])),
        )
        if not isinstance(raw_warnings, list):
            raise ValueError("China Weather warning feed did not contain a list")
        return {
            "source": "China Weather",
            "updateTime": payload.get("updateTime") or payload.get("publishTime"),
            "warnings": [self._decode_warning(record) for record in raw_warnings],
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
    """Create the JWT-only QWeather client from private entry data."""
    configured_host = config_data.get(CONF_HOST)
    project_id = config_data.get(CONF_PROJECT_ID)
    key_id = config_data.get(CONF_KEY_ID)
    private_key = config_data.get(CONF_PRIVATE_KEY)
    if (
        config_data.get(CONF_USE_TOKEN) is not True
        or not all(
            isinstance(value, str) and value.strip()
            for value in (configured_host, project_id, key_id, private_key)
        )
    ):
        raise JWTConfigurationError(
            "QWeather Pro requires a JWT/Ed25519 credential configuration"
        )

    return QWeatherAPI(
        session=async_get_clientsession(hass),
        project_id=project_id.strip(),
        key_id=key_id.strip(),
        private_key=private_key,
        host=configured_host.strip(),
    )


def create_provider_clients(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> ProviderClients:
    """Create production provider clients without exposing credentials."""
    return ProviderClients(
        qweather=create_qweather_client(hass, entry.data),
        nationwide_warnings=ChinaWeatherWarningClient(async_get_clientsession(hass)),
    )
