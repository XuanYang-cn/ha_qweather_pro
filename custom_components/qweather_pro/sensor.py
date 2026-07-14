"""QWeather (和风天气) 传感器平台."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import QWeatherUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import QWeatherConfigEntry

@dataclass(frozen=True, kw_only=True)
class QWeatherSensorEntityDescription(SensorEntityDescription):
    """自定义描述类，确保 key 用于唯一标识，translation_key 用于命名."""
    value_fn: Callable[[dict[str, Any]], Any]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _today_temperature_range(data: dict[str, Any]) -> str:
    """Format a range only when both provider temperatures are known."""
    daily = data.get("daily")
    if not daily:
        return "unknown"
    low = daily[0].get("native_templow")
    high = daily[0].get("native_temperature")
    if low is None or high is None:
        return "unknown"
    return f"{int(low)}°C/{int(high)}°C"


def _temperature_attribute(value: Any) -> str | None:
    """Avoid formatting an absent provider temperature as a real value."""
    return f"{value}°C" if value is not None else None


def _today_temperature_attributes(data: dict[str, Any]) -> dict[str, str | None]:
    """Expose today values only when the provider supplied each one."""
    daily = data.get("daily")
    if not daily:
        return {"max_temp": None, "min_temp": None}
    return {
        "max_temp": _temperature_attribute(daily[0].get("native_temperature")),
        "min_temp": _temperature_attribute(daily[0].get("native_templow")),
    }


def _warning_sensor_value(data: dict[str, Any]) -> str | None:
    """Distinguish a confirmed clear list from warnings that cannot be confirmed."""
    warnings = data.get("warning", [])
    status = data.get("dataset_status", {}).get("warning", {})
    if status.get("state") in {"unavailable", "stale"} and not warnings:
        return "warning_unconfirmed"
    if warnings:
        return warnings[0].get("title")
    return "without_warning"


def _warning_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Keep the legacy first-warning fields while publishing the complete list."""
    warnings = data.get("warning", [])
    status = data.get("dataset_status", {}).get("warning", {})
    if not warnings:
        return {"warnings": [], "warning_status": status}
    return {
        **warnings[0],
        "warnings": warnings,
        "warning_status": status,
    }


SENSOR_DESCRIPTIONS: tuple[QWeatherSensorEntityDescription, ...] = (
    QWeatherSensorEntityDescription(
        key="aqi",
        translation_key="aqi",
        icon="mdi:air-filter",
        value_fn=lambda data: data.get("aqi", {}).get("category") or "unknown",
        attr_fn=lambda data: {
            # 基础数据
            "aqi_value": (aqi := data.get("aqi", {})).get("aqi"),
            "aqi_level": aqi.get("level"),
            "primary_pollutant": aqi.get("primary") or "unknown",

            # 污染物浓度 (带单位，且增加空值保护)
            # 使用 get(..., '--') 确保在数据缺失时不会显示 'None μg/m3'
            "pm2p5": f"{aqi.get('pm2p5', '--')} {aqi.get('pm2p5_unit', 'μg/m3')}",
            "pm10": f"{aqi.get('pm10', '--')} {aqi.get('pm10_unit', 'μg/m3')}",
            "no2": f"{aqi.get('no2', '--')} {aqi.get('no2_unit', 'ppb')}",
            "so2": f"{aqi.get('so2', '--')} {aqi.get('so2_unit', 'ppb')}",
            "o3": f"{aqi.get('o3', '--')} {aqi.get('o3_unit', 'ppb')}",
            "co": f"{aqi.get('co', '--')} {aqi.get('co_unit', 'ppm')}",

            # 健康建议 (V1 接口的精华字段)
            "health_effect": aqi.get("health_effect") or "unknown",
            "health_advice": aqi.get("health_advice") or "unknown",

            # 监测站信息
            "stations": aqi.get("stations"),
        },
    ),
    QWeatherSensorEntityDescription(
        key="today_temp_range",
        translation_key="today_temp_range",
        icon="mdi:thermometer-lines",
        value_fn=_today_temperature_range,
        attr_fn=_today_temperature_attributes,
    ),
    QWeatherSensorEntityDescription(
        key="warning_info",
        translation_key="warning_info",
        icon="mdi:alert-decagram",
        value_fn=_warning_sensor_value,
        attr_fn=_warning_attributes,
    ),
    QWeatherSensorEntityDescription(
        key="precipitation_summary",
        translation_key="precipitation_summary",
        icon="mdi:message-text-clock",
        value_fn=lambda data: data.get("minutely_summary"),
        attr_fn=lambda data: {
            "detail": data.get("minutely_detail", [])
        },
    ),
    QWeatherSensorEntityDescription(
        key="weather_summary",
        translation_key="weather_summary",
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda data: data.get("weather_abstract", {}).get("tonight_text"),
        attr_fn=lambda data: data.get("weather_abstract", {}),
    ),
)

async def async_setup_entry(
    hass: HomeAssistant, 
    entry: QWeatherConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """设置平台实体."""
    coordinator = entry.runtime_data

    async_add_entities(
        QWeatherSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )

class QWeatherSensor(CoordinatorEntity[QWeatherUpdateCoordinator], SensorEntity):
    """和风天气传感器."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator)

        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Any:
        """从 Coordinator 获取数据."""
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """添加额外属性."""
        attrs = {"attribution": ATTRIBUTION}
        if self.coordinator.data:
            attrs["dataset_status"] = self.coordinator.data.get(
                "dataset_status", {}
            )
        if self.entity_description.attr_fn:
            try:
                attrs.update(self.entity_description.attr_fn(self.coordinator.data))
            except Exception:
                pass
        return attrs
