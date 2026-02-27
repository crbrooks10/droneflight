import pytest
from app import app


def test_index_route(client):
    rv = client.get('/')
    assert rv.status_code == 200
    assert b"DroneFlight Planner" in rv.data


@pytest.fixture

def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c
