import re

def test_index_includes_coordinate_textarea():
    text = open('templates/index.html').read()
    assert 'id="coordsText"' in text
    assert 'id="loadCoordsBtn"' in text
    # should have JS handler registration
    assert re.search(r"loadCoordsBtn" , text)
