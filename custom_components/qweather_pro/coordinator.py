"""QWeather (和风天气) 数据协调器."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.storage import Store
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
    QuantizedLocationMismatch,
    quantize_location_input,
    verified_shanghai_location,
    warning_city_coordinates,
    warning_jurisdiction_from_config,
)
from .household_warnings import (
    WarningContractError,
    alerts_for_configured_source,
    build_household_warning_contract,
)
from .rain_guidance import daily_rain_guidance
from .warning_history import WarningHistory

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
        self.warning_jurisdiction = warning_jurisdiction_from_config(dict(entry.data))
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
        self._recent_warning_changes: dict[str, datetime] = {}
        self._warning_history_store = Store[dict[str, Any]](
            hass,
            1,
            f"{DOMAIN}.{entry.entry_id}.household_warning_history",
        )
        self._warning_history = WarningHistory(self._warning_history_key())
        self._household_warning_contract = self._empty_household_warning_contract(
            "uninitialized",
            None,
        )

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
            elif result in {"failed", "unchanged", "stale", "contract_error"}:
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

    def _store_household_warning_responses(
        self,
        city_response: Mapping[str, Any],
        district_response: Mapping[str, Any],
        refresh_time: datetime,
    ) -> None:
        """Store two source snapshots only when they form one coherent batch."""
        city_time = self._provider_time_from_response("warning", city_response)
        district_time = self._provider_time_from_response("warning", district_response)
        city_timestamp = self._parse_provider_time(city_time)
        district_timestamp = self._parse_provider_time(district_time)
        if (
            city_timestamp is not None
            and district_timestamp is not None
            and city_timestamp != district_timestamp
        ):
            raise WarningContractError("Warning source snapshots have different times")
        provider_time = city_time or district_time
        provider_timestamp = city_timestamp or district_timestamp
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
                self._cache_data["warning"] = {
                    "metadata": {"updateTime": provider_time},
                    "city_alerts": city_response["alerts"],
                    "district_alerts": district_response["alerts"],
                }
            self._last_update_results["warning"] = "stale"
            return

        self._cache_data["warning"] = {
            "metadata": {"updateTime": provider_time} if provider_time else {},
            "city_alerts": city_response["alerts"],
            "district_alerts": district_response["alerts"],
        }
        self._last_success_times["warning"] = refresh_time
        self._last_update_results["warning"] = "success"
        if provider_timestamp is not None:
            self._latest_provider_times["warning"] = provider_timestamp

    def _empty_household_warning_contract(
        self, state: str, now: datetime | None
    ) -> dict[str, Any]:
        """Hide local warning content whenever its household contract is unhealthy."""
        return {
            "state": state,
            "jurisdiction": (
                self.warning_jurisdiction.label if self.warning_jurisdiction else None
            ),
            "effective_warnings": [],
            "sources": {},
            "recent_changes": {},
            "history": [],
            "published_at": now.isoformat() if now is not None else None,
        }

    def _warning_history_key(self) -> str:
        """Keep the private source-history key tied to one configured jurisdiction."""
        if self.warning_jurisdiction is None:
            return "unconfigured"
        return "\x1f".join(
            (
                self.warning_jurisdiction.district_id,
                self.warning_jurisdiction.city_id,
                self.warning_jurisdiction.country,
            )
        )

    async def async_load_warning_history(self) -> None:
        """Restore the local warning timeline before the first coordinator refresh."""
        now = self._now()
        payload = await self._warning_history_store.async_load()
        self._warning_history = WarningHistory.from_storage(
            payload,
            self._warning_history_key(),
            now,
        )
        if payload is not None and self._warning_history.as_storage() != payload:
            await self._warning_history_store.async_save(
                self._warning_history.as_storage()
            )

    def _set_household_warning_failure(self, state: str, now: datetime) -> None:
        """Hide local warning content whenever its household contract is unhealthy."""
        self._household_warning_contract = self._empty_household_warning_contract(
            state,
            now,
        )

    @staticmethod
    def _warning_sources_by_hazard(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Index public source records by their stable hazard identity."""
        indexed: dict[str, dict[str, Any]] = {}
        sources = contract.get("sources")
        if not isinstance(sources, Mapping):
            return indexed
        for source_level in ("city", "district"):
            source = sources.get(source_level)
            warnings = source.get("warnings") if isinstance(source, Mapping) else None
            if not isinstance(warnings, list):
                continue
            for warning in warnings:
                if isinstance(warning, Mapping) and isinstance(
                    hazard_id := warning.get("hazard_id"), str
                ):
                    indexed.setdefault(hazard_id, {})[source_level] = dict(warning)
        return indexed

    async def _publish_household_warning_contract(
        self, contract: dict[str, Any], now: datetime
    ) -> None:
        """Attach stable recent-change times before atomically publishing a snapshot."""
        previous = self._warning_sources_by_hazard(self._household_warning_contract)
        current = self._warning_sources_by_hazard(contract)
        provider_changes = contract.get("recent_changes", {})
        for hazard_id in previous.keys() | current.keys():
            if previous.get(hazard_id) == current.get(hazard_id):
                continue
            provider_time = (
                provider_changes.get(hazard_id)
                if isinstance(provider_changes, Mapping)
                else None
            )
            self._recent_warning_changes[hazard_id] = (
                self._parse_provider_time(provider_time) or now
                if hazard_id in current
                else now
            )
        retention_cutoff = now - timedelta(hours=24)
        for hazard_id, changed_at in tuple(self._recent_warning_changes.items()):
            if hazard_id not in current and changed_at < retention_cutoff:
                del self._recent_warning_changes[hazard_id]
        contract["recent_changes"] = {
            hazard_id: changed_at.isoformat()
            for hazard_id, changed_at in sorted(self._recent_warning_changes.items())
        }
        if self._warning_history.observe(contract, now):
            await self._warning_history_store.async_save(self._warning_history.as_storage())
        contract["history"] = self._warning_history.events
        self._household_warning_contract = contract

    async def _refresh_household_warning_contract(
        self,
        city_response: Mapping[str, Any],
        district_response: Mapping[str, Any],
        now: datetime,
    ) -> None:
        """Publish the provider batch only after every applicable record normalizes."""
        if self.warning_jurisdiction is None:
            self._set_household_warning_failure("uninitialized", now)
            return
        try:
            city_alerts = alerts_for_configured_source(
                city_response["alerts"],
                self.warning_jurisdiction,
                "city",
            )
            district_alerts = alerts_for_configured_source(
                district_response["alerts"],
                self.warning_jurisdiction,
                "district",
            )
            contract = build_household_warning_contract(
                self.warning_jurisdiction,
                city_alerts=city_alerts,
                district_alerts=district_alerts,
                now=now,
            )
            await self._publish_household_warning_contract(contract, now)
        except WarningContractError:
            self._last_update_results["warning"] = "contract_error"
            self._set_household_warning_failure("contract_error", now)

    async def _async_refresh_household_warnings(
        self, language: str, refresh_time: datetime
    ) -> None:
        """Refresh city and district alerts as one explicitly scoped provider batch."""
        assert self.warning_jurisdiction is not None
        self._last_attempt_times["warning"] = refresh_time
        try:
            city_lookup = await self.api.city_lookup(
                self.warning_jurisdiction.city_id,
                lang=language,
            )
            city_lon, city_lat = warning_city_coordinates(
                city_lookup,
                self.warning_jurisdiction,
            )
            city_response, district_response = await asyncio.gather(
                self.api.get_warning_v1(city_lat, city_lon, language),
                self.api.get_warning_v1(
                    self.warning_jurisdiction.latitude,
                    self.warning_jurisdiction.longitude,
                    language,
                ),
            )
        except QuantizedLocationMismatch:
            self._last_update_results["warning"] = "contract_error"
            self._set_household_warning_failure("contract_error", refresh_time)
            return
        except Exception as error:
            self._last_update_results["warning"] = "failed"
            self._set_household_warning_failure("failed", refresh_time)
            LOGGER.debug(
                "QWeather local warning refresh failed (%s)", type(error).__name__
            )
            return

        if not all(
            self._response_succeeded("warning", response)
            for response in (city_response, district_response)
        ):
            self._last_update_results["warning"] = "failed"
            self._set_household_warning_failure("failed", refresh_time)
            return
        try:
            self._store_household_warning_responses(
                city_response,
                district_response,
                refresh_time,
            )
            if self._last_update_results["warning"] == "success":
                await self._refresh_household_warning_contract(
                    city_response,
                    district_response,
                    refresh_time,
                )
            elif self._last_update_results["warning"] in {"unchanged", "stale"}:
                self._set_household_warning_failure("stale", refresh_time)
            else:
                self._set_household_warning_failure("failed", refresh_time)
        except WarningContractError:
            self._last_update_results["warning"] = "contract_error"
            self._set_household_warning_failure("contract_error", refresh_time)

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
        refresh_household_warnings = False
        if self.warning_jurisdiction is None:
            self._last_update_results["warning"] = "uninitialized"
            self._set_household_warning_failure("uninitialized", refresh_time)
        elif self._should_update("warning", refresh_time):
            refresh_household_warnings = True
        if self._should_update("air", refresh_time):
            tasks["air"] = self.api.get_air_v1(lat, lon, qweather_lang)
        if self._should_update("indices", refresh_time):
            tasks["indices"] = self.api.get_indices(lat, lon, restricted_lang)

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for category, response in zip(tasks, results, strict=True):
            self._last_attempt_times[category] = refresh_time
            if self._response_succeeded(category, response):
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

        if refresh_household_warnings:
            await self._async_refresh_household_warnings(qweather_lang, refresh_time)

        if not any(self._cache_data[category] is not None for category in CORE_DATASETS):
            raise UpdateFailed("No core QWeather data snapshots are available")

        c = self._cache_data
        now_raw = (c.get("now") or {}).get("now", {})
        daily_list = (c.get("daily") or {}).get("daily", [])
        hourly_list = (c.get("hourly") or {}).get("hourly", [])
        air_raw = c.get("air") or {}
        indices_list = (c.get("indices") or {}).get("daily", [])

        parsed_warnings = self._household_warning_contract["effective_warnings"]

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
            "household_warning": self._household_warning_contract,
            "indices": self._parse_indices(indices_list),
            "city": self.city_name,
            "minutely_summary": None,
            "minutely_detail": [],
            "weather_abstract": self._generate_smart_abstract(c, now_dt),
            "dataset_status": dataset_status,
            "update_time": self._provider_time("now"),
        }

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
