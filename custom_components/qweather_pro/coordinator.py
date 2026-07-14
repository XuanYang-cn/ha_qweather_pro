"""QWeather (和风天气) 数据协调器."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
import homeassistant.util.dt as dt_util

from .clients import ProviderClients
from .const import (
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    CONF_LOCATION_ID,
    LANGUAGE_MAP,
    LOGGER,
    SUGGESTION_TYPE_MAP,
)
from .condition import CONDITION_MAP
from .location import (
    quantize_location_input,
    verified_shanghai_location,
)
from .rain_guidance import daily_rain_guidance

CORE_DATASETS = ("now", "daily", "hourly", "air")
STATUS_DATASETS = (*CORE_DATASETS, "warning")
DATASET_INTERVALS = {
    "now": timedelta(minutes=10),
    "daily": timedelta(minutes=60),
    "hourly": timedelta(minutes=60),
    "air": timedelta(minutes=60),
    "warning": timedelta(minutes=30),
    "indices": timedelta(minutes=180),
}

class QWeatherUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """QWeather 数据异步调度中心."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        version: str,
        clients: ProviderClients,
    ) -> None:
        """初始化协调器."""
        self.entry = entry
        self.version = version
        self.location = quantize_location_input(entry.data.get(CONF_LOCATION_ID, ""))
        self._location_verified = False
        self.city_name = entry.title
        self._base_interval = timedelta(minutes=DEFAULT_UPDATE_INTERVAL)

        self.api = clients.qweather

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._base_interval,
        )
        
        self._cache_data: dict[str, dict[str, Any] | None] = {
            "now": None,
            "daily": None,
            "hourly": None,
            "air": None,
            "indices": None,
            "warning": None,
        }
        self._last_success_times: dict[str, datetime] = {}
        self._last_attempt_times: dict[str, datetime] = {}
        self._latest_provider_times: dict[str, datetime] = {}
        self._last_update_results: dict[str, str] = {
            dataset: "unavailable" for dataset in DATASET_INTERVALS
        }

    def _now(self) -> datetime:
        """Return the refresh time through one controllable contract seam."""
        return dt_util.utcnow()

    def _should_update(self, category: str, now: datetime) -> bool:
        """Refresh a dataset as soon as its fixed next-refresh time is due."""
        last_attempt = self._last_attempt_times.get(category)
        return (
            last_attempt is None
            or now - last_attempt >= DATASET_INTERVALS[category]
        )

    @staticmethod
    def _response_succeeded(category: str, response: object) -> bool:
        """Identify successful envelopes with the required forecast coverage."""
        if not isinstance(response, Mapping) or (
            response.get("code") != "200" and "metadata" not in response
        ):
            return False
        if category == "daily":
            return isinstance(response.get("daily"), list) and len(response["daily"]) >= 7
        if category == "hourly":
            return isinstance(response.get("hourly"), list) and len(response["hourly"]) >= 24
        if category == "warning":
            return isinstance(response.get("alerts"), list)
        return True

    @staticmethod
    def _response_failure_type(response: object) -> str:
        """Describe a failed fake/provider result without logging its contents."""
        if isinstance(response, Exception):
            return type(response).__name__
        if isinstance(response, Mapping):
            return f"response-{response.get('code', 'invalid')}"
        return type(response).__name__

    @staticmethod
    def _provider_time_from_response(
        category: str,
        response: Mapping[str, Any] | None,
    ) -> str | None:
        """Read an authoritative provider timestamp without inventing one."""
        if not isinstance(response, Mapping):
            return None
        if category == "now":
            now_data = response.get("now")
            return now_data.get("obsTime") if isinstance(now_data, Mapping) else None
        if category == "air":
            indexes = response.get("indexes")
            if isinstance(indexes, list) and indexes and isinstance(indexes[0], Mapping):
                return indexes[0].get("pubTime") or indexes[0].get("updateTime")
        metadata = response.get("metadata")
        if isinstance(metadata, Mapping):
            provider_time = metadata.get("updateTime") or metadata.get("publishTime")
            if provider_time:
                return provider_time
        provider_time = response.get("updateTime") or response.get("publishTime")
        if provider_time:
            return provider_time
        return None

    def _provider_time(self, category: str) -> str | None:
        """Read a provider timestamp from the retained dataset snapshot."""
        return self._provider_time_from_response(category, self._cache_data.get(category))

    @staticmethod
    def _parse_provider_time(value: str | None) -> datetime | None:
        """Parse a provider timestamp only when it has an explicit timezone."""
        if not isinstance(value, str):
            return None
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if timestamp.tzinfo is None:
            return None
        return timestamp.astimezone(timezone.utc)

    @staticmethod
    def _provider_time_is_current(
        category: str,
        provider_time: datetime,
        refresh_time: datetime,
    ) -> bool:
        """Require source data to be within the dataset's current interval."""
        source_age = refresh_time - provider_time
        return timedelta(0) <= source_age < DATASET_INTERVALS[category]

    def _dataset_statuses(self, now: datetime) -> dict[str, dict[str, str | None]]:
        """Publish independent freshness and result state for public datasets."""
        statuses: dict[str, dict[str, str | None]] = {}
        for category in STATUS_DATASETS:
            last_success = self._last_success_times.get(category)
            result = self._last_update_results[category]
            provider_time = self._provider_time(category)
            provider_timestamp = self._parse_provider_time(provider_time)
            if self._cache_data[category] is None:
                state = "unavailable"
            elif result in {"failed", "unchanged", "stale"}:
                state = "stale"
            elif last_success is None or provider_timestamp is None:
                state = "unavailable"
            elif not self._provider_time_is_current(category, provider_timestamp, now):
                state = "stale"
            else:
                state = "fresh"
            statuses[category] = {
                "provider_time": provider_time,
                "last_success_time": last_success.isoformat() if last_success else None,
                "last_update_result": result,
                "state": state,
            }
        return statuses

    def _to_f(self, val: Any) -> float | None:
        """Convert a provider number without inventing a default value."""
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _store_warning_response(
        self,
        response: Mapping[str, Any],
        refresh_time: datetime,
    ) -> None:
        """Accept a usable warning response without conflating it with source age."""
        provider_time = self._provider_time_from_response("warning", response)
        provider_timestamp = self._parse_provider_time(provider_time)
        previous_provider_timestamp = self._latest_provider_times.get("warning")
        if (
            provider_timestamp is not None
            and previous_provider_timestamp is not None
            and provider_timestamp <= previous_provider_timestamp
        ):
            self._last_update_results["warning"] = "unchanged"
            return
        if provider_timestamp is not None and not self._provider_time_is_current(
            "warning",
            provider_timestamp,
            refresh_time,
        ):
            if self._cache_data["warning"] is None:
                self._cache_data["warning"] = dict(response)
            self._last_update_results["warning"] = "stale"
            return

        incoming_alerts = response["alerts"]
        cached_alerts = (self._cache_data["warning"] or {}).get("alerts", [])
        snapshot = dict(response)
        snapshot["alerts"] = self._merge_warning_alerts(
            cached_alerts,
            incoming_alerts,
            refresh_time,
        )
        self._cache_data["warning"] = snapshot
        self._last_success_times["warning"] = refresh_time
        self._last_update_results["warning"] = "success"
        if provider_timestamp is not None:
            self._latest_provider_times["warning"] = provider_timestamp

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh independent provider datasets without hiding failed snapshots."""

        if not self._location_verified:
            try:
                location_response = await self.api.city_lookup(
                    self.location,
                    lang="zh",
                )
                verified_shanghai_location(location_response)
            except Exception as err:
                raise UpdateFailed(
                    "Configured location is outside the expected Shanghai jurisdiction"
                ) from err
            self._location_verified = True

        ha_lang = self.hass.config.language
        qweather_lang = LANGUAGE_MAP.get(ha_lang, "en")
        restricted_lang = "zh" if ha_lang.startswith("zh") else "en"
        refresh_time = self._now()
        now_dt = dt_util.as_local(refresh_time)

        # 预处理坐标参数
        try:
            lon, lat = [c.strip() for c in self.location.split(',')]
        except ValueError as error:
            raise UpdateFailed("Invalid configured location format") from error

        tasks: dict[str, Any] = {}
        if self._should_update("now", refresh_time):
            tasks["now"] = self.api.get_weather_now(lat, lon, qweather_lang)
        if self._should_update("daily", refresh_time):
            tasks["daily"] = self.api.get_forecast(lat, lon, "7d", qweather_lang)
        if self._should_update("hourly", refresh_time):
            tasks["hourly"] = self.api.get_hourly(lat, lon, "24h", qweather_lang)
        if self._should_update("warning", refresh_time):
            tasks["warning"] = self.api.get_warning_v1(lat, lon, qweather_lang)
        if self._should_update("air", refresh_time):
            tasks["air"] = self.api.get_air_v1(lat, lon, qweather_lang)
        if self._should_update("indices", refresh_time):
            tasks["indices"] = self.api.get_indices(lat, lon, restricted_lang)

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for category, response in zip(tasks, results, strict=True):
            self._last_attempt_times[category] = refresh_time
            if self._response_succeeded(category, response):
                if category == "warning":
                    self._store_warning_response(response, refresh_time)
                    continue
                provider_time = self._provider_time_from_response(category, response)
                provider_timestamp = self._parse_provider_time(provider_time)
                previous_provider_timestamp = self._latest_provider_times.get(category)
                if category in STATUS_DATASETS and (
                    provider_timestamp is None
                    or (
                        previous_provider_timestamp is not None
                        and provider_timestamp <= previous_provider_timestamp
                    )
                ):
                    if previous_provider_timestamp is None:
                        self._cache_data[category] = dict(response)
                        self._last_update_results[category] = "unavailable"
                    else:
                        self._last_update_results[category] = "unchanged"
                elif category in STATUS_DATASETS and not self._provider_time_is_current(
                    category,
                    provider_timestamp,
                    refresh_time,
                ):
                    if self._cache_data[category] is None:
                        self._cache_data[category] = dict(response)
                    self._last_update_results[category] = "stale"
                else:
                    self._cache_data[category] = dict(response)
                    self._last_success_times[category] = refresh_time
                    self._last_update_results[category] = "success"
                    if provider_timestamp is not None:
                        self._latest_provider_times[category] = provider_timestamp
            else:
                self._last_update_results[category] = "failed"
                LOGGER.debug(
                    "QWeather endpoint %s refresh failed (%s)",
                    category,
                    self._response_failure_type(response),
                )

        if not any(self._cache_data[category] is not None for category in CORE_DATASETS):
            raise UpdateFailed("No core QWeather data snapshots are available")

        c = self._cache_data
        now_raw = (c.get("now") or {}).get("now", {})
        daily_list = (c.get("daily") or {}).get("daily", [])
        hourly_list = (c.get("hourly") or {}).get("hourly", [])
        air_raw = c.get("air") or {}
        warning_raw = (c.get("warning") or {}).get("alerts", [])
        indices_list = (c.get("indices") or {}).get("daily", [])

        parsed_warnings = self._parse_local_warnings(warning_raw, refresh_time)

        # 针对 V1 空气质量的深度解析逻辑
        parsed_air: dict[str, Any] = {}
        if "indexes" in air_raw and air_raw["indexes"]:
            idx = air_raw["indexes"][0] # 默认取第一项（通常是本地标准）
            
            # 安全获取首要污染物
            primary_info = idx.get("primaryPollutant")
            primary_name = primary_info.get("name") if isinstance(primary_info, dict) else None
            
            # 安全获取健康建议
            health_info = idx.get("health")
            health_effect = health_info.get("effect") if isinstance(health_info, dict) else None
            health_advice = None
            if isinstance(health_info, dict):
                advice_info = health_info.get("advice")
                if isinstance(advice_info, dict):
                    health_advice = advice_info.get("generalPopulation")

            parsed_air = {
                "aqi": idx.get("aqi"),
                "category": idx.get("category"),
                "level": idx.get("level"),
                "primary": primary_name,
                "health_effect": health_effect,
                "health_advice": health_advice,
            }
            
            # 污染物浓度
            for p in air_raw.get("pollutants", []):
                code = p.get("code", "").replace(".", "p")
                conc = p.get("concentration", {})
                if code and isinstance(conc, dict):
                    parsed_air[code] = conc.get("value")
                    parsed_air[f"{code}_unit"] = conc.get("unit")

        parsed_hourly = self._parse_hourly(hourly_list)
        dataset_status = self._dataset_statuses(refresh_time)
        return {
            "now": {
                "temp": self._to_f(now_raw.get("temp")),
                "text_cn": now_raw.get("text"),
                "condition": CONDITION_MAP.get(now_raw.get("icon")) if now_raw.get("icon") else None,
                "humidity": self._to_f(now_raw.get("humidity")),
                "pressure": self._to_f(now_raw.get("pressure")),
                "windSpeed": self._to_f(now_raw.get("windSpeed")),
                "wind360": self._to_f(now_raw.get("wind360")),
                "windDir": now_raw.get("windDir"),
                "windScale": now_raw.get("windScale"),
                "feelsLike": self._to_f(now_raw.get("feelsLike")),
                "icon": now_raw.get("icon"),
                "obsTime": now_raw.get("obsTime"),
                "vis": self._to_f(now_raw.get("vis")),
                "precip": self._to_f(now_raw.get("precip")),
                "cloud": self._to_f(now_raw.get("cloud")),
                "dew": self._to_f(now_raw.get("dew")),
            },
            "daily": self._parse_daily(daily_list),
            "hourly": parsed_hourly,
            "rain_guidance": daily_rain_guidance(
                parsed_hourly,
                dataset_status["hourly"],
                refresh_time,
            ),
            "aqi": parsed_air,
            "warning": parsed_warnings,
            "indices": self._parse_indices(indices_list),
            "city": self.city_name,
            "minutely_summary": None,
            "minutely_detail": [],
            "weather_abstract": self._generate_smart_abstract(c, now_dt),
            "dataset_status": dataset_status,
            "update_time": self._provider_time("now"),
        }

    @staticmethod
    def _warning_base_identity(alert: Mapping[str, Any]) -> str:
        """Prefer the provider ID and otherwise derive a deterministic identity."""
        provider_id = alert.get("id") or alert.get("warningId")
        if provider_id:
            return str(provider_id)
        event_type = alert.get("eventType")
        type_name = event_type.get("name") if isinstance(event_type, Mapping) else None
        identity_material = {
            "sender": alert.get("senderName") or alert.get("sender"),
            "type_code": (
                event_type.get("id") or event_type.get("code")
                if isinstance(event_type, Mapping)
                else None
            )
            or alert.get("typeCode")
            or alert.get("eventCode"),
            "type": type_name or alert.get("typeName") or alert.get("type"),
            "issued": alert.get("issuedTime") or alert.get("pubTime"),
            "effective": alert.get("effectiveTime") or alert.get("startTime"),
        }
        encoded = json.dumps(
            identity_material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"qweather-{hashlib.sha256(encoded.encode()).hexdigest()[:16]}"

    @classmethod
    def _warning_identity(cls, alert: Mapping[str, Any]) -> str:
        """Read the locally retained ID before falling back to provider fields."""
        retained_identity = alert.get("_qweather_identity")
        if retained_identity:
            return str(retained_identity)
        return cls._warning_base_identity(alert)

    @staticmethod
    def _warning_signature(alert: Mapping[str, Any]) -> str:
        """Serialize a provider alert without leaking the local identity marker."""
        return json.dumps(
            {
                key: value
                for key, value in alert.items()
                if key != "_qweather_identity"
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _warning_identities(cls, alerts: list[Mapping[str, Any]]) -> list[str]:
        """Resolve rare fallback-ID collisions deterministically."""
        base_ids = [cls._warning_base_identity(alert) for alert in alerts]
        grouped_indexes: dict[str, list[int]] = {}
        for index, identity in enumerate(base_ids):
            grouped_indexes.setdefault(identity, []).append(index)

        identities = list(base_ids)
        for identity, indexes in grouped_indexes.items():
            if len(indexes) == 1:
                continue
            ordered_indexes = sorted(
                indexes,
                key=lambda index: cls._warning_signature(alerts[index]),
            )
            for position, index in enumerate(ordered_indexes, start=1):
                identities[index] = f"{identity}-{position}"
        return identities

    @staticmethod
    def _warning_match_score(
        cached_alert: Mapping[str, Any],
        incoming_alert: Mapping[str, Any],
    ) -> int:
        """Score mutable fields to retain a collision suffix across an update."""
        field_aliases = (
            ("headline", "title"),
            ("description", "text"),
            ("instruction", "defense"),
            ("severity", "level"),
            ("expireTime", "endTime", "expires"),
        )
        score = 0
        for aliases in field_aliases:
            cached_value = next(
                (cached_alert.get(alias) for alias in aliases if cached_alert.get(alias)),
                None,
            )
            incoming_value = next(
                (
                    incoming_alert.get(alias)
                    for alias in aliases
                    if incoming_alert.get(alias)
                ),
                None,
            )
            if cached_value is not None and cached_value == incoming_value:
                score += 1
        return score

    def _incoming_warning_identities(
        self,
        cached_alerts: list[Mapping[str, Any]],
        incoming_alerts: list[Mapping[str, Any]],
    ) -> list[str]:
        """Match colliding incoming alerts to the IDs retained in the snapshot."""
        identities = ["" for _ in incoming_alerts]
        cached_by_base: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
        incoming_by_base: dict[str, list[int]] = {}
        for alert in cached_alerts:
            cached_by_base.setdefault(self._warning_base_identity(alert), []).append(
                (self._warning_identity(alert), alert)
            )
        for index, alert in enumerate(incoming_alerts):
            incoming_by_base.setdefault(self._warning_base_identity(alert), []).append(index)

        for base_identity, indexes in incoming_by_base.items():
            cached = sorted(
                cached_by_base.get(base_identity, []),
                key=lambda candidate: candidate[0],
            )
            if not cached:
                for index, identity in zip(
                    indexes,
                    self._warning_identities(
                        [incoming_alerts[index] for index in indexes]
                    ),
                    strict=True,
                ):
                    identities[index] = identity
                continue

            remaining_cached = list(cached)
            remaining_indexes = list(indexes)
            for index in indexes:
                signature = self._warning_signature(incoming_alerts[index])
                match = next(
                    (
                        candidate
                        for candidate in remaining_cached
                        if self._warning_signature(candidate[1]) == signature
                    ),
                    None,
                )
                if match is not None:
                    identities[index] = match[0]
                    remaining_cached.remove(match)
                    remaining_indexes.remove(index)

            while remaining_cached and remaining_indexes:
                candidates = [
                    (
                        self._warning_match_score(cached_alert, incoming_alerts[index]),
                        index,
                        identity,
                    )
                    for identity, cached_alert in remaining_cached
                    for index in remaining_indexes
                ]
                best_score = max(score for score, _, _ in candidates)
                if best_score == 0 and len(remaining_cached) != len(remaining_indexes):
                    break
                _, index, identity = min(
                    candidate
                    for candidate in candidates
                    if candidate[0] == best_score
                )
                identities[index] = identity
                remaining_indexes.remove(index)
                remaining_cached = [
                    candidate
                    for candidate in remaining_cached
                    if candidate[0] != identity
                ]

            used_identities = {
                identity for identity, _ in cached
            } | {identities[index] for index in indexes if identities[index]}
            for index in remaining_indexes:
                identity = base_identity
                suffix = 1
                while identity in used_identities:
                    identity = f"{base_identity}-{suffix}"
                    suffix += 1
                identities[index] = identity
                used_identities.add(identity)

        return identities

    def _warning_is_active(
        self,
        alert: Mapping[str, Any],
        now: datetime,
    ) -> bool:
        """Exclude only explicit cancellation or expiration from a success response."""
        status = str(alert.get("status") or alert.get("warningStatus") or "active")
        if status.casefold() in {"cancelled", "canceled", "cleared", "expired", "ended"}:
            return False
        expires = (
            alert.get("expireTime")
            or alert.get("endTime")
            or alert.get("expires")
        )
        expires_at = self._parse_provider_time(expires)
        return expires_at is None or expires_at > now

    def _merge_warning_alerts(
        self,
        cached_alerts: object,
        incoming_alerts: object,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Retain active warnings unless the provider gives their clear condition."""
        if not isinstance(incoming_alerts, list):
            return []
        if not incoming_alerts:
            return []

        cached = (
            [
                alert
                for alert in cached_alerts
                if isinstance(alert, Mapping) and self._warning_is_active(alert, now)
            ]
            if isinstance(cached_alerts, list)
            else []
        )
        incoming = [alert for alert in incoming_alerts if isinstance(alert, Mapping)]
        active_alerts: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for alert in cached:
            identity = self._warning_identity(alert)
            active_alerts[identity] = dict(alert)
            order.append(identity)

        for alert, identity in zip(
            incoming,
            self._incoming_warning_identities(cached, incoming),
            strict=True,
        ):
            if self._warning_is_active(alert, now):
                stored_alert = dict(alert)
                stored_alert["_qweather_identity"] = identity
                active_alerts[identity] = stored_alert
                if identity not in order:
                    order.append(identity)
            else:
                active_alerts.pop(identity, None)

        return [active_alerts[identity] for identity in order if identity in active_alerts]

    def _parse_local_warnings(
        self,
        alerts: object,
        now: datetime,
    ) -> list[dict[str, Any]]:
        """Normalize every still-active provider warning without collapsing the list."""
        if not isinstance(alerts, list):
            return []
        active_alerts = [
            alert
            for alert in alerts
            if isinstance(alert, Mapping) and self._warning_is_active(alert, now)
        ]
        parsed: list[dict[str, Any]] = []
        for alert in active_alerts:
            identity = self._warning_identity(alert)
            event_type = alert.get("eventType")
            type_name = (
                event_type.get("name") if isinstance(event_type, Mapping) else None
            ) or alert.get("typeName") or alert.get("type")
            severity = alert.get("severity") or alert.get("level")
            color = alert.get("color")
            parsed.append(
                {
                    "id": identity,
                    "type": type_name,
                    "severity": severity,
                    "title": alert.get("headline") or alert.get("title"),
                    "text": alert.get("description") or alert.get("text"),
                    "instruction": alert.get("instruction") or alert.get("defense"),
                    "sender": alert.get("senderName") or alert.get("sender"),
                    "issued": alert.get("issuedTime") or alert.get("pubTime"),
                    "effective": alert.get("effectiveTime") or alert.get("startTime"),
                    "expires": alert.get("expireTime") or alert.get("endTime"),
                    "source": "QWeather",
                    "level": severity,
                    "color": color.get("code") if isinstance(color, Mapping) else color,
                    "type_name": type_name,
                }
            )
        return parsed

    def _generate_smart_abstract(self, c: dict, now_dt: datetime) -> dict[str, Any]:
        """全天候智能语义引擎 - 国际化逻辑版"""
        now_raw = (c.get("now") or {}).get("now", {})
        daily = (c.get("daily") or {}).get("daily", [])
        air_raw = c.get("air") or {}
        indexes = air_raw.get("indexes", [])
        idx = indexes[0] if isinstance(indexes, list) and indexes else {}
        
        if not daily or len(daily) < 2:
            return {"display_state": now_raw.get("text"), "status": "unavailable"}

        today = daily[0]
        tomorrow = daily[1]
        hour = now_dt.hour
        
        # ---时段感知 (Time Period) ---
        if 5 <= hour < 11:
            period = "morning"
        elif 11 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 23:
            period = "evening"
        else:
            period = "night"

        # ---智能显示状态判定 (Display State Logic) ---
        # 5:00 - 17:00 (白天/下午)：状态显示【今日实况】
        # 17:00 - 05:00 (傍晚/深夜)：状态显示【明日白天预报】
        if 5 <= hour < 17:
            display_state = now_raw.get("text", "Unknown")
        else:
            display_state = tomorrow.get("textDay", "Unknown")

        # ---气温趋势监控 (基于今日与明日最高温对比) ---
        t_max_today = self._to_f(today.get("tempMax"))
        t_max_tomorrow = self._to_f(tomorrow.get("tempMax"))
        diff = (
            t_max_tomorrow - t_max_today
            if t_max_today is not None and t_max_tomorrow is not None
            else None
        )

        if diff is None:
            temp_type = "unknown"
        elif diff >= 5:
            temp_type = "heat_surge"    # 气温剧升
        elif diff >= 2:
            temp_type = "warmer"        # 明显升温
        elif diff <= -5:
            temp_type = "cold_snap"     # 断崖式降温
        elif diff <= -2:
            temp_type = "colder"        # 明显降温
        else:
            temp_type = "steady"        # 气温平稳

        # --- 风力判定 (Wind Scale) ---
        # 3级以上视为“有风”
        wind_scale = self._to_f(now_raw.get("windScale"))

        if wind_scale is None:
            wind_status = "unknown"
        elif wind_scale == 0:
            wind_status = "no_wind"
        elif wind_scale < 3:
            wind_status = "calm"
        else:
            wind_status = "windy"

        # --- 空气质量等级 (AQI Level) ---
        # 即使 category 是中文，我们也可以根据 aqi 数值输出逻辑 key
        aqi_val = self._to_f(idx.get("aqi"))

        if aqi_val is None:
            aqi_level = "unknown"
        elif aqi_val <= 50:
            aqi_level = "good"
        elif aqi_val <= 100:
            aqi_level = "moderate"
        elif aqi_val <= 150:
            aqi_level = "unhealthy"
        elif aqi_val <= 200:
            aqi_level = "very_unhealthy"
        else:
            aqi_level = "extazardous"

        # --- 组装逻辑包 (全部使用英文 Key) ---
        return {
            "period": period, 
            "tonight_text": display_state,
            "temp_change_type": temp_type,
            "current_temp": (
                int(current_temp)
                if (current_temp := self._to_f(now_raw.get("temp"))) is not None
                else None
            ),
            "wind_status": wind_status, 
            "aqi_level": aqi_level, 
        }

    # --- 解析辅助方法 (逻辑下沉) ---
    def _parse_daily(self, data: list) -> list:
        return [{
            "datetime": (
                f"{d['fxDate']}T00:00:00" if d.get("fxDate") else None
            ),
            "condition": (
                CONDITION_MAP.get(d["iconDay"]) if d.get("iconDay") else None
            ),
            "condition_night": (
                CONDITION_MAP.get(d["iconNight"]) if d.get("iconNight") else None
            ),
            "icon": d.get("iconDay"),
            "icon_night": d.get("iconNight"),
            "text": d.get("textDay"),
            "text_night": d.get("textNight"),
            "native_temperature": self._to_f(d.get("tempMax")),
            "native_templow": self._to_f(d.get("tempMin")),
            "native_precipitation": self._to_f(d.get("precip")),
            "wind_360_day": self._to_f(d.get("wind360Day")),
            "wind_dir_day": d.get("windDirDay"),
            "wind_scale_day": d.get("windScaleDay"),
            "native_wind_speed": self._to_f(d.get("windSpeedDay")),
            "wind_360_night": self._to_f(d.get("wind360Night")),
            "wind_dir_night": d.get("windDirNight"),
            "wind_scale_night": d.get("windScaleNight"),
            "wind_speed_night": self._to_f(d.get("windSpeedNight")),
            "sunrise": d.get("sunrise"),
            "sunset": d.get("sunset"),
            "moonrise": d.get("moonrise"),
            "moonset": d.get("moonset"),
            "moon_phase": d.get("moonPhase"),
            "moon_phase_icon": d.get("moonPhaseIcon"),
            "humidity": self._to_f(d.get("humidity")),
            "pressure": self._to_f(d.get("pressure")),
            "vis": self._to_f(d.get("vis")),
            "cloud": self._to_f(d.get("cloud")),
            "uv_index": d.get("uvIndex"),
        } for d in data]

    def _parse_hourly(self, data: list) -> list:
        return [{
            "datetime": d.get("fxTime"),
            "native_temperature": self._to_f(d.get("temp")),
            "native_precipitation": self._to_f(d.get("precip")),
            "condition": CONDITION_MAP.get(d["icon"]) if d.get("icon") else None,
            "icon": d.get("icon"),
            "text": d.get("text"),
            "precipitation_probability": self._to_f(d.get("pop")),
        } for d in data]

    def _parse_indices(self, data: list) -> list:
        return [{
            "type": SUGGESTION_TYPE_MAP.get(d.get("type"), "unknown"),
            "title": d.get("name"),
            "title_cn": d.get("name"),
            "brf": d.get("category"),
            "txt": d.get("text"),
        } for d in data]
    
    @property
    def device_info(self) -> DeviceInfo:
        """设备信息."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=f"QWeather Pro {self.entry.title}",
            manufacturer="QWeather Pro",
            model="Advanced Weather Engine",
            sw_version=str(self.version),
            configuration_url="https://console.qweather.com",
            entry_type=DeviceEntryType.SERVICE,
        )
