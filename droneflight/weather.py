# ---------------------------------------------------------------------------
# Weather API Integration
# ---------------------------------------------------------------------------

import requests
import datetime
from typing import Dict
import streamlit as st

def get_aviation_weather(lat: float, lon: float) -> Dict:
    """Fetch aviation weather data for given coordinates."""
    try:
        # Using OpenWeatherMap API (free tier available)
        # In production, you'd want to use aviation-specific APIs like Aviation Weather Center
        api_key = st.secrets.get("OPENWEATHER_API_KEY", "demo_key")
        
        # Current weather
        weather_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        
        # Forecast
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric"
        
        weather_response = requests.get(weather_url, timeout=10)
        forecast_response = requests.get(forecast_url, timeout=10)
        
        if weather_response.status_code == 200 and forecast_response.status_code == 200:
            weather_data = weather_response.json()
            forecast_data = forecast_response.json()
            
            return {
                "current": {
                    "temperature": weather_data["main"]["temp"],
                    "humidity": weather_data["main"]["humidity"],
                    "pressure": weather_data["main"]["pressure"],
                    "wind_speed": weather_data["wind"]["speed"],
                    "wind_direction": weather_data["wind"].get("deg", 0),
                    "visibility": weather_data.get("visibility", 10000) / 1000,  # Convert to km
                    "clouds": weather_data.get("clouds", {}).get("all", 0),
                    "conditions": weather_data["weather"][0]["description"].title(),
                    "timestamp": datetime.datetime.now().strftime("%H:%M UTC")
                },
                "forecast": [
                    {
                        "time": datetime.datetime.fromtimestamp(item["dt"]).strftime("%H:%M"),
                        "temp": item["main"]["temp"],
                        "wind_speed": item["wind"]["speed"],
                        "conditions": item["weather"][0]["description"].title(),
                        "clouds": item.get("clouds", {}).get("all", 0)
                    }
                    for item in forecast_data["list"][:8]  # Next 8 intervals (24 hours)
                ]
            }
        else:
            return {"error": "Weather data unavailable"}
            
    except Exception as e:
        return {"error": f"Weather API error: {str(e)}"}

def display_weather_panel(weather_data: Dict, lat: float, lon: float):
    """Display weather information in a formatted panel."""
    if "error" in weather_data:
        st.error(f"❌ {weather_data['error']}")
        return
    
    current = weather_data["current"]
    
    st.markdown("### 🌤️ Current Weather")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Temperature", f"{current['temperature']:.1f}°C")
        st.metric("Conditions", current["conditions"])
    
    with col2:
        st.metric("Wind", f"{current['wind_speed']:.1f} m/s @ {current['wind_direction']}°")
        st.metric("Visibility", f"{current['visibility']:.1f} km")
    
    with col3:
        st.metric("Pressure", f"{current['pressure']:.0f} hPa")
        st.metric("Humidity", f"{current['humidity']}%")
    
    st.markdown("### 📈 24-Hour Forecast")
    forecast_df = []
    for item in weather_data["forecast"]:
        forecast_df.append({
            "Time": item["time"],
            "Temp (°C)": f"{item['temp']:.1f}",
            "Wind (m/s)": f"{item['wind_speed']:.1f}",
            "Conditions": item["conditions"],
            "Clouds (%)": item["clouds"]
        })
    
    st.dataframe(forecast_df, use_container_width=True, hide_index=True)
    
    st.caption(f"📍 Location: {lat:.4f}, {lon:.4f} | Updated: {current['timestamp']}")