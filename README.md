<div align="right">
  <strong>English</strong> | <a href="./README_CN.md">中文版</a>
</div>

# <img src="custom_components/qweather_pro/brand/icon.png" width="64"> QWeather Pro for Home Assistant

> This branch belongs to the `XuanYang-cn` personal maintenance fork. Its first
> audited baseline is upstream `v1.1.6` at
> `9232254cf7dd56c72aefb23b425a4dd29bab1f4e`; see
> [docs/MAINTENANCE.md](docs/MAINTENANCE.md) before installing or upgrading.

[![Release](https://img.shields.io/github/v/release/XuanYang-cn/ha_qweather_pro)](https://github.com/XuanYang-cn/ha_qweather_pro/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/XuanYang-cn/ha_qweather_pro/blob/main/LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![](https://komarev.com/ghpvc/?username=XuanYang-cn&color=ff69b4)

## A maintained QWeather data integration for Home Assistant.

This personal fork focuses on trustworthy provider data and stable Home Assistant
entities. Dashboard and detail UI are owned by the separate Home Assistant
operations repository rather than auto-registered by this integration.
Its first version is limited to one configured household; setup verifies that
the privacy-quantized location remains in the configured warning jurisdiction.

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
- Retired upstream card and custom more-info files are not packaged or registered.
  - Repository-owned Lovelace UI consumes the integration entities instead.

- 🔄 **Latest Standards**  
  - Compatible with Home Assistant 2026.3+ and its WebSocket forecast subscription.

## 🌏 Configured-household scope and localization

This initial personal fork is not a worldwide integration. It supports the
verified location configured for this household and shows provider data
in Home Assistant's selected language where QWeather supplies it.

- **Automatic language sync**: The integration requests data in Home Assistant's
  configured language where the provider supports it.
- **Localized title**: During setup, the verified configured location name becomes
  the config-entry title.

## 📦 Installation

### Install via HACS (Recommended)

1. HACS installs only tagged releases; the current candidate is the [latest tagged release](https://github.com/XuanYang-cn/ha_qweather_pro/releases/latest).
2. In HACS → “Integrations”, click the three-dot menu.
3. Select **“Custom repositories”**.
4. Enter the repository address HACS uses to discover its tagged releases:
```yaml
https://github.com/XuanYang-cn/ha_qweather_pro
```
5. Choose category **Integration**.
6. Click **Add**, install **QWeather Pro** from HACS, and restart Home Assistant.

### Manual Installation

1. Download the [latest tagged release](https://github.com/XuanYang-cn/ha_qweather_pro/releases/latest).
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
