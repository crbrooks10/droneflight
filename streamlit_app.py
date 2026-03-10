import json
import zipfile
import io
import math
import re
import streamlit as st
from streamlit.components.v1 import html as components_html

# ---------------------------------------------------------------------------
# Phase 1 — Structured KMZ / KML parser
# Preserves: named segments, per-waypoint altitude, route order
# ---------------------------------------------------------------------------

def _get_text(el_text: str) -> str:
    return el_text.strip() if el_text else ""

def _parse_coords_block(block: str) -> list:
    """Parse a raw <coordinates> text block into [[lon, lat, alt], ...]."""
    pts = []
    for token in block.strip().split():
        token = token.strip()
        if not token:
            continue
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
            pts.append([lon, lat, alt])
        except ValueError:
            pass
    return pts


def _parse_kml_structured(kml_text: str) -> list:
    """
    Parse KML and return a list of named segments:
      [{"name": str, "coords": [[lon, lat, alt], ...]}, ...]

    Handles:
      - Named Placemarks with LineString / Polygon / MultiGeometry
      - Point clusters (grouped into one segment if no lines found)
      - Flat coordinate dumps (single unnamed segment fallback)
    """
    segments = []

    # --- Find all Placemarks -------------------------------------------------
    placemark_blocks = re.findall(
        r"<Placemark\b[^>]*>(.*?)</Placemark>",
        kml_text,
        re.DOTALL | re.IGNORECASE,
    )

    point_coords = []  # collect stray points

    for i, block in enumerate(placemark_blocks):
        # Extract name
        name_match = re.search(r"<n(?:ame)?[^>]*>(.*?)</n(?:ame)?>", block, re.DOTALL | re.IGNORECASE)
        name = _get_text(name_match.group(1)) if name_match else f"Waypoint {i + 1}"
        # strip CDATA
        name = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", name).strip()

        # Gather all coordinate blocks inside this placemark
        coord_blocks = re.findall(
            r"<coordinates[^>]*>(.*?)</coordinates>",
            block,
            re.DOTALL | re.IGNORECASE,
        )

        # Detect geometry type to decide how to group
        has_line = bool(re.search(r"<LineString|<Polygon|<MultiGeometry", block, re.IGNORECASE))
        has_point = bool(re.search(r"<Point\b", block, re.IGNORECASE))

        for cb in coord_blocks:
            pts = _parse_coords_block(cb)
            if not pts:
                continue
            if has_point and not has_line and len(pts) == 1:
                # Single point placemark — collect for grouping
                point_coords.append({"name": name, "pt": pts[0]})
            elif pts:
                segments.append({"name": name, "coords": pts})

    # Group any stray Point placemarks into the segment list as individual entries
    for pc in point_coords:
        segments.append({"name": pc["name"], "coords": [pc["pt"]]})

    # --- Fallback: no Placemarks, parse raw coordinate blocks ----------------
    if not segments:
        all_blocks = re.findall(
            r"<coordinates[^>]*>(.*?)</coordinates>",
            kml_text,
            re.DOTALL | re.IGNORECASE,
        )
        for i, cb in enumerate(all_blocks):
            pts = _parse_coords_block(cb)
            if len(pts) >= 1:
                segments.append({"name": f"Route {i + 1}", "coords": pts})

    return segments


def parse_kmz_structured(raw_bytes: bytes) -> list:
    """
    Unzip a KMZ and return structured segments from all KML files inside.
    Returns: [{"name": str, "coords": [[lon, lat, alt], ...]}, ...]
    """
    segments = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError("No .kml files found inside KMZ archive.")
            for name in kml_names:
                kml_text = z.read(name).decode("utf-8", errors="replace")
                segs = _parse_kml_structured(kml_text)
                segments.extend(segs)
    except zipfile.BadZipFile:
        raise ValueError("File is not a valid KMZ/ZIP archive.")
    except Exception as e:
        raise ValueError(f"Could not read KMZ: {e}") from e

    if not segments:
        raise ValueError("No coordinate data found in KMZ file.")

    return segments


def parse_kml_file(raw_bytes: bytes) -> list:
    """Parse a raw KML file and return structured segments."""
    kml_text = raw_bytes.decode("utf-8", errors="replace")
    segments = _parse_kml_structured(kml_text)
    if not segments:
        raise ValueError("No coordinate data found in KML file.")
    return segments


def segments_to_flat(segments: list) -> list:
    """Flatten segments back to [[lon, lat, alt], ...] for globe rendering."""
    flat = []
    for seg in segments:
        flat.extend(seg["coords"])
    return flat


