"""Skyphor — LiDAR Mission Planner
Streamlit Cloud entry point.
presented by Charlie Brooks
"""

from __future__ import annotations  # enables List[List[float]] on Python 3.8

import io
import json
import re
import zipfile
from typing import List

import streamlit as st
from streamlit.components.v1 import html as components_html


# ---------------------------------------------------------------------------
# KMZ / KML parsing  (pure stdlib — no external deps)
# ---------------------------------------------------------------------------

def _parse_kml_coords(kml_text: str) -> List[List[float]]:
    """Extract coordinates from KML text → [[lon, lat, alt], ...]."""
    blocks = re.findall(r"<coordinates[^>]*>(.*?)</coordinates>", kml_text, re.DOTALL)
    coords: List[List[float]] = []
    for block in blocks:
        for token in block.strip().split():
            parts = token.strip().split(",")
            if len(parts) >= 2:
                try:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    alt = float(parts[2]) if len(parts) > 2 else 0.0
                    coords.append([lon, lat, alt])
                except ValueError:
                    pass
    return coords


def parse_kmz(raw_bytes: bytes) -> dict:
    """Parse a KMZ file → GeoJSON LineString dict."""
    coords: List[List[float]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            for name in kml_names:
                kml_text = z.read(name).decode("utf-8", errors="replace")
                coords.extend(_parse_kml_coords(kml_text))
    except Exception as exc:
        raise ValueError(f"Could not read KMZ: {exc}") from exc

    if not coords:
        raise ValueError("No coordinates found in KMZ file.")

    return {"type": "LineString", "coordinates": coords}


def parse_kml_file(raw_bytes: bytes) -> dict:
    """Parse a plain KML file → GeoJSON LineString dict."""
    kml_text = raw_bytes.decode("utf-8", errors="replace")
    coords = _parse_kml_coords(kml_text)
    if not coords:
        raise ValueError("No coordinates found in KML file.")
    return {"type": "LineString", "coordinates": coords}


# ---------------------------------------------------------------------------
# Embed Skyphor HTML
# ---------------------------------------------------------------------------

def _load_skyphor_html() -> str:
    """
    Load the Skyphor HTML app.
    Looks for index.html next to app.py (standard GitHub Pages layout).
    Falls back to a minimal placeholder if not found.
    """
    import os
    # Try index.html in same directory as app.py
    base = os.path.dirname(os.path.abspath(__file__))
    for candidate in ["index.html", "Skyphor_-_FV.html", "skyphor_v4.html"]:
        path = os.path.join(base, candidate)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return "<p style='color:red;font-family:sans-serif'>index.html not found next to app.py</p>"


# ---------------------------------------------------------------------------
# Streamlit page config  (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Skyphor — LiDAR Mission Planner",
    page_icon="🛸",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Hide Streamlit's default menu/footer for a clean embed
st.markdown("""
<style>
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }
  .block-container { padding: 0 !important; max-width: 100% !important; }
  iframe { border: none !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Render the Skyphor app fullscreen inside Streamlit
# ---------------------------------------------------------------------------

html_content = _load_skyphor_html()
components_html(html_content, height=900, scrolling=False)