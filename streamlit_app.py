import json
import base64
import zipfile
import io
import streamlit as st
from streamlit.components.v1 import html as components_html

# ---------------------------------------------------------------------------
# KMZ / KML parsing (self-contained, no external droneflight dependency)
# ---------------------------------------------------------------------------

def _parse_kml_coords(kml_text: str) -> list[list[float]]:
    """Extract coordinates from KML text, returning [[lon, lat, alt?], ...]."""
    import re
    # Find all <coordinates> blocks
    blocks = re.findall(r"<coordinates[^>]*>(.*?)</coordinates>", kml_text, re.DOTALL)
    coords = []
    for block in blocks:
        for token in block.strip().split():
            parts = token.strip().split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                    alt = float(parts[2]) if len(parts) > 2 else 0.0
                    coords.append([lon, lat, alt])
                except ValueError:
                    pass
    return coords


def parse_kmz(raw_bytes: bytes) -> dict:
    """Parse a KMZ file and return a GeoJSON LineString."""
    coords = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            kml_names = [n for n in z.namelist() if n.lower().endswith(".kml")]
            for name in kml_names:
                kml_text = z.read(name).decode("utf-8", errors="replace")
                coords.extend(_parse_kml_coords(kml_text))
    except Exception as e:
        raise ValueError(f"Could not read KMZ: {e}") from e

    if not coords:
        raise ValueError("No coordinates found in KMZ file.")

    return {"type": "LineString", "coordinates": coords}


# ---------------------------------------------------------------------------
# Cesium HTML builder
# ---------------------------------------------------------------------------

