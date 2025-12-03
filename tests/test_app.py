from typing import Generator

import pytest
from app import create_app


@pytest.fixture()
def client() -> Generator:
    app = create_app({"DEBUG": True})
    with app.test_client() as client:
        yield client


def test_index_returns_ok_and_content(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Borealis" in body

def test_unknown_route_returns_404(client) -> None:
    resp = client.get("/not-found")
    assert resp.status_code == 404

def test_index_has_navbar_and_active_home(client) -> None:
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    # Navbar elements
    assert '<header class="navbar"' in body
    assert ">Home<" in body
    assert ">Users<" in body
    assert ">Libraries<" in body
    assert ">Settings<" in body
    # Active state on Home for index route
    assert '<a href="/" class="active">Home</a>' in body

def test_static_css_is_served(client) -> None:
    resp = client.get("/assets/css/site.css")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert ":root" in text
    assert "--bg" in text