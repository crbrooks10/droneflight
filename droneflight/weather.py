"""Weather and radar integration for drone flight planning."""

import requests
import os
from typing import Optional, Dict, Any
from datetime import datetime


class WeatherProvider:
    """Fetch weather data for drone flight planning."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize weather provider with optional API key."""
        self.api_key = api_key or os.getenv("OPENWEATHER_API_KEY")
        self.base_url = "https://api.openweathermap.org/data/2.5"

    def get_current_weather(self, lat: float, lon: float) -> Dict[str, Any]:
        """Get current weather conditions for a location."""
        if not self.api_key:
            return {"error": "OpenWeather API key not configured", "status": "stub"}

        try:
            url = f"{self.base_url}/weather"
            params = {"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"}
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    def get_forecast(
        self, lat: float, lon: float, hours: int = 24
    ) -> Dict[str, Any]:
        """Get hourly forecast for the next N hours."""
        if not self.api_key:
            return {"error": "OpenWeather API key not configured", "status": "stub"}

        try:
            url = f"{self.base_url}/forecast"
            params = {
                "lat": lat,
                "lon": lon,
                "appid": self.api_key,
                "units": "metric",
                "cnt": hours,
            }
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e), "status": "failed"}

    def check_flight_conditions(
        self, lat: float, lon: float, wind_limit_mps: float = 10.0
    ) -> Dict[str, Any]:
        """Check if current conditions are suitable for flight."""
        weather = self.get_current_weather(lat, lon)
        if "error" in weather:
            return weather

        wind_speed = weather.get("wind", {}).get("speed", 0)
        clouds = weather.get("clouds", {}).get("all", 0)  # % coverage
        rain = weather.get("rain", {}).get("1h", 0)  # mm/hour
        visibility = weather.get("visibility", 10000)  # meters
        temp = weather.get("main", {}).get("temp", 0)

        safe = wind_speed <= wind_limit_mps and rain == 0 and visibility > 5000

        return {
            "safe": safe,
            "wind_speed_mps": wind_speed,
            "wind_limit_mps": wind_limit_mps,
            "rain_mm_h": rain,
            "cloud_coverage_pct": clouds,
            "visibility_m": visibility,
            "temp_c": temp,
            "timestamp": datetime.now().isoformat(),
        }


class RadarProvider:
    """Placeholder for radar/airspace integration."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize radar provider with optional base URL."""
        self.base_url = base_url or os.getenv(
            "RADAR_API_URL", "https://api.example.com/radar"
        )

    def get_nearby_activity(self, lat: float, lon: float, radius_nm: float = 5.0):
        """Get nearby aircraft and airspace restrictions."""
        # Placeholder: in production, integrate with ADS-B Exchange, NORAD, or FAA APIs
        return {
            "status": "stub",
            "message": "Connect to real radar/airspace API (ADS-B, NORAD, FAA)",
            "radius_nm": radius_nm,
            "center": {"lat": lat, "lon": lon},
            "nearby_activity": [],
        }

    def check_airspace(self, lat: float, lon: float) -> Dict[str, Any]:
        """Check airspace restrictions (controlled, TFR, etc.)."""
        return {
            "status": "stub",
            "message": "Connect to FAA Airspace API or local aviation database",
            "restricted": False,
            "location": {"lat": lat, "lon": lon},
        }
