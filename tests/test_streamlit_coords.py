import json
import streamlit_app


def test_builder_includes_manual_coords():
    # passing a simple coordinate list should embed it verbatim
    coords = [-122.0, 37.0, -121.0, 38.0]
    html = streamlit_app._build_cesium_html("", thickness=5.0, manual_coords=coords)
    assert "const manualCoords" in html
    # the JSON should match
    assert json.dumps(coords) in html
    # kmzBase64 should be empty string
    assert 'const kmzBase64 = ""' in html
    # thickness value present
    assert "const thickness = 5.0" in html
    assert "weatherPanel" in html and "mscweather.com/weekly" in html


def test_builder_handles_no_manual():
    html = streamlit_app._build_cesium_html("", thickness=2.5, manual_coords=None)
    assert "const manualCoords = null" in html
    assert "const kmzBase64 = \"\"" in html
    assert "const thickness = 2.5" in html
    assert "weatherPanel" in html