#!/usr/bin/env python3
"""
Example: Using DroneFlight modules programmatically.

This demonstrates how to:
1. Load a KMZ file
2. Check weather conditions
3. Get flight time suggestions
4. Customize the flight path
5. Export to multiple formats
"""

from droneflight.kmz import parse_kmz
from droneflight.weather import WeatherProvider
from droneflight.flight_optimizer import FlightOptimizer
from droneflight.path_editor import FlightPathEditor

# Example flight area: San Francisco Bay
LAT, LON = 37.7749, -122.4194


def main():
    print("=" * 60)
    print("DroneFlight Planning Example")
    print("=" * 60)

    # Step 1: Check weather
    print("\n1. Checking Weather Conditions...")
    weather = WeatherProvider()
    conditions = weather.check_flight_conditions(LAT, LON, wind_limit_mps=10.0)

    if "error" in conditions:
        print(f"   ⚠ {conditions['error']}")
    else:
        print(f"   ✓ Safe: {conditions['safe']}")
        print(f"   • Wind: {conditions['wind_speed_mps']:.1f} m/s")
        print(f"   • Rain: {conditions['rain_mm_h']:.1f} mm/h")
        print(f"   • Clouds: {conditions['cloud_coverage_pct']}%")
        print(f"   • Visibility: {conditions['visibility_m'] / 1000:.1f} km")

    # Step 2: Get launch time suggestions
    print("\n2. Suggesting Optimal Launch Times...")
    optimizer = FlightOptimizer()
    suggestions = optimizer.suggest_launch_times(
        LAT, LON, hours_lookahead=24, wind_limit_mps=10.0
    )

    if "error" in suggestions:
        print(f"   ⚠ {suggestions['error']}")
    elif suggestions.get("suggestions"):
        print("   Top 3 recommended launch windows:")
        for i, sug in enumerate(suggestions["suggestions"][:3], 1):
            print(f"   {i}. {sug['timestamp']}")
            print(f"      • Score: {sug['score']:.1f}")
            print(f"      • Wind: {sug['wind_mps']:.1f} m/s")
    else:
        print("   ⚠ No suggestions available yet")

    # Step 3: Create and edit a sample flight path
    print("\n3. Creating Flight Path...")
    # Create a simple circular path
    sample_geojson = {
        "type": "LineString",
        "coordinates": [
            [-122.42, 37.77],
            [-122.41, 37.77],
            [-122.41, 37.78],
            [-122.42, 37.78],
            [-122.42, 37.77],
        ],
    }

    editor = FlightPathEditor(sample_geojson)
    stats = editor.get_path_stats()
    print(f"   ✓ Created path with {stats['num_waypoints']} waypoints")
    print(f"   • Distance: {stats['total_distance_km']:.2f} km")

    # Step 4: Customize the path
    print("\n4. Customizing Path...")
    print("   • Adding waypoint...")
    editor.add_waypoint(2, 37.775, -122.415)

    print("   • Simplifying path...")
    editor.simplify_path(tolerance_meters=100)

    updated_stats = editor.get_path_stats()
    print(f"   ✓ Updated path: {updated_stats['num_waypoints']} waypoints")

    # Step 5: Rate the flight path
    print("\n5. Rating Flight Path...")
    rating = optimizer.rate_flight_path(
        LAT,
        LON,
        [(wp["lat"], wp["lon"]) for wp in updated_stats["waypoints"]],
    )
    print(f"   ✓ Path Rating: {rating['path_rating']:.1f}/100")
    print(f"   • Recommendation: {rating['recommendation']}")

    # Step 6: Export
    print("\n6. Exporting...")
    print("   • GeoJSON: available via .export_geojson()")
    geojson = editor.export_geojson()
    print(f"     Coordinates: {len(geojson['coordinates'])} points")

    print("   • CSV: available via .export_csv()")
    csv_data = editor.export_csv()
    print(f"     Lines: {len(csv_data.splitlines())}")

    print("   • KMZ: available via .export_kmz()")
    kmz_data = editor.export_kmz()
    print(f"     Size: {len(kmz_data)} bytes")

    print("\n" + "=" * 60)
    print("Example Complete!")
    print("=" * 60)
    print("\nFor API key setup:")
    print("  1. Get OpenWeather API key: https://openweathermap.org/api")
    print("  2. Copy config.example.env to .env")
    print("  3. Add your key to OPENWEATHER_API_KEY")
    print("  4. Run again to see real weather data")


if __name__ == "__main__":
    main()
