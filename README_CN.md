<div align="right">
  <a href="./README.md">English Version</a> | <strong>中文版</strong>
</div>

# <img src="custom_components/qweather_pro/brand/icon.png" width="64"> 和风天气Pro (QWeather Pro)

> 当前分支属于 `XuanYang-cn` 个人维护 fork。首个审计基线是上游
> `v1.1.6` / `9232254cf7dd56c72aefb23b425a4dd29bab1f4e`；安装或升级前请先阅读
> [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。

[![Release](https://img.shields.io/github/v/release/XuanYang-cn/ha_qweather_pro)](https://github.com/XuanYang-cn/ha_qweather_pro/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/XuanYang-cn/ha_qweather_pro/blob/main/LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![](https://komarev.com/ghpvc/?username=XuanYang-cn&color=ff69b4)

## 面向 Home Assistant 的可维护和风天气数据集成

个人 fork 聚焦可信的提供方数据和稳定的 Home Assistant 实体；仪表盘与详情 UI
由独立的 Home Assistant 运维仓库负责，本集成不再自动注册上游前端。第一版仅服务于
一个上海住宅；设置时会确认隐私量化后的坐标仍在上海气象预警辖区内。

## ✨ 核心特性

- 🛡️ 安全先行：支持和风天气最新的 JWT (EdDSA) 认证，本地自动生成 Ed25519 密钥对，保护您的 API 额度不被盗用。
- ⚡ 极致性能：
  - 后端：采用 DataUpdateCoordinator 并发请求机制，智能缓存，最大限度节省免费版 API 额度。
  - 前端：不向 Home Assistant 注入集成自有 JavaScript。
- 📊 提供方数据：
  - 标准城市当前天气、逐小时和逐日预报、AQI 与本地气象预警。
  - 坐标先量化到约 5 公里精度，再验证仍属于所选气象预警辖区。
  - 第一版关闭分钟降雨和格点天气调用。
- 🎨 纯数据前端合同：
  - 不自动注册上游天气卡与 custom more-info。
  - 仓库自有 Lovelace UI 通过集成实体读取数据。
- 🔄 最新标准：兼容 HA 2026.3+ 及其 WebSocket 预报订阅机制。

## 🌏 上海范围与本地化

此初始个人 fork 并非面向全球使用；它只支持为本住宅验证过的上海位置，并在和风天气
提供相应语言时按 Home Assistant 的系统语言展示数据。

- **自动同步系统语言**：集成在提供方支持时，按 Home Assistant 的系统语言请求数据。
- **本地化标题**：安装时，已经验证的上海位置名称会作为配置条目标题。

## 📦 安装

### 通过HACS安装（推荐）

1. HACS 只安装已发布标签；当前候选为[最新已发布标签](https://github.com/XuanYang-cn/ha_qweather_pro/releases/latest)。
2. 在HACS的"集成"部分，点击右上角的三点菜单
3. 选择"自定义存储库"
4. 在存储库字段输入 HACS 用于发现已发布标签的地址：
```yaml
https://github.com/XuanYang-cn/ha_qweather_pro
```
5. 类别选择"集成"
6. 点击"添加"，在 HACS 安装"和风天气Pro"后重启 Home Assistant

### 手动安装

1. 下载[最新已发布标签](https://github.com/XuanYang-cn/ha_qweather_pro/releases/latest)。
2. 解压并将`custom_components/qweather_pro`文件夹放入Home Assistant的`custom_components`目录
3. 重启Home Assistant

## 📖 文档导航
- [🚀 详细配置与使用教程 (DOCS.md)](md/DOCS_CN.md)
- [📜 版本更新历史 (CHANGELOG.md)](md/CHANGELOG_CN.md)

## 特别感谢： 本次更新由 AI 协助完成架构优化，并基于原版 [dscao/qweather](https://github.com/dscao/qweather) 进行了深度重构。

## 📜 声明

- 本项目与和风天气官方无直接隶属关系。
- 气象数据由 和风天气 (QWeather) 提供。
- 请遵守和风天气的 API 使用协议。

## 🤝 贡献

欢迎贡献代码、报告问题或提出功能建议！

1. 提交Issues：报告问题或功能请求
2. 提交Pull Requests：贡献代码改进
3. 项目讨论：分享使用经验或建议

## 📄 许可证

本项目基于MIT许可证开源。详情请查看LICENSE文件。

## ❤️ 支持

如果这个项目对您有帮助，请给项目点个Star ⭐！

---
**兼容版本**: Home Assistant 2026.3+