def _build_cesium_html(coords_geojson: list[list[float]]) -> str:
    """Return a self-contained Cesium page pre-loaded with the given coordinates.

    coords_geojson is a list of [lon, lat] or [lon, lat, alt] pairs.
    Cesium and JSZip are loaded from CDN here so the page works in any browser.
    """
    coords_json = json.dumps(coords_geojson)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <script src="https://cesium.com/downloads/cesiumjs/releases/1.114/Build/Cesium/Cesium.js"></script>
  <link href="https://cesium.com/downloads/cesiumjs/releases/1.114/Build/Cesium/Widgets/widgets.css" rel="stylesheet"/>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ height:100%; margin:0; padding:0; font-family: Arial, sans-serif; background:#1a1a2e; }}
    #mainContainer {{ display:flex; height:100%; flex-direction:row; }}

    /* ── Left Sidebar ── */
    #flightPlanPanel {{
      flex: 0 0 280px;
      border-right: 2px solid #333;
      background: #16213e;
      display: flex;
      flex-direction: column;
      color: #e0e0e0;
    }}
    #flightPlanHeader {{
      padding: 12px 14px;
      background: #0f3460;
      color: #e94560;
      font-weight: bold;
      font-size: 15px;
      letter-spacing: 1px;
      border-bottom: 2px solid #e94560;
    }}
    #flightPlanToolbar {{
      padding: 8px;
      background: #1a1a2e;
      border-bottom: 1px solid #333;
      display: flex;
      gap: 6px;
    }}
    #flightPlanToolbar button {{
      flex: 1;
      padding: 7px 8px;
      font-size: 12px;
      cursor: pointer;
      background: #0f3460;
      color: #e0e0e0;
      border: 1px solid #e94560;
      border-radius: 4px;
      transition: background 0.2s;
    }}
    #flightPlanToolbar button:hover {{ background: #e94560; color: white; }}
    #waypointsList {{ flex:1; overflow-y:auto; padding:8px; }}
    .waypoint-item {{
      padding: 8px 10px;
      margin-bottom: 5px;
      background: #0f3460;
      border: 1px solid #333;
      border-radius: 4px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
    }}
    .waypoint-item:hover {{ border-color: #e94560; }}
    .waypoint-item.selected {{ background: #e94560; color: white; border-color: #e94560; }}
    .waypoint-number {{ font-weight:bold; min-width:22px; }}
    .waypoint-coords {{ flex:1; margin:0 8px; font-family:monospace; font-size:11px; color:#aaa; }}
    .waypoint-item.selected .waypoint-coords {{ color: white; }}
    .waypoint-delete {{
      background: #c0392b; color:white; border:none;
      padding: 3px 7px; cursor:pointer; border-radius:3px; font-size:11px;
    }}
    .waypoint-delete:hover {{ background:#e74c3c; }}
    #wpCount {{ padding:6px 10px; font-size:11px; color:#888; border-top:1px solid #333; }}

    /* ── Map Area ── */
    #mapArea {{ flex:1; display:flex; flex-direction:column; }}
    #topToolbar {{
      padding: 8px 10px;
      background: #16213e;
      border-bottom: 1px solid #333;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }}
    #topToolbar button {{
      padding: 6px 14px;
      font-size: 12px;
      cursor: pointer;
      background: #0f3460;
      color: #e0e0e0;
      border: 1px solid #555;
      border-radius: 4px;
      transition: background 0.2s;
    }}
    #topToolbar button:hover {{ background: #1a4a8a; }}
    #topToolbar button.active {{ background: #27ae60; border-color: #2ecc71; color: white; }}
    #topToolbar button.danger {{ background: #c0392b; border-color: #e74c3c; color: white; }}
    #cesiumContainer {{ flex:1; position:relative; width:100%; }}
    #mainContainer.fullscreen {{
      position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:10000;
    }}
    #statusBar {{
      padding: 4px 10px; font-size:11px; color:#888; background:#16213e;
      border-top: 1px solid #333;
    }}
  </style>
</head>
<body>
<div id="mainContainer">
  <!-- Sidebar -->
  <div id="flightPlanPanel">
    <div id="flightPlanHeader">✈ FLIGHT PLAN</div>
    <div id="flightPlanToolbar">
      <button id="addWaypointBtn">+ Waypoint</button>
      <button id="clearAllBtn">✕ Clear</button>
    </div>
    <div id="waypointsList"></div>
    <div id="wpCount">0 waypoints</div>
  </div>

  <!-- Map -->
  <div id="mapArea">
    <div id="topToolbar">
      <button id="drawModeBtn">✏ Draw Mode</button>
      <button id="finishDrawBtn" style="display:none;">✓ Finish</button>
      <button id="undoBtn">↶ Undo</button>
      <button id="fitViewBtn">⊡ Fit View</button>
      <button id="fullscreenBtn">⛶ Fullscreen</button>
      <button id="droneBtn">▶ Trace Drone</button>
      <button id="stopDroneBtn" style="display:none;" class="danger">⊠ Stop</button>
    </div>
    <div id="cesiumContainer"></div>
    <div id="statusBar" id="statusBar">Ready — enable Draw Mode to add waypoints by clicking the globe.</div>
  </div>
</div>

<script>
// ── Cesium init ──────────────────────────────────────────────────────────────
let viewer;
try {{
  Cesium.Ion.defaultAccessToken = '';  // anonymous / no token needed for basic use
  viewer = new Cesium.Viewer('cesiumContainer', {{
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    animation: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: true,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    timeline: false,
  }});
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#0d1117');
}} catch(e) {{
  console.error('Cesium init failed', e);
  document.getElementById('cesiumContainer').innerText = '3D view failed to load.';
  viewer = null;
}}

// ── State ───────────────────────────────────────────────────────────────────
const INITIAL_COORDS = {coords_json};
let waypoints      = [];
let pathEntity     = null;
let waypointMarkers= [];
let drawingMode    = false;
let selectedWp     = -1;
let droneEntity    = null;
let droneHandler   = null;

// ── Helpers ──────────────────────────────────────────────────────────────────
function setStatus(msg) {{
  document.getElementById('statusBar').textContent = msg;
}}

function updateWpCount() {{
  document.getElementById('wpCount').textContent = waypoints.length + ' waypoint' + (waypoints.length !== 1 ? 's' : '');
}}

function updateSidebar() {{
  const list = document.getElementById('waypointsList');
  list.innerHTML = '';
  waypoints.forEach((wp, idx) => {{
    const item = document.createElement('div');
    item.className = 'waypoint-item' + (selectedWp === idx ? ' selected' : '');
    item.innerHTML =
      `<span class="waypoint-number">${{idx+1}}</span>` +
      `<span class="waypoint-coords">${{wp.lon.toFixed(5)}}<br>${{wp.lat.toFixed(5)}}</span>` +
      `<button class="waypoint-delete" data-idx="${{idx}}">✕</button>`;
    item.querySelector('.waypoint-delete').addEventListener('click', e => {{
      e.stopPropagation();
      deleteWp(+e.target.dataset.idx);
    }});
    item.addEventListener('click', () => flyToWp(idx));
    list.appendChild(item);
  }});
  updateWpCount();
}}

function flyToWp(idx) {{
  selectedWp = idx;
  updateSidebar();
  if (!viewer || !waypoints[idx]) return;
  viewer.camera.flyTo({{
    destination: Cesium.Cartesian3.fromDegrees(waypoints[idx].lon, waypoints[idx].lat, 800),
    duration: 1.2
  }});
}}

function addWp(lon, lat, alt) {{
  waypoints.push({{ lon, lat, alt: alt || 0 }});
  updateSidebar();
  redrawPath();
}}

function deleteWp(idx) {{
  waypoints.splice(idx, 1);
  if (selectedWp >= waypoints.length) selectedWp = -1;
  updateSidebar();
  redrawPath();
}}

function clearAllWps() {{
  waypoints = [];
  selectedWp = -1;
  updateSidebar();
  redrawPath();
  setStatus('All waypoints cleared.');
}}

function redrawPath() {{
  if (!viewer) return;
  if (pathEntity) {{ viewer.entities.remove(pathEntity); pathEntity = null; }}
  waypointMarkers.forEach(m => viewer.entities.remove(m));
  waypointMarkers = [];

  if (waypoints.length >= 2) {{
    const positions = waypoints.map(wp => Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, wp.alt || 0));
    pathEntity = viewer.entities.add({{
      polyline: {{
        positions,
        width: 3,
        material: new Cesium.PolylineGlowMaterialProperty({{
          glowPower: 0.2,
          color: Cesium.Color.CYAN
        }}),
        clampToGround: true
      }}
    }});
  }}

  waypoints.forEach((wp, idx) => {{
    const isSelected = selectedWp === idx;
    const m = viewer.entities.add({{
      position: Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, 50),
      point: {{
        pixelSize: isSelected ? 14 : 10,
        color: isSelected ? Cesium.Color.YELLOW : Cesium.Color.fromCssColorString('#e94560'),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      }},
      label: {{
        text: String(idx + 1),
        font: 'bold 11px sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      }}
    }});
    waypointMarkers.push(m);
  }});
}}

// ── Load initial coords from Python ─────────────────────────────────────────
if (INITIAL_COORDS && INITIAL_COORDS.length) {{
  INITIAL_COORDS.forEach(c => addWp(c[0], c[1], c[2] || 0));
  // Fly to first point
  if (viewer && waypoints.length) {{
    const first = waypoints[0];
    viewer.camera.flyTo({{
      destination: Cesium.Cartesian3.fromDegrees(first.lon, first.lat, 3000),
      duration: 1.5
    }});
  }}
  setStatus(`Loaded ${{waypoints.length}} waypoints from file.`);
}}

// ── Drawing mode ─────────────────────────────────────────────────────────────
const clickHandler = new Cesium.ScreenSpaceEventHandler(viewer ? viewer.canvas : document.createElement('canvas'));
clickHandler.setInputAction(click => {{
  if (!drawingMode || !viewer) return;
  const ellipsoid = viewer.scene.globe.ellipsoid;
  const cartesian = viewer.camera.pickEllipsoid(click.position, ellipsoid);
  if (Cesium.defined(cartesian)) {{
    const carto = ellipsoid.cartesianToCartographic(cartesian);
    const lon = Cesium.Math.toDegrees(carto.longitude);
    const lat = Cesium.Math.toDegrees(carto.latitude);
    addWp(lon, lat, 0);
    setStatus(`Added waypoint ${{waypoints.length}} at ${{lon.toFixed(5)}}, ${{lat.toFixed(5)}}`);
  }}
}}, Cesium.ScreenSpaceEventType.LEFT_CLICK);

function setDrawMode(on) {{
  drawingMode = on;
  document.getElementById('drawModeBtn').classList.toggle('active', on);
  document.getElementById('finishDrawBtn').style.display = on ? 'inline-block' : 'none';
  if (viewer) viewer.canvas.style.cursor = on ? 'crosshair' : 'default';
  setStatus(on ? 'Draw Mode ON — click globe to place waypoints.' : 'Draw Mode OFF.');
}}

// ── Drone trace ───────────────────────────────────────────────────────────────
function startDrone() {{
  if (waypoints.length < 2) {{ alert('Need at least 2 waypoints.'); return; }}
  if (droneEntity) stopDrone();

  const start = Cesium.JulianDate.now();
  const totalSecs = waypoints.length * 3;
  const stop = Cesium.JulianDate.addSeconds(start, totalSecs, new Cesium.JulianDate());

  const prop = new Cesium.SampledPositionProperty();
  waypoints.forEach((wp, i) => {{
    const t = Cesium.JulianDate.addSeconds(start, i * 3, new Cesium.JulianDate());
    prop.addSample(t, Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, 150));
  }});

  droneEntity = viewer.entities.add({{
    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({{ start, stop }})]),
    position: prop,
    point: {{
      pixelSize: 14,
      color: Cesium.Color.YELLOW,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 2,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    }},
    label: {{
      text: '✈',
      font: '20px sans-serif',
      fillColor: Cesium.Color.YELLOW,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    }},
    path: {{
      show: true,
      leadTime: 0,
      trailTime: 60,
      width: 2,
      material: new Cesium.PolylineGlowMaterialProperty({{ glowPower: 0.3, color: Cesium.Color.YELLOW }})
    }}
  }});

  viewer.clock.startTime    = start;
  viewer.clock.stopTime     = stop;
  viewer.clock.currentTime  = start;
  viewer.clock.multiplier   = 1;
  viewer.clock.shouldAnimate= true;
  viewer.clock.clockRange   = Cesium.ClockRange.LOOP_STOP;
  viewer.trackedEntity      = droneEntity;

  document.getElementById('droneBtn').style.display    = 'none';
  document.getElementById('stopDroneBtn').style.display= 'inline-block';
  setStatus('Drone trace running…');
}}

