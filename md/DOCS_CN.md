# 使用指南 (Documentation)

## ⚙️ 配置

### 1. 获取和风天气凭据

前往 和风天气控制台：

- JWT 模式（个人 fork 必需）：在项目中添加 JSON Web Token 凭据。
- 获取 API host。 （个人 API服务地址）

### 步骤2：在Home Assistant中添加集成

1. 进入 配置 -> 设备与服务 -> 添加集成。
2. 搜索并选择 QWeather Pro。
3. 在配置界面填写以下基础信息:
     - API 服务器地址 `API host`。
     - 已验证的上海城市或坐标；坐标会在查询提供方前量化。
4. 集成会自动为 JWT 认证生成一段公钥 (Public Key)：
    - 复制该公钥。
    - 粘贴到和风天气控制台的凭据设置中。
    - 在 HA 中填入生成的 Project ID 和 Key ID 即可完成绑定。

### 📈 前端展示

本集成不自动注册上游天气卡或 custom more-info；请使用 Home Assistant
运维仓库自有的户外天气摘要。

### 第一版固定数据合同

- 当前天气每 10 分钟刷新。
- 逐小时预报、逐日预报与 AQI 每 60 分钟刷新。
- 预报固定请求 24 小时和 7 天。
- 第一版固定使用标准城市天气，并关闭格点天气和分钟级降水调用。
- 每个核心数据集通过 `dataset_status` 公开各自的提供方时间、最近成功时间、
  最近更新结果及新鲜/陈旧/不可用状态。

### 🛠️ 传感器列表

## 和风天气实体说明

| **实体 ID** | **名称** | **说明** |
|-------------|----------|----------|
| `sensor.qweather_aqi` | 空气质量 | 提供 AQI 数值与等级（如：优 / 良 / 轻度污染），属性包含 PM2.5、PM10、CO、NO₂、O₃ 等详细污染物数据 |
| `sensor.qweather_precipitation_summary` | 降水简报 | 兼容实体；第一版不调用分钟接口，因此保持未知 |
| `sensor.qweather_weather_summary` | 天气概况 | 未来 6 小时天气趋势总结，例如“未来 6 小时：扬沙” |
| `sensor.qweather_today_temp_range` | 今日温度范围 | 今日最高/最低温度范围，格式如 `12°C / 25°C`，属性包含 `min_temp` 与 `max_temp` |
| `sensor.qweather_warning_count` | 气象预警数量 | 当前生效中的气象预警数量（如台风、暴雨、大风等） |
