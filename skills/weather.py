"""
Javris Weather Skill — Multi-Source
─────────────────────────────────────
Sources (in priority order):
  1. OpenWeatherMap  — full data, keyed
  2. Open-Meteo      — free fallback, no key, always available
  3. AQICN           — air quality layer (added to OWM result)

10-minute TTL cache + 3 retries.
Registered as both "weather" and "get_weather" for compat.
"""

from __future__ import annotations

import httpx
from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger
from core.retry import resilient, with_retry

logger = get_logger("javris.skill.weather")
cfg = get_config()

OWM_URL = "https://api.openweathermap.org/data/2.5"


class WeatherSkill(BaseSkill):
    name = "weather"
    aliases = ["get_weather"]
    description = "Get current weather, forecast, and air quality for a location"

    tool_definition = {
        "name": "get_weather",
        "description": (
            "Get current weather conditions, forecast, and air quality "
            "for any city or location."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name, 'lat,lon' coordinates, or 'current location'",
                },
                "units": {
                    "type": "string",
                    "enum": ["metric", "imperial"],
                    "default": "metric",
                    "description": "Temperature units",
                },
                "forecast_days": {
                    "type": "integer",
                    "description": "Number of forecast days (0 = current only, max 5)",
                    "default": 0,
                },
                "include_aqi": {
                    "type": "boolean",
                    "description": "Include air quality index data",
                    "default": True,
                },
            },
            "required": ["location"],
        },
    }

    @resilient(ttl=600, max_retries=3, base_delay=1.0, max_delay=15.0)
    async def run(
        self,
        location: str,
        units: str = "metric",
        forecast_days: int = 0,
        include_aqi: bool = True,
        **_,
    ) -> dict:
        unit_sym = "°C" if units == "metric" else "°F"

        # ── 1. OpenWeatherMap ──────────────────────────────────
        if cfg.weather_api_key:
            result = await self._owm(location, units, unit_sym, forecast_days)
        else:
            # ── 2. Open-Meteo (free, no key) ──────────────────
            result = await self._open_meteo(location, unit_sym)

        if not result or "error" in result:
            return result or {"error": f"Could not fetch weather for '{location}'"}

        # ── 3. Air quality (AQICN overlay) ────────────────────
        if include_aqi and cfg.aqicn_api_key:
            aqi = await self._aqi(location)
            if aqi:
                result["air_quality"] = aqi

        return result

    # ── Source: OpenWeatherMap ──────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _owm(self, location: str, units: str, unit_sym: str, forecast_days: int) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{OWM_URL}/weather",
                    params={"q": location, "units": units, "appid": cfg.weather_api_key},
                )
                if r.status_code != 200:
                    logger.warning(f"OWM failed ({r.status_code}) for {location!r}")
                    return {}

                data = r.json()
                result: dict = {
                    "source": "OpenWeatherMap",
                    "current": {
                        "location":    f"{data['name']}, {data['sys']['country']}",
                        "temp":        f"{data['main']['temp']}{unit_sym}",
                        "feels_like":  f"{data['main']['feels_like']}{unit_sym}",
                        "humidity":    f"{data['main']['humidity']}%",
                        "description": data["weather"][0]["description"].capitalize(),
                        "wind_speed":  f"{data['wind']['speed']} m/s",
                        "visibility":  f"{data.get('visibility', 'N/A')} m",
                        "pressure":    f"{data['main']['pressure']} hPa",
                        "icon":        data["weather"][0].get("icon", ""),
                        "lat":         data["coord"]["lat"],
                        "lon":         data["coord"]["lon"],
                    },
                }

                if forecast_days > 0:
                    fr = await client.get(
                        f"{OWM_URL}/forecast",
                        params={"q": location, "units": units,
                                "cnt": forecast_days * 8, "appid": cfg.weather_api_key},
                    )
                    if fr.status_code == 200:
                        daily: dict[str, dict] = {}
                        for item in fr.json()["list"]:
                            day = item["dt_txt"][:10]
                            if day not in daily:
                                daily[day] = {
                                    "date":        day,
                                    "temp_min":    item["main"]["temp_min"],
                                    "temp_max":    item["main"]["temp_max"],
                                    "description": item["weather"][0]["description"].capitalize(),
                                    "icon":        item["weather"][0].get("icon", ""),
                                }
                            else:
                                daily[day]["temp_min"] = min(daily[day]["temp_min"], item["main"]["temp_min"])
                                daily[day]["temp_max"] = max(daily[day]["temp_max"], item["main"]["temp_max"])
                        result["forecast"] = list(daily.values())[:forecast_days]

                return result
        except Exception as e:
            logger.debug(f"OWM exception: {e}")
            return {}

    # ── Source: Open-Meteo (no API key) ────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _open_meteo(self, location: str, unit_sym: str) -> dict:
        """Geocode via nominatim then fetch from Open-Meteo."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Geocode
                geo = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": location, "format": "json", "limit": 1},
                    headers={"User-Agent": "Javris/3.0"},
                )
                if geo.status_code != 200 or not geo.json():
                    return {"error": f"Location '{location}' not found"}

                geo_data = geo.json()[0]
                lat  = float(geo_data["lat"])
                lon  = float(geo_data["lon"])
                name = geo_data.get("display_name", location).split(",")[0]

                # Fetch weather
                r = await client.get(
                    f"{cfg.open_meteo_base_url}/forecast",
                    params={
                        "latitude": lat, "longitude": lon,
                        "current_weather": True,
                        "hourly": "relativehumidity_2m,precipitation_probability",
                        "forecast_days": 1,
                        "timezone": "auto",
                    },
                )
                if r.status_code != 200:
                    return {}

                data = r.json()
                cw   = data.get("current_weather", {})
                return {
                    "source": "Open-Meteo",
                    "current": {
                        "location":    name,
                        "temp":        f"{cw.get('temperature', '?')}{unit_sym}",
                        "feels_like":  f"{cw.get('apparent_temperature', cw.get('temperature', '?'))}{unit_sym}",
                        "humidity":    "N/A",
                        "description": _wmo_code(cw.get("weathercode", 0)),
                        "wind_speed":  f"{cw.get('windspeed', '?')} km/h",
                        "visibility":  "N/A",
                        "pressure":    "N/A",
                        "icon":        "",
                        "lat": lat, "lon": lon,
                    },
                }
        except Exception as e:
            logger.debug(f"Open-Meteo exception: {e}")
            return {}

    # ── Source: AQICN air quality ───────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _aqi(self, location: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(
                    f"{cfg.aqicn_base_url}/feed/{location}/",
                    params={"token": cfg.aqicn_api_key},
                )
                if r.status_code == 200:
                    d = r.json()
                    if d.get("status") == "ok":
                        aqi_val = d["data"].get("aqi", "N/A")
                        level = _aqi_level(aqi_val)
                        return {
                            "aqi":   aqi_val,
                            "level": level,
                            "city":  d["data"].get("city", {}).get("name", location),
                        }
        except Exception as e:
            logger.debug(f"AQICN exception: {e}")
        return None


def _wmo_code(code: int) -> str:
    """Translate WMO weather interpretation codes to text."""
    table = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Depositing rime fog",
        51: "Light drizzle", 61: "Slight rain", 71: "Slight snow fall",
        80: "Slight rain showers", 95: "Thunderstorm",
    }
    return table.get(code, f"Weather code {code}")


def _aqi_level(aqi) -> str:
    try:
        v = int(aqi)
        if v <= 50:   return "Good"
        if v <= 100:  return "Moderate"
        if v <= 150:  return "Unhealthy for sensitive groups"
        if v <= 200:  return "Unhealthy"
        if v <= 300:  return "Very Unhealthy"
        return "Hazardous"
    except Exception:
        return "Unknown"
