import json
import streamlit as st
from streamlit.components.v1 import html as components_html
from droneflight.kmz import parse_kmz

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
        try:
            from droneflight.kmz import kmz_to_obj

            thickness = st.number_input("Ribbon thickness (m)", min_value=0.0, value=0.0, step=0.1)
            obj_text = kmz_to_obj(raw, thickness=thickness)
            st.download_button("Download 3D model (OBJ)", data=obj_text,
                                file_name="flight_path.obj", mime="text/plain")
        except Exception:
            # if conversion fails we silently ignore
            pass

        # prepare one or more coordinate groups for the Cesium HTML
        if isinstance(geojson, dict) and geojson.get("type") == "FeatureCollection":
            groups = []
            for feat in geojson.get("features", []):
                coords = feat.get("geometry", {}).get("coordinates", [])
                groups.append([c for pair in coords for c in pair])
        else:
            coords = geojson.get("coordinates", [])
            groups = [[c for pair in coords for c in pair]]
        coords_groups_json = json.dumps(groups)

        # Minimal Cesium HTML using the same logic as the Flask app
        html = f"""
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
            const groups = {coords_groups_json};
            let firstEntity = null;
            groups.forEach((coordsArr) => {{
                const e = viewer.entities.add({{
                    corridor: {{
                        positions: Cesium.Cartesian3.fromDegreesArray(coordsArr),
                        width: {thickness},
                        material: Cesium.Color.RED.withAlpha(0.8),
                        height: 0,
                        extrudedHeight: 5.0
                    }}
                }});
                if (!firstEntity) firstEntity = e;
            }});
            if (firstEntity) viewer.zoomTo(firstEntity);

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

        components_html(html, height=700, scrolling=True)

    except Exception as e:
        st.error(f"Failed to parse KMZ: {e}")
else:
    st.info("Upload a KMZ file to preview the route in 3D.")
