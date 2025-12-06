"""
Pytest integration tests validating route availability, template rendering,
static file serving, and fundamental page structure provided by Flask.
"""

from typing import Generator

import pytest
from app import create_app


@pytest.fixture()
def client() -> Generator:
    """
    Create Flask test client with DEBUG enabled.
    
    :return: A test client instance for making requests
    :rtype: Generator[Any, None, None]
    """
    app = create_app({"DEBUG": True})
    with app.test_client() as client:
        yield client


def test_index_returns_ok_and_content(client) -> None:
    """
    Ensure the index route returns HTTP 200 and expected page content.
    
    :param client: The generated client
    :type client: Any
    """
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Borealis" in body

def test_unknown_route_returns_404(client) -> None:
    """
    Ensure that unknown URLs return a 404 status code.
    
    :param client: The generated client
    :type client: Any
    """
    resp = client.get("/not-found")
    assert resp.status_code == 404

def test_index_has_navbar_and_active_home(client) -> None:
    """
    Ensure that the index page includes navbar structure and active state for Home.
    
    :param client: The generated client
    :type client: Any
    """
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
    """
    Ensure that static CSS assets are available and contain expected rules.

    :param client: The generated client
    :type client: Any
    """
    resp = client.get("/static/css/site.css")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert ":root" in text
    assert "--bg" in text

def test_static_logo_is_served(client) -> None:
    """
    Ensure that the Borealis logo image is served from assets.
    """
    resp = client.get("/assets/images/borealis.png")
    assert resp.status_code == 200
    assert resp.headers.get("Content-Type", "").startswith("image/")