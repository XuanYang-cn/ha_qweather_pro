# Documentation (Usage Guide)

## ⚙️ Configuration

### 1. Obtain QWeather Credentials

Go to the QWeather Console:

- JWT Mode (required by this fork): Add a JSON Web Token credential to your project.
- Obtain the API host (your personal API service address).

### Step 2: Add the Integration in Home Assistant

1. Go to Settings → Devices & Services → Add Integration.
2. Search for and select QWeather Pro.
3. Fill in the following basic information:
   - API server address: `API host`
   - Location: the verified Shanghai city or a coordinate; coordinates are
     quantized before provider lookup.
4. The integration automatically generates a Public Key for JWT authentication:
   - Copy this public key
   - Paste it into the credential settings in the QWeather Console
   - Enter the generated Project ID and Key ID in Home Assistant to complete the binding

### 📈 Frontend Display

The integration does not auto-register the bundled upstream card or custom
more-info UI. Use the repository-owned outdoor weather summary in Home Assistant.

### Fixed first-version data contract

- Current conditions refresh every 10 minutes.
- Hourly forecast, daily forecast, and AQI refresh every 60 minutes.
- Forecasts request 24 hours and 7 days.
- Standard city weather is fixed on; grid weather and minute precipitation are disabled.
- Each core dataset publishes its own provider time, latest-success time,
  update result, and fresh/stale/unavailable state through `dataset_status`.

### 🛠️ Sensor List

## QWeather Entity Description

| **Entity ID** | **Name** | **Description** |
|---------------|----------|-----------------|
| `sensor.qweather_aqi` | Air Quality | Provides AQI value and level (e.g., Excellent / Good / Light Pollution). Attributes include PM2.5, PM10, CO, NO₂, O₃, and other pollutant details |
| `sensor.qweather_precipitation_summary` | Precipitation Summary | Compatibility entity; remains unknown because the first fork version does not call minute precipitation |
| `sensor.qweather_weather_summary` | Weather Summary | 6‑hour weather trend summary, e.g., “Next 6 hours: blowing sand” |
| `sensor.qweather_today_temp_range` | Today’s Temperature Range | Today’s high/low temperature range, e.g., `12°C / 25°C`. Attributes include `min_temp` and `max_temp` |
| `sensor.qweather_warning_count` | Weather Warning Count | Number of active weather alerts (e.g., typhoon, heavy rain, strong wind) |
