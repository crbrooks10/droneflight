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
    """
    # JSON-encode the manual coordinate list so it can be interpolated into
    # the generated script.  ``null`` in the template means "no manual data"
    coords_json = json.dumps(manual_coords) if manual_coords is not None else "null"
    # allow passing None for kmz_b64 as empty string in JS
    kmz = kmz_b64 or ""
    return f"""
        <!DOCTYPE html>
        <html lang=\"en\"> 
        <head>
            <meta charset=\"utf-8\" />
            <script src=\"https://cesium.com/downloads/cesiumjs/releases/1.111/Build/Cesium/Cesium.js\"></script>
            <link href=\"https://cesium.com/downloads/cesiumjs/releases/1.111/Build/Cesium/Widgets/widgets.css\" rel=\"stylesheet\" />
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
            <div id="weatherPanel"><iframe id="weatherFrame" src="https://mscweather.com/weekly" sandbox="allow-scripts allow-same-origin"></iframe></div>
            <div id="controls">
            <button id="startDraw">Start new line</button>
            <button id="finishDraw">Finish line</button>
            <button id="clearDrawings">Clear drawings</button>
        </div>
        <div id="cesiumContainer"></div>
        </div>
        <script>
            const viewer = new Cesium.Viewer('cesiumContainer', {{ terrainProvider: Cesium.createWorldTerrain() }});
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
                    if (!window.JSZip) {{
                        await new Promise((res, rej) => {{
                            const s = document.createElement('script');
                            s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.7.1/jszip.min.js';
                            s.onload = res; s.onerror = rej; document.head.appendChild(s);
                        }});
                    }}
                    let groups = [];
                    if (manualCoords && manualCoords.length) {{
                        groups = [manualCoords];
                    }} else {{
                        const data = b64ToUint8Array(kmzBase64).buffer;
                        const zip = await JSZip.loadAsync(data);
                        const kmlFiles = Object.keys(zip.files).filter(n => n.toLowerCase().endsWith('.kml'));
                        for (const name of kmlFiles) {{
                            const text = await zip.file(name).async('string');
                            const re = /<coordinates>([^<]+)<\/coordinates>/g;
                            let m;
                            while ((m = re.exec(text)) !== null) {{
                                const coordsText = m[1].trim();
                                const parts = coordsText.split(/\s+/);
                                const flat = [];
                                for (const p of parts) {{
                                    const comps = p.split(',');
                                    if (comps.length >= 2) {{ flat.push(parseFloat(comps[0])); flat.push(parseFloat(comps[1])); }}
                                }}
                                if (flat.length >= 4) groups.push(flat);
                            }}
                        }}
                    }} // end else for manualCoords
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