function stopDrone() {{
  if (droneEntity) {{ viewer.entities.remove(droneEntity); droneEntity = null; }}
  viewer.trackedEntity = undefined;
  viewer.clock.shouldAnimate = false;
  document.getElementById('droneBtn').style.display    = 'inline-block';
  document.getElementById('stopDroneBtn').style.display= 'none';
  setStatus('Drone trace stopped.');
}}

// ── Toolbar buttons ───────────────────────────────────────────────────────────
document.getElementById('drawModeBtn').addEventListener('click', () => setDrawMode(!drawingMode));
document.getElementById('finishDrawBtn').addEventListener('click', () => setDrawMode(false));
document.getElementById('undoBtn').addEventListener('click', () => {{
  if (waypoints.length) {{ waypoints.pop(); updateSidebar(); redrawPath(); setStatus('Last waypoint removed.'); }}
}});
document.getElementById('addWaypointBtn').addEventListener('click', () => setDrawMode(!drawingMode));
document.getElementById('clearAllBtn').addEventListener('click', () => {{
  if (confirm('Clear all waypoints?')) clearAllWps();
}});
document.getElementById('fitViewBtn').addEventListener('click', () => {{
  if (!viewer || !waypoints.length) return;
  if (waypoints.length === 1) {{
    viewer.camera.flyTo({{ destination: Cesium.Cartesian3.fromDegrees(waypoints[0].lon, waypoints[0].lat, 2000) }});
  }} else {{
    const positions = waypoints.map(wp => Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, 0));
    viewer.camera.flyToBoundingSphere(Cesium.BoundingSphere.fromPoints(positions), {{ duration: 1.5 }});
  }}
}});
document.getElementById('fullscreenBtn').addEventListener('click', () => {{
  const c = document.getElementById('mainContainer');
  c.classList.toggle('fullscreen');
  if (viewer) viewer.forceResize();
}});
document.getElementById('droneBtn').addEventListener('click', startDrone);
document.getElementById('stopDroneBtn').addEventListener('click', stopDrone);
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{
    setDrawMode(false);
    document.getElementById('mainContainer').classList.remove('fullscreen');
    if (viewer) viewer.forceResize();
  }}
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

