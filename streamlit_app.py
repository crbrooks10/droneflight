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
            <style>html, body, #cesiumContainer {{ height:100%; margin:0; padding:0; }}
            #mainContainer {{ display:flex; height:100%; }}
            #mainContainer {{ display:flex; height:100%; }}
            #weatherPanel {{ flex:1; order:0; border-right:1px solid #ccc; }}
            #controls {{ order:1; padding:8px; }}
            #cesiumContainer {{ flex:3; order:2; }}
            #weatherPanel iframe {{ width:100%; height:100%; border:0; }}
            </style>
        </head>
        <body>
        <div id="mainContainer">
            <div id="weatherPanel"><iframe id="weatherFrame" src="/weather" sandbox="allow-scripts allow-same-origin" onerror="this.parentElement.innerText='Weather unavailable';"></iframe></div>
            <div id="controls">
            <button id="startDraw">Start new line</button>
            <button id="finishDraw">Finish line</button>
            <button id="clearDrawings">Clear drawings</button>
            <button id="droneBtn">Trace Drone</button>
        </div>
        <div id="cesiumContainer"></div>
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

            function b64ToUint8Array(b64) {{
                const binary = atob(b64);
                const len = binary.length;
                const bytes = new Uint8Array(len);
                for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
                return bytes;
            }}

            (async function() {{
                try {{
                    // JSZip is already inlined above; no need to load remotely
                    let groups = [];
                    if (manualCoords && manualCoords.length) {{
                        groups = [manualCoords];
                    }} else if (kmzBase64 && kmzBase64.length) {{
                        // send KMZ to backend and use returned geojson/obj
                        try {{
                            const blob = new Blob([b64ToUint8Array(kmzBase64)], {{type:'application/vnd.google-earth.kmz'}});
                            const form = new FormData();
                            form.append('file', blob, 'upload.kmz');
                            const resp = await fetch('/upload-kmz', {{method:'POST', body: form}});
                            const json = await resp.json();
                            if (json.geojson && json.geojson.coordinates) {{
                                const coordsRaw = json.geojson.coordinates;
                                const coordsArr = coordsRaw.map(c=>[c[0],c[1]]);
                                const flat = [];
                                coordsArr.forEach(c=>{{ flat.push(c[0]); flat.push(c[1]); }});
                                groups = [flat];
                                // if altitude present, render altitude polyline preview
                                try {{
                                    const hasAlt = coordsRaw.length && coordsRaw[0].length >= 3;
                                    if (hasAlt) {{
                                        const positions = coordsRaw.map(c=>Cesium.Cartesian3.fromDegrees(c[0], c[1], c[2] || 0));
                                        viewer.entities.add({{ polyline: {{ positions: positions, width:3, material: Cesium.Color.CYAN }} }});
                                    }}
                                }} catch(e) {{ console.error('preview polyline failed', e); }}
                            }}
                            if (json.obj) {{
                                // render OBJ altitude polyline
                                const verts=[];
                                json.obj.split('\n').forEach(l=>{{
                                    if (l.startsWith('v ')) {{
                                        const parts=l.split(/\s+/);
                                        if (parts.length>=4) verts.push({{lon:parseFloat(parts[1]),lat:parseFloat(parts[2]),alt:parseFloat(parts[3])}});
                                    }}
                                }});
                                if (verts.length>1) {{
                                    const positions=verts.map(v=>Cesium.Cartesian3.fromDegrees(v.lon,v.lat,v.alt));
                                    viewer.entities.add({{polyline: {{positions, width:4, material:Cesium.Color.GREEN}}}});
                                }}
                            }}
                        }} catch(e) {{ console.error('server parse failed', e); }}
                    }} // end else-if kmzBase64
                    let firstEntity = null;
                    groups.forEach((coordsArr) => {{
                        const e = viewer.entities.add({{ // braces doubled to escape f-string
                            corridor: {{ positions: Cesium.Cartesian3.fromDegreesArray(coordsArr), width: thickness, material: Cesium.Color.RED.withAlpha(0.8), height:0, extrudedHeight:5.0 }}
                        }});
                        if (!firstEntity) firstEntity = e;
                    }});
                    if (firstEntity) viewer.zoomTo(firstEntity);

                    // animate along ALL KML lines, not just the first
                    groups.forEach((coords) => {{
                        if (coords.length >= 2) {{
                            const property = new Cesium.SampledPositionProperty();
                            for (let i = 0; i < coords.length; i += 2) {{
                                const lon = coords[i]; const lat = coords[i+1];
                                const time = Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), i, new Cesium.JulianDate());
                                property.addSample(time, Cesium.Cartesian3.fromDegrees(lon, lat));
                            }}
                            viewer.entities.add({{position: property, point: {{ pixelSize: 8, color: Cesium.Color.BLUE }}}});
                        }}
                    }});
                    // drone tracing support for Streamlit
                    let droneEntity = null;
                    document.getElementById('droneBtn').addEventListener('click', () => {{
                        if (!groups.length) return;
                        if (droneEntity) {{ viewer.entities.remove(droneEntity); droneEntity = null; return; }}
                        const coords = groups[0];
                        const prop = new Cesium.SampledPositionProperty();
                        for (let i = 0; i < coords.length; i += 2) {{
                            const lon = coords[i], lat = coords[i+1];
                            const time = Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), i, new Cesium.JulianDate());
                            prop.addSample(time, Cesium.Cartesian3.fromDegrees(lon, lat));
                        }}
                        droneEntity = viewer.entities.add({{position: prop, point: {{ pixelSize: 12, color: Cesium.Color.YELLOW }}}});
                        viewer.clock.startTime = Cesium.JulianDate.now();
                        viewer.clock.stopTime = Cesium.JulianDate.addSeconds(viewer.clock.startTime, coords.length/2, new Cesium.JulianDate());
                        viewer.clock.currentTime = viewer.clock.startTime;
                        viewer.clock.multiplier = 1;
                        viewer.clock.shouldAnimate = true;
                    }});
                    // set clock to span the longest path
                    if (groups.length > 0) {{
                        const maxLen = Math.max(...groups.map(g => g.length / 2));
                        viewer.clock.startTime = Cesium.JulianDate.now();
                        viewer.clock.stopTime = Cesium.JulianDate.addSeconds(viewer.clock.startTime, maxLen, new Cesium.JulianDate());
                        viewer.clock.currentTime = viewer.clock.startTime;
                        viewer.clock.multiplier = 1;
                        viewer.clock.shouldAnimate = true;
                    }}
                }} catch (err) {{ console.error('KMZ parse failed', err); }}
            }})();

            // drawing support
            let drawing = false;
            let currentPositions = [];
            let currentEntity = null;
            const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
            handler.setInputAction(function(click) {{
                if (!drawing) return;
                const cart = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
                if (cart) {{
                    currentPositions.push(cart);
                    if (!currentEntity) {{
                        currentEntity = viewer.entities.add({{
                            polyline: {{
                                positions: new Cesium.CallbackProperty(function() {{ return currentPositions; }}, false),
                                width: 4,
                                material: Cesium.Color.BLUE
                            }}
                        }});
                    }}
                }}
            }}, Cesium.ScreenSpaceEventType.LEFT_CLICK);
            document.getElementById('startDraw').addEventListener('click', () => {{
                drawing = true;
                currentPositions = [];
                if (currentEntity) {{ viewer.entities.remove(currentEntity); currentEntity = null; }}
            }});
            document.getElementById('finishDraw').addEventListener('click', () => {{ drawing = false; }});
            document.getElementById('clearDrawings').addEventListener('click', () => {{
                drawing = false;
                currentPositions = [];
                if (currentEntity) {{ viewer.entities.remove(currentEntity); currentEntity = null; }}
            }});

            // Drawing support - same as Flask frontend
        </script>
        </body>
        </html>
        """

st.set_page_config(page_title="DroneFlight Planner")
st.title("DroneFlight Planner — Streamlit")

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
