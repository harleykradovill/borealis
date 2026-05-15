import pytest

from app import create_app


@pytest.fixture
def app_instance(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app(
        {
            "TESTING": True,
            "DEBUG": True,
            "DATABASE_URL": f"sqlite:///{db_path}",
            "ENCRYPTION_KEY_PATH": ":memory:",
        }
    )
    yield app


@pytest.fixture
def client(app_instance):
    return app_instance.test_client()


def _configure_server(client):
    response = client.put(
        "/api/settings",
        json={
            "jf_host": "localhost",
            "jf_port": "8096",
            "jf_api_key": "test-token",
        },
    )
    assert response.status_code == 200


def test_app_factory_creates_flask_app(app_instance):
    assert app_instance is not None
    assert app_instance.config["TESTING"] is True


def test_setup_page_is_public(client):
    response = client.get("/setup")
    assert response.status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/", "/libraries", "/playbackactivity", "/settings"],
)
def test_protected_pages_redirect_to_setup_without_server(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code in (301, 302, 308)
    assert response.headers["Location"].endswith("/setup")


@pytest.mark.parametrize(
    "path",
    ["/", "/libraries", "/playbackactivity", "/settings"],
)
def test_protected_pages_are_available_after_server_config(client, path):
    _configure_server(client)
    response = client.get(path)
    assert response.status_code == 200


def test_assets_js_route_serves_from_static(client):
    response = client.get("/assets/js/site.js")
    assert response.status_code == 200
    assert response.data


def test_api_sync_periodic_uses_scheduler_trigger(client, app_instance):
    class TriggerSpy:
        def __init__(self):
            self.called = False

        def trigger_periodic_now(self):
            self.called = True

        def stop(self):
            return None

    spy = TriggerSpy()
    app_instance.sync_scheduler = spy

    response = client.post("/api/sync/periodic")
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert "timer reset" in body["message"].lower()
    assert spy.called is True


def test_api_jellyfin_libraries_returns_error_when_not_configured(client):
    response = client.get("/api/jellyfin/libraries")
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is False


def test_api_jellyfin_libraries_with_temp_credentials(monkeypatch, client):
    def fake_libraries(self):
        return {
            "ok": True,
            "data": [
                {"Id": "1", "CollectionType": "movies"},
                {"Id": "2", "CollectionType": "books"},
            ],
        }

    monkeypatch.setattr("services.jellyfin.JellyfinClient.libraries", fake_libraries)

    response = client.post(
        "/api/jellyfin/libraries",
        json={
            "jf_host": "localhost",
            "jf_port": "8096",
            "jf_api_key": "temp-token",
        },
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["Id"] == "1"


def test_primary_image_proxy_returns_404_when_not_configured(client):
    response = client.get("/api/jellyfin/items/123/images/primary")
    assert response.status_code == 404


def test_primary_image_proxy_uses_client_method(monkeypatch, client):
    def fake_item_primary_image(self, item_id, tag=None):
        assert item_id == "abc123"
        assert tag == "xyz"
        return {
            "ok": True,
            "status": 200,
            "body": b"image-bytes",
            "content_type": "image/png",
        }

    monkeypatch.setattr(
        "services.jellyfin.JellyfinClient.item_primary_image",
        fake_item_primary_image,
    )

    response = client.get("/api/jellyfin/items/abc123/images/primary?tag=xyz")

    assert response.status_code == 200
    assert response.data == b"image-bytes"
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "public, max-age=300"
