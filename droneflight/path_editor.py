"""Interactive flight path editor and customizer."""

import json
import zipfile
from io import BytesIO
from typing import List, Tuple, Dict, Any
from droneflight.kmz import parse_kmz


class FlightPathEditor:
    """Edit, customize, and export drone flight paths."""

    def __init__(self, geojson: Dict[str, Any]):
        """Initialize with a GeoJSON linestring."""
        self.geojson = geojson
        self.waypoints = [tuple(c) for c in geojson["coordinates"]]

    def add_waypoint(self, index: int, lat: float, lon: float):
        """Insert a waypoint at a specific position."""
        self.waypoints.insert(index, (lon, lat))
        self._sync_geojson()

    def remove_waypoint(self, index: int):
        """Remove a waypoint by index."""
        if 0 <= index < len(self.waypoints):
            self.waypoints.pop(index)
            self._sync_geojson()

    def move_waypoint(self, index: int, lat: float, lon: float):
        """Move a waypoint to a new location."""
        if 0 <= index < len(self.waypoints):
            self.waypoints[index] = (lon, lat)
            self._sync_geojson()

    def set_altitude(self, index: int, altitude_m: float):
        """Set altitude for a waypoint (stored as 3D coordinate)."""
        if 0 <= index < len(self.waypoints):
            lon, lat = self.waypoints[index]
            # Store as 3D if needed
            self.waypoints[index] = (lon, lat, altitude_m)
            self._sync_geojson()

    def reverse_path(self):
        """Reverse the direction of the flight path."""
        self.waypoints.reverse()
        self._sync_geojson()

    def simplify_path(self, tolerance_meters: float = 50.0):
        """Simplify path by removing points within tolerance (Ramer-Douglas-Peucker)."""
        # Basic implementation - for production use a proper geodesic library

        def perpendicular_distance(point, line_start, line_end):
            """Calculate perpendicular distance from point to line segment."""
            x, y = point[0], point[1]
            x1, y1 = line_start[0], line_start[1]
            x2, y2 = line_end[0], line_end[1]

            if x1 == x2:
                return abs(x - x1)
            if y1 == y2:
                return abs(y - y1)

            num = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1)
            den = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5
            return num / den

        def rdp(points, epsilon):
            """Ramer-Douglas-Peucker algorithm."""
            if len(points) < 3:
                return points

            dmax = 0
            index = 0
            for i in range(1, len(points) - 1):
                d = perpendicular_distance(points[i], points[0], points[-1])
                if d > dmax:
                    dmax = d
                    index = i

            if dmax > epsilon:
                rec1 = rdp(points[: index + 1], epsilon)
                rec2 = rdp(points[index:], epsilon)
                return rec1[:-1] + rec2
            else:
                return [points[0], points[-1]]

        # Convert tolerance from meters to degrees (rough approximation)
        tolerance_deg = tolerance_meters / 111000.0
        self.waypoints = rdp(self.waypoints, tolerance_deg)
        self._sync_geojson()

    def export_kmz(self, filename: str = "flight_path.kmz") -> bytes:
        """Export path as KMZ file."""
        kml = self._generate_kml()
        kmz_buffer = BytesIO()
        with zipfile.ZipFile(kmz_buffer, "w") as z:
            z.writestr("doc.kml", kml)
        kmz_buffer.seek(0)
        return kmz_buffer.getvalue()

    def export_geojson(self) -> Dict[str, Any]:
        """Export path as GeoJSON."""
        return self.geojson.copy()

    def export_csv(self, filename: str = "waypoints.csv") -> str:
        """Export path as CSV for use in flight controllers."""
        csv_lines = ["lon,lat,alt_m,speed_mps"]
        for wp in self.waypoints:
            if len(wp) == 3:
                lon, lat, alt = wp
            else:
                lon, lat = wp
                alt = 50  # Default altitude

            csv_lines.append(f"{lon},{lat},{alt},0")
        return "\n".join(csv_lines)

    def export_obj(self, default_alt: float = 0.0) -> str:
        """Export the current flight path as a simple OBJ 3D model.

        This produces a Wavefront OBJ text string with one object named
        ``flight_path``. Each waypoint becomes a <code>v</code> vertex (lon,
        lat, altitude) and the path is expressed as a single polyline (<code>l</code>).
        The coordinates are treated as x (longitude), y (latitude), and z
        (altitude) in the OBJ space. Missing altitudes are replaced with
        ``default_alt``.
        """
        lines = ["# exported by FlightPathEditor.export_obj", "o flight_path"]
        for wp in self.waypoints:
            if len(wp) == 3:
                lon, lat, alt = wp
            else:
                lon, lat = wp
                alt = default_alt
            lines.append(f"v {lon} {lat} {alt}")
        if len(self.waypoints) > 1:
            idxs = " ".join(str(i + 1) for i in range(len(self.waypoints)))
            lines.append(f"l {idxs}")
        return "\n".join(lines)

    def _sync_geojson(self):
        """Sync waypoints back to GeoJSON."""
        self.geojson["coordinates"] = list(self.waypoints)

    def _generate_kml(self) -> str:
        """Generate KML from waypoints."""
        coords_str = " ".join([f"{lon},{lat},0" for lon, lat in self.waypoints])

        kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Flight Path</name>
      <LineString>
        <coordinates>
{coords_str}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
        return kml

    def get_path_stats(self) -> Dict[str, Any]:
        """Calculate path statistics."""
        if not self.waypoints:
            return {}

        total_distance = 0
        for i in range(1, len(self.waypoints)):
            lon1, lat1 = self.waypoints[i - 1][:2]
            lon2, lat2 = self.waypoints[i][:2]
            # Simple Haversine approximation
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            dist = (dlat**2 + dlon**2) ** 0.5 * 111000  # approx meters
            total_distance += dist

        return {
            "num_waypoints": len(self.waypoints),
            "total_distance_m": total_distance,
            "total_distance_km": total_distance / 1000,
            "waypoints": [
                {"lon": wp[0], "lat": wp[1], "alt": wp[2] if len(wp) > 2 else None}
                for wp in self.waypoints
            ],
        }
