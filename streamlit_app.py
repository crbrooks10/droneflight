import json
import streamlit as st
from streamlit.components.v1 import html as components_html
from droneflight.kmz import parse_kmz


def _build_cesium_html(kmz_b64: str | None, thickness: float, manual_coords: list | None = None) -> str:
    """Return a minimal Cesium HTML page that will visualize a KMZ payload or
    a list of manually supplied coordinates.

    ``kmz_b64`` should be a base64-encoded string of the raw KMZ bytes; if
    ``manual_coords`` is non-``None`` the JS will ignore the KMZ and instead
    render the provided flat array of longitude/latitude pairs.  ``thickness``
    is injected into the JS to control corridor width / animation behaviour.

    The generated HTML inlines Cesium, its CSS widgets, and JSZip from the
    repository's ``static/`` directory.  This allows the page to function even
    when the browser does not have internet access (important for the
    Streamlit-hosted version).
    """
    # JSON-encode the manual coordinate list so it can be interpolated into
    # the generated script.  ``null`` in the template means "no manual data"
    coords_json = json.dumps(manual_coords) if manual_coords is not None else "null"
    # allow passing None for kmz_b64 as empty string in JS
    kmz = kmz_b64 or ""

    # inline static assets if available (Cesium, CSS, JSZip)
    try:
        with open('static/cesium.js', 'r', encoding='utf-8') as f:
            cesium_js = f.read()
    except Exception:
        cesium_js = ''
    try:
        with open('static/widgets.css', 'r', encoding='utf-8') as f:
            widgets_css = f.read()
    except Exception:
        widgets_css = ''
    try:
        with open('static/jszip.min.js', 'r', encoding='utf-8') as f:
            jszip_js = f.read()
    except Exception:
        jszip_js = ''

    return f"""
        <!DOCTYPE html>
        <html lang=\"en\"> 
        <head>
            <meta charset=\"utf-8\" />
            <script>{cesium_js}</script>
            <style>{widgets_css}</style>
            <script>{jszip_js}</script>
            <style>
            * {{ box-sizing: border-box; }}
            html, body {{ height:100%; margin:0; padding:0; font-family: Arial, sans-serif; }}
            #mainContainer {{ display:flex; height:100%; flex-direction:row; }}
            
            /* Left Sidebar - Flight Plan */
            #flightPlanPanel {{ 
                flex: 0 0 300px; 
                width: 300px;
                border-right: 2px solid #333; 
                background: #f5f5f5; 
                display: flex; 
                flex-direction: column;
                z-index: 1000;
            }}
            #flightPlanHeader {{ 
                padding: 12px; 
                background: #333; 
                color: white; 
                font-weight: bold; 
                font-size: 14px;
            }}
            #flightPlanToolbar {{
                padding: 8px;
                background: #e8e8e8;
                border-bottom: 1px solid #ccc;
                display: flex;
                gap: 4px;
                flex-wrap: wrap;
            }}
            #flightPlanToolbar button {{
                flex: 1;
                min-width: 70px;
                padding: 6px 8px;
                font-size: 11px;
                cursor: pointer;
                background: #007acc;
                color: white;
                border: none;
                border-radius: 2px;
            }}
            #flightPlanToolbar button:hover {{ background: #005a9e; }}
            #flightPlanToolbar button:active {{ background: #004578; }}
            
            #waypointsList {{
                flex: 1;
                overflow-y: auto;
                padding: 8px;
                background: #f5f5f5;
            }}
            .waypoint-item {{
                padding: 8px;
                margin-bottom: 6px;
                background: white;
                border: 1px solid #ddd;
                border-radius: 3px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }}
            .waypoint-item:hover {{ background: #e3f2fd; border-color: #007acc; }}
            .waypoint-item.selected {{ background: #007acc; color: white; border-color: #007acc; }}
            .waypoint-number {{ font-weight: bold; min-width: 25px; }}
            .waypoint-coords {{ font-size: 11px; flex: 1; margin: 0 8px; font-family: monospace; }}
            .waypoint-delete {{ 
                background: #dc3545; 
                color: white; 
                border: none; 
                padding: 3px 6px; 
                cursor: pointer; 
                border-radius: 2px;
                font-size: 11px;
            }}
            .waypoint-delete:hover {{ background: #c82333; }}
            
            /* Map Area */
            #mapArea {{
                flex: 1;
                display: flex;
                flex-direction: column;
            }}
            #topToolbar {{
                padding: 8px;
                background: #e8e8e8;
                border-bottom: 1px solid #999;
                display: flex;
                gap: 6px;
                flex-wrap: wrap;
                align-items: center;
            }}
            #topToolbar button {{
                padding: 6px 12px;
                font-size: 12px;
                cursor: pointer;
                background: #007acc;
                color: white;
                border: none;
                border-radius: 2px;
            }}
            #topToolbar button:hover {{ background: #005a9e; }}
            #topToolbar button.active {{ background: #107c10; }}
            
            #cesiumContainer {{ 
                flex:1; 
                position: relative;
                width: 100%;
            }}
            
            #mainContainer.fullscreen {{ position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:10000; }}
            </style>
        </head>
        <body>
        <div id="mainContainer">
            <!-- Left Sidebar -->
            <div id="flightPlanPanel">
                <div id="flightPlanHeader">FLIGHT PLAN</div>
                <div id="flightPlanToolbar">
                    <button id="addWaypoint">+ Waypoint</button>
                    <button id="clearAll">Clear All</button>
                </div>
                <div id="waypointsList"></div>
            </div>
            
            <!-- Map Area -->
            <div id="mapArea">
                <div id="topToolbar">
                    <button id="drawMode" title="Click to draw waypoints on map">✏ Draw Mode</button>
                    <button id="finishDraw" style="display:none;">✓ Finish</button>
                    <button id="undoBtn">↶ Undo</button>
                    <button id="fullscreenBtn">⛶ Fullscreen</button>
                    <button id="droneBtn">▶ Trace Drone</button>
                </div>
                <div id="cesiumContainer"></div>
            </div>
        </div>
        <script>
            let viewer;
            try {{
                viewer = new Cesium.Viewer('cesiumContainer', {{ terrainProvider: Cesium.createWorldTerrain() }});
            }} catch (e) {{
                console.error('Cesium initialization failed', e);
                document.getElementById('cesiumContainer').innerText = '3D view failed to load; see console for details.';
                viewer = null;
            }}
            const kmzBase64 = "{kmz}";
            const manualCoords = {coords_json};
            const thickness = {thickness};

            // Waypoint management
            let waypoints = [];
            let pathEntity = null;
            let waypointMarkers = [];
            let drawingMode = false;
            let selectedWaypoint = -1;

            function b64ToUint8Array(b64) {{
                const binary = atob(b64);
                const len = binary.length;
                const bytes = new Uint8Array(len);
                for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
                return bytes;
            }}
            
            function updateWaypointsList() {{
                const list = document.getElementById('waypointsList');
                list.innerHTML = '';
                waypoints.forEach((wp, idx) => {{
                    const item = document.createElement('div');
                    item.className = 'waypoint-item' + (selectedWaypoint === idx ? ' selected' : '');
                    item.innerHTML = `
                        <span class="waypoint-number">${{idx + 1}}.</span>
                        <span class="waypoint-coords">${{wp.lon.toFixed(4)}}, ${{wp.lat.toFixed(4)}}</span>
                        <button class="waypoint-delete">✕</button>
                    `;
                    item.querySelector('.waypoint-delete').addEventListener('click', (e) => {{
                        e.stopPropagation();
                        deleteWaypoint(idx);
                    }});
                    item.addEventListener('click', () => selectWaypoint(idx));
                    list.appendChild(item);
                }});
            }}
            
            function selectWaypoint(idx) {{
                selectedWaypoint = idx;
                updateWaypointsList();
                // Pan to waypoint
                if (waypoints[idx]) {{
                    const wp = waypoints[idx];
                    viewer.camera.flyTo({{
                        destination: Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, 500)
                    }});
                }}
            }}
            
            function addWaypoint(lon, lat) {{
                waypoints.push({{ lon, lat }});
                updateWaypointsList();
                updatePath();
            }}
            
            function deleteWaypoint(idx) {{
                waypoints.splice(idx, 1);
                if (selectedWaypoint >= waypoints.length) selectedWaypoint = -1;
                updateWaypointsList();
                updatePath();
            }}
            
            function clearWaypoints() {{
                waypoints = [];
                selectedWaypoint = -1;
                updateWaypointsList();
                updatePath();
            }}
            
            function updatePath() {{
                // Remove old path and markers
                if (pathEntity) viewer.entities.remove(pathEntity);
                waypointMarkers.forEach(m => viewer.entities.remove(m));
                waypointMarkers = [];
                
                // Draw path
                if (waypoints.length >= 2) {{
                    const positions = waypoints.map(wp => Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, 0));
                    pathEntity = viewer.entities.add({{
                        polyline: {{
                            positions: positions,
                            width: 3,
                            material: Cesium.Color.CYAN,
                            clampToGround: true
                        }}
                    }});
                }}
                
                // Draw waypoint markers
                waypoints.forEach((wp, idx) => {{
                    const marker = viewer.entities.add({{
                        position: Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat),
                        point: {{
                            pixelSize: 10,
                            color: selectedWaypoint === idx ? Cesium.Color.YELLOW : Cesium.Color.RED,
                            outlineColor: Cesium.Color.WHITE,
                            outlineWidth: 2
                        }},
                        label: {{
                            text: (idx + 1).toString(),
                            font: '12px sans-serif',
                            fillColor: Cesium.Color.WHITE,
                            horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
                            verticalOrigin: Cesium.VerticalOrigin.CENTER
                        }}
                    }});
                    waypointMarkers.push(marker);
                }});
            }}
            
            function displayKMLRoutes(geojson) {{
                const panel = document.getElementById('kmlPanel');
                if (!geojson || !geojson.coordinates) {{
                    panel.innerHTML = '<h3>KML Routes</h3><p style="color: #888;">No route data available.</p>';
                    return;
                }}
                const coords = geojson.coordinates;
                let html = '<h3>KML Routes</h3>';
                html += `<div class="kml-route"><div class="kml-route-title">Total Waypoints: ${{coords.length}}</div>`;
                html += '<div class="kml-coords">';
                coords.forEach((c, i) => {{
                    const lon = c[0].toFixed(6), lat = c[1].toFixed(6), alt = (c[2] || 0).toFixed(1);
                    html += `${{i + 1}}. [${{lon}}, ${{lat}}, ${{alt}}m]\\n`;
                }});
                html += '</div></div>';
                panel.innerHTML = html;
            }}

            (async function() {{
                try {{
                    // JSZip is already inlined above; no need to load remotely
                    let groups = [];
                    if (manualCoords && manualCoords.length) {{
                        groups = [manualCoords];
                    }} else if (kmzBase64 && kmzBase64.length) {{
                        // send KMZ to backend and use returned geojson
                        try {{
                            const blob = new Blob([b64ToUint8Array(kmzBase64)], {{type:'application/vnd.google-earth.kmz'}});
                            const form = new FormData();
                            form.append('file', blob, 'upload.kmz');
                            const resp = await fetch('/upload-kmz', {{method:'POST', body: form}});
                            const json = await resp.json();
                            if (json.geojson && json.geojson.coordinates) {{
                                const coordsRaw = json.geojson.coordinates;
                                // Load waypoints from KMZ file
                                coordsRaw.forEach(c => {{
                                    addWaypoint(c[0], c[1]);
                                }});
                            }}
                        }} catch(e) {{ console.error('KMZ load failed', e); }}
                    }}
                }} catch (err) {{ console.error('KMZ parse failed', err); }}
            }})();

            // Drawing mode support
            const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
            handler.setInputAction(function(click) {{
                if (!drawingMode) return;
                const ellipsoid = viewer.scene.globe.ellipsoid;
                const cartesian = viewer.camera.pickEllipsoid(click.position, ellipsoid);
                if (Cesium.defined(cartesian)) {{
                    const cartographic = ellipsoid.cartesianToCartographic(cartesian);
                    const lon = Cesium.Math.toDegrees(cartographic.longitude);
                    const lat = Cesium.Math.toDegrees(cartographic.latitude);
                    addWaypoint(lon, lat);
                }}
            }}, Cesium.ScreenSpaceEventType.LEFT_CLICK);
            
            // Button event listeners
            document.getElementById('drawMode').addEventListener('click', (e) => {{
                drawingMode = !drawingMode;
                e.target.classList.toggle('active');
                document.getElementById('finishDraw').style.display = drawingMode ? 'block' : 'none';
                if (!drawingMode) {{
                    viewer.canvas.style.cursor = 'default';
                }} else {{
                    viewer.canvas.style.cursor = 'crosshair';
                }}
            }});
            
            document.getElementById('finishDraw').addEventListener('click', () => {{
                drawingMode = false;
                document.getElementById('drawMode').classList.remove('active');
                document.getElementById('finishDraw').style.display = 'none';
                viewer.canvas.style.cursor = 'default';
            }});
            
            document.getElementById('undoBtn').addEventListener('click', () => {{
                if (waypoints.length > 0) {{
                    waypoints.pop();
                    updateWaypointsList();
                    updatePath();
                }}
            }});
            
            document.getElementById('addWaypoint').addEventListener('click', () => {{
                drawingMode = !drawingMode;
                document.getElementById('drawMode').classList.toggle('active');
                document.getElementById('finishDraw').style.display = drawingMode ? 'block' : 'none';
                viewer.canvas.style.cursor = drawingMode ? 'crosshair' : 'default';
            }});
            
            document.getElementById('clearAll').addEventListener('click', () => {{
                if (confirm('Clear all waypoints?')) {{
                    clearWaypoints();
                }}
            }});
            
            // Fullscreen toggle
            document.getElementById('fullscreenBtn').addEventListener('click', () => {{
                const container = document.getElementById('mainContainer');
                container.classList.toggle('fullscreen');
                if (viewer) viewer.forceResize();
            }});
            document.addEventListener('keydown', (e) => {{
                if (e.key === 'Escape') {{
                    document.getElementById('mainContainer').classList.remove('fullscreen');
                    document.getElementById('drawMode').classList.remove('active');
                    drawingMode = false;
                    if (viewer) viewer.forceResize();
                }}
            }});
            
            // Drone trace animation
            let droneEntity = null;
            document.getElementById('droneBtn').addEventListener('click', () => {{
                if (waypoints.length < 2) {{
                    alert('Add at least 2 waypoints to trace drone path');
                    return;
                }}
                if (droneEntity) {{
                    viewer.entities.remove(droneEntity);
                    droneEntity = null;
                    document.getElementById('droneBtn').textContent = '▶ Trace Drone';
                    return;
                }}
                const positions = waypoints.map(wp => Cesium.Cartesian3.fromDegrees(wp.lon, wp.lat, 100));
                const property = new Cesium.SampledPositionProperty();
                positions.forEach((pos, idx) => {{
                    const time = Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), idx * 2, new Cesium.JulianDate());
                    property.addSample(time, pos);
                }});
                droneEntity = viewer.entities.add({{
                    position: property,
                    point: {{
                        pixelSize: 12,
                        color: Cesium.Color.YELLOW,
                        outlineColor: Cesium.Color.BLACK,
                        outlineWidth: 2
                    }},
                    label: {{
                        text: 'DRONE',
                        font: '10px sans-serif',
                        fillColor: Cesium.Color.WHITE,
                        verticalOrigin: Cesium.VerticalOrigin.BOTTOM
                    }}
                }});
                viewer.clock.startTime = Cesium.JulianDate.now();
                viewer.clock.stopTime = Cesium.JulianDate.addSeconds(viewer.clock.startTime, waypoints.length * 2, new Cesium.JulianDate());
                viewer.clock.currentTime = viewer.clock.startTime;
                viewer.clock.multiplier = 1;
                viewer.clock.shouldAnimate = true;
                document.getElementById('droneBtn').textContent = '⊠ Stop Trace';
            }});
        </script>
        </body>
        </html>
        """