def haversine_km(lon1, lat1, lon2, lat2) -> float:
    """Great-circle distance in km between two lon/lat points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def route_stats(segments: list) -> dict:
    """Compute total distance (km) and waypoint count."""
    total_km = 0.0
    total_pts = 0
    prev = None
    for seg in segments:
        for pt in seg["coords"]:
            total_pts += 1
            if prev:
                total_km += haversine_km(prev[0], prev[1], pt[0], pt[1])
            prev = pt
    return {"total_km": total_km, "total_pts": total_pts}


# ---------------------------------------------------------------------------
# Phase 2 — Cesium HTML with live editable flight plan panel
# ---------------------------------------------------------------------------


import base64 as _b64


def _build_cesium_html(segments_json_str: str) -> str:
    """Return self-contained Cesium HTML with flight segments injected.

    The HTML template is base64-encoded below to avoid any triple-quote or
    f-string ambiguity that caused previous deployment failures on Streamlit Cloud.
    To read the template: base64.b64decode(_CESIUM_TEMPLATE_B64).decode("utf-8")
    """
    html = _b64.b64decode(_CESIUM_TEMPLATE_B64).decode("utf-8")
    return html.replace("@@SEGMENTS_JSON@@", segments_json_str)


# ---------------------------------------------------------------------------
# Cesium HTML template — base64-encoded plain string.
# Original template uses @@SEGMENTS_JSON@@ as the single injection point.
# ---------------------------------------------------------------------------
_CESIUM_TEMPLATE_B64 = (
    "PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9ImVuIj4KPGhlYWQ+CiAgPG1ldGEgY2hhcnNldD0i"
    "dXRmLTgiLz4KICA8bGluayByZWw9InByZWNvbm5lY3QiIGhyZWY9Imh0dHBzOi8vZm9udHMuZ29v"
    "Z2xlYXBpcy5jb20iPgogIDxsaW5rIGhyZWY9Imh0dHBzOi8vZm9udHMuZ29vZ2xlYXBpcy5jb20v"
    "Y3NzMj9mYW1pbHk9U3luZTp3Z2h0QDQwMDs2MDA7NzAwJmZhbWlseT1JQk0rUGxleCtNb25vOndn"
    "aHRANDAwOzUwMCZkaXNwbGF5PXN3YXAiIHJlbD0ic3R5bGVzaGVldCI+CiAgPHNjcmlwdCBzcmM9"
    "Imh0dHBzOi8vY2VzaXVtLmNvbS9kb3dubG9hZHMvY2VzaXVtanMvcmVsZWFzZXMvMS4xMTQvQnVp"
    "bGQvQ2VzaXVtL0Nlc2l1bS5qcyI+PC9zY3JpcHQ+CiAgPGxpbmsgaHJlZj0iaHR0cHM6Ly9jZXNp"
    "dW0uY29tL2Rvd25sb2Fkcy9jZXNpdW1qcy9yZWxlYXNlcy8xLjExNC9CdWlsZC9DZXNpdW0vV2lk"
    "Z2V0cy93aWRnZXRzLmNzcyIgcmVsPSJzdHlsZXNoZWV0Ii8+CiAgPHN0eWxlPgogICAgOnJvb3Qg"
    "ewogICAgICAtLWJnOiAgICAgICMwODBkMTQ7CiAgICAgIC0tcGFuZWw6ICAgIzBkMTQyMTsKICAg"
    "ICAgLS1jYXJkOiAgICAjMTExZDJmOwogICAgICAtLWNhcmQyOiAgICMxNjIyMzc7CiAgICAgIC0t"
    "Ym9yZGVyOiAgcmdiYSgyNTUsMjU1LDI1NSwwLjA3KTsKICAgICAgLS1iaGk6ICAgICByZ2JhKDI1"
    "NSwyNTUsMjU1LDAuMTQpOwogICAgICAtLWJsdWU6ICAgICMzYjdmZjU7CiAgICAgIC0tdGVhbDog"
    "ICAgIzJkZDRiZjsKICAgICAgLS1hbWJlcjogICAjZmJiZjI0OwogICAgICAtLXJlZDogICAgICNm"
    "ODcxNzE7CiAgICAgIC0tZ3JlZW46ICAgIzRhZGU4MDsKICAgICAgLS10ZXh0OiAgICAjZGNlNmYw"
    "OwogICAgICAtLXRleHQyOiAgICM3YTlhYjg7CiAgICAgIC0tdGV4dDM6ICAgIzNhNTQ3MjsKICAg"
    "ICAgLS1yOiAgICAgICAxMHB4OwogICAgICAtLXJzOiAgICAgIDZweDsKICAgIH0KICAgICosICo6"
    "OmJlZm9yZSwgKjo6YWZ0ZXIgeyBib3gtc2l6aW5nOiBib3JkZXItYm94OyBtYXJnaW46IDA7IHBh"
    "ZGRpbmc6IDA7IH0KICAgIGh0bWwsIGJvZHkgewogICAgICBoZWlnaHQ6IDEwMCU7IGZvbnQtZmFt"
    "aWx5OiAnU3luZScsIHNhbnMtc2VyaWY7CiAgICAgIGJhY2tncm91bmQ6IHZhcigtLWJnKTsgY29s"
    "b3I6IHZhcigtLXRleHQpOyBvdmVyZmxvdzogaGlkZGVuOwogICAgfQoKICAgIC8qIOKUgOKUgCBT"
    "aGVsbCDilIDilIAgKi8KICAgICNhcHAgeyBkaXNwbGF5OiBmbGV4OyBoZWlnaHQ6IDEwMHZoOyB9"
    "CiAgICAjYXBwLmZ1bGxzY3JlZW4geyBwb3NpdGlvbjogZml4ZWQ7IGluc2V0OiAwOyB6LWluZGV4"
    "OiA5OTk5OyB9CgogICAgLyog4pSA4pSAIFNpZGViYXIg4pSA4pSAICovCiAgICAjc2lkZWJhciB7"
    "CiAgICAgIGZsZXg6IDAgMCAzMDBweDsKICAgICAgZGlzcGxheTogZmxleDsgZmxleC1kaXJlY3Rp"
    "b246IGNvbHVtbjsKICAgICAgYmFja2dyb3VuZDogdmFyKC0tcGFuZWwpOwogICAgICBib3JkZXIt"
    "cmlnaHQ6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOwogICAgICBvdmVyZmxvdzogaGlkZGVuOwog"
    "ICAgfQoKICAgIC5zaWRlYmFyLWhlYWQgewogICAgICBwYWRkaW5nOiAxNnB4IDE4cHggMTRweDsK"
    "ICAgICAgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHZhcigtLWJvcmRlcik7CiAgICAgIGZsZXgt"
    "c2hyaW5rOiAwOwogICAgfQogICAgLmJyYW5kIHsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6"
    "IGNlbnRlcjsgZ2FwOiAxMXB4OyBtYXJnaW4tYm90dG9tOiAycHg7IH0KICAgIC5icmFuZC1pY29u"
    "IHsKICAgICAgd2lkdGg6IDM2cHg7IGhlaWdodDogMzZweDsgYm9yZGVyLXJhZGl1czogMTBweDsK"
    "ICAgICAgYmFja2dyb3VuZDogbGluZWFyLWdyYWRpZW50KDEzNWRlZywgIzE1NTdlOCwgIzBjYTZl"
    "OCk7CiAgICAgIGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50ZXI7IGp1c3RpZnktY29u"
    "dGVudDogY2VudGVyOwogICAgICBmb250LXNpemU6IDE4cHg7IGZsZXgtc2hyaW5rOiAwOwogICAg"
    "ICBib3gtc2hhZG93OiAwIDNweCAxNHB4IHJnYmEoNTksMTI3LDI0NSwuNCk7CiAgICB9CiAgICAu"
    "YnJhbmQgaDEgeyBmb250LXNpemU6IDE1cHg7IGZvbnQtd2VpZ2h0OiA3MDA7IGxldHRlci1zcGFj"
    "aW5nOiAtLjJweDsgfQogICAgLmJyYW5kIHAgIHsgZm9udC1zaXplOiAxMHB4OyBjb2xvcjogdmFy"
    "KC0tdGV4dDMpOyBsZXR0ZXItc3BhY2luZzogLjdweDsgdGV4dC10cmFuc2Zvcm06IHVwcGVyY2Fz"
    "ZTsgbWFyZ2luLXRvcDogMnB4OyB9CgogICAgLyogVG9vbGJhciBzdHJpcCBpbnNpZGUgc2lkZWJh"
    "ciAqLwogICAgLnNiLXRvb2xiYXIgewogICAgICBkaXNwbGF5OiBmbGV4OyBnYXA6IDVweDsKICAg"
    "ICAgcGFkZGluZzogMTBweCAxOHB4OwogICAgICBib3JkZXItYm90dG9tOiAxcHggc29saWQgdmFy"
    "KC0tYm9yZGVyKTsKICAgICAgZmxleC1zaHJpbms6IDA7CiAgICB9CiAgICAuc2ItYnRuIHsKICAg"
    "ICAgZmxleDogMTsgcGFkZGluZzogN3B4IDZweDsKICAgICAgZm9udC1mYW1pbHk6ICdTeW5lJywg"
    "c2Fucy1zZXJpZjsgZm9udC1zaXplOiAxMXB4OyBmb250LXdlaWdodDogNjAwOwogICAgICBiYWNr"
    "Z3JvdW5kOiB2YXIoLS1jYXJkKTsgY29sb3I6IHZhcigtLXRleHQyKTsKICAgICAgYm9yZGVyOiAx"
    "cHggc29saWQgdmFyKC0tYm9yZGVyKTsgYm9yZGVyLXJhZGl1czogdmFyKC0tcnMpOwogICAgICBj"
    "dXJzb3I6IHBvaW50ZXI7IHRyYW5zaXRpb246IGFsbCAuMTVzOyB3aGl0ZS1zcGFjZTogbm93cmFw"
    "OwogICAgfQogICAgLnNiLWJ0bjpob3ZlciB7IGJhY2tncm91bmQ6IHZhcigtLWNhcmQyKTsgY29s"
    "b3I6IHZhcigtLXRleHQpOyB9CiAgICAuc2ItYnRuLmRhbmdlciB7IGNvbG9yOiB2YXIoLS1yZWQp"
    "OyBib3JkZXItY29sb3I6IHJnYmEoMjQ4LDExMywxMTMsLjIpOyB9CiAgICAuc2ItYnRuLmRhbmdl"
    "cjpob3ZlciB7IGJhY2tncm91bmQ6IHJnYmEoMjQ4LDExMywxMTMsLjEpOyB9CgogICAgLyogUm91"
    "dGUgaW5mbyBzdHJpcCAqLwogICAgI3JvdXRlSW5mbyB7CiAgICAgIHBhZGRpbmc6IDhweCAxOHB4"
    "OwogICAgICBib3JkZXItYm90dG9tOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsKICAgICAgZm9u"
    "dC1zaXplOiAxMXB4OyBjb2xvcjogdmFyKC0tdGV4dDMpOwogICAgICBkaXNwbGF5OiBmbGV4OyBn"
    "YXA6IDE2cHg7IGZsZXgtc2hyaW5rOiAwOwogICAgfQogICAgI3JvdXRlSW5mbyBzcGFuIHsgY29s"
    "b3I6IHZhcigtLXRleHQyKTsgZm9udC13ZWlnaHQ6IDYwMDsgZm9udC1mYW1pbHk6ICdJQk0gUGxl"
    "eCBNb25vJywgbW9ub3NwYWNlOyB9CgogICAgLyogU2VnbWVudHMgKyB3YXlwb2ludHMgbGlzdCAq"
    "LwogICAgI2ZsaWdodFBsYW4gewogICAgICBmbGV4OiAxOyBvdmVyZmxvdy15OiBhdXRvOwogICAg"
    "ICBwYWRkaW5nOiAxMHB4IDEycHg7CiAgICB9CiAgICAjZmxpZ2h0UGxhbjo6LXdlYmtpdC1zY3Jv"
    "bGxiYXIgeyB3aWR0aDogNHB4OyB9CiAgICAjZmxpZ2h0UGxhbjo6LXdlYmtpdC1zY3JvbGxiYXIt"
    "dGh1bWIgeyBiYWNrZ3JvdW5kOiB2YXIoLS1jYXJkMik7IGJvcmRlci1yYWRpdXM6IDRweDsgfQoK"
    "ICAgIC5lbXB0eS1oaW50IHsKICAgICAgcGFkZGluZzogMzJweCAxMnB4OyB0ZXh0LWFsaWduOiBj"
    "ZW50ZXI7IGNvbG9yOiB2YXIoLS10ZXh0Myk7CiAgICB9CiAgICAuZW1wdHktaGludCAuZWkgeyBm"
    "b250LXNpemU6IDMycHg7IG9wYWNpdHk6IC4yOyBtYXJnaW4tYm90dG9tOiAxMHB4OyB9CiAgICAu"
    "ZW1wdHktaGludCBwIHsgZm9udC1zaXplOiAxMnB4OyBsaW5lLWhlaWdodDogMS42OyB9CgogICAg"
    "LyogU2VnbWVudCBncm91cCAqLwogICAgLnNlZy1ncm91cCB7IG1hcmdpbi1ib3R0b206IDEwcHg7"
    "IH0KICAgIC5zZWctaGVhZGVyIHsKICAgICAgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNl"
    "bnRlcjsgZ2FwOiA4cHg7CiAgICAgIHBhZGRpbmc6IDlweCAxMXB4OyBtYXJnaW4tYm90dG9tOiA0"
    "cHg7CiAgICAgIGJhY2tncm91bmQ6IHZhcigtLWNhcmQpOyBib3JkZXI6IDFweCBzb2xpZCB2YXIo"
    "LS1ib3JkZXIpOwogICAgICBib3JkZXItcmFkaXVzOiB2YXIoLS1yKTsgY3Vyc29yOiBwb2ludGVy"
    "OyB1c2VyLXNlbGVjdDogbm9uZTsKICAgICAgdHJhbnNpdGlvbjogYm9yZGVyLWNvbG9yIC4yczsK"
    "ICAgIH0KICAgIC5zZWctaGVhZGVyOmhvdmVyIHsgYm9yZGVyLWNvbG9yOiB2YXIoLS1iaGkpOyB9"
    "CiAgICAuc2VnLWhlYWRlci5vcGVuIHsgYm9yZGVyLWNvbG9yOiB2YXIoLS1ibHVlKTsgfQogICAg"
    "LnNlZy1kb3QgeyB3aWR0aDogOHB4OyBoZWlnaHQ6IDhweDsgYm9yZGVyLXJhZGl1czogNTAlOyBm"
    "bGV4LXNocmluazogMDsgfQogICAgLnNlZy1uYW1lIHsgZmxleDogMTsgZm9udC1zaXplOiAxMi41"
    "cHg7IGZvbnQtd2VpZ2h0OiA2MDA7IH0KICAgIC5zZWctY291bnQgewogICAgICBmb250LXNpemU6"
    "IDEwcHg7IGNvbG9yOiB2YXIoLS10ZXh0Myk7CiAgICAgIGJhY2tncm91bmQ6IHZhcigtLWNhcmQy"
    "KTsgcGFkZGluZzogMnB4IDhweDsgYm9yZGVyLXJhZGl1czogMjBweDsKICAgIH0KICAgIC5zZWct"
    "Y2hldiB7IGZvbnQtc2l6ZTogMTFweDsgY29sb3I6IHZhcigtLXRleHQzKTsgdHJhbnNpdGlvbjog"
    "dHJhbnNmb3JtIC4yczsgfQogICAgLnNlZy1oZWFkZXIub3BlbiAuc2VnLWNoZXYgeyB0cmFuc2Zv"
    "cm06IHJvdGF0ZSg5MGRlZyk7IH0KCiAgICAuc2VnLXdwcyB7IGRpc3BsYXk6IG5vbmU7IHBhZGRp"
    "bmctbGVmdDogNHB4OyB9CiAgICAuc2VnLWhlYWRlci5vcGVuICsgLnNlZy13cHMgeyBkaXNwbGF5"
    "OiBibG9jazsgfQoKICAgIC8qIFdheXBvaW50IHJvdyAqLwogICAgLndwLXJvdyB7CiAgICAgIGRp"
    "c3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50ZXI7IGdhcDogNnB4OwogICAgICBwYWRkaW5n"
    "OiA3cHggMTBweDsgbWFyZ2luLWJvdHRvbTogM3B4OwogICAgICBiYWNrZ3JvdW5kOiB2YXIoLS1j"
    "YXJkKTsgYm9yZGVyOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsKICAgICAgYm9yZGVyLXJhZGl1"
    "czogdmFyKC0tcnMpOwogICAgICB0cmFuc2l0aW9uOiBib3JkZXItY29sb3IgLjE1czsKICAgICAg"
    "Y3Vyc29yOiBwb2ludGVyOwogICAgfQogICAgLndwLXJvdzpob3ZlciB7IGJvcmRlci1jb2xvcjog"
    "dmFyKC0tYmhpKTsgfQogICAgLndwLXJvdy5zZWxlY3RlZCB7IGJvcmRlci1jb2xvcjogdmFyKC0t"
    "YW1iZXIpOyBiYWNrZ3JvdW5kOiByZ2JhKDI1MSwxOTEsMzYsLjA1KTsgfQoKICAgIC53cC1udW0g"
    "ewogICAgICB3aWR0aDogMjJweDsgaGVpZ2h0OiAyMnB4OyBib3JkZXItcmFkaXVzOiA1MCU7CiAg"
    "ICAgIGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50ZXI7IGp1c3RpZnktY29udGVudDog"
    "Y2VudGVyOwogICAgICBmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiA3MDA7IGZsZXgtc2hy"
    "aW5rOiAwOwogICAgICBjb2xvcjogIzAwMDsKICAgIH0KICAgIC53cC1jb29yZHMgewogICAgICBm"
    "bGV4OiAxOyBmb250LWZhbWlseTogJ0lCTSBQbGV4IE1vbm8nLCBtb25vc3BhY2U7CiAgICAgIGZv"
    "bnQtc2l6ZTogOS41cHg7IGxpbmUtaGVpZ2h0OiAxLjY7IGNvbG9yOiB2YXIoLS10ZXh0Mik7CiAg"
    "ICB9CiAgICAud3AtYWx0IHsKICAgICAgZm9udC1mYW1pbHk6ICdJQk0gUGxleCBNb25vJywgbW9u"
    "b3NwYWNlOwogICAgICBmb250LXNpemU6IDlweDsgY29sb3I6IHZhcigtLXRleHQzKTsgd2hpdGUt"
    "c3BhY2U6IG5vd3JhcDsKICAgIH0KICAgIC53cC1hY3Rpb25zIHsgZGlzcGxheTogZmxleDsgZ2Fw"
    "OiAzcHg7IH0KICAgIC53cC1kZWwgewogICAgICB3aWR0aDogMjJweDsgaGVpZ2h0OiAyMnB4OyBi"
    "b3JkZXItcmFkaXVzOiA0cHg7CiAgICAgIGJhY2tncm91bmQ6IHJnYmEoMjQ4LDExMywxMTMsLjA4"
    "KTsgY29sb3I6IHZhcigtLXJlZCk7CiAgICAgIGJvcmRlcjogbm9uZTsgY3Vyc29yOiBwb2ludGVy"
    "OyBmb250LXNpemU6IDExcHg7CiAgICAgIGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50"
    "ZXI7IGp1c3RpZnktY29udGVudDogY2VudGVyOwogICAgICB0cmFuc2l0aW9uOiBiYWNrZ3JvdW5k"
    "IC4xNXM7CiAgICB9CiAgICAud3AtZGVsOmhvdmVyIHsgYmFja2dyb3VuZDogcmdiYSgyNDgsMTEz"
    "LDExMywuMik7IH0KCiAgICAvKiBJbmxpbmUgZWRpdCByb3cgKi8KICAgIC53cC1lZGl0LXJvdyB7"
    "CiAgICAgIHBhZGRpbmc6IDhweCAxMHB4OyBtYXJnaW4tYm90dG9tOiAzcHg7CiAgICAgIGJhY2tn"
    "cm91bmQ6IHJnYmEoNTksMTI3LDI0NSwuMDYpOwogICAgICBib3JkZXI6IDFweCBzb2xpZCB2YXIo"
    "LS1ibHVlKTsgYm9yZGVyLXJhZGl1czogdmFyKC0tcnMpOwogICAgfQogICAgLndwLWVkaXQtcm93"
    "IGxhYmVsIHsgZm9udC1zaXplOiA5cHg7IGNvbG9yOiB2YXIoLS10ZXh0Myk7IGRpc3BsYXk6IGJs"
    "b2NrOyBtYXJnaW4tYm90dG9tOiAzcHg7IGxldHRlci1zcGFjaW5nOiAuNXB4OyB0ZXh0LXRyYW5z"
    "Zm9ybTogdXBwZXJjYXNlOyB9CiAgICAud3AtZWRpdC1pbnB1dHMgeyBkaXNwbGF5OiBmbGV4OyBn"
    "YXA6IDVweDsgbWFyZ2luLWJvdHRvbTogN3B4OyB9CiAgICAud3AtZWRpdC1pbnB1dHMgaW5wdXQg"
    "ewogICAgICBmbGV4OiAxOyBwYWRkaW5nOiA1cHggN3B4OwogICAgICBmb250LWZhbWlseTogJ0lC"
    "TSBQbGV4IE1vbm8nLCBtb25vc3BhY2U7IGZvbnQtc2l6ZTogMTFweDsgY29sb3I6IHZhcigtLXRl"
    "eHQpOwogICAgICBiYWNrZ3JvdW5kOiB2YXIoLS1jYXJkKTsgYm9yZGVyOiAxcHggc29saWQgdmFy"
    "KC0tYm9yZGVyKTsgYm9yZGVyLXJhZGl1czogNHB4OwogICAgICBvdXRsaW5lOiBub25lOwogICAg"
    "fQogICAgLndwLWVkaXQtaW5wdXRzIGlucHV0OmZvY3VzIHsgYm9yZGVyLWNvbG9yOiB2YXIoLS1i"
    "bHVlKTsgfQogICAgLndwLWVkaXQtYnRucyB7IGRpc3BsYXk6IGZsZXg7IGdhcDogNXB4OyB9CiAg"
    "ICAud3Atc2F2ZS1idG4gewogICAgICBmbGV4OiAxOyBwYWRkaW5nOiA2cHg7IGZvbnQtc2l6ZTog"
    "MTFweDsgZm9udC13ZWlnaHQ6IDYwMDsKICAgICAgZm9udC1mYW1pbHk6ICdTeW5lJywgc2Fucy1z"
    "ZXJpZjsKICAgICAgYmFja2dyb3VuZDogcmdiYSg1OSwxMjcsMjQ1LC4xNSk7IGNvbG9yOiB2YXIo"
    "LS1ibHVlKTsKICAgICAgYm9yZGVyOiAxcHggc29saWQgcmdiYSg1OSwxMjcsMjQ1LC4zKTsgYm9y"
    "ZGVyLXJhZGl1czogNHB4OyBjdXJzb3I6IHBvaW50ZXI7CiAgICB9CiAgICAud3Atc2F2ZS1idG46"
    "aG92ZXIgeyBiYWNrZ3JvdW5kOiByZ2JhKDU5LDEyNywyNDUsLjI1KTsgfQogICAgLndwLWNhbmNl"
    "bC1idG4gewogICAgICBwYWRkaW5nOiA2cHggMTBweDsgZm9udC1zaXplOiAxMXB4OyBmb250LXdl"
    "aWdodDogNjAwOwogICAgICBmb250LWZhbWlseTogJ1N5bmUnLCBzYW5zLXNlcmlmOwogICAgICBi"
    "YWNrZ3JvdW5kOiB2YXIoLS1jYXJkKTsgY29sb3I6IHZhcigtLXRleHQzKTsKICAgICAgYm9yZGVy"
    "OiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsgYm9yZGVyLXJhZGl1czogNHB4OyBjdXJzb3I6IHBv"
    "aW50ZXI7CiAgICB9CgogICAgLyogRXhwb3J0IGJ1dHRvbiAqLwogICAgI2V4cG9ydFJvdyB7CiAg"
    "ICAgIHBhZGRpbmc6IDEwcHggMTJweDsKICAgICAgYm9yZGVyLXRvcDogMXB4IHNvbGlkIHZhcigt"
    "LWJvcmRlcik7CiAgICAgIGZsZXgtc2hyaW5rOiAwOwogICAgfQogICAgLmV4cG9ydC1idG4gewog"
    "ICAgICB3aWR0aDogMTAwJTsgcGFkZGluZzogOXB4OwogICAgICBmb250LWZhbWlseTogJ1N5bmUn"
    "LCBzYW5zLXNlcmlmOyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiA3MDA7CiAgICAgIGJh"
    "Y2tncm91bmQ6IHJnYmEoNDUsMjEyLDE5MSwuMSk7IGNvbG9yOiB2YXIoLS10ZWFsKTsKICAgICAg"
    "Ym9yZGVyOiAxcHggc29saWQgcmdiYSg0NSwyMTIsMTkxLC4yNSk7IGJvcmRlci1yYWRpdXM6IHZh"
    "cigtLXJzKTsKICAgICAgY3Vyc29yOiBwb2ludGVyOyB0cmFuc2l0aW9uOiBiYWNrZ3JvdW5kIC4x"
    "NXM7CiAgICB9CiAgICAuZXhwb3J0LWJ0bjpob3ZlciB7IGJhY2tncm91bmQ6IHJnYmEoNDUsMjEy"
    "LDE5MSwuMTgpOyB9CgogICAgLyogU3RhdHVzICovCiAgICAjc3RhdHVzQmFyIHsKICAgICAgcGFk"
    "ZGluZzogMTBweCAxOHB4OyBib3JkZXItdG9wOiAxcHggc29saWQgdmFyKC0tYm9yZGVyKTsKICAg"
    "ICAgZm9udC1zaXplOiAxMS41cHg7IGNvbG9yOiB2YXIoLS10ZXh0Mik7IGJhY2tncm91bmQ6IHZh"
    "cigtLXBhbmVsKTsKICAgICAgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNlbnRlcjsgZ2Fw"
    "OiA4cHg7IG1pbi1oZWlnaHQ6IDQwcHg7IGZsZXgtc2hyaW5rOiAwOwogICAgfQogICAgI3NEb3Qg"
    "ewogICAgICB3aWR0aDogNnB4OyBoZWlnaHQ6IDZweDsgYm9yZGVyLXJhZGl1czogNTAlOwogICAg"
    "ICBiYWNrZ3JvdW5kOiB2YXIoLS10ZXh0Myk7IGZsZXgtc2hyaW5rOiAwOyB0cmFuc2l0aW9uOiBi"
    "YWNrZ3JvdW5kIC4zczsKICAgIH0KICAgICNzRG90Lm9rICAgeyBiYWNrZ3JvdW5kOiB2YXIoLS1n"
    "cmVlbik7IH0KICAgICNzRG90LmVyciAgeyBiYWNrZ3JvdW5kOiB2YXIoLS1yZWQpOyB9CiAgICAj"
    "c0RvdC5idXN5IHsgYmFja2dyb3VuZDogdmFyKC0tYW1iZXIpOyBhbmltYXRpb246IGJsaW5rIDFz"
    "IGluZmluaXRlOyB9CiAgICBAa2V5ZnJhbWVzIGJsaW5rIHsgMCUsMTAwJXtvcGFjaXR5OjF9IDUw"
    "JXtvcGFjaXR5Oi4zfSB9CgogICAgLyog4pSA4pSAIE1hcCBhcmVhIOKUgOKUgCAqLwogICAgI21h"
    "cEFyZWEgeyBmbGV4OiAxOyBkaXNwbGF5OiBmbGV4OyBmbGV4LWRpcmVjdGlvbjogY29sdW1uOyBt"
    "aW4td2lkdGg6IDA7IH0KCiAgICAjdG9vbGJhciB7CiAgICAgIGRpc3BsYXk6IGZsZXg7IGFsaWdu"
    "LWl0ZW1zOiBjZW50ZXI7IGhlaWdodDogNTBweDsKICAgICAgcGFkZGluZzogMCAxNHB4OyBnYXA6"
    "IDJweDsKICAgICAgYmFja2dyb3VuZDogdmFyKC0tcGFuZWwpOyBib3JkZXItYm90dG9tOiAxcHgg"
    "c29saWQgdmFyKC0tYm9yZGVyKTsKICAgICAgZmxleC1zaHJpbms6IDA7IGZsZXgtd3JhcDogd3Jh"
    "cDsKICAgIH0KICAgIC50ZyB7CiAgICAgIGRpc3BsYXk6IGZsZXg7IGFsaWduLWl0ZW1zOiBjZW50"
    "ZXI7IGdhcDogMnB4OwogICAgICBoZWlnaHQ6IDEwMCU7IHBhZGRpbmc6IDAgOHB4OwogICAgICBi"
    "b3JkZXItcmlnaHQ6IDFweCBzb2xpZCB2YXIoLS1ib3JkZXIpOwogICAgfQogICAgLnRnOmxhc3Qt"
    "Y2hpbGQgeyBib3JkZXItcmlnaHQ6IG5vbmU7IH0KICAgIC50Zy1sYmwgewogICAgICBmb250LXNp"
    "emU6IDlweDsgZm9udC13ZWlnaHQ6IDcwMDsgbGV0dGVyLXNwYWNpbmc6IC44cHg7CiAgICAgIHRl"
    "eHQtdHJhbnNmb3JtOiB1cHBlcmNhc2U7IGNvbG9yOiB2YXIoLS10ZXh0Myk7IG1hcmdpbi1yaWdo"
    "dDogNHB4OwogICAgfQogICAgLnRidG4gewogICAgICBkaXNwbGF5OiBpbmxpbmUtZmxleDsgYWxp"
    "Z24taXRlbXM6IGNlbnRlcjsgZ2FwOiA1cHg7CiAgICAgIHBhZGRpbmc6IDZweCAxMXB4OwogICAg"
    "ICBmb250LWZhbWlseTogJ1N5bmUnLCBzYW5zLXNlcmlmOyBmb250LXNpemU6IDExLjVweDsgZm9u"
    "dC13ZWlnaHQ6IDYwMDsKICAgICAgY29sb3I6IHZhcigtLXRleHQyKTsgYmFja2dyb3VuZDogdHJh"
    "bnNwYXJlbnQ7CiAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHRyYW5zcGFyZW50OyBib3JkZXItcmFk"
    "aXVzOiB2YXIoLS1ycyk7CiAgICAgIGN1cnNvcjogcG9pbnRlcjsgd2hpdGUtc3BhY2U6IG5vd3Jh"
    "cDsgdHJhbnNpdGlvbjogYWxsIC4xNXM7CiAgICB9CiAgICAudGJ0bjpob3ZlciB7IGJhY2tncm91"
    "bmQ6IHZhcigtLWNhcmQpOyBjb2xvcjogdmFyKC0tdGV4dCk7IGJvcmRlci1jb2xvcjogdmFyKC0t"
    "YmhpKTsgfQogICAgLnRidG4ub24gIHsgYmFja2dyb3VuZDogcmdiYSg3NCwyMjIsMTI4LC4xKTsg"
    "Y29sb3I6IHZhcigtLWdyZWVuKTsgYm9yZGVyLWNvbG9yOiByZ2JhKDc0LDIyMiwxMjgsLjI1KTsg"
    "fQogICAgLnRidG4ucmVkIHsgYmFja2dyb3VuZDogcmdiYSgyNDgsMTEzLDExMywuMDgpOyBjb2xv"
    "cjogdmFyKC0tcmVkKTsgYm9yZGVyLWNvbG9yOiByZ2JhKDI0OCwxMTMsMTEzLC4yKTsgfQogICAg"
    "LnRidG4ucmVkOmhvdmVyIHsgYmFja2dyb3VuZDogcmdiYSgyNDgsMTEzLDExMywuMTUpOyB9Cgog"
    "ICAgI2Nlc2l1bUNvbnRhaW5lciB7IGZsZXg6IDE7IHBvc2l0aW9uOiByZWxhdGl2ZTsgfQogIDwv"
    "c3R5bGU+CjwvaGVhZD4KPGJvZHk+CjxkaXYgaWQ9ImFwcCI+CgogIDwhLS0g4pWQ4pWQ4pWQIFNJ"
    "REVCQVIg4pWQ4pWQ4pWQIC0tPgogIDxkaXYgaWQ9InNpZGViYXIiPgoKICAgIDxkaXYgY2xhc3M9"
    "InNpZGViYXItaGVhZCI+CiAgICAgIDxkaXYgY2xhc3M9ImJyYW5kIj4KICAgICAgICA8ZGl2IGNs"
    "YXNzPSJicmFuZC1pY29uIj7inIg8L2Rpdj4KICAgICAgICA8ZGl2PgogICAgICAgICAgPGgxPlNr"
    "eXBob3I8L2gxPgogICAgICAgICAgPHA+RmxpZ2h0IFBsYW4gRWRpdG9yPC9wPgogICAgICAgIDwv"
    "ZGl2PgogICAgICA8L2Rpdj4KICAgIDwvZGl2PgoKICAgIDxkaXYgY2xhc3M9InNiLXRvb2xiYXIi"
    "PgogICAgICA8YnV0dG9uIGNsYXNzPSJzYi1idG4iIGlkPSJkcmF3QnRuIj7inI8gRHJhdzwvYnV0"
    "dG9uPgogICAgICA8YnV0dG9uIGNsYXNzPSJzYi1idG4iIGlkPSJmaW5pc2hCdG4iPuKckyBGaW5p"
    "c2g8L2J1dHRvbj4KICAgICAgPGJ1dHRvbiBjbGFzcz0ic2ItYnRuIiBpZD0idW5kb0J0biI+4oa2"
    "IFVuZG88L2J1dHRvbj4KICAgICAgPGJ1dHRvbiBjbGFzcz0ic2ItYnRuIGRhbmdlciIgaWQ9ImNs"
    "ZWFyQnRuIj7inJUgQ2xlYXI8L2J1dHRvbj4KICAgIDwvZGl2PgoKICAgIDxkaXYgaWQ9InJvdXRl"
    "SW5mbyI+CiAgICAgIDxkaXY+V2F5cG9pbnRzOiA8c3BhbiBpZD0id3BUb3RhbCI+MDwvc3Bhbj48"
    "L2Rpdj4KICAgICAgPGRpdj5EaXN0YW5jZTogPHNwYW4gaWQ9IndwRGlzdCI+MCBrbTwvc3Bhbj48"
    "L2Rpdj4KICAgIDwvZGl2PgoKICAgIDxkaXYgaWQ9ImZsaWdodFBsYW4iPgogICAgICA8ZGl2IGNs"
    "YXNzPSJlbXB0eS1oaW50Ij4KICAgICAgICA8ZGl2IGNsYXNzPSJlaSI+8J+Xuu+4jzwvZGl2Pgog"
    "ICAgICAgIDxwPlVwbG9hZCBhIEtNWi9LTUwgZmlsZSBvciBwYXN0ZSBjb29yZGluYXRlcyDigJQg"
    "eW91ciBmbGlnaHQgcGxhbiB3aWxsIGFwcGVhciBoZXJlIGZvciBlZGl0aW5nPC9wPgogICAgICA8"
    "L2Rpdj4KICAgIDwvZGl2PgoKICAgIDxkaXYgaWQ9ImV4cG9ydFJvdyI+CiAgICAgIDxidXR0b24g"
    "Y2xhc3M9ImV4cG9ydC1idG4iIGlkPSJleHBvcnRCdG4iPuKshyBFeHBvcnQgS01aPC9idXR0b24+"
    "CiAgICA8L2Rpdj4KCiAgICA8ZGl2IGlkPSJzdGF0dXNCYXIiPgogICAgICA8ZGl2IGlkPSJzRG90"
    "Ij48L2Rpdj4KICAgICAgPHNwYW4gaWQ9InNUeHQiPlJlYWR5PC9zcGFuPgogICAgPC9kaXY+Cgog"
    "IDwvZGl2PgoKICA8IS0tIOKVkOKVkOKVkCBNQVAg4pWQ4pWQ4pWQIC0tPgogIDxkaXYgaWQ9Im1h"
    "cEFyZWEiPgogICAgPGRpdiBpZD0idG9vbGJhciI+CgogICAgICA8ZGl2IGNsYXNzPSJ0ZyI+CiAg"
    "ICAgICAgPHNwYW4gY2xhc3M9InRnLWxibCI+Vmlldzwvc3Bhbj4KICAgICAgICA8YnV0dG9uIGNs"
    "YXNzPSJ0YnRuIiBpZD0iZml0QnRuIj7iiqEgRml0PC9idXR0b24+CiAgICAgICAgPGJ1dHRvbiBj"
    "bGFzcz0idGJ0biIgaWQ9ImZzQnRuIj7im7YgRnVsbHNjcmVlbjwvYnV0dG9uPgogICAgICA8L2Rp"
    "dj4KCiAgICAgIDxkaXYgY2xhc3M9InRnIj4KICAgICAgICA8c3BhbiBjbGFzcz0idGctbGJsIj5E"
    "cm9uZTwvc3Bhbj4KICAgICAgICA8YnV0dG9uIGNsYXNzPSJ0YnRuIiBpZD0iZHJvbmVCdG4iPuKW"
    "tiBTaW11bGF0ZTwvYnV0dG9uPgogICAgICAgIDxidXR0b24gY2xhc3M9InRidG4gcmVkIiBpZD0i"
    "c3RvcEJ0biIgc3R5bGU9ImRpc3BsYXk6bm9uZTsiPuKPuSBTdG9wPC9idXR0b24+CiAgICAgIDwv"
    "ZGl2PgoKICAgICAgPGRpdiBjbGFzcz0idGciPgogICAgICAgIDxzcGFuIGNsYXNzPSJ0Zy1sYmwi"
    "PlRlcnJhaW48L3NwYW4+CiAgICAgICAgPGJ1dHRvbiBjbGFzcz0idGJ0biIgaWQ9InRlcnJhaW5C"
    "dG4iPuKbsCAzRCBUZXJyYWluPC9idXR0b24+CiAgICAgIDwvZGl2PgoKICAgIDwvZGl2PgogICAg"
    "PGRpdiBpZD0iY2VzaXVtQ29udGFpbmVyIj48L2Rpdj4KICA8L2Rpdj4KCjwvZGl2Pgo8c2NyaXB0"
    "PgondXNlIHN0cmljdCc7CgovLyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZAKLy8gUEhBU0UgMSBEQVRBIOKAlCBpbmplY3RlZCBmcm9tIFB5dGhvbiBz"
    "dHJ1Y3R1cmVkIHBhcnNlcgovLyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZAKY29uc3QgSU5JVElBTF9TRUdNRU5UUyA9IEBAU0VHTUVOVFNfSlNPTkBA"
    "OwoKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "Ci8vIENFU0lVTSBJTklUCi8vIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkApDZXNpdW0uSW9uLmRlZmF1bHRBY2Nlc3NUb2tlbiA9ICcnOwpjb25zdCBf"
    "Y3MgPSBkb2N1bWVudC5jcmVhdGVFbGVtZW50KCdkaXYnKTsKbGV0IHZpZXdlcjsKdHJ5IHsKICB2"
    "aWV3ZXIgPSBuZXcgQ2VzaXVtLlZpZXdlcignY2VzaXVtQ29udGFpbmVyJywgewogICAgdGVycmFp"
    "blByb3ZpZGVyOiBDZXNpdW0uRWxsaXBzb2lkVGVycmFpblByb3ZpZGVyLklOU1RBTkNFLAogICAg"
    "YW5pbWF0aW9uOiBmYWxzZSwgYmFzZUxheWVyUGlja2VyOiBmYWxzZSwgZ2VvY29kZXI6IGZhbHNl"
    "LAogICAgaG9tZUJ1dHRvbjogZmFsc2UsIHNjZW5lTW9kZVBpY2tlcjogZmFsc2UsCiAgICBuYXZp"
    "Z2F0aW9uSGVscEJ1dHRvbjogZmFsc2UsIGZ1bGxzY3JlZW5CdXR0b246IGZhbHNlLAogICAgdGlt"
    "ZWxpbmU6IGZhbHNlLCBjcmVkaXRDb250YWluZXI6IF9jcywKICB9KTsKICB2aWV3ZXIuc2NlbmUu"
    "YmFja2dyb3VuZENvbG9yID0gQ2VzaXVtLkNvbG9yLmZyb21Dc3NDb2xvclN0cmluZygnIzA2MDkw"
    "ZicpOwp9IGNhdGNoIChlKSB7CiAgY29uc29sZS5lcnJvcignQ2VzaXVtIGluaXQ6JywgZSk7CiAg"
    "dmlld2VyID0gbnVsbDsKfQoKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQCi8vIFNUQVRFIOKAlCBzaW5nbGUgc291cmNlIG9mIHRydXRoCi8vIOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAovLyBzZWdt"
    "ZW50czogW3sgbmFtZSwgY29vcmRzOiBbW2xvbixsYXQsYWx0XSwuLi5dIH0sIC4uLl0KLy8gZWRp"
    "dFN0YXRlOiB7IHNlZ0lkeCwgd3BJZHggfSB8IG51bGwKbGV0IHNlZ21lbnRzICAgID0gW107Cmxl"
    "dCBzZWxlY3RlZFdwICA9IG51bGw7ICAvLyB7IHNlZ0lkeCwgd3BJZHggfQpsZXQgZWRpdFN0YXRl"
    "ICAgPSBudWxsOwpsZXQgZHJhd2luZ01vZGUgPSBmYWxzZTsKbGV0IHBhdGhFbnRpdGllcz0gW107"
    "CmxldCBtYXJrZXJFbnRpdGllcyA9IFtdOwpsZXQgZHJvbmVFbnQgICAgPSBudWxsOwpsZXQgdGVy"
    "cmFpbk9uICAgPSBmYWxzZTsKCmNvbnN0IENPTE9SUyA9IFsnIzNiN2ZmNScsJyMyZGQ0YmYnLCcj"
    "ZmJiZjI0JywnI2Y0NzJiNicsJyNhNzhiZmEnLCcjZmI5MjNjJywnIzRhZGU4MCddOwoKLy8g4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCi8vIFNUQVRV"
    "UwovLyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAK"
    "ZnVuY3Rpb24gc2V0U3RhdHVzKG1zZywgdHlwZSkgewogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlk"
    "KCdzVHh0JykudGV4dENvbnRlbnQgPSBtc2c7CiAgY29uc3QgZCA9IGRvY3VtZW50LmdldEVsZW1l"
    "bnRCeUlkKCdzRG90Jyk7CiAgZC5jbGFzc05hbWUgPSB0eXBlIHx8ICcnOwp9CgovLyDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKLy8gR0xPQkUg4oCU"
    "IHJlbmRlciAvIGNsZWFyCi8vIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkApmdW5jdGlvbiBjbGVhckdsb2JlKCkgewogIGlmICghdmlld2VyKSByZXR1"
    "cm47CiAgWy4uLnBhdGhFbnRpdGllcywgLi4ubWFya2VyRW50aXRpZXNdLmZvckVhY2goZSA9PiB2"
    "aWV3ZXIuZW50aXRpZXMucmVtb3ZlKGUpKTsKICBwYXRoRW50aXRpZXMgPSBbXTsgbWFya2VyRW50"
    "aXRpZXMgPSBbXTsKfQoKZnVuY3Rpb24gcmVuZGVyR2xvYmUoKSB7CiAgY2xlYXJHbG9iZSgpOwog"
    "IGlmICghdmlld2VyKSByZXR1cm47CgogIHNlZ21lbnRzLmZvckVhY2goKHNlZywgc2kpID0+IHsK"
    "ICAgIGNvbnN0IGNvbG9yID0gQ2VzaXVtLkNvbG9yLmZyb21Dc3NDb2xvclN0cmluZyhDT0xPUlNb"
    "c2kgJSBDT0xPUlMubGVuZ3RoXSk7CgogICAgaWYgKHNlZy5jb29yZHMubGVuZ3RoID49IDIpIHsK"
    "ICAgICAgY29uc3QgcG9zaXRpb25zID0gc2VnLmNvb3Jkcy5tYXAoYyA9PiBDZXNpdW0uQ2FydGVz"
    "aWFuMy5mcm9tRGVncmVlcyhjWzBdLCBjWzFdLCBjWzJdIHx8IDApKTsKICAgICAgcGF0aEVudGl0"
    "aWVzLnB1c2godmlld2VyLmVudGl0aWVzLmFkZCh7CiAgICAgICAgcG9seWxpbmU6IHsKICAgICAg"
    "ICAgIHBvc2l0aW9ucywKICAgICAgICAgIHdpZHRoOiAzLAogICAgICAgICAgbWF0ZXJpYWw6IG5l"
    "dyBDZXNpdW0uUG9seWxpbmVHbG93TWF0ZXJpYWxQcm9wZXJ0eSh7CiAgICAgICAgICAgIGdsb3dQ"
    "b3dlcjogMC4yNSwgdGFwZXJQb3dlcjogMS4wLCBjb2xvciwKICAgICAgICAgIH0pLAogICAgICAg"
    "ICAgY2xhbXBUb0dyb3VuZDogZmFsc2UsCiAgICAgICAgfQogICAgICB9KSk7CiAgICB9CgogICAg"
    "c2VnLmNvb3Jkcy5mb3JFYWNoKChjLCB3aSkgPT4gewogICAgICBjb25zdCBpc1NlbCA9IHNlbGVj"
    "dGVkV3AgJiYgc2VsZWN0ZWRXcC5zZWdJZHggPT09IHNpICYmIHNlbGVjdGVkV3Aud3BJZHggPT09"
    "IHdpOwogICAgICBjb25zdCBlbnQgPSB2aWV3ZXIuZW50aXRpZXMuYWRkKHsKICAgICAgICBwb3Np"
    "dGlvbjogQ2VzaXVtLkNhcnRlc2lhbjMuZnJvbURlZ3JlZXMoY1swXSwgY1sxXSwgKGNbMl0gfHwg"
    "MCkgKyA4KSwKICAgICAgICBwb2ludDogewogICAgICAgICAgcGl4ZWxTaXplOiBpc1NlbCA/IDEz"
    "IDogOCwKICAgICAgICAgIGNvbG9yOiBpc1NlbCA/IENlc2l1bS5Db2xvci5mcm9tQ3NzQ29sb3JT"
    "dHJpbmcoJyNmYmJmMjQnKSA6IGNvbG9yLAogICAgICAgICAgb3V0bGluZUNvbG9yOiBDZXNpdW0u"
    "Q29sb3IuV0hJVEUsCiAgICAgICAgICBvdXRsaW5lV2lkdGg6IGlzU2VsID8gMi41IDogMS41LAog"
    "ICAgICAgICAgZGlzYWJsZURlcHRoVGVzdERpc3RhbmNlOiBOdW1iZXIuUE9TSVRJVkVfSU5GSU5J"
    "VFksCiAgICAgICAgfSwKICAgICAgICBsYWJlbDogewogICAgICAgICAgdGV4dDogU3RyaW5nKHdp"
    "ICsgMSksCiAgICAgICAgICBmb250OiAnMTBweCAiSUJNIFBsZXggTW9ubyIsIG1vbm9zcGFjZScs"
    "CiAgICAgICAgICBmaWxsQ29sb3I6IENlc2l1bS5Db2xvci5XSElURSwKICAgICAgICAgIG91dGxp"
    "bmVDb2xvcjogQ2VzaXVtLkNvbG9yLkJMQUNLLCBvdXRsaW5lV2lkdGg6IDIsCiAgICAgICAgICBz"
    "dHlsZTogQ2VzaXVtLkxhYmVsU3R5bGUuRklMTF9BTkRfT1VUTElORSwKICAgICAgICAgIHZlcnRp"
    "Y2FsT3JpZ2luOiBDZXNpdW0uVmVydGljYWxPcmlnaW4uQk9UVE9NLAogICAgICAgICAgcGl4ZWxP"
    "ZmZzZXQ6IG5ldyBDZXNpdW0uQ2FydGVzaWFuMigwLCAtNSksCiAgICAgICAgICBkaXNhYmxlRGVw"
    "dGhUZXN0RGlzdGFuY2U6IE51bWJlci5QT1NJVElWRV9JTkZJTklUWSwKICAgICAgICAgIHNob3c6"
    "IHNlZy5jb29yZHMubGVuZ3RoIDw9IDgwLAogICAgICAgIH0sCiAgICAgIH0pOwogICAgICAvLyBz"
    "dG9yZSBpZGVudGl0eSBmb3IgY2xpY2sgZGV0ZWN0aW9uCiAgICAgIGVudC5fc2t5cGhvclNlZyA9"
    "IHNpOwogICAgICBlbnQuX3NreXBob3JXcCAgPSB3aTsKICAgICAgbWFya2VyRW50aXRpZXMucHVz"
    "aChlbnQpOwogICAgfSk7CiAgfSk7Cn0KCi8vIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkAovLyBTVEFUUwovLyDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKZnVuY3Rpb24gaGF2ZXJzaW5lS20obG9uMSwg"
    "bGF0MSwgbG9uMiwgbGF0MikgewogIGNvbnN0IFIgPSA2MzcxLCB0b1JhZCA9IE1hdGguUEkgLyAx"
    "ODA7CiAgY29uc3QgZExhdCA9IChsYXQyIC0gbGF0MSkgKiB0b1JhZCwgZExvbiA9IChsb24yIC0g"
    "bG9uMSkgKiB0b1JhZDsKICBjb25zdCBhID0gTWF0aC5zaW4oZExhdC8yKSoqMiArIE1hdGguY29z"
    "KGxhdDEqdG9SYWQpKk1hdGguY29zKGxhdDIqdG9SYWQpKk1hdGguc2luKGRMb24vMikqKjI7CiAg"
    "cmV0dXJuIDIgKiBSICogTWF0aC5hc2luKE1hdGguc3FydChhKSk7Cn0KCmZ1bmN0aW9uIHVwZGF0"
    "ZVN0YXRzKCkgewogIGxldCB0b3RhbCA9IDAsIGRpc3QgPSAwLCBwcmV2ID0gbnVsbDsKICBzZWdt"
    "ZW50cy5mb3JFYWNoKHNlZyA9PiB7CiAgICB0b3RhbCArPSBzZWcuY29vcmRzLmxlbmd0aDsKICAg"
    "IHNlZy5jb29yZHMuZm9yRWFjaChjID0+IHsKICAgICAgaWYgKHByZXYpIGRpc3QgKz0gaGF2ZXJz"
    "aW5lS20ocHJldlswXSwgcHJldlsxXSwgY1swXSwgY1sxXSk7CiAgICAgIHByZXYgPSBjOwogICAg"
    "fSk7CiAgfSk7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3dwVG90YWwnKS50ZXh0Q29udGVu"
    "dCA9IHRvdGFsOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd3cERpc3QnKS50ZXh0Q29udGVu"
    "dCAgPSBkaXN0LnRvRml4ZWQoMSkgKyAnIGttJzsKfQoKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCi8vIFBIQVNFIDIg4oCUIEZMSUdIVCBQTEFO"
    "IFBBTkVMCi8vIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkApmdW5jdGlvbiBidWlsZFBhbmVsKCkgewogIGNvbnN0IGZwID0gZG9jdW1lbnQuZ2V0RWxl"
    "bWVudEJ5SWQoJ2ZsaWdodFBsYW4nKTsKICBmcC5pbm5lckhUTUwgPSAnJzsKCiAgaWYgKCFzZWdt"
    "ZW50cy5sZW5ndGgpIHsKICAgIGZwLmlubmVySFRNTCA9ICc8ZGl2IGNsYXNzPSJlbXB0eS1oaW50"
    "Ij48ZGl2IGNsYXNzPSJlaSI+8J+Xuu+4jzwvZGl2PjxwPlVwbG9hZCBhIEtNWi9LTUwgZmlsZSBv"
    "ciBwYXN0ZSBjb29yZGluYXRlcyB0byBlZGl0IHlvdXIgZmxpZ2h0IHBsYW48L3A+PC9kaXY+JzsK"
    "ICAgIHJldHVybjsKICB9CgogIHNlZ21lbnRzLmZvckVhY2goKHNlZywgc2kpID0+IHsKICAgIGNv"
    "bnN0IGNvbG9yID0gQ09MT1JTW3NpICUgQ09MT1JTLmxlbmd0aF07CiAgICBjb25zdCBncm91cCA9"
    "IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpOwogICAgZ3JvdXAuY2xhc3NOYW1lID0gJ3Nl"
    "Zy1ncm91cCc7CiAgICBncm91cC5kYXRhc2V0LnNpID0gc2k7CgogICAgLy8gU2VnbWVudCBoZWFk"
    "ZXIKICAgIGNvbnN0IGhkciA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpOwogICAgaGRy"
    "LmNsYXNzTmFtZSA9ICdzZWctaGVhZGVyIG9wZW4nOwogICAgaGRyLmlubmVySFRNTCA9IGAKICAg"
    "ICAgPHNwYW4gY2xhc3M9InNlZy1kb3QiIHN0eWxlPSJiYWNrZ3JvdW5kOiR7Y29sb3J9Ij48L3Nw"
    "YW4+CiAgICAgIDxzcGFuIGNsYXNzPSJzZWctbmFtZSI+JHtlc2NIdG1sKHNlZy5uYW1lKX08L3Nw"
    "YW4+CiAgICAgIDxzcGFuIGNsYXNzPSJzZWctY291bnQiPiR7c2VnLmNvb3Jkcy5sZW5ndGh9IHB0"
    "czwvc3Bhbj4KICAgICAgPHNwYW4gY2xhc3M9InNlZy1jaGV2Ij7igLo8L3NwYW4+YDsKICAgIGhk"
    "ci5hZGRFdmVudExpc3RlbmVyKCdjbGljaycsICgpID0+IHsKICAgICAgaGRyLmNsYXNzTGlzdC50"
    "b2dnbGUoJ29wZW4nKTsKICAgICAgd3BzRGl2LnN0eWxlLmRpc3BsYXkgPSBoZHIuY2xhc3NMaXN0"
    "LmNvbnRhaW5zKCdvcGVuJykgPyAnYmxvY2snIDogJ25vbmUnOwogICAgfSk7CiAgICBncm91cC5h"
    "cHBlbmRDaGlsZChoZHIpOwoKICAgIC8vIFdheXBvaW50cyBjb250YWluZXIKICAgIGNvbnN0IHdw"
    "c0RpdiA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpOwogICAgd3BzRGl2LmNsYXNzTmFt"
    "ZSA9ICdzZWctd3BzJzsKICAgIHdwc0Rpdi5zdHlsZS5kaXNwbGF5ID0gJ2Jsb2NrJzsKCiAgICBz"
    "ZWcuY29vcmRzLmZvckVhY2goKGMsIHdpKSA9PiB7CiAgICAgIHdwc0Rpdi5hcHBlbmRDaGlsZCht"
    "YWtlV3BSb3coc2ksIHdpLCBjLCBjb2xvcikpOwogICAgfSk7CgogICAgZ3JvdXAuYXBwZW5kQ2hp"
    "bGQod3BzRGl2KTsKICAgIGZwLmFwcGVuZENoaWxkKGdyb3VwKTsKICB9KTsKCiAgdXBkYXRlU3Rh"
    "dHMoKTsKfQoKZnVuY3Rpb24gZXNjSHRtbChzKSB7CiAgcmV0dXJuIFN0cmluZyhzKS5yZXBsYWNl"
    "KC8mL2csJyZhbXA7JykucmVwbGFjZSgvPC9nLCcmbHQ7JykucmVwbGFjZSgvPi9nLCcmZ3Q7Jyk7"
    "Cn0KCmZ1bmN0aW9uIG1ha2VXcFJvdyhzaSwgd2ksIGMsIGNvbG9yKSB7CiAgLy8gSWYgdGhpcyB3"
    "YXlwb2ludCBpcyBpbiBlZGl0IG1vZGUsIHJlbmRlciB0aGUgZWRpdCBmb3JtIGluc3RlYWQKICBp"
    "ZiAoZWRpdFN0YXRlICYmIGVkaXRTdGF0ZS5zZWdJZHggPT09IHNpICYmIGVkaXRTdGF0ZS53cElk"
    "eCA9PT0gd2kpIHsKICAgIHJldHVybiBtYWtlRWRpdFJvdyhzaSwgd2ksIGMpOwogIH0KCiAgY29u"
    "c3QgaXNTZWwgPSBzZWxlY3RlZFdwICYmIHNlbGVjdGVkV3Auc2VnSWR4ID09PSBzaSAmJiBzZWxl"
    "Y3RlZFdwLndwSWR4ID09PSB3aTsKICBjb25zdCBkaXYgPSBkb2N1bWVudC5jcmVhdGVFbGVtZW50"
    "KCdkaXYnKTsKICBkaXYuY2xhc3NOYW1lID0gJ3dwLXJvdycgKyAoaXNTZWwgPyAnIHNlbGVjdGVk"
    "JyA6ICcnKTsKCiAgY29uc3QgYWx0TSA9IGNbMl0gPyBjWzJdLnRvRml4ZWQoMCkgKyAnbScgOiAn"
    "MG0nOwogIGNvbnN0IGFsdEZ0ID0gY1syXSA/IChjWzJdICogMy4yODA4NCkudG9GaXhlZCgwKSAr"
    "ICdmdCcgOiAnMGZ0JzsKCiAgZGl2LmlubmVySFRNTCA9IGAKICAgIDxzcGFuIGNsYXNzPSJ3cC1u"
    "dW0iIHN0eWxlPSJiYWNrZ3JvdW5kOiR7Y29sb3J9Ij4ke3dpICsgMX08L3NwYW4+CiAgICA8c3Bh"
    "biBjbGFzcz0id3AtY29vcmRzIj4ke2NbMF0udG9GaXhlZCg1KX08YnI+JHtjWzFdLnRvRml4ZWQo"
    "NSl9PC9zcGFuPgogICAgPHNwYW4gY2xhc3M9IndwLWFsdCI+JHthbHRGdH08YnI+JHthbHRNfTwv"
    "c3Bhbj4KICAgIDxzcGFuIGNsYXNzPSJ3cC1hY3Rpb25zIj4KICAgICAgPGJ1dHRvbiBjbGFzcz0i"
    "d3AtZGVsIiB0aXRsZT0iRWRpdCB3YXlwb2ludCI+4pyOPC9idXR0b24+CiAgICAgIDxidXR0b24g"
    "Y2xhc3M9IndwLWRlbCIgdGl0bGU9IkRlbGV0ZSB3YXlwb2ludCIgc3R5bGU9ImNvbG9yOnZhcigt"
    "LXJlZCkiPuKclTwvYnV0dG9uPgogICAgPC9zcGFuPmA7CgogIC8vIENsaWNrIHJvdyB0byBmbHkg"
    "dGhlcmUgYW5kIHNlbGVjdAogIGRpdi5hZGRFdmVudExpc3RlbmVyKCdjbGljaycsIChlKSA9PiB7"
    "CiAgICBpZiAoZS50YXJnZXQuY2xvc2VzdCgnLndwLWFjdGlvbnMnKSkgcmV0dXJuOwogICAgc2Vs"
    "ZWN0V3Aoc2ksIHdpKTsKICB9KTsKCiAgY29uc3QgYnRucyA9IGRpdi5xdWVyeVNlbGVjdG9yQWxs"
    "KCcud3AtZGVsJyk7CiAgLy8gRWRpdCBidXR0b24KICBidG5zWzBdLmFkZEV2ZW50TGlzdGVuZXIo"
    "J2NsaWNrJywgKGUpID0+IHsKICAgIGUuc3RvcFByb3BhZ2F0aW9uKCk7CiAgICBlZGl0U3RhdGUg"
    "PSB7IHNlZ0lkeDogc2ksIHdwSWR4OiB3aSB9OwogICAgYnVpbGRQYW5lbCgpOwogIH0pOwogIC8v"
    "IERlbGV0ZSBidXR0b24KICBidG5zWzFdLmFkZEV2ZW50TGlzdGVuZXIoJ2NsaWNrJywgKGUpID0+"
    "IHsKICAgIGUuc3RvcFByb3BhZ2F0aW9uKCk7CiAgICBkZWxldGVXcChzaSwgd2kpOwogIH0pOwoK"
    "ICByZXR1cm4gZGl2Owp9CgpmdW5jdGlvbiBtYWtlRWRpdFJvdyhzaSwgd2ksIGMpIHsKICBjb25z"
    "dCBkaXYgPSBkb2N1bWVudC5jcmVhdGVFbGVtZW50KCdkaXYnKTsKICBkaXYuY2xhc3NOYW1lID0g"
    "J3dwLWVkaXQtcm93JzsKICBkaXYuaW5uZXJIVE1MID0gYAogICAgPGxhYmVsPkxvbmdpdHVkZSAv"
    "IExhdGl0dWRlIC8gQWx0aXR1ZGUgKG0pPC9sYWJlbD4KICAgIDxkaXYgY2xhc3M9IndwLWVkaXQt"
    "aW5wdXRzIj4KICAgICAgPGlucHV0IGlkPSJlbG9uIiB0eXBlPSJudW1iZXIiIHN0ZXA9IjAuMDAw"
    "MDEiIHZhbHVlPSIke2NbMF0udG9GaXhlZCg1KX0iIHBsYWNlaG9sZGVyPSJMb24iLz4KICAgICAg"
    "PGlucHV0IGlkPSJlbGF0IiB0eXBlPSJudW1iZXIiIHN0ZXA9IjAuMDAwMDEiIHZhbHVlPSIke2Nb"
    "MV0udG9GaXhlZCg1KX0iIHBsYWNlaG9sZGVyPSJMYXQiLz4KICAgICAgPGlucHV0IGlkPSJlYWx0"
    "IiB0eXBlPSJudW1iZXIiIHN0ZXA9IjEiICAgICAgIHZhbHVlPSIkeyhjWzJdfHwwKS50b0ZpeGVk"
    "KDApfSIgcGxhY2Vob2xkZXI9IkFsdCAobSkiLz4KICAgIDwvZGl2PgogICAgPGRpdiBjbGFzcz0i"
    "d3AtZWRpdC1idG5zIj4KICAgICAgPGJ1dHRvbiBjbGFzcz0id3Atc2F2ZS1idG4iIGlkPSJlU2F2"
    "ZSI+U2F2ZTwvYnV0dG9uPgogICAgICA8YnV0dG9uIGNsYXNzPSJ3cC1jYW5jZWwtYnRuIiBpZD0i"
    "ZUNhbmNlbCI+Q2FuY2VsPC9idXR0b24+CiAgICA8L2Rpdj5gOwoKICBkaXYucXVlcnlTZWxlY3Rv"
    "cignI2VTYXZlJykuYWRkRXZlbnRMaXN0ZW5lcignY2xpY2snLCAoKSA9PiB7CiAgICBjb25zdCBs"
    "b24gPSBwYXJzZUZsb2F0KGRpdi5xdWVyeVNlbGVjdG9yKCcjZWxvbicpLnZhbHVlKTsKICAgIGNv"
    "bnN0IGxhdCA9IHBhcnNlRmxvYXQoZGl2LnF1ZXJ5U2VsZWN0b3IoJyNlbGF0JykudmFsdWUpOwog"
    "ICAgY29uc3QgYWx0ID0gcGFyc2VGbG9hdChkaXYucXVlcnlTZWxlY3RvcignI2VhbHQnKS52YWx1"
    "ZSkgfHwgMDsKICAgIGlmICghaXNGaW5pdGUobG9uKSB8fCAhaXNGaW5pdGUobGF0KSkgewogICAg"
    "ICBzZXRTdGF0dXMoJ0ludmFsaWQgY29vcmRpbmF0ZXMg4oCUIGNoZWNrIHZhbHVlcy4nLCAnZXJy"
    "Jyk7IHJldHVybjsKICAgIH0KICAgIHNlZ21lbnRzW3NpXS5jb29yZHNbd2ldID0gW2xvbiwgbGF0"
    "LCBhbHRdOwogICAgZWRpdFN0YXRlID0gbnVsbDsKICAgIHVwZGF0ZUFsbCgnV2F5cG9pbnQgdXBk"
    "YXRlZC4nKTsKICB9KTsKICBkaXYucXVlcnlTZWxlY3RvcignI2VDYW5jZWwnKS5hZGRFdmVudExp"
    "c3RlbmVyKCdjbGljaycsICgpID0+IHsKICAgIGVkaXRTdGF0ZSA9IG51bGw7CiAgICBidWlsZFBh"
    "bmVsKCk7CiAgfSk7CgogIHJldHVybiBkaXY7Cn0KCmZ1bmN0aW9uIHNlbGVjdFdwKHNpLCB3aSkg"
    "ewogIHNlbGVjdGVkV3AgPSB7IHNlZ0lkeDogc2ksIHdwSWR4OiB3aSB9OwogIGJ1aWxkUGFuZWwo"
    "KTsKICByZW5kZXJHbG9iZSgpOwogIGlmICh2aWV3ZXIpIHsKICAgIGNvbnN0IGMgPSBzZWdtZW50"
    "c1tzaV0uY29vcmRzW3dpXTsKICAgIHZpZXdlci5jYW1lcmEuZmx5VG8oewogICAgICBkZXN0aW5h"
    "dGlvbjogQ2VzaXVtLkNhcnRlc2lhbjMuZnJvbURlZ3JlZXMoY1swXSwgY1sxXSwgODAwKSwKICAg"
    "ICAgZHVyYXRpb246IDEuMCwKICAgIH0pOwogIH0KfQoKZnVuY3Rpb24gZGVsZXRlV3Aoc2ksIHdp"
    "KSB7CiAgc2VnbWVudHNbc2ldLmNvb3Jkcy5zcGxpY2Uod2ksIDEpOwogIC8vIFJlbW92ZSBlbXB0"
    "eSBzZWdtZW50cwogIGlmIChzZWdtZW50c1tzaV0uY29vcmRzLmxlbmd0aCA9PT0gMCkgc2VnbWVu"
    "dHMuc3BsaWNlKHNpLCAxKTsKICBpZiAoc2VsZWN0ZWRXcCAmJiAoc2VsZWN0ZWRXcC5zZWdJZHgg"
    "PT09IHNpICYmIHNlbGVjdGVkV3Aud3BJZHggPj0gc2VnbWVudHNbc2ldPy5jb29yZHMubGVuZ3Ro"
    "IHx8IHNlbGVjdGVkV3Auc2VnSWR4ID4gc2kpKSB7CiAgICBzZWxlY3RlZFdwID0gbnVsbDsKICB9"
    "CiAgdXBkYXRlQWxsKCdXYXlwb2ludCBkZWxldGVkLicpOwp9CgpmdW5jdGlvbiB1cGRhdGVBbGwo"
    "bXNnKSB7CiAgYnVpbGRQYW5lbCgpOwogIHJlbmRlckdsb2JlKCk7CiAgdXBkYXRlU3RhdHMoKTsK"
    "ICBpZiAobXNnKSBzZXRTdGF0dXMobXNnLCAnb2snKTsKfQoKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCi8vIExPQUQgSU5JVElBTCBEQVRBCi8v"
    "IOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkApmdW5j"
    "dGlvbiBsb2FkU2VnbWVudHMoc2VncykgewogIHNlZ21lbnRzID0gc2Vncy5tYXAocyA9PiAoewog"
    "ICAgbmFtZTogICBzLm5hbWUgICB8fCAnUm91dGUnLAogICAgY29vcmRzOiAocy5jb29yZHMgfHwg"
    "W10pLm1hcChjID0+IFsKICAgICAgcGFyc2VGbG9hdChjWzBdKSB8fCAwLAogICAgICBwYXJzZUZs"
    "b2F0KGNbMV0pIHx8IDAsCiAgICAgIHBhcnNlRmxvYXQoY1syXSkgfHwgMCwKICAgIF0pCiAgfSkp"
    "OwogIHNlbGVjdGVkV3AgPSBudWxsOyBlZGl0U3RhdGUgPSBudWxsOwogIHVwZGF0ZUFsbCgpOwoK"
    "ICAvLyBGbHkgdG8gZmlyc3QgcG9pbnQKICBpZiAodmlld2VyICYmIHNlZ21lbnRzLmxlbmd0aCAm"
    "JiBzZWdtZW50c1swXS5jb29yZHMubGVuZ3RoKSB7CiAgICBjb25zdCBhbGwgPSBzZWdtZW50cy5m"
    "bGF0TWFwKHMgPT4gcy5jb29yZHMpOwogICAgY29uc3QgcG9zaXRpb25zID0gYWxsLm1hcChjID0+"
    "IENlc2l1bS5DYXJ0ZXNpYW4zLmZyb21EZWdyZWVzKGNbMF0sIGNbMV0sIGNbMl18fDApKTsKICAg"
    "IGlmIChwb3NpdGlvbnMubGVuZ3RoID09PSAxKSB7CiAgICAgIHZpZXdlci5jYW1lcmEuZmx5VG8o"
    "eyBkZXN0aW5hdGlvbjogQ2VzaXVtLkNhcnRlc2lhbjMuZnJvbURlZ3JlZXMoYWxsWzBdWzBdLCBh"
    "bGxbMF1bMV0sIDIwMDApIH0pOwogICAgfSBlbHNlIHsKICAgICAgY29uc3Qgc3BoZXJlID0gQ2Vz"
    "aXVtLkJvdW5kaW5nU3BoZXJlLmZyb21Qb2ludHMocG9zaXRpb25zKTsKICAgICAgY29uc3QgcmFu"
    "Z2UgID0gTWF0aC5tYXgoc3BoZXJlLnJhZGl1cyAqIDMsIDUwMCk7CiAgICAgIHZpZXdlci5jYW1l"
    "cmEuZmx5VG9Cb3VuZGluZ1NwaGVyZShzcGhlcmUsIHsKICAgICAgICBkdXJhdGlvbjogMS41LAog"
    "ICAgICAgIG9mZnNldDogbmV3IENlc2l1bS5IZWFkaW5nUGl0Y2hSYW5nZSgwLCBDZXNpdW0uTWF0"
    "aC50b1JhZGlhbnMoLTQwKSwgcmFuZ2UpLAogICAgICB9KTsKICAgIH0KICB9Cn0KCmlmIChJTklU"
    "SUFMX1NFR01FTlRTICYmIElOSVRJQUxfU0VHTUVOVFMubGVuZ3RoKSB7CiAgbG9hZFNlZ21lbnRz"
    "KElOSVRJQUxfU0VHTUVOVFMpOwogIGNvbnN0IHRvdGFsID0gSU5JVElBTF9TRUdNRU5UUy5yZWR1"
    "Y2UoKG4sIHMpID0+IG4gKyAocy5jb29yZHMgfHwgW10pLmxlbmd0aCwgMCk7CiAgc2V0U3RhdHVz"
    "KGBMb2FkZWQgJHtJTklUSUFMX1NFR01FTlRTLmxlbmd0aH0gc2VnbWVudChzKSwgJHt0b3RhbH0g"
    "d2F5cG9pbnRzLmAsICdvaycpOwp9IGVsc2UgewogIGJ1aWxkUGFuZWwoKTsKICBzZXRTdGF0dXMo"
    "J1JlYWR5IOKAlCB1cGxvYWQgYSBLTVovS01MIG9yIGRyYXcgd2F5cG9pbnRzLicsICcnKTsKfQoK"
    "Ly8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCi8v"
    "IEdMT0JFIENMSUNLIOKAlCBzZWxlY3QgbWFya2VyCi8vIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAppZiAodmlld2VyKSB7CiAgY29uc3QgaGFuZGxl"
    "ciA9IG5ldyBDZXNpdW0uU2NyZWVuU3BhY2VFdmVudEhhbmRsZXIodmlld2VyLmNhbnZhcyk7Cgog"
    "IC8vIExlZnQgY2xpY2sg4oCUIGRyYXcgb3Igc2VsZWN0CiAgaGFuZGxlci5zZXRJbnB1dEFjdGlv"
    "bigoY2xpY2spID0+IHsKICAgIGlmIChkcmF3aW5nTW9kZSkgewogICAgICBjb25zdCBjYXJ0ID0g"
    "dmlld2VyLmNhbWVyYS5waWNrRWxsaXBzb2lkKGNsaWNrLnBvc2l0aW9uLCB2aWV3ZXIuc2NlbmUu"
    "Z2xvYmUuZWxsaXBzb2lkKTsKICAgICAgaWYgKCFDZXNpdW0uZGVmaW5lZChjYXJ0KSkgcmV0dXJu"
    "OwogICAgICBjb25zdCBjYXJ0byA9IHZpZXdlci5zY2VuZS5nbG9iZS5lbGxpcHNvaWQuY2FydGVz"
    "aWFuVG9DYXJ0b2dyYXBoaWMoY2FydCk7CiAgICAgIGNvbnN0IGxvbiA9IENlc2l1bS5NYXRoLnRv"
    "RGVncmVlcyhjYXJ0by5sb25naXR1ZGUpOwogICAgICBjb25zdCBsYXQgPSBDZXNpdW0uTWF0aC50"
    "b0RlZ3JlZXMoY2FydG8ubGF0aXR1ZGUpOwogICAgICAvLyBBZGQgdG8gbGFzdCBzZWdtZW50IG9y"
    "IGNyZWF0ZSBuZXcgb25lCiAgICAgIGlmICghc2VnbWVudHMubGVuZ3RoKSBzZWdtZW50cy5wdXNo"
    "KHsgbmFtZTogJ1JvdXRlIDEnLCBjb29yZHM6IFtdIH0pOwogICAgICBzZWdtZW50c1tzZWdtZW50"
    "cy5sZW5ndGggLSAxXS5jb29yZHMucHVzaChbbG9uLCBsYXQsIDBdKTsKICAgICAgdXBkYXRlQWxs"
    "KGBQbGFjZWQgd2F5cG9pbnQgYXQgJHtsb24udG9GaXhlZCg1KX0sICR7bGF0LnRvRml4ZWQoNSl9"
    "YCk7CiAgICB9IGVsc2UgewogICAgICAvLyBUcnkgdG8gcGljayBhIG1hcmtlciBlbnRpdHkKICAg"
    "ICAgY29uc3QgcGlja2VkID0gdmlld2VyLnNjZW5lLnBpY2soY2xpY2sucG9zaXRpb24pOwogICAg"
    "ICBpZiAoQ2VzaXVtLmRlZmluZWQocGlja2VkKSAmJiBwaWNrZWQuaWQgJiYgcGlja2VkLmlkLl9z"
    "a3lwaG9yU2VnICE9PSB1bmRlZmluZWQpIHsKICAgICAgICBzZWxlY3RXcChwaWNrZWQuaWQuX3Nr"
    "eXBob3JTZWcsIHBpY2tlZC5pZC5fc2t5cGhvcldwKTsKICAgICAgfQogICAgfQogIH0sIENlc2l1"
    "bS5TY3JlZW5TcGFjZUV2ZW50VHlwZS5MRUZUX0NMSUNLKTsKfQoKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCi8vIFNJREVCQVIgVE9PTEJBUgov"
    "LyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKZnVu"
    "Y3Rpb24gc2V0RHJhdyhvbikgewogIGRyYXdpbmdNb2RlID0gb247CiAgZG9jdW1lbnQuZ2V0RWxl"
    "bWVudEJ5SWQoJ2RyYXdCdG4nKS5jbGFzc0xpc3QudG9nZ2xlKCdvbicsIG9uKTsKICBpZiAodmll"
    "d2VyKSB2aWV3ZXIuY2FudmFzLnN0eWxlLmN1cnNvciA9IG9uID8gJ2Nyb3NzaGFpcicgOiAnZGVm"
    "YXVsdCc7CiAgc2V0U3RhdHVzKG9uID8gJ0RyYXcgbW9kZSDigJQgY2xpY2sgZ2xvYmUgdG8gcGxh"
    "Y2Ugd2F5cG9pbnRzLicgOiAnUmVhZHknLCBvbiA/ICdidXN5JyA6ICcnKTsKfQoKZG9jdW1lbnQu"
    "Z2V0RWxlbWVudEJ5SWQoJ2RyYXdCdG4nKS5hZGRFdmVudExpc3RlbmVyKCdjbGljaycsICgpID0+"
    "IHsKICBpZiAoIWRyYXdpbmdNb2RlICYmICFzZWdtZW50cy5sZW5ndGgpIHsKICAgIHNlZ21lbnRz"
    "LnB1c2goeyBuYW1lOiAnUm91dGUgMScsIGNvb3JkczogW10gfSk7CiAgfSBlbHNlIGlmICghZHJh"
    "d2luZ01vZGUpIHsKICAgIHNlZ21lbnRzLnB1c2goeyBuYW1lOiBgUm91dGUgJHtzZWdtZW50cy5s"
    "ZW5ndGggKyAxfWAsIGNvb3JkczogW10gfSk7CiAgfQogIHNldERyYXcoIWRyYXdpbmdNb2RlKTsK"
    "fSk7CmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdmaW5pc2hCdG4nKS5hZGRFdmVudExpc3RlbmVy"
    "KCdjbGljaycsICgpID0+IHNldERyYXcoZmFsc2UpKTsKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQo"
    "J3VuZG9CdG4nKS5hZGRFdmVudExpc3RlbmVyKCdjbGljaycsICgpID0+IHsKICAvLyBSZW1vdmUg"
    "bGFzdCB3YXlwb2ludCBmcm9tIGxhc3Qgbm9uLWVtcHR5IHNlZ21lbnQKICBmb3IgKGxldCBpID0g"
    "c2VnbWVudHMubGVuZ3RoIC0gMTsgaSA+PSAwOyBpLS0pIHsKICAgIGlmIChzZWdtZW50c1tpXS5j"
    "b29yZHMubGVuZ3RoKSB7CiAgICAgIHNlZ21lbnRzW2ldLmNvb3Jkcy5wb3AoKTsKICAgICAgaWYg"
    "KHNlZ21lbnRzW2ldLmNvb3Jkcy5sZW5ndGggPT09IDApIHNlZ21lbnRzLnNwbGljZShpLCAxKTsK"
    "ICAgICAgdXBkYXRlQWxsKCdMYXN0IHdheXBvaW50IHJlbW92ZWQuJyk7CiAgICAgIHJldHVybjsK"
    "ICAgIH0KICB9Cn0pOwpkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnY2xlYXJCdG4nKS5hZGRFdmVu"
    "dExpc3RlbmVyKCdjbGljaycsICgpID0+IHsKICBpZiAoIWNvbmZpcm0oJ0NsZWFyIGFsbCB3YXlw"
    "b2ludHM/JykpIHJldHVybjsKICBzZWdtZW50cyA9IFtdOyBzZWxlY3RlZFdwID0gbnVsbDsgZWRp"
    "dFN0YXRlID0gbnVsbDsKICB1cGRhdGVBbGwoJ0NsZWFyZWQuJyk7CiAgc2V0U3RhdHVzKCdSZWFk"
    "eScsICcnKTsKfSk7CgovLyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZAKLy8gTUFQIFRPT0xCQVIKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCmRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdmaXRCdG4n"
    "KS5hZGRFdmVudExpc3RlbmVyKCdjbGljaycsICgpID0+IHsKICBpZiAoIXZpZXdlcikgcmV0dXJu"
    "OwogIGNvbnN0IGFsbCA9IHNlZ21lbnRzLmZsYXRNYXAocyA9PiBzLmNvb3Jkcyk7CiAgaWYgKCFh"
    "bGwubGVuZ3RoKSByZXR1cm47CiAgY29uc3QgcG9zaXRpb25zID0gYWxsLm1hcChjID0+IENlc2l1"
    "bS5DYXJ0ZXNpYW4zLmZyb21EZWdyZWVzKGNbMF0sIGNbMV0sIGNbMl18fDApKTsKICBjb25zdCBz"
    "cGhlcmUgPSBDZXNpdW0uQm91bmRpbmdTcGhlcmUuZnJvbVBvaW50cyhwb3NpdGlvbnMpOwogIHZp"
    "ZXdlci5jYW1lcmEuZmx5VG9Cb3VuZGluZ1NwaGVyZShzcGhlcmUsIHsKICAgIGR1cmF0aW9uOiAx"
    "LjUsCiAgICBvZmZzZXQ6IG5ldyBDZXNpdW0uSGVhZGluZ1BpdGNoUmFuZ2UoMCwgQ2VzaXVtLk1h"
    "dGgudG9SYWRpYW5zKC00MCksIE1hdGgubWF4KHNwaGVyZS5yYWRpdXMqMywgNTAwKSksCiAgfSk7"
    "Cn0pOwoKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2ZzQnRuJykuYWRkRXZlbnRMaXN0ZW5lcign"
    "Y2xpY2snLCAoKSA9PiB7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FwcCcpLmNsYXNzTGlz"
    "dC50b2dnbGUoJ2Z1bGxzY3JlZW4nKTsKICBpZiAodmlld2VyKSB2aWV3ZXIuZm9yY2VSZXNpemUo"
    "KTsKfSk7CmRvY3VtZW50LmFkZEV2ZW50TGlzdGVuZXIoJ2tleWRvd24nLCBlID0+IHsKICBpZiAo"
    "ZS5rZXkgPT09ICdFc2NhcGUnKSB7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnYXBwJyku"
    "Y2xhc3NMaXN0LnJlbW92ZSgnZnVsbHNjcmVlbicpOwogICAgc2V0RHJhdyhmYWxzZSk7CiAgICBp"
    "ZiAodmlld2VyKSB2aWV3ZXIuZm9yY2VSZXNpemUoKTsKICB9Cn0pOwoKLy8gVGVycmFpbiB0b2dn"
    "bGUKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RlcnJhaW5CdG4nKS5hZGRFdmVudExpc3RlbmVy"
    "KCdjbGljaycsICgpID0+IHsKICBpZiAoIXZpZXdlcikgcmV0dXJuOwogIHRlcnJhaW5PbiA9ICF0"
    "ZXJyYWluT247CiAgaWYgKHRlcnJhaW5PbikgewogICAgdmlld2VyLnRlcnJhaW5Qcm92aWRlciA9"
    "IG5ldyBDZXNpdW0uQ2VzaXVtVGVycmFpblByb3ZpZGVyKHsKICAgICAgdXJsOiBDZXNpdW0uSW9u"
    "UmVzb3VyY2UuZnJvbUFzc2V0SWQoMSksCiAgICB9KTsKICAgIHZpZXdlci5zY2VuZS5nbG9iZS5l"
    "bmFibGVMaWdodGluZyA9IHRydWU7CiAgICB2aWV3ZXIuc2NlbmUuZ2xvYmUuZGVwdGhUZXN0QWdh"
    "aW5zdFRlcnJhaW4gPSB0cnVlOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RlcnJhaW5C"
    "dG4nKS5jbGFzc0xpc3QuYWRkKCdvbicpOwogICAgc2V0U3RhdHVzKCczRCB0ZXJyYWluIGVuYWJs"
    "ZWQuJywgJ29rJyk7CiAgfSBlbHNlIHsKICAgIHZpZXdlci50ZXJyYWluUHJvdmlkZXIgPSBDZXNp"
    "dW0uRWxsaXBzb2lkVGVycmFpblByb3ZpZGVyLklOU1RBTkNFOwogICAgdmlld2VyLnNjZW5lLmds"
    "b2JlLmVuYWJsZUxpZ2h0aW5nID0gZmFsc2U7CiAgICB2aWV3ZXIuc2NlbmUuZ2xvYmUuZGVwdGhU"
    "ZXN0QWdhaW5zdFRlcnJhaW4gPSBmYWxzZTsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0"
    "ZXJyYWluQnRuJykuY2xhc3NMaXN0LnJlbW92ZSgnb24nKTsKICAgIHNldFN0YXR1cygnRmxhdCB0"
    "ZXJyYWluLicsICcnKTsKICB9Cn0pOwoKLy8g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCi8vIERST05FIFNJTVVMQVRJT04KLy8g4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCmRvY3VtZW50LmdldEVsZW1l"
    "bnRCeUlkKCdkcm9uZUJ0bicpLmFkZEV2ZW50TGlzdGVuZXIoJ2NsaWNrJywgKCkgPT4gewogIGlm"
    "ICghdmlld2VyKSByZXR1cm47CiAgY29uc3QgYWxsID0gc2VnbWVudHMuZmxhdE1hcChzID0+IHMu"
    "Y29vcmRzKTsKICBpZiAoYWxsLmxlbmd0aCA8IDIpIHsgc2V0U3RhdHVzKCdOZWVkIGF0IGxlYXN0"
    "IDIgd2F5cG9pbnRzIHRvIHNpbXVsYXRlLicsICdlcnInKTsgcmV0dXJuOyB9CiAgaWYgKGRyb25l"
    "RW50KSBzdG9wRHJvbmUoKTsKCiAgY29uc3Qgc3RhcnQgPSBDZXNpdW0uSnVsaWFuRGF0ZS5ub3co"
    "KSwgc2VjcyA9IDM7CiAgY29uc3Qgc3RvcCAgPSBDZXNpdW0uSnVsaWFuRGF0ZS5hZGRTZWNvbmRz"
    "KHN0YXJ0LCBhbGwubGVuZ3RoICogc2VjcywgbmV3IENlc2l1bS5KdWxpYW5EYXRlKCkpOwogIGNv"
    "bnN0IHByb3AgID0gbmV3IENlc2l1bS5TYW1wbGVkUG9zaXRpb25Qcm9wZXJ0eSgpOwogIGFsbC5m"
    "b3JFYWNoKChjLCBpKSA9PiB7CiAgICBjb25zdCB0ID0gQ2VzaXVtLkp1bGlhbkRhdGUuYWRkU2Vj"
    "b25kcyhzdGFydCwgaSAqIHNlY3MsIG5ldyBDZXNpdW0uSnVsaWFuRGF0ZSgpKTsKICAgIHByb3Au"
    "YWRkU2FtcGxlKHQsIENlc2l1bS5DYXJ0ZXNpYW4zLmZyb21EZWdyZWVzKGNbMF0sIGNbMV0sIChj"
    "WzJdfHwwKSArIDgwKSk7CiAgfSk7CiAgZHJvbmVFbnQgPSB2aWV3ZXIuZW50aXRpZXMuYWRkKHsK"
    "ICAgIGF2YWlsYWJpbGl0eTogbmV3IENlc2l1bS5UaW1lSW50ZXJ2YWxDb2xsZWN0aW9uKFtuZXcg"
    "Q2VzaXVtLlRpbWVJbnRlcnZhbCh7c3RhcnQsc3RvcH0pXSksCiAgICBwb3NpdGlvbjogcHJvcCwK"
    "ICAgIHBvaW50OiB7IHBpeGVsU2l6ZToxNCwgY29sb3I6Q2VzaXVtLkNvbG9yLmZyb21Dc3NDb2xv"
    "clN0cmluZygnI2ZiYmYyNCcpLCBvdXRsaW5lQ29sb3I6Q2VzaXVtLkNvbG9yLkJMQUNLLCBvdXRs"
    "aW5lV2lkdGg6MiwgZGlzYWJsZURlcHRoVGVzdERpc3RhbmNlOk51bWJlci5QT1NJVElWRV9JTkZJ"
    "TklUWSB9LAogICAgbGFiZWw6IHsgdGV4dDon4pyIJywgZm9udDonMjBweCBzYW5zLXNlcmlmJywg"
    "ZmlsbENvbG9yOkNlc2l1bS5Db2xvci5mcm9tQ3NzQ29sb3JTdHJpbmcoJyNmYmJmMjQnKSwgdmVy"
    "dGljYWxPcmlnaW46Q2VzaXVtLlZlcnRpY2FsT3JpZ2luLkJPVFRPTSwgZGlzYWJsZURlcHRoVGVz"
    "dERpc3RhbmNlOk51bWJlci5QT1NJVElWRV9JTkZJTklUWSB9LAogICAgcGF0aDogeyBzaG93OnRy"
    "dWUsIGxlYWRUaW1lOjAsIHRyYWlsVGltZTo0MCwgd2lkdGg6MiwgbWF0ZXJpYWw6bmV3IENlc2l1"
    "bS5Qb2x5bGluZUdsb3dNYXRlcmlhbFByb3BlcnR5KHtnbG93UG93ZXI6MC4zLHRhcGVyUG93ZXI6"
    "MS4wLGNvbG9yOkNlc2l1bS5Db2xvci5mcm9tQ3NzQ29sb3JTdHJpbmcoJyNmYmJmMjQnKX0pIH0s"
    "CiAgfSk7CiAgdmlld2VyLmNsb2NrLnN0YXJ0VGltZT1zdGFydDsgdmlld2VyLmNsb2NrLnN0b3BU"
    "aW1lPXN0b3A7IHZpZXdlci5jbG9jay5jdXJyZW50VGltZT1zdGFydDsKICB2aWV3ZXIuY2xvY2su"
    "bXVsdGlwbGllcj0xOyB2aWV3ZXIuY2xvY2suc2hvdWxkQW5pbWF0ZT10cnVlOyB2aWV3ZXIuY2xv"
    "Y2suY2xvY2tSYW5nZT1DZXNpdW0uQ2xvY2tSYW5nZS5MT09QX1NUT1A7CiAgdmlld2VyLnRyYWNr"
    "ZWRFbnRpdHk9ZHJvbmVFbnQ7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Ryb25lQnRuJyku"
    "c3R5bGUuZGlzcGxheT0nbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0b3BCdG4n"
    "KS5zdHlsZS5kaXNwbGF5PSdpbmxpbmUtZmxleCc7CiAgc2V0U3RhdHVzKCdEcm9uZSBzaW11bGF0"
    "aW9uIHJ1bm5pbmcuLi4nLCAnYnVzeScpOwp9KTsKZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0"
    "b3BCdG4nKS5hZGRFdmVudExpc3RlbmVyKCdjbGljaycsIHN0b3BEcm9uZSk7CmZ1bmN0aW9uIHN0"
    "b3BEcm9uZSgpIHsKICBpZiAoZHJvbmVFbnQpIHsgdmlld2VyLmVudGl0aWVzLnJlbW92ZShkcm9u"
    "ZUVudCk7IGRyb25lRW50PW51bGw7IH0KICBpZiAodmlld2VyKSB7IHZpZXdlci50cmFja2VkRW50"
    "aXR5PXVuZGVmaW5lZDsgdmlld2VyLmNsb2NrLnNob3VsZEFuaW1hdGU9ZmFsc2U7IH0KICBkb2N1"
    "bWVudC5nZXRFbGVtZW50QnlJZCgnZHJvbmVCdG4nKS5zdHlsZS5kaXNwbGF5PSdpbmxpbmUtZmxl"
    "eCc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3N0b3BCdG4nKS5zdHlsZS5kaXNwbGF5PSdu"
    "b25lJzsKICBzZXRTdGF0dXMoJ1NpbXVsYXRpb24gc3RvcHBlZC4nLCAnJyk7Cn0KCi8vIOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAovLyBFWFBPUlQg"
    "S01aCi8vIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kApkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZXhwb3J0QnRuJykuYWRkRXZlbnRMaXN0ZW5lcign"
    "Y2xpY2snLCAoKSA9PiB7CiAgaWYgKCFzZWdtZW50cy5sZW5ndGgpIHsgc2V0U3RhdHVzKCdOb3Ro"
    "aW5nIHRvIGV4cG9ydC4nLCAnZXJyJyk7IHJldHVybjsgfQoKICAvLyBCdWlsZCBLTUwgc3RyaW5n"
    "CiAgbGV0IHBsYWNlbWFya3MgPSAnJzsKICBzZWdtZW50cy5mb3JFYWNoKChzZWcsIHNpKSA9PiB7"
    "CiAgICBpZiAoIXNlZy5jb29yZHMubGVuZ3RoKSByZXR1cm47CiAgICBjb25zdCBjb29yZFN0ciA9"
    "IHNlZy5jb29yZHMubWFwKGMgPT4gYCR7Y1swXX0sJHtjWzFdfSwke2NbMl18fDB9YCkuam9pbign"
    "ICcpOwogICAgcGxhY2VtYXJrcyArPSBgCiAgICA8UGxhY2VtYXJrPgogICAgICA8bmFtZT4ke3Nl"
    "Zy5uYW1lfTwvbmFtZT4KICAgICAgPExpbmVTdHJpbmc+CiAgICAgICAgPGFsdGl0dWRlTW9kZT5h"
    "YnNvbHV0ZTwvYWx0aXR1ZGVNb2RlPgogICAgICAgIDxjb29yZGluYXRlcz4ke2Nvb3JkU3RyfTwv"
    "Y29vcmRpbmF0ZXM+CiAgICAgIDwvTGluZVN0cmluZz4KICAgIDwvUGxhY2VtYXJrPmA7CiAgfSk7"
    "CiAgY29uc3Qga21sID0gYDw/eG1sIHZlcnNpb249IjEuMCIgZW5jb2Rpbmc9IlVURi04Ij8+Cjxr"
    "bWwgeG1sbnM9Imh0dHA6Ly93d3cub3Blbmdpcy5uZXQva21sLzIuMiI+CiAgPERvY3VtZW50Pgog"
    "ICAgPG5hbWU+U2t5cGhvciBGbGlnaHQgUGxhbjwvbmFtZT4ke3BsYWNlbWFya3N9CiAgPC9Eb2N1"
    "bWVudD4KPC9rbWw+YDsKCiAgLy8gRG93bmxvYWQgYXMgLmttbCAoYnJvd3NlcnMgY2FuJ3QgY3Jl"
    "YXRlIFpJUCBuYXRpdmVseSB3aXRob3V0IGEgbGlicmFyeSkKICBjb25zdCBibG9iID0gbmV3IEJs"
    "b2IoW2ttbF0sIHt0eXBlOidhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWVhcnRoLmttbCt4bWwnfSk7"
    "CiAgY29uc3QgdXJsICA9IFVSTC5jcmVhdGVPYmplY3RVUkwoYmxvYik7CiAgY29uc3QgYSAgICA9"
    "IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2EnKTsKICBhLmhyZWYgPSB1cmw7IGEuZG93bmxvYWQg"
    "PSAnc2t5cGhvcl9mbGlnaHRfcGxhbi5rbWwnOwogIGEuY2xpY2soKTsgVVJMLnJldm9rZU9iamVj"
    "dFVSTCh1cmwpOwogIHNldFN0YXR1cygnS01MIGV4cG9ydGVkLicsICdvaycpOwp9KTsKPC9zY3Jp"
    "cHQ+CjwvYm9keT4KPC9odG1sPg=="
)




# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Skyphor", page_icon="✈", layout="wide")
st.title("✈ Skyphor")
st.caption("presented by Charlie Brooks")

# ── Session state init ────────────────────────────────────────────────────────
if "segments" not in st.session_state:
    st.session_state.segments = []

# ── Upload / input row ────────────────────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns([1, 1])

with col1:
    uploaded = st.file_uploader(
        "📁 Upload KMZ or KML file",
        type=["kmz", "kml"],
        help="Supports multi-segment KMZ files — all named routes will appear in the flight plan panel."
    )

with col2:
    coords_text = st.text_area(
        "Or paste lon,lat pairs (one per line)",
        placeholder="-87.6298,41.8781\n-87.6350,41.8800\n-87.6400,41.8820",
        height=130,
    )

# ── Parse KMZ / KML ──────────────────────────────────────────────────────────
if uploaded is not None:
    try:
        raw = uploaded.read()
        if uploaded.name.lower().endswith(".kmz"):
            segs = parse_kmz_structured(raw)
        else:
            segs = parse_kml_file(raw)

        st.session_state.segments = segs
        stats = route_stats(segs)
        st.success(
            f"✅ Loaded **{uploaded.name}** — "
            f"{len(segs)} segment(s), "
            f"{stats['total_pts']} waypoints, "
            f"{stats['total_km']:.1f} km total route distance."
        )

        # Show segment breakdown
        with st.expander(f"📋 Route segments ({len(segs)})", expanded=False):
            for i, seg in enumerate(segs):
                color_labels = ["🔵","🟢","🟡","🟠","🟣","🔴","⚪"]
                lbl = color_labels[i % len(color_labels)]
                st.markdown(
                    f"{lbl} **{seg['name']}** — {len(seg['coords'])} waypoints  "
                    f"  Start: `{seg['coords'][0][0]:.5f}, {seg['coords'][0][1]:.5f}`"
                )

    except Exception as e:
        st.error(f"❌ Failed to parse file: {e}")

# ── Parse manual coords ───────────────────────────────────────────────────────
elif coords_text.strip():
    try:
        pts = []
        for line in coords_text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 2:
                raise ValueError(f"Bad line: {line!r}")
            lon = float(parts[0].strip())
            lat = float(parts[1].strip())
            alt = float(parts[2].strip()) if len(parts) > 2 else 0.0
            pts.append([lon, lat, alt])
        if len(pts) < 2:
            raise ValueError("Need at least 2 coordinate pairs.")
        st.session_state.segments = [{"name": "Manual Route", "coords": pts}]
        st.success(f"✅ {len(pts)} manual waypoints loaded.")
    except Exception as e:
        st.error(f"❌ Could not parse coordinates: {e}")

# ── Render Cesium ─────────────────────────────────────────────────────────────
segments_json = json.dumps(st.session_state.segments)
html_str = _build_cesium_html(segments_json)
components_html(html_str, height=700, scrolling=False)