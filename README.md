# DroneFlight

Python‑based pre‑flight planning application for unmanned aircraft systems.

This project provides a starting point for mapping a drone mission in 3‑D,
importing a KMZ flight plan, overlaying weather and radar information, and
suggesting optimal launch times.  The application is implemented as a simple
Flask web service with a lightweight frontend that uses CesiumJS to render
the flight path and terrain.

## Features (planned)

1. **KMZ upload & parsing** – drag’n’drop or file selector for Google Earth
	KMZ files; routes are extracted and converted to GeoJSON for display.
2. **3D visualization** – interactive globe/terrain powered by CesiumJS.

   * New: uploaded KMZ routes can now be converted into a simple 3D model
     (Wavefront OBJ) for offline use or import into modeling tools. The
     backend exposes a `kmz_to_obj` helper and the path editor can also
     export any route as OBJ.  
     By default the OBJ is a polyline; if you supply a small
     ``thickness`` value the code will build a thin ribbon (quad faces)
     which mesh viewers such as MeshLab will render properly.
3. **Weather & radar integration** – fetch current and forecast conditions
	from an external API (OpenWeather, NOAA, etc.) and overlay them on the map.
4. **Flight‑time recommendations** – simple logic to suggest a departure window
	based on wind, precipitation, and nearby airspace activity.
5. **Path editing** – adjust waypoints in the browser using the Cesium drawing
	API or by modifying the uploaded route; the client side code can be extended
	to allow dragging, inserting or deleting points and then exporting the
	revised path as KMZ/GeoJSON.
6. **Streamlit frontend** – optional lightweight UI that runs entirely in
	Streamlit, useful for desktop or spill‑proof demos.

## Quick start
## Made a new branch
```bash
git clone https://github.com/crbrooks10/droneflight.git
cd droneflight
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Flask web service:
export FLASK_APP=app.py
flask run
# open http://localhost:5000 in your browser

# Streamlit frontend (optional):
# streamlit run streamlit_app.py
```
Edit `config.example.env` and rename it to `.env` to configure API keys and
other settings.

## Development notes

- Backend is in `app.py` and helper modules under `droneflight/`.
- Static assets (HTML/JS/CSS) are in `static/`; templates use Jinja2.
- Extend the `get_weather` and `get_radar` functions to tie into real APIs.
Contributions welcome – file an issue or open a pull request on GitHub.
