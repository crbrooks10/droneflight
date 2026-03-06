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

def _build_cesium_html(segments_json_str: str) -> str:
    """
    Build a self-contained Cesium page.
    segments_json_str: JSON string of [{"name":str, "coords":[[lon,lat,alt],...]}]
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cesium.com/downloads/cesiumjs/releases/1.114/Build/Cesium/Cesium.js"></script>
  <link href="https://cesium.com/downloads/cesiumjs/releases/1.114/Build/Cesium/Widgets/widgets.css" rel="stylesheet"/>
  <style>
    :root {{
      --bg:      #080d14;
      --panel:   #0d1421;
      --card:    #111d2f;
      --card2:   #162237;
      --border:  rgba(255,255,255,0.07);
      --bhi:     rgba(255,255,255,0.14);
      --blue:    #3b7ff5;
      --teal:    #2dd4bf;
      --amber:   #fbbf24;
      --red:     #f87171;
      --green:   #4ade80;
      --text:    #dce6f0;
      --text2:   #7a9ab8;
      --text3:   #3a5472;
      --r:       10px;
      --rs:      6px;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      height: 100%; font-family: 'Syne', sans-serif;
      background: var(--bg); color: var(--text); overflow: hidden;
    }}

    /* ── Shell ── */
    #app {{ display: flex; height: 100vh; }}
    #app.fullscreen {{ position: fixed; inset: 0; z-index: 9999; }}

    /* ── Sidebar ── */
    #sidebar {{
      flex: 0 0 300px;
      display: flex; flex-direction: column;
      background: var(--panel);
      border-right: 1px solid var(--border);
      overflow: hidden;
    }}

    .sidebar-head {{
      padding: 16px 18px 14px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .brand {{ display: flex; align-items: center; gap: 11px; margin-bottom: 2px; }}
    .brand-icon {{
      width: 36px; height: 36px; border-radius: 10px;
      background: linear-gradient(135deg, #1557e8, #0ca6e8);
      display: flex; align-items: center; justify-content: center;
      font-size: 18px; flex-shrink: 0;
      box-shadow: 0 3px 14px rgba(59,127,245,.4);
    }}
    .brand h1 {{ font-size: 15px; font-weight: 700; letter-spacing: -.2px; }}
    .brand p  {{ font-size: 10px; color: var(--text3); letter-spacing: .7px; text-transform: uppercase; margin-top: 2px; }}

    /* Toolbar strip inside sidebar */
    .sb-toolbar {{
      display: flex; gap: 5px;
      padding: 10px 18px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .sb-btn {{
      flex: 1; padding: 7px 6px;
      font-family: 'Syne', sans-serif; font-size: 11px; font-weight: 600;
      background: var(--card); color: var(--text2);
      border: 1px solid var(--border); border-radius: var(--rs);
      cursor: pointer; transition: all .15s; white-space: nowrap;
    }}
    .sb-btn:hover {{ background: var(--card2); color: var(--text); }}
    .sb-btn.danger {{ color: var(--red); border-color: rgba(248,113,113,.2); }}
    .sb-btn.danger:hover {{ background: rgba(248,113,113,.1); }}

    /* Route info strip */
    #routeInfo {{
      padding: 8px 18px;
      border-bottom: 1px solid var(--border);
      font-size: 11px; color: var(--text3);
      display: flex; gap: 16px; flex-shrink: 0;
    }}
    #routeInfo span {{ color: var(--text2); font-weight: 600; font-family: 'IBM Plex Mono', monospace; }}

    /* Segments + waypoints list */
    #flightPlan {{
      flex: 1; overflow-y: auto;
      padding: 10px 12px;
    }}
    #flightPlan::-webkit-scrollbar {{ width: 4px; }}
    #flightPlan::-webkit-scrollbar-thumb {{ background: var(--card2); border-radius: 4px; }}

    .empty-hint {{
      padding: 32px 12px; text-align: center; color: var(--text3);
    }}
    .empty-hint .ei {{ font-size: 32px; opacity: .2; margin-bottom: 10px; }}
    .empty-hint p {{ font-size: 12px; line-height: 1.6; }}

    /* Segment group */
    .seg-group {{ margin-bottom: 10px; }}
    .seg-header {{
      display: flex; align-items: center; gap: 8px;
      padding: 9px 11px; margin-bottom: 4px;
      background: var(--card); border: 1px solid var(--border);
      border-radius: var(--r); cursor: pointer; user-select: none;
      transition: border-color .2s;
    }}
    .seg-header:hover {{ border-color: var(--bhi); }}
    .seg-header.open {{ border-color: var(--blue); }}
    .seg-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
    .seg-name {{ flex: 1; font-size: 12.5px; font-weight: 600; }}
    .seg-count {{
      font-size: 10px; color: var(--text3);
      background: var(--card2); padding: 2px 8px; border-radius: 20px;
    }}
    .seg-chev {{ font-size: 11px; color: var(--text3); transition: transform .2s; }}
    .seg-header.open .seg-chev {{ transform: rotate(90deg); }}

    .seg-wps {{ display: none; padding-left: 4px; }}
    .seg-header.open + .seg-wps {{ display: block; }}

    /* Waypoint row */
    .wp-row {{
      display: flex; align-items: center; gap: 6px;
      padding: 7px 10px; margin-bottom: 3px;
      background: var(--card); border: 1px solid var(--border);
      border-radius: var(--rs);
      transition: border-color .15s;
      cursor: pointer;
    }}
    .wp-row:hover {{ border-color: var(--bhi); }}
    .wp-row.selected {{ border-color: var(--amber); background: rgba(251,191,36,.05); }}

    .wp-num {{
      width: 22px; height: 22px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-size: 10px; font-weight: 700; flex-shrink: 0;
      color: #000;
    }}
    .wp-coords {{
      flex: 1; font-family: 'IBM Plex Mono', monospace;
      font-size: 9.5px; line-height: 1.6; color: var(--text2);
    }}
    .wp-alt {{
      font-family: 'IBM Plex Mono', monospace;
      font-size: 9px; color: var(--text3); white-space: nowrap;
    }}
    .wp-actions {{ display: flex; gap: 3px; }}
    .wp-del {{
      width: 22px; height: 22px; border-radius: 4px;
      background: rgba(248,113,113,.08); color: var(--red);
      border: none; cursor: pointer; font-size: 11px;
      display: flex; align-items: center; justify-content: center;
      transition: background .15s;
    }}
    .wp-del:hover {{ background: rgba(248,113,113,.2); }}

    /* Inline edit row */
    .wp-edit-row {{
      padding: 8px 10px; margin-bottom: 3px;
      background: rgba(59,127,245,.06);
      border: 1px solid var(--blue); border-radius: var(--rs);
    }}
    .wp-edit-row label {{ font-size: 9px; color: var(--text3); display: block; margin-bottom: 3px; letter-spacing: .5px; text-transform: uppercase; }}
    .wp-edit-inputs {{ display: flex; gap: 5px; margin-bottom: 7px; }}
    .wp-edit-inputs input {{
      flex: 1; padding: 5px 7px;
      font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--text);
      background: var(--card); border: 1px solid var(--border); border-radius: 4px;
      outline: none;
    }}
    .wp-edit-inputs input:focus {{ border-color: var(--blue); }}
    .wp-edit-btns {{ display: flex; gap: 5px; }}
    .wp-save-btn {{
      flex: 1; padding: 6px; font-size: 11px; font-weight: 600;
      font-family: 'Syne', sans-serif;
      background: rgba(59,127,245,.15); color: var(--blue);
      border: 1px solid rgba(59,127,245,.3); border-radius: 4px; cursor: pointer;
    }}
    .wp-save-btn:hover {{ background: rgba(59,127,245,.25); }}
    .wp-cancel-btn {{
      padding: 6px 10px; font-size: 11px; font-weight: 600;
      font-family: 'Syne', sans-serif;
      background: var(--card); color: var(--text3);
      border: 1px solid var(--border); border-radius: 4px; cursor: pointer;
    }}

    /* Export button */
    #exportRow {{
      padding: 10px 12px;
      border-top: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .export-btn {{
      width: 100%; padding: 9px;
      font-family: 'Syne', sans-serif; font-size: 12px; font-weight: 700;
      background: rgba(45,212,191,.1); color: var(--teal);
      border: 1px solid rgba(45,212,191,.25); border-radius: var(--rs);
      cursor: pointer; transition: background .15s;
    }}
    .export-btn:hover {{ background: rgba(45,212,191,.18); }}

    /* Status */
    #statusBar {{
      padding: 10px 18px; border-top: 1px solid var(--border);
      font-size: 11.5px; color: var(--text2); background: var(--panel);
      display: flex; align-items: center; gap: 8px; min-height: 40px; flex-shrink: 0;
    }}
    #sDot {{
      width: 6px; height: 6px; border-radius: 50%;
      background: var(--text3); flex-shrink: 0; transition: background .3s;
    }}
    #sDot.ok   {{ background: var(--green); }}
    #sDot.err  {{ background: var(--red); }}
    #sDot.busy {{ background: var(--amber); animation: blink 1s infinite; }}
    @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}

    /* ── Map area ── */
    #mapArea {{ flex: 1; display: flex; flex-direction: column; min-width: 0; }}

    #toolbar {{
      display: flex; align-items: center; height: 50px;
      padding: 0 14px; gap: 2px;
      background: var(--panel); border-bottom: 1px solid var(--border);
      flex-shrink: 0; flex-wrap: wrap;
    }}
    .tg {{
      display: flex; align-items: center; gap: 2px;
      height: 100%; padding: 0 8px;
      border-right: 1px solid var(--border);
    }}
    .tg:last-child {{ border-right: none; }}
    .tg-lbl {{
      font-size: 9px; font-weight: 700; letter-spacing: .8px;
      text-transform: uppercase; color: var(--text3); margin-right: 4px;
    }}
    .tbtn {{
      display: inline-flex; align-items: center; gap: 5px;
      padding: 6px 11px;
      font-family: 'Syne', sans-serif; font-size: 11.5px; font-weight: 600;
      color: var(--text2); background: transparent;
      border: 1px solid transparent; border-radius: var(--rs);
      cursor: pointer; white-space: nowrap; transition: all .15s;
    }}
    .tbtn:hover {{ background: var(--card); color: var(--text); border-color: var(--bhi); }}
    .tbtn.on  {{ background: rgba(74,222,128,.1); color: var(--green); border-color: rgba(74,222,128,.25); }}
    .tbtn.red {{ background: rgba(248,113,113,.08); color: var(--red); border-color: rgba(248,113,113,.2); }}
    .tbtn.red:hover {{ background: rgba(248,113,113,.15); }}

    #cesiumContainer {{ flex: 1; position: relative; }}
  </style>
</head>
<body>
<div id="app">

  <!-- ═══ SIDEBAR ═══ -->
  <div id="sidebar">

    <div class="sidebar-head">
      <div class="brand">
        <div class="brand-icon">✈</div>
        <div>
          <h1>Skyphor</h1>
          <p>Flight Plan Editor</p>
        </div>
      </div>
    </div>

    <div class="sb-toolbar">
      <button class="sb-btn" id="drawBtn">✏ Draw</button>
      <button class="sb-btn" id="finishBtn">✓ Finish</button>
      <button class="sb-btn" id="undoBtn">↶ Undo</button>
      <button class="sb-btn danger" id="clearBtn">✕ Clear</button>
    </div>

    <div id="routeInfo">
      <div>Waypoints: <span id="wpTotal">0</span></div>
      <div>Distance: <span id="wpDist">0 km</span></div>
    </div>

    <div id="flightPlan">
      <div class="empty-hint">
        <div class="ei">🗺️</div>
        <p>Upload a KMZ/KML file or paste coordinates — your flight plan will appear here for editing</p>
      </div>
    </div>

    <div id="exportRow">
      <button class="export-btn" id="exportBtn">⬇ Export KMZ</button>
    </div>

    <div id="statusBar">
      <div id="sDot"></div>
      <span id="sTxt">Ready</span>
    </div>

  </div>

  <!-- ═══ MAP ═══ -->
  <div id="mapArea">
    <div id="toolbar">

      <div class="tg">
        <span class="tg-lbl">View</span>
        <button class="tbtn" id="fitBtn">⊡ Fit</button>
        <button class="tbtn" id="fsBtn">⛶ Fullscreen</button>
      </div>

      <div class="tg">
        <span class="tg-lbl">Drone</span>
        <button class="tbtn" id="droneBtn">▶ Simulate</button>
        <button class="tbtn red" id="stopBtn" style="display:none;">⏹ Stop</button>
      </div>

      <div class="tg">
        <span class="tg-lbl">Terrain</span>
        <button class="tbtn" id="terrainBtn">⛰ 3D Terrain</button>
      </div>

    </div>
    <div id="cesiumContainer"></div>
  </div>

</div>
<script>
'use strict';

// ═══════════════════════════════════════════════════════
// PHASE 1 DATA — injected from Python structured parser
// ═══════════════════════════════════════════════════════
const INITIAL_SEGMENTS = {segments_json_str};

// ═══════════════════════════════════════════════════════
// CESIUM INIT
// ═══════════════════════════════════════════════════════
Cesium.Ion.defaultAccessToken = '';
const _cs = document.createElement('div');
let viewer;
try {{
  viewer = new Cesium.Viewer('cesiumContainer', {{
    terrainProvider: Cesium.EllipsoidTerrainProvider.INSTANCE,
    animation: false, baseLayerPicker: false, geocoder: false,
    homeButton: false, sceneModePicker: false,
    navigationHelpButton: false, fullscreenButton: false,
    timeline: false, creditContainer: _cs,
  }});
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#06090f');
}} catch (e) {{
  console.error('Cesium init:', e);
  viewer = null;
}}

// ═══════════════════════════════════════════════════════
// STATE — single source of truth
// ═══════════════════════════════════════════════════════
// segments: [{{ name, coords: [[lon,lat,alt],...] }}, ...]
// editState: {{ segIdx, wpIdx }} | null
let segments    = [];
let selectedWp  = null;  // {{ segIdx, wpIdx }}
let editState   = null;
let drawingMode = false;
let pathEntities= [];
let markerEntities = [];
let droneEnt    = null;
let terrainOn   = false;

const COLORS = ['#3b7ff5','#2dd4bf','#fbbf24','#f472b6','#a78bfa','#fb923c','#4ade80'];

// ═══════════════════════════════════════════════════════
// STATUS
// ═══════════════════════════════════════════════════════
function setStatus(msg, type) {{
  document.getElementById('sTxt').textContent = msg;
  const d = document.getElementById('sDot');
  d.className = type || '';
}}

// ═══════════════════════════════════════════════════════
// GLOBE — render / clear
// ═══════════════════════════════════════════════════════
function clearGlobe() {{
  if (!viewer) return;
  [...pathEntities, ...markerEntities].forEach(e => viewer.entities.remove(e));
  pathEntities = []; markerEntities = [];
}}

function renderGlobe() {{
  clearGlobe();
  if (!viewer) return;

  segments.forEach((seg, si) => {{
    const color = Cesium.Color.fromCssColorString(COLORS[si % COLORS.length]);

    if (seg.coords.length >= 2) {{
      const positions = seg.coords.map(c => Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2] || 0));
      pathEntities.push(viewer.entities.add({{
        polyline: {{
          positions,
          width: 3,
          material: new Cesium.PolylineGlowMaterialProperty({{
            glowPower: 0.25, taperPower: 1.0, color,
          }}),
          clampToGround: false,
        }}
      }}));
    }}

    seg.coords.forEach((c, wi) => {{
      const isSel = selectedWp && selectedWp.segIdx === si && selectedWp.wpIdx === wi;
      const ent = viewer.entities.add({{
        position: Cesium.Cartesian3.fromDegrees(c[0], c[1], (c[2] || 0) + 8),
        point: {{
          pixelSize: isSel ? 13 : 8,
          color: isSel ? Cesium.Color.fromCssColorString('#fbbf24') : color,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: isSel ? 2.5 : 1.5,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        }},
        label: {{
          text: String(wi + 1),
          font: '10px "IBM Plex Mono", monospace',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -5),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          show: seg.coords.length <= 80,
        }},
      }});
      // store identity for click detection
      ent._skyphorSeg = si;
      ent._skyphorWp  = wi;
      markerEntities.push(ent);
    }});
  }});
}}

// ═══════════════════════════════════════════════════════
// STATS
// ═══════════════════════════════════════════════════════
function haversineKm(lon1, lat1, lon2, lat2) {{
  const R = 6371, toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad, dLon = (lon2 - lon1) * toRad;
  const a = Math.sin(dLat/2)**2 + Math.cos(lat1*toRad)*Math.cos(lat2*toRad)*Math.sin(dLon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(a));
}}

function updateStats() {{
  let total = 0, dist = 0, prev = null;
  segments.forEach(seg => {{
    total += seg.coords.length;
    seg.coords.forEach(c => {{
      if (prev) dist += haversineKm(prev[0], prev[1], c[0], c[1]);
      prev = c;
    }});
  }});
  document.getElementById('wpTotal').textContent = total;
  document.getElementById('wpDist').textContent  = dist.toFixed(1) + ' km';
}}

// ═══════════════════════════════════════════════════════
// PHASE 2 — FLIGHT PLAN PANEL
// ═══════════════════════════════════════════════════════
function buildPanel() {{
  const fp = document.getElementById('flightPlan');
  fp.innerHTML = '';

  if (!segments.length) {{
    fp.innerHTML = '<div class="empty-hint"><div class="ei">🗺️</div><p>Upload a KMZ/KML file or paste coordinates to edit your flight plan</p></div>';
    return;
  }}

  segments.forEach((seg, si) => {{
    const color = COLORS[si % COLORS.length];
    const group = document.createElement('div');
    group.className = 'seg-group';
    group.dataset.si = si;

    // Segment header
    const hdr = document.createElement('div');
    hdr.className = 'seg-header open';
    hdr.innerHTML = `
      <span class="seg-dot" style="background:${{color}}"></span>
      <span class="seg-name">${{escHtml(seg.name)}}</span>
      <span class="seg-count">${{seg.coords.length}} pts</span>
      <span class="seg-chev">›</span>`;
    hdr.addEventListener('click', () => {{
      hdr.classList.toggle('open');
      wpsDiv.style.display = hdr.classList.contains('open') ? 'block' : 'none';
    }});
    group.appendChild(hdr);

    // Waypoints container
    const wpsDiv = document.createElement('div');
    wpsDiv.className = 'seg-wps';
    wpsDiv.style.display = 'block';

    seg.coords.forEach((c, wi) => {{
      wpsDiv.appendChild(makeWpRow(si, wi, c, color));
    }});

    group.appendChild(wpsDiv);
    fp.appendChild(group);
  }});

  updateStats();
}}

function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function makeWpRow(si, wi, c, color) {{
  // If this waypoint is in edit mode, render the edit form instead
  if (editState && editState.segIdx === si && editState.wpIdx === wi) {{
    return makeEditRow(si, wi, c);
  }}

  const isSel = selectedWp && selectedWp.segIdx === si && selectedWp.wpIdx === wi;
  const div = document.createElement('div');
  div.className = 'wp-row' + (isSel ? ' selected' : '');

  const altM = c[2] ? c[2].toFixed(0) + 'm' : '0m';
  const altFt = c[2] ? (c[2] * 3.28084).toFixed(0) + 'ft' : '0ft';

  div.innerHTML = `
    <span class="wp-num" style="background:${{color}}">${{wi + 1}}</span>
    <span class="wp-coords">${{c[0].toFixed(5)}}<br>${{c[1].toFixed(5)}}</span>
    <span class="wp-alt">${{altFt}}<br>${{altM}}</span>
    <span class="wp-actions">
      <button class="wp-del" title="Edit waypoint">✎</button>
      <button class="wp-del" title="Delete waypoint" style="color:var(--red)">✕</button>
    </span>`;

  // Click row to fly there and select
  div.addEventListener('click', (e) => {{
    if (e.target.closest('.wp-actions')) return;
    selectWp(si, wi);
  }});

  const btns = div.querySelectorAll('.wp-del');
  // Edit button
  btns[0].addEventListener('click', (e) => {{
    e.stopPropagation();
    editState = {{ segIdx: si, wpIdx: wi }};
    buildPanel();
  }});
  // Delete button
  btns[1].addEventListener('click', (e) => {{
    e.stopPropagation();
    deleteWp(si, wi);
  }});

  return div;
}}

function makeEditRow(si, wi, c) {{
  const div = document.createElement('div');
  div.className = 'wp-edit-row';
  div.innerHTML = `
    <label>Longitude / Latitude / Altitude (m)</label>
    <div class="wp-edit-inputs">
      <input id="elon" type="number" step="0.00001" value="${{c[0].toFixed(5)}}" placeholder="Lon"/>
      <input id="elat" type="number" step="0.00001" value="${{c[1].toFixed(5)}}" placeholder="Lat"/>
      <input id="ealt" type="number" step="1"       value="${{(c[2]||0).toFixed(0)}}" placeholder="Alt (m)"/>
    </div>
    <div class="wp-edit-btns">
      <button class="wp-save-btn" id="eSave">Save</button>
      <button class="wp-cancel-btn" id="eCancel">Cancel</button>
    </div>`;

  div.querySelector('#eSave').addEventListener('click', () => {{
    const lon = parseFloat(div.querySelector('#elon').value);
    const lat = parseFloat(div.querySelector('#elat').value);
    const alt = parseFloat(div.querySelector('#ealt').value) || 0;
    if (!isFinite(lon) || !isFinite(lat)) {{
      setStatus('Invalid coordinates — check values.', 'err'); return;
    }}
    segments[si].coords[wi] = [lon, lat, alt];
    editState = null;
    updateAll('Waypoint updated.');
  }});
  div.querySelector('#eCancel').addEventListener('click', () => {{
    editState = null;
    buildPanel();
  }});

  return div;
}}

function selectWp(si, wi) {{
  selectedWp = {{ segIdx: si, wpIdx: wi }};
  buildPanel();
  renderGlobe();
  if (viewer) {{
    const c = segments[si].coords[wi];
    viewer.camera.flyTo({{
      destination: Cesium.Cartesian3.fromDegrees(c[0], c[1], 800),
      duration: 1.0,
    }});
  }}
}}

function deleteWp(si, wi) {{
  segments[si].coords.splice(wi, 1);
  // Remove empty segments
  if (segments[si].coords.length === 0) segments.splice(si, 1);
  if (selectedWp && (selectedWp.segIdx === si && selectedWp.wpIdx >= segments[si]?.coords.length || selectedWp.segIdx > si)) {{
    selectedWp = null;
  }}
  updateAll('Waypoint deleted.');
}}

function updateAll(msg) {{
  buildPanel();
  renderGlobe();
  updateStats();
  if (msg) setStatus(msg, 'ok');
}}

// ═══════════════════════════════════════════════════════
// LOAD INITIAL DATA
// ═══════════════════════════════════════════════════════
function loadSegments(segs) {{
  segments = segs.map(s => ({{
    name:   s.name   || 'Route',
    coords: (s.coords || []).map(c => [
      parseFloat(c[0]) || 0,
      parseFloat(c[1]) || 0,
      parseFloat(c[2]) || 0,
    ])
  }}));
  selectedWp = null; editState = null;
  updateAll();

  // Fly to first point
  if (viewer && segments.length && segments[0].coords.length) {{
    const all = segments.flatMap(s => s.coords);
    const positions = all.map(c => Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2]||0));
    if (positions.length === 1) {{
      viewer.camera.flyTo({{ destination: Cesium.Cartesian3.fromDegrees(all[0][0], all[0][1], 2000) }});
    }} else {{
      const sphere = Cesium.BoundingSphere.fromPoints(positions);
      const range  = Math.max(sphere.radius * 3, 500);
      viewer.camera.flyToBoundingSphere(sphere, {{
        duration: 1.5,
        offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-40), range),
      }});
    }}
  }}
}}

if (INITIAL_SEGMENTS && INITIAL_SEGMENTS.length) {{
  loadSegments(INITIAL_SEGMENTS);
  const total = INITIAL_SEGMENTS.reduce((n, s) => n + (s.coords || []).length, 0);
  setStatus(`Loaded ${{INITIAL_SEGMENTS.length}} segment(s), ${{total}} waypoints.`, 'ok');
}} else {{
  buildPanel();
  setStatus('Ready — upload a KMZ/KML or draw waypoints.', '');
}}

// ═══════════════════════════════════════════════════════
// GLOBE CLICK — select marker
// ═══════════════════════════════════════════════════════
if (viewer) {{
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);

  // Left click — draw or select
  handler.setInputAction((click) => {{
    if (drawingMode) {{
      const cart = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
      if (!Cesium.defined(cart)) return;
      const carto = viewer.scene.globe.ellipsoid.cartesianToCartographic(cart);
      const lon = Cesium.Math.toDegrees(carto.longitude);
      const lat = Cesium.Math.toDegrees(carto.latitude);
      // Add to last segment or create new one
      if (!segments.length) segments.push({{ name: 'Route 1', coords: [] }});
      segments[segments.length - 1].coords.push([lon, lat, 0]);
      updateAll(`Placed waypoint at ${{lon.toFixed(5)}}, ${{lat.toFixed(5)}}`);
    }} else {{
      // Try to pick a marker entity
      const picked = viewer.scene.pick(click.position);
      if (Cesium.defined(picked) && picked.id && picked.id._skyphorSeg !== undefined) {{
        selectWp(picked.id._skyphorSeg, picked.id._skyphorWp);
      }}
    }}
  }}, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}}

// ═══════════════════════════════════════════════════════
// SIDEBAR TOOLBAR
// ═══════════════════════════════════════════════════════
function setDraw(on) {{
  drawingMode = on;
  document.getElementById('drawBtn').classList.toggle('on', on);
  if (viewer) viewer.canvas.style.cursor = on ? 'crosshair' : 'default';
  setStatus(on ? 'Draw mode — click globe to place waypoints.' : 'Ready', on ? 'busy' : '');
}}

document.getElementById('drawBtn').addEventListener('click', () => {{
  if (!drawingMode && !segments.length) {{
    segments.push({{ name: 'Route 1', coords: [] }});
  }} else if (!drawingMode) {{
    segments.push({{ name: `Route ${{segments.length + 1}}`, coords: [] }});
  }}
  setDraw(!drawingMode);
}});
document.getElementById('finishBtn').addEventListener('click', () => setDraw(false));
document.getElementById('undoBtn').addEventListener('click', () => {{
  // Remove last waypoint from last non-empty segment
  for (let i = segments.length - 1; i >= 0; i--) {{
    if (segments[i].coords.length) {{
      segments[i].coords.pop();
      if (segments[i].coords.length === 0) segments.splice(i, 1);
      updateAll('Last waypoint removed.');
      return;
    }}
  }}
}});
document.getElementById('clearBtn').addEventListener('click', () => {{
  if (!confirm('Clear all waypoints?')) return;
  segments = []; selectedWp = null; editState = null;
  updateAll('Cleared.');
  setStatus('Ready', '');
}});

// ═══════════════════════════════════════════════════════
// MAP TOOLBAR
// ═══════════════════════════════════════════════════════
document.getElementById('fitBtn').addEventListener('click', () => {{
  if (!viewer) return;
  const all = segments.flatMap(s => s.coords);
  if (!all.length) return;
  const positions = all.map(c => Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2]||0));
  const sphere = Cesium.BoundingSphere.fromPoints(positions);
  viewer.camera.flyToBoundingSphere(sphere, {{
    duration: 1.5,
    offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-40), Math.max(sphere.radius*3, 500)),
  }});
}});

document.getElementById('fsBtn').addEventListener('click', () => {{
  document.getElementById('app').classList.toggle('fullscreen');
  if (viewer) viewer.forceResize();
}});
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{
    document.getElementById('app').classList.remove('fullscreen');
    setDraw(false);
    if (viewer) viewer.forceResize();
  }}
}});

// Terrain toggle
document.getElementById('terrainBtn').addEventListener('click', () => {{
  if (!viewer) return;
  terrainOn = !terrainOn;
  if (terrainOn) {{
    viewer.terrainProvider = new Cesium.CesiumTerrainProvider({{
      url: Cesium.IonResource.fromAssetId(1),
    }});
    viewer.scene.globe.enableLighting = true;
    viewer.scene.globe.depthTestAgainstTerrain = true;
    document.getElementById('terrainBtn').classList.add('on');
    setStatus('3D terrain enabled.', 'ok');
  }} else {{
    viewer.terrainProvider = Cesium.EllipsoidTerrainProvider.INSTANCE;
    viewer.scene.globe.enableLighting = false;
    viewer.scene.globe.depthTestAgainstTerrain = false;
    document.getElementById('terrainBtn').classList.remove('on');
    setStatus('Flat terrain.', '');
  }}
}});

// ═══════════════════════════════════════════════════════
// DRONE SIMULATION
// ═══════════════════════════════════════════════════════
document.getElementById('droneBtn').addEventListener('click', () => {{
  if (!viewer) return;
  const all = segments.flatMap(s => s.coords);
  if (all.length < 2) {{ setStatus('Need at least 2 waypoints to simulate.', 'err'); return; }}
  if (droneEnt) stopDrone();

  const start = Cesium.JulianDate.now(), secs = 3;
  const stop  = Cesium.JulianDate.addSeconds(start, all.length * secs, new Cesium.JulianDate());
  const prop  = new Cesium.SampledPositionProperty();
  all.forEach((c, i) => {{
    const t = Cesium.JulianDate.addSeconds(start, i * secs, new Cesium.JulianDate());
    prop.addSample(t, Cesium.Cartesian3.fromDegrees(c[0], c[1], (c[2]||0) + 80));
  }});
  droneEnt = viewer.entities.add({{
    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({{start,stop}})]),
    position: prop,
    point: {{ pixelSize:14, color:Cesium.Color.fromCssColorString('#fbbf24'), outlineColor:Cesium.Color.BLACK, outlineWidth:2, disableDepthTestDistance:Number.POSITIVE_INFINITY }},
    label: {{ text:'✈', font:'20px sans-serif', fillColor:Cesium.Color.fromCssColorString('#fbbf24'), verticalOrigin:Cesium.VerticalOrigin.BOTTOM, disableDepthTestDistance:Number.POSITIVE_INFINITY }},
    path: {{ show:true, leadTime:0, trailTime:40, width:2, material:new Cesium.PolylineGlowMaterialProperty({{glowPower:0.3,taperPower:1.0,color:Cesium.Color.fromCssColorString('#fbbf24')}}) }},
  }});
  viewer.clock.startTime=start; viewer.clock.stopTime=stop; viewer.clock.currentTime=start;
  viewer.clock.multiplier=1; viewer.clock.shouldAnimate=true; viewer.clock.clockRange=Cesium.ClockRange.LOOP_STOP;
  viewer.trackedEntity=droneEnt;
  document.getElementById('droneBtn').style.display='none';
  document.getElementById('stopBtn').style.display='inline-flex';
  setStatus('Drone simulation running...', 'busy');
}});
document.getElementById('stopBtn').addEventListener('click', stopDrone);
function stopDrone() {{
  if (droneEnt) {{ viewer.entities.remove(droneEnt); droneEnt=null; }}
  if (viewer) {{ viewer.trackedEntity=undefined; viewer.clock.shouldAnimate=false; }}
  document.getElementById('droneBtn').style.display='inline-flex';
  document.getElementById('stopBtn').style.display='none';
  setStatus('Simulation stopped.', '');
}}

// ═══════════════════════════════════════════════════════
// EXPORT KMZ
// ═══════════════════════════════════════════════════════
document.getElementById('exportBtn').addEventListener('click', () => {{
  if (!segments.length) {{ setStatus('Nothing to export.', 'err'); return; }}

  // Build KML string
  let placemarks = '';
  segments.forEach((seg, si) => {{
    if (!seg.coords.length) return;
    const coordStr = seg.coords.map(c => `${{c[0]}},${{c[1]}},${{c[2]||0}}`).join(' ');
    placemarks += `
    <Placemark>
      <name>${{seg.name}}</name>
      <LineString>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>${{coordStr}}</coordinates>
      </LineString>
    </Placemark>`;
  }});
  const kml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Skyphor Flight Plan</name>${{placemarks}}
  </Document>
</kml>`;

  // Download as .kml (browsers can't create ZIP natively without a library)
  const blob = new Blob([kml], {{type:'application/vnd.google-earth.kml+xml'}});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'skyphor_flight_plan.kml';
  a.click(); URL.revokeObjectURL(url);
  setStatus('KML exported.', 'ok');
}});
</script>
</body>
</html>"""


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