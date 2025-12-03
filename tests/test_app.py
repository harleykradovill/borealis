from typing import Generator

import pytest
from app import create_app


@pytest.fixture()
def client() -> Generator:
    """
    Create a Flask test client for the application.
    Uses the factory with DEBUG enabled to make failures more verbose.
    """
    app = create_app({"DEBUG": True})
    with app.test_client() as client:
        yield client


def test_index_returns_ok_and_content(client) -> None:
    """GET / should return 200 and mention 'Borealis' in the body."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Borealis" in body