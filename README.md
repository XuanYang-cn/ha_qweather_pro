<div align="right">
  <strong>English</strong> | <a href="./README_CN.md">中文版</a>
</div>

# <img src="custom_components/qweather_pro/brand/icon.png" width="64"> QWeather Pro for Home Assistant

> This branch belongs to the `XuanYang-cn` personal maintenance fork. Its first
> audited baseline is upstream `v1.1.6` at
> `9232254cf7dd56c72aefb23b425a4dd29bab1f4e`; see
> [docs/MAINTENANCE.md](docs/MAINTENANCE.md) before installing or upgrading.

[![Release](https://img.shields.io/github/v/release/XuanYang-cn/ha_qweather_pro)](https://github.com/XuanYang-cn/ha_qweather_pro/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/XuanYang-cn/ha_qweather_pro/blob/main/LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![](https://komarev.com/ghpvc/?username=XuanYang-cn&color=ff69b4)

## A maintained QWeather data integration for Home Assistant.

This personal fork focuses on trustworthy provider data and stable Home Assistant
entities. Dashboard and detail UI are owned by the separate Home Assistant
operations repository rather than auto-registered by this integration.

## ✨ Core Features

- 🛡️ **Security First**  
  - Supports QWeather’s latest JWT (EdDSA) authentication.  
  - Automatically generates local Ed25519 key pairs to protect your API quota from unauthorized use.

- ⚡ **Extreme Performance**
  - **Backend:** Powered by DataUpdateCoordinator with concurrent requests and smart caching to minimize API usage.
  - **Frontend boundary:** Does not inject integration-owned JavaScript into Home Assistant.

- 📊 **Provider Data**
  - Standard city current conditions, hourly and daily forecasts, AQI, and local alerts.
  - Privacy-quantized coordinates with a warning-jurisdiction verification step.
  - Minute precipitation and grid-weather calls are disabled in the first fork version.

- 🎨 **Data-only Frontend Contract**
  - The bundled upstream card and custom more-info files are not auto-registered.
  - Repository-owned Lovelace UI consumes the integration entities instead.

- 🔄 **Latest Standards**  
  - Fully compatible with HA 2024.3+ WebSocket forecast subscription for long-term smooth operation.

## 🌍 Internationalization & Multi-language Support (i18n)

QWeather Pro  internationalized, providing a seamless localized experience for users worldwide.

- **Automatic Language Sync**: The integration automatically detects your Home Assistant system language (Settings -> System -> General) and requests weather data in the matching language (supporting 30+ languages).
- **Smart Fallback Mechanism**:
  - **Core Weather/Alerts/AQI**: Supports all 30+ languages provided by QWeather API (e.g., German, French, Japanese, etc.).
  - **Life Indices**: Fall back to English when the provider does not support the Home Assistant language. The first fork version does not call minute precipitation.
- **Localized Titles & IDs**: During the setup flow, the integration fetches and locks the city name based on your current language (e.g., "BeiJing" in Chinese or "BeiJing" in English), generating clean, localized Entity IDs.

## 📦 Installation

### Install via HACS (Recommended)

1. In HACS → “Integrations”, click the three-dot menu.
2. Select **“Custom repositories”**.
3. Enter:
```yaml
https://github.com/XuanYang-cn/ha_qweather_pro
```
4. Choose category **Integration**.
5. Click **Add**.
6. Find **QWeather Pro** in HACS and install it.
7. Restart Home Assistant.

### Manual Installation

1. Download the latest release:  
```yaml
https://github.com/XuanYang-cn/ha_qweather_pro
```
2. Extract and place `custom_components/qweather_pro` into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.

## 📖 Documentation Navigation

- [🚀 Detailed Configuration & Usage Guide (DOCS.md)](md/DOCS.md)
- [📜 Changelog (CHANGELOG.md)](md/CHANGELOG.md)

## Special Thanks

This update was optimized with AI assistance and deeply refactored based on the original project:  
[dscao/qweather](https://github.com/dscao/qweather)

## 📜 Disclaimer

- This project is not officially affiliated with QWeather.  
- Meteorological data is provided by **QWeather**.  
- Please comply with QWeather’s API usage policies.

## 🤝 Contributing

Contributions are welcome!

1. Submit **Issues** for bug reports or feature requests  
2. Submit **Pull Requests** to contribute code  
3. Join discussions to share ideas or suggestions

## 📄 License

This project is open-sourced under the **MIT License**.  
See the LICENSE file for details.

## ❤️ Support

If this project helps you, please consider giving it a ⭐!

---

**Compatible Version:** Home Assistant 2026.3+
