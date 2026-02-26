#!/usr/bin/env python3
"""
DroneFlight Planner CLI — Complete pre-flight planning tool.

Usage:
  python flight_planner.py <kmz_file> --lat 37.0 --lon -122.0 [options]

Features:
  - Upload and parse KMZ files
  - Check weather conditions
  - Suggest optimal launch times
  - Customize flight paths
  - Rate flight safety
  - Export to multiple formats
"""

import argparse
import json
import sys
from pathlib import Path

from droneflight.kmz import parse_kmz
from droneflight.path_editor import FlightPathEditor
from droneflight.flight_optimizer import FlightOptimizer
from droneflight.weather import WeatherProvider


def main():
    parser = argparse.ArgumentParser(
        description="DroneFlight Planner — Pre-flight operations assistant"
    )
    parser.add_argument("kmz_file", help="Path to KMZ file")
    parser.add_argument("--lat", type=float, required=True, help="Flight area latitude")
    parser.add_argument("--lon", type=float, required=True, help="Flight area longitude")
    parser.add_argument(
        "--wind-limit", type=float, default=10.0, help="Max wind speed (m/s)"
    )
    parser.add_argument(
        "--lookahead", type=int, default=24, help="Hours to look ahead for weather"
    )
    parser.add_argument(
        "--export-kmz", help="Export modified path to KMZ file"
    )
    parser.add_argument(
        "--export-csv", help="Export waypoints to CSV file"
    )
    parser.add_argument(
        "--simplify", type=float, help="Simplify path (tolerance in meters)"
    )
    parser.add_argument(
        "--reverse", action="store_true", help="Reverse flight direction"
    )
    parser.add_argument(
        "--check-weather", action="store_true", help="Check current weather conditions"
    )
    parser.add_argument(
        "--suggest-times", action="store_true", help="Suggest optimal launch times"
    )

    args = parser.parse_args()

    # Load KMZ
    try:
        kmz_path = Path(args.kmz_file)
        if not kmz_path.exists():
            print(f"Error: File not found: {args.kmz_file}")
            sys.exit(1)

        with open(kmz_path, "rb") as f:
            geojson = parse_kmz(f.read())
        print(f"✓ Loaded KMZ: {kmz_path.name}")
    except Exception as e:
        print(f"Error parsing KMZ: {e}")
        sys.exit(1)

    # Initialize tools
    editor = FlightPathEditor(geojson)
    optimizer = FlightOptimizer()
    weather = WeatherProvider()

    print(f"✓ Loaded flight path with {editor.get_path_stats()['num_waypoints']} waypoints")

    # Check weather
    if args.check_weather:
        print("\n--- Current Weather Conditions ---")
        conditions = weather.check_flight_conditions(args.lat, args.lon, args.wind_limit)
        if "error" not in conditions:
            print(f"Safe to fly: {conditions['safe']}")
            print(f"Wind: {conditions['wind_speed_mps']:.1f} m/s (limit: {conditions['wind_limit_mps']:.1f})")
            print(f"Rain: {conditions['rain_mm_h']:.1f} mm/h")
            print(f"Cloud cover: {conditions['cloud_coverage_pct']}%")
            print(f"Visibility: {conditions['visibility_m']/1000:.1f} km")
            print(f"Temperature: {conditions['temp_c']:.1f}°C")
        else:
            print(f"Weather check failed: {conditions.get('error')}")

    # Suggest launch times
    if args.suggest_times:
        print("\n--- Suggested Launch Times ---")
        suggestions = optimizer.suggest_launch_times(
            args.lat,
            args.lon,
            duration_hours=1.0,
            hours_lookahead=args.lookahead,
            wind_limit_mps=args.wind_limit,
        )
        if "suggestions" in suggestions and suggestions["suggestions"]:
            for i, sug in enumerate(suggestions["suggestions"][:3], 1):
                print(f"{i}. {sug['timestamp']} (score: {sug['score']:.1f})")
                print(f"   Wind: {sug['wind_mps']:.1f} m/s")
                print(f"   Rain: {sug['rain_mm']:.1f} mm")
                print(f"   Clouds: {sug['cloud_pct']}%")
        else:
            print("No suggestions available")

    # Path operations
    if args.simplify:
        print(f"\n✓ Simplifying path (tolerance: {args.simplify}m)...")
        editor.simplify_path(args.simplify)

    if args.reverse:
        print("\n✓ Reversing flight direction...")
        editor.reverse_path()

    # Rate path
    print("\n--- Path Rating ---")
    path_stats = editor.get_path_stats()
    print(f"Waypoints: {path_stats['num_waypoints']}")
    print(f"Total distance: {path_stats['total_distance_km']:.2f} km")

    rating = optimizer.rate_flight_path(args.lat, args.lon, 
                                        [(wp["lat"], wp["lon"]) for wp in path_stats["waypoints"]])
    print(f"Path rating: {rating['path_rating']:.1f}/100")
    print(f"Recommendation: {rating['recommendation']}")

    # Export
    if args.export_kmz:
        kmz_data = editor.export_kmz()
        with open(args.export_kmz, "wb") as f:
            f.write(kmz_data)
        print(f"\n✓ Exported KMZ: {args.export_kmz}")

    if args.export_csv:
        csv_data = editor.export_csv()
        with open(args.export_csv, "w") as f:
            f.write(csv_data)
        print(f"✓ Exported CSV: {args.export_csv}")

    print("\n✓ Flight planning complete!")


if __name__ == "__main__":
    main()
