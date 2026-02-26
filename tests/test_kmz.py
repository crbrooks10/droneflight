import io
import zipfile

import pytest

from droneflight.kmz import parse_kmz, kmz_to_obj



# create a small valid KMZ in-memory for testing
from io import BytesIO
import zipfile

def make_sample_kmz() -> bytes:
    buf = BytesIO()
    coords = "-122.42,37.77,100 -122.41,37.77,100 -122.41,37.78,100"
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
{coords}
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>""")
    buf.seek(0)
    return buf.getvalue()

KMZ_SAMPLE = make_sample_kmz()


def test_parse_kmz_creates_geojson():
    geo = parse_kmz(KMZ_SAMPLE)
    assert geo["type"] == "LineString"
    assert len(geo["coordinates"]) == 3
    assert geo["coordinates"][0] == [-122.42, 37.77, 100]


def test_kmz_to_obj_output():
    obj = kmz_to_obj(KMZ_SAMPLE)
    # should contain vertices and a line
    assert "v -122.42 37.77 100" in obj
    assert obj.strip().endswith("l 1 2 3")


def test_kmz_to_obj_with_thickness():
    obj = kmz_to_obj(KMZ_SAMPLE, thickness=1.0)
    # vertices should double
    assert obj.count("v ") == 6
    # there should be faces connecting quads
    assert "f 1 3 4 2" in obj or "f 1 3 4 2" in obj
    # no polyline line element when thickness used
    assert "l " not in obj
