import json
import streamlit as st
from streamlit.components.v1 import html as components_html
from droneflight.kmz import parse_kmz


def _build_cesium_html(kmz_b64: str, thickness: float) -> str:
    """Return a minimal Cesium HTML page that will visualize a KMZ payload.

    ``kmz_b64`` should be a base64-encoded string of the raw KMZ bytes and
    ``thickness`` is injected into the JS to control corridor width / sample
    animation behaviour. The body of this function is a verbatim copy of the
    large f-string previously embedded inline; extracting it makes it
    easier to test and avoids accidental f-string brace bugs (see
    https://github.com/crbrooks10/droneflight/pull/???).
    """
    return f"""
        <!DOCTYPE html>
        <html lang=\"en\"> 
        <head>
            <meta charset=\"utf-8\" />
            <script src=\"https://cesium.com/downloads/cesiumjs/releases/1.111/Build/Cesium/Cesium.js\"></script>
            <link href=\"https://cesium.com/downloads/cesiumjs/releases/1.111/Build/Cesium/Widgets/widgets.css\" rel=\"stylesheet\" />
            <style>html, body, #cesiumContainer {{ height:100%; margin:0; padding:0; }}</style>
        </head>
        <body>
        <div id=\"controls\">
            <button id=\"startDraw\">Start new line</button>
            <button id=\"finishDraw\">Finish line</button>
            <button id=\"clearDrawings\">Clear drawings</button>
        </div>
        <div id=\"cesiumContainer\"></div>
        <script>
            const viewer = new Cesium.Viewer('cesiumContainer', {{ terrainProvider: Cesium.createWorldTerrain() }});
            const kmzBase64 = "{kmz_b64}";
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
                    const data = b64ToUint8Array(kmzBase64).buffer;
                    const zip = await JSZip.loadAsync(data);
                    const kmlFiles = Object.keys(zip.files).filter(n => n.toLowerCase().endsWith('.kml'));
                    const groups = [];
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
                    let firstEntity = null;
                    groups.forEach((coordsArr) => {{
                        const e = viewer.entities.add({{ // braces doubled to escape f-string
                            corridor: {{ positions: Cesium.Cartesian3.fromDegreesArray(coordsArr), width: thickness, material: Cesium.Color.RED.withAlpha(0.8), height:0, extrudedHeight:5.0 }}
                        }});
                        if (!firstEntity) firstEntity = e;
                    }});
                    if (firstEntity) viewer.zoomTo(firstEntity);

                    if (firstEntity) {{
                        const coords = groups[0];
                        const property = new Cesium.SampledPositionProperty();
                        for (let i = 0; i < coords.length; i += 2) {{
                            const lon = coords[i]; const lat = coords[i+1];
                            const time = Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), i, new Cesium.JulianDate());
                            property.addSample(time, Cesium.Cartesian3.fromDegrees(lon, lat));
                        }}
                        // outer braces doubled to avoid Python interpreting ``position``
                        viewer.entities.add({{position: property, point: {{ pixelSize: 8, color: Cesium.Color.BLUE }}}});
                        viewer.clock.startTime = Cesium.JulianDate.now();
                        viewer.clock.stopTime = Cesium.JulianDate.addSeconds(viewer.clock.startTime, groups[0].length/2, new Cesium.JulianDate());
                        viewer.clock.currentTime = viewer.clock.startTime; viewer.clock.multiplier = 1; viewer.clock.shouldAnimate = true;
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

            // animate along first group if available
            if (groups.length && groups[0].length >= 2) {{
                const coordsAnim = groups[0];
                const property = new Cesium.SampledPositionProperty();
                for (let i = 0; i < coordsAnim.length; i += 2) {{
                    const lon = coordsAnim[i];
                    const lat = coordsAnim[i+1];
                    const time = Cesium.JulianDate.addSeconds(Cesium.JulianDate.now(), i, new Cesium.JulianDate());
                    property.addSample(time, Cesium.Cartesian3.fromDegrees(lon, lat));
                }}
                viewer.entities.add({{position: property, point: {{ pixelSize: 8, color: Cesium.Color.BLUE }}}});
                viewer.clock.startTime = Cesium.JulianDate.now();
                viewer.clock.stopTime = Cesium.JulianDate.addSeconds(viewer.clock.startTime, coordsAnim.length/2, new Cesium.JulianDate());
                viewer.clock.currentTime = viewer.clock.startTime;
                viewer.clock.multiplier = 1;
                viewer.clock.shouldAnimate = true;
            }}
        </script>
        </body>
        </html>
        """

st.set_page_config(page_title="DroneFlight Planner")
st.title("DroneFlight Planner — Streamlit")

uploaded = st.file_uploader("Upload KMZ file", type=["kmz"]) 

if uploaded is not None:
    try:
        raw = uploaded.read()
        geojson = parse_kmz(raw)
        st.success("KMZ parsed successfully")
        st.write(geojson)

        # offer a downloadable 3D model (OBJ format)
        # older versions of the app allowed downloading a generated OBJ
        # model, however the current requirements forbid exporting anything
        # derived from the KMZ.  The backend helper :func:`kmz_to_obj` is
        # still available for internal use and unit tests, but we deliberately
        # do not expose it in the UI.
        #
        # hence, no download button is shown here.
        pass

        # embed raw KMZ bytes into the HTML so the client (browser) can parse
        import base64
        kmz_b64 = base64.b64encode(raw).decode('ascii')

        # Minimal Cesium HTML; use helper to avoid f-string brace issues
        html = _build_cesium_html(kmz_b64, thickness)

        components_html(html, height=700, scrolling=True)

    except Exception as e:
        st.error(f"Failed to parse KMZ: {e}")
else:
    st.info("Upload a KMZ file to preview the route in 3D.")
