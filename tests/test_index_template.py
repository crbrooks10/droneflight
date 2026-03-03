import re

def test_index_includes_coordinate_textarea():
    text = open('templates/index.html').read()
    assert 'id="coordsText"' in text
    assert 'id="loadCoordsBtn"' in text
    # should have JS handler registration
    assert re.search(r"loadCoordsBtn" , text)
    # weather panel with KML routes should appear
    assert 'id="weatherPanel"' in text
    assert 'id="kmlPanel"' in text
    # should load our local Cesium assets
    assert '/static/cesium.js' in text or 'Cesium.js' in text
    assert 'id="droneBtn"' in text
