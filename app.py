import os
import zipfile
import json
from io import BytesIO
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv

# load configuration from .env
load_dotenv()

app = Flask(__name__)
app.config.from_mapping(
    OPENWEATHER_API_KEY=os.getenv("OPENWEATHER_API_KEY"),
    RADAR_API_URL=os.getenv("RADAR_API_URL"),
)


def parse_kmz(kmz_bytes: bytes) -> dict:
    """Unpack a KMZ (zip) stream and return the first <coordinates> element as
    a GeoJSON LineString.  For simplicity we only handle the very common case
    of a single <Placemark><LineString> path.  A real implementation should
    be more robust.
    """
    with zipfile.ZipFile(BytesIO(kmz_bytes)) as z:
        # find the KML file
        kml_name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
        if not kml_name:
            raise ValueError("no .kml found in kmz")
        kml_data = z.read(kml_name).decode("utf-8")

    # crude extraction of coordinates; use lxml or BeautifulSoup in prod
    import re
    m = re.search(r"<coordinates>([^<]+)</coordinates>", kml_data)
    if not m:
        raise ValueError("no coordinates in kml")
    coords_text = m.group(1).strip()
    coords = []
    for pair in coords_text.split():
        lon, lat, *_ = pair.split(",")
        coords.append([float(lon), float(lat)])
    return {"type": "LineString", "coordinates": coords}


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/upload-kmz", methods=["POST"])
def upload_kmz():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file provided"}), 400
    try:
        geojson = parse_kmz(file.read())
    except Exception as ex:
        return jsonify({"error": str(ex)}), 400
    return jsonify({"geojson": geojson})


@app.route("/weather", methods=["GET"])
def get_weather():
    # dummy implementation; in a real app call an external API
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    api_key = app.config["OPENWEATHER_API_KEY"]
    if not api_key:
        return jsonify({"error": "no api key configured"}), 500
    # example call:
    # r = requests.get("https://api.openweathermap.org/data/2.5/onecall", params={
    #     "lat": lat, "lon": lon, "appid": api_key
    # })
    # return r.json()
    return jsonify({"dummy": True, "lat": lat, "lon": lon})


@app.route("/radar", methods=["GET"])
def get_radar():
    # placeholder
    return jsonify({"radar": "not implemented"})


if __name__ == "__main__":
    app.run(debug=True)
