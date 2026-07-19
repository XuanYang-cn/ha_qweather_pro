"""QWeather (和风天气) integration entry point."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.loader import async_get_integration

from .clients import JWTConfigurationError, create_provider_clients
from .const import DOMAIN, PLATFORMS
from .coordinator import QWeatherUpdateCoordinator
from .nationwide_warnings import NationwideWarningCoordinator

# 定义强类型别名，便于 IDE 补全 runtime_data
type QWeatherConfigEntry = ConfigEntry[QWeatherUpdateCoordinator]

async def async_setup_entry(hass: HomeAssistant, entry: QWeatherConfigEntry) -> bool:
    """设置配置条目."""
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version) if integration.version else "1.0.0"

    try:
        clients = create_provider_clients(hass, entry)
    except JWTConfigurationError as error:
        raise ConfigEntryAuthFailed(
            "QWeather Pro requires JWT/Ed25519 reconfiguration"
        ) from error
    coordinator = QWeatherUpdateCoordinator(hass, entry, version, clients)
    nationwide_warning_coordinator = NationwideWarningCoordinator(
        hass,
        entry,
        clients.nationwide_warnings,
    )
    
    # 先恢复只保存在 Home Assistant 本地的预警轨迹，再执行首次刷新。
    await coordinator.async_load_warning_history()
    await coordinator.async_config_entry_first_refresh()
    await nationwide_warning_coordinator.async_config_entry_first_refresh()
    coordinator.nationwide_warning_coordinator = nationwide_warning_coordinator

    # 存储 runtime_data 并加载平台
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 注册选项更新监听器
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True

async def async_reload_entry(hass: HomeAssistant, entry: QWeatherConfigEntry) -> None:
    """当用户在 UI 修改配置选项时，重新加载整个集成."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: QWeatherConfigEntry) -> bool:
    """卸载集成实例."""
    # 卸载所有平台 (sensor, weather)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
