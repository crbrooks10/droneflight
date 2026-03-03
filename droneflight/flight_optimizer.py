"""Flight optimization and time recommendation engine."""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
from droneflight.weather import WeatherProvider, RadarProvider


class FlightOptimizer:
    """Suggest optimal launch times based on weather and conditions."""

    def __init__(self):
        """Initialize with weather and radar providers."""
        self.weather = WeatherProvider()
        self.radar = RadarProvider()

    def suggest_launch_times(
        self,
        lat: float,
        lon: float,
        duration_hours: float = 1.0,
        hours_lookahead: int = 24,
        wind_limit_mps: float = 10.0,
    ) -> Dict[str, Any]:
        """Suggest optimal launch window in the next N hours."""
        result = {
            "location": {"lat": lat, "lon": lon},
            "duration_hours": duration_hours,
            "hours_lookahead": hours_lookahead,
            "wind_limit_mps": wind_limit_mps,
            "suggestions": [],
        }

        # Get forecast
        forecast = self.weather.get_forecast(lat, lon, hours=hours_lookahead)
        if "error" in forecast or "list" not in forecast:
            result["error"] = "Could not fetch forecast"
            return result

        # Score each hour
        best_windows = []
        for item in forecast["list"]:
            timestamp = item["dt"]
            dt = datetime.fromtimestamp(timestamp)
            wind_speed = item.get("wind", {}).get("speed", 0)
            rain = item.get("rain", {}).get("1h", 0)
            clouds = item.get("clouds", {}).get("all", 100)

            # Simple score: lower is better
            # Factors: wind speed, rain, clouds
            score = (
                (wind_speed / wind_limit_mps) * 100
                + (rain * 50)
                + (clouds / 2)
            )

            best_windows.append(
                {
                    "timestamp": dt.isoformat(),
                    "score": score,
                    "wind_mps": wind_speed,
                    "rain_mm": rain,
                    "cloud_pct": clouds,
                }
            )

        # Sort by score and find windows
        best_windows.sort(key=lambda x: x["score"])
        result["suggestions"] = best_windows[:5]  # Top 5
        return result

    def rate_flight_path(
        self, lat: float, lon: float, waypoints: List[Tuple[float, float]]
    ) -> Dict[str, Any]:
        """Rate a flight path based on weather and terrain complexity."""
        # Simple scoring: average conditions along the path
        scores = []
        for wp_lat, wp_lon in waypoints:
            conditions = self.weather.check_flight_conditions(wp_lat, wp_lon)
            if not conditions.get("error"):
                score = 0
                if conditions["safe"]:
                    score += 50
                score += (
                    max(0, 30 - conditions["wind_speed_mps"] * 2)
                )  # Penalize high wind
                scores.append(score)

        avg_score = sum(scores) / len(scores) if scores else 0

        return {
            "path_rating": avg_score,
            "max_score": 100,
            "waypoint_scores": scores,
            "recommendation": "Good to fly"
            if avg_score > 60
            else ("Marginal conditions" if avg_score > 30 else "Not recommended"),
        }