st.set_page_config(page_title="Skyphor")
st.title("Skyphor")
# small subtitle below the main title
st.caption("presented by Charlie Brooks")

# allow users to paste raw coordinate pairs if KMZ fails
coords_text = st.text_area("Or paste lon,lat coordinate pairs (space/newline separated)", "")

uploaded = st.file_uploader("Upload KMZ file", type=["kmz"]) 

if coords_text.strip():
    # parse manual coordinates
    parts = coords_text.strip().split()
    flat = []
    try:
        for p in parts:
            lon, lat = p.split(',')
            flat.extend([float(lon), float(lat)])
        if len(flat) < 4:
            raise ValueError("need at least two points")
        geojson = {"type": "LineString", "coordinates": [[flat[i], flat[i+1]] for i in range(0, len(flat), 2)]}
        st.success("Coordinates loaded")
        st.write(geojson)
        manual_coords = flat
    except Exception as e:
        st.error(f"Failed to parse coordinates: {e}")
        manual_coords = None
else:
    manual_coords = None

if uploaded is not None or manual_coords is not None:
    try:
        if uploaded is not None:
            raw = uploaded.read()
            geojson = parse_kmz(raw)
            st.success("KMZ parsed successfully")
            st.write(geojson)
            import base64
            kmz_b64 = base64.b64encode(raw).decode('ascii')
        else:
            kmz_b64 = ""
        # use a reasonable default corridor width for visualization
        thickness = 10.0

        html = _build_cesium_html(kmz_b64, thickness, manual_coords)
        components_html(html, height=700, scrolling=True)
    except Exception as e:
        st.error(f"Failed to process input: {e}")
else:
    st.info("Upload a KMZ file or paste coordinates to preview the route in 3D.")
