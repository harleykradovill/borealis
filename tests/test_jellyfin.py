import json
from jellyfin import create_client


class FakeSettings:
    def get(self):
        return {
            "jf_host": "127.0.0.1",
            "jf_port": "8096",
            "jf_api_key": "token123",
        }


class FakeResp:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def fake_urlopen(req, timeout: float = 5.0):
    url = getattr(req, "full_url", None)
    if not url:
        url = req.get_full_url() if hasattr(req, "get_full_url") else ""
    if url.endswith("/System/Info"):
        return FakeResp(200, {"name": "jellyfin", "version": "10.8"})
    if url.endswith("/Users"):
        return FakeResp(200, [{"Id": "1", "Name": "admin"}])
    if url.endswith("/Library/MediaFolders"):
        return FakeResp(200, [{"Id": "folder1", "Path": "/media"}])
    return FakeResp(404, {})


def test_system_users_libraries_success(monkeypatch):
    svc = FakeSettings()
    client = create_client(svc)

    monkeypatch.setattr("jellyfin.urlopen", fake_urlopen)

    sys_info = client.system_info()
    assert sys_info["ok"] is True
    assert sys_info["status"] == 200
    assert sys_info["data"]["name"] == "jellyfin"

    users = client.users()
    assert users["ok"] is True
    assert users["status"] == 200
    assert isinstance(users["data"], list)
    assert users["data"][0]["Id"] == "1"

    libs = client.libraries()
    assert libs["ok"] is True
    assert libs["status"] == 200
    assert isinstance(libs["data"], list)
    assert libs["data"][0]["Id"] == "folder1"

def test_get_http_error_returns_proper_response(monkeypatch):
    from urllib.error import HTTPError

    def raise_http(req, timeout: float = 5.0):
        raise HTTPError(url="http://fake", code=401, msg="Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("jellyfin.urlopen", raise_http)

    client = create_client(FakeSettings())
    res = client.system_info()

    assert res["ok"] is False
    assert res["status"] == 401
    assert "HTTP error from Jellyfin (401)" in res.get("message", "")


def test_get_url_error_returns_proper_response(monkeypatch):
    from urllib.error import URLError

    def raise_url(req, timeout: float = 5.0):
        raise URLError("timed out")

    monkeypatch.setattr("jellyfin.urlopen", raise_url)

    client = create_client(FakeSettings())
    res = client.system_info()

    assert res["ok"] is False
    assert res["status"] == 0
    assert "Network error" in res.get("message", "")
    assert "timed out" in res.get("message", "")

def test_missing_settings_returns_400():
    class MissingSettings:
        def get(self):
            return {}

    client = create_client(MissingSettings())
    res = client.system_info()

    assert res["ok"] is False
    assert res["status"] == 400
    assert "Missing or invalid host/port/token" in res.get("message", "")


def test_missing_token_returns_400():
    class NoTokenSettings:
        def get(self):
            return {
                "jf_host": "127.0.0.1",
                "jf_port": "8096",
                "jf_api_key": "",
            }

    client = create_client(NoTokenSettings())
    res = client.system_info()

    assert res["ok"] is False
    assert res["status"] == 400
    assert "Missing or invalid host/port/token" in res.get("message", "")


def test_non_numeric_port_returns_400():
    class BadPortSettings:
        def get(self):
            return {
                "jf_host": "127.0.0.1",
                "jf_port": "eightythree",
                "jf_api_key": "token123",
            }

    client = create_client(BadPortSettings())
    res = client.system_info()

    assert res["ok"] is False
    assert res["status"] == 400
    assert "Missing or invalid host/port/token" in res.get("message", "")