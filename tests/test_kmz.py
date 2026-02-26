import io
import zipfile

import pytest

from droneflight.kmz import parse_kmz, kmz_to_obj


KMZ_SAMPLE = b"""
PK\x03\x04\x14\x00\x00\x00\x00\x00\x00\x00!\x00\x8c}\xa6n\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00kml/\n<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">
  <Document>
    <Placemark>
      <LineString>
        <coordinates>
-122.42,37.77,100 -122.41,37.77,100 -122.41,37.78,100
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
PK\x01\x02\x14\x00\x14\x00\x00\x00\x00\x00\x00\x00!\x00\x8c}\xa6n\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00kml/\nPK\x05\x06\x00\x00\x00\x00\x01\x00\x01\x00*\x00\x00\x00\x93\x00\x00\x00\x00\x00"
"""  # small synthetic KMZ


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
