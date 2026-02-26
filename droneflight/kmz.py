import zipfile
from io import BytesIO


def parse_kmz(kmz_bytes: bytes) -> dict:
    """Unpack a KMZ (zip) stream and return the first <coordinates> element as
    a GeoJSON LineString. For simplicity we only handle the very common case
    of a single <Placemark><LineString> path. A real implementation should be
    more robust.
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