st.markdown("---")

col1, col2 = st.columns([1, 1])

with col1:
    uploaded = st.file_uploader("📁 Upload KMZ file", type=["kmz"])

with col2:
    coords_text = st.text_area(
        "Or paste lon,lat pairs (one per line or space-separated)",
        placeholder="-87.6298,41.8781\n-87.6350,41.8800",
        height=120,
    )

coords_geojson: list[list[float]] = []

# Parse manual coords
if coords_text.strip():
    parts = coords_text.strip().replace("\n", " ").split()
    try:
        for p in parts:
            lon_s, lat_s = p.split(",")
            coords_geojson.append([float(lon_s), float(lat_s), 0.0])
        if len(coords_geojson) < 2:
            raise ValueError("Need at least two coordinate pairs.")
        st.success(f"✅ {len(coords_geojson)} coordinates parsed from text input.")
    except Exception as e:
        st.error(f"❌ Could not parse coordinates: {e}")
        coords_geojson = []

# Parse KMZ (overrides manual coords if both supplied)
if uploaded is not None:
    try:
        raw = uploaded.read()
        geojson = parse_kmz(raw)
        coords_geojson = geojson["coordinates"]
        st.success(f"✅ KMZ parsed - {len(coords_geojson)} waypoints found.")
        with st.expander("GeoJSON preview"):
            st.json(geojson)
    except Exception as e:
        st.error(f"❌ Failed to parse KMZ: {e}")

# Render map
if coords_geojson or uploaded is None:
    html_str = _build_cesium_html(coords_geojson)
    components_html(html_str, height=680, scrolling=False)
else:
    st.info("📍 Upload a KMZ file or paste coordinates above to preview the route in 3D.")