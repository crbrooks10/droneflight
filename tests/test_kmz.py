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


def test_streamlit_html_builder():
    # importing the module should succeed and building HTML must not raise
    import base64
    # streamlit isn't installed in the test environment so insert a simple
    # fake module before importing the app. only the helper function is used,
    # so most of the API can be a no-op.
    import sys, types
    streamlit_mock = types.SimpleNamespace(
        set_page_config=lambda *args, **kwargs: None,
        title=lambda *args, **kwargs: None,
        file_uploader=lambda *args, **kwargs: None,
        number_input=lambda *args, **kwargs: 0.0,
        download_button=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: None,
        write=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
    )
    comp_v1 = types.SimpleNamespace(html=lambda *args, **kwargs: None)
    streamlit_components = types.SimpleNamespace(v1=comp_v1)
    sys.modules['streamlit'] = streamlit_mock
    sys.modules['streamlit.components'] = streamlit_components
    sys.modules['streamlit.components.v1'] = comp_v1
    import streamlit_app

    kmz_b64 = base64.b64encode(KMZ_SAMPLE).decode('ascii')
    html = streamlit_app._build_cesium_html(kmz_b64, thickness=0.5)
    # core pieces are present and braces were escaped correctly during f-string
    assert "kmzBase64" in html
    assert "viewer.entities.add({position" in html
    # the templating escape should have been resolved, so no literal '{{position'
    assert "{{position" not in html
