"""Independent China Weather nationwide-warning lifecycle."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .clients import NationwideWarningClient
from .const import DOMAIN, LOGGER

NATIONWIDE_WARNING_INTERVAL = timedelta(minutes=30)
CHINA_WEATHER_SOURCE = "China Weather"
WARNING_LEVELS = ("blue", "yellow", "orange", "red")
WARNING_LEVEL_RANK = {level: index for index, level in enumerate(WARNING_LEVELS)}


class NationwideWarningCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keep China Weather warnings independent from QWeather datasets."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: NationwideWarningClient,
    ) -> None:
        """Create an isolated 30-minute provider lifecycle."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_nationwide_warnings",
            update_interval=NATIONWIDE_WARNING_INTERVAL,
        )
        self._client = client
        self._snapshot: dict[str, Any] | None = None
        self._last_success_time: datetime | None = None
        self._last_update_result = "unavailable"

    def _now(self) -> datetime:
        """Return time through a seam shared by lifecycle contract tests."""
        return dt_util.utcnow()

    @staticmethod
    def _parse_provider_time(value: object) -> datetime | None:
        """Parse an explicit provider timestamp without inventing a replacement."""
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _provider_time(snapshot: Mapping[str, Any]) -> str | None:
        """Read the provider-wide timestamp, never an individual alert issue time."""
        provider_time = snapshot.get("provider_time") or snapshot.get("updateTime")
        if provider_time:
            return str(provider_time)
        metadata = snapshot.get("metadata")
        if isinstance(metadata, Mapping):
            provider_time = metadata.get("updateTime") or metadata.get("publishTime")
            if provider_time:
                return str(provider_time)
        provider_time = snapshot.get("publishTime")
        return str(provider_time) if provider_time else None

    @staticmethod
    def _warning_value(alert: Mapping[str, Any], *keys: str) -> str | None:
        """Return the first non-empty provider alias as a string."""
        for key in keys:
            value = alert.get(key)
            if value is not None and str(value).strip():
                return str(value)
        return None

    @classmethod
    def _warning_level(cls, alert: Mapping[str, Any]) -> str:
        """Normalize the four China Weather color levels for consumers."""
        raw_level = cls._warning_value(alert, "level", "signallevel", "severity")
        if raw_level:
            normalized = raw_level.casefold()
            for level, chinese in (
                ("red", "红"),
                ("orange", "橙"),
                ("yellow", "黄"),
                ("blue", "蓝"),
            ):
                if level in normalized or chinese in raw_level:
                    return level
        return "unknown"

    @classmethod
    def _warning_region(cls, alert: Mapping[str, Any]) -> str | None:
        """Prefer a provider region, then retain the broadest named jurisdiction."""
        return cls._warning_value(
            alert,
            "region",
            "regionName",
            "provinceName",
            "province",
            "areaName",
        )

    @classmethod
    def _warning_identity(
        cls,
        alert: Mapping[str, Any],
        region: str | None,
        warning_type: str | None,
        issued: str | None,
        effective: str | None,
    ) -> str:
        """Use the provider ID or a stable identity that excludes mutable text."""
        provider_id = cls._warning_value(alert, "id", "alarmId", "warningId")
        if provider_id:
            return provider_id
        material = {
            "region": region,
            "type": warning_type,
            "issued": issued,
            "effective": effective,
        }
        encoded = json.dumps(material, ensure_ascii=False, sort_keys=True)
        return f"china-weather-{hashlib.sha256(encoded.encode()).hexdigest()[:16]}"

    @classmethod
    def _normalize_warning(cls, alert: Mapping[str, Any]) -> dict[str, str | None]:
        """Translate the provider record into the public read-only contract."""
        region = cls._warning_region(alert)
        warning_type = cls._warning_value(
            alert,
            "type",
            "signaltype",
            "typeName",
            "eventType",
        )
        issued = cls._warning_value(
            alert,
            "issued",
            "issuedTime",
            "issueTime",
            "pubTime",
            "publishTime",
        )
        effective = cls._warning_value(alert, "effective", "effectiveTime", "startTime")
        title = cls._warning_value(alert, "title", "headline")
        if not title:
            title = " ".join(
                value
                for value in (region, warning_type, cls._warning_level(alert))
                if value
            )
        return {
            "id": cls._warning_identity(alert, region, warning_type, issued, effective),
            "region": region,
            "type": warning_type,
            "level": cls._warning_level(alert),
            "title": title,
            "issued": issued,
            "effective": effective,
            "expires": cls._warning_value(alert, "expires", "expireTime", "endTime"),
            "source": CHINA_WEATHER_SOURCE,
        }

    @classmethod
    def _normalize_snapshot(cls, response: object) -> dict[str, Any]:
        """Validate the narrow client contract and preserve every supplied alert."""
        if not isinstance(response, Mapping):
            raise ValueError("China Weather returned a non-object warning snapshot")
        raw_warnings = response.get("warnings", response.get("alerts", []))
        if not isinstance(raw_warnings, list):
            raise ValueError("China Weather warning snapshot did not contain a list")
        warnings = [
            cls._normalize_warning(alert)
            for alert in raw_warnings
            if isinstance(alert, Mapping)
        ]
        return {
            "source": CHINA_WEATHER_SOURCE,
            "provider_time": cls._provider_time(response),
            "warnings": warnings,
        }

    @staticmethod
    def _summary(warnings: list[Mapping[str, Any]]) -> dict[str, int | str]:
        """Provide overview counts without discarding lower-level warning records."""
        levels = [str(warning.get("level", "unknown")) for warning in warnings]
        highest_level = max(levels, key=lambda level: WARNING_LEVEL_RANK.get(level, -1), default="none")
        return {
            "warning_count": len(warnings),
            "orange_red_count": sum(
                level in {"orange", "red"} for level in levels
            ),
            "highest_level": highest_level,
        }

    def _dataset_status(self, now: datetime) -> dict[str, str | None]:
        """Publish independent provider time, outcome, and freshness."""
        if self._snapshot is None:
            state = "unavailable"
            provider_time = None
        else:
            provider_time = self._snapshot["provider_time"]
            provider_timestamp = self._parse_provider_time(provider_time)
            if self._last_update_result == "failed":
                state = "stale"
            elif provider_timestamp is None:
                state = "unavailable"
            elif timedelta(0) <= now - provider_timestamp < NATIONWIDE_WARNING_INTERVAL:
                state = "fresh"
            else:
                state = "stale"
        return {
            "provider_time": provider_time,
            "last_success_time": (
                self._last_success_time.isoformat() if self._last_success_time else None
            ),
            "last_update_result": self._last_update_result,
            "state": state,
        }

    def _public_data(self, now: datetime) -> dict[str, Any]:
        """Build the small summary and complete read-only detail contracts."""
        warnings = self._snapshot["warnings"] if self._snapshot else []
        return {
            "source": CHINA_WEATHER_SOURCE,
            "warnings": warnings,
            "summary": self._summary(warnings),
            "dataset_status": self._dataset_status(now),
        }

    @property
    def detail_contract(self) -> dict[str, Any]:
        """Expose the complete list through a named, never-truncated transport."""
        data = self.data or self._public_data(self._now())
        return {
            "transport": "entity_attribute",
            "source": CHINA_WEATHER_SOURCE,
            "warning_count": data["summary"]["warning_count"],
            "warnings": data["warnings"],
            "dataset_status": data["dataset_status"],
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh only nationwide warnings and retain stale data on failure."""
        now = self._now()
        try:
            self._snapshot = self._normalize_snapshot(
                await self._client.async_fetch_active_warnings()
            )
        except Exception as err:
            self._last_update_result = "failed"
            LOGGER.debug("China Weather nationwide warning refresh failed (%s)", type(err).__name__)
        else:
            self._last_success_time = now
            self._last_update_result = "success"
        return self._public_data(now)
