import os
from typing import Generator

import pytest
from app import create_app

@pytest.fixture()
def client() -> Generator:
    """
    Create Flask test client bound to a temp SQLite DB and key file.
    """
    db_path = "sqlite:///test_settings.db"
    key_path = "test_secret.key"
    if os.path.exists("test_settings.db"):
        os.remove("test_settings.db")
    if os.path.exists(key_path):
        os.remove(key_path)

    app = create_app({
        "DEBUG": True,
        "DATABASE_URL": db_path,
        "ENCRYPTION_KEY_PATH": key_path,
    })
    with app.test_client() as client:
        yield client

    # Cleanup
    if os.path.exists("test_settings.db"):
        os.remove("test_settings.db")
    if os.path.exists(key_path):
        os.remove(key_path)


def test_api_settings_bootstrap_defaults(client) -> None:
    """
    First GET should create defaults and return them.
    """
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["hour_format"] in ("12", "24")
    assert data["language"] == "en"
    assert data["jf_host"] == "127.0.0.1"
    assert data["jf_port"] == "8096"
    assert data["jf_api_key"] is None


def test_api_settings_update_and_decrypt(client) -> None:
    """
    PUT should persist values and return decrypted jf_api_key in response.
    """
    payload = {
        "hour_format": "12",
        "language": "en",
        "jf_host": "localhost",
        "jf_port": "8096",
        "jf_api_key": "secret-api-key",
    }
    put = client.put("/api/settings", json=payload)
    assert put.status_code == 200
    updated = put.get_json()
    assert updated["hour_format"] == "12"
    assert updated["jf_host"] == "localhost"
    assert updated["jf_api_key"] == "secret-api-key"

    get = client.get("/api/settings")
    assert get.status_code == 200
    data = get.get_json()
    assert data["jf_api_key"] == "secret-api-key"


def test_api_settings_clear_key(client) -> None:
    """
    Clearing the API key sets stored ciphertext to None; response returns None.
    """
    client.put("/api/settings", json={"jf_api_key": "abc123"})
    resp = client.put("/api/settings", json={"jf_api_key": ""})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["jf_api_key"] is None

    get = client.get("/api/settings")
    assert get.status_code == 200
    data = get.get_json()
    assert data["jf_api_key"] is None