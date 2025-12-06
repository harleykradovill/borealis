"""
Provides an application factory that constructs and configures a
Flask instance used to server the Borealis site.
"""

from typing import Optional, Dict

try:
    from flask import Flask, Response, render_template, jsonify, request
except Exception as exc:
    raise RuntimeError(
        "Flask is required to run the local config site. "
        "Install with: pip install Flask"
    ) from exc


def create_app(test_config: Optional[Dict] = None) -> "Flask":
    """
    Create and configure the Borealis Flask application.
    
    :param test_config: Optional dictionary to inject configuration for tests
    :return: A fully initialized Flash application instance for Borealis
    :rtype: Flask
    """
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    app.config.setdefault("DEBUG", False)
    app.config.setdefault("PORT", 2929)
    app.config.setdefault("DATABASE_URL", "sqlite:///borealis.db")
    app.config.setdefault("ENCRYPTION_KEY_PATH", "secret.key")

    if test_config:
        app.config.update(test_config)
        if app.config.get("DEBUG", False):
            if "DATABASE_URL" not in test_config:
                app.config["DATABASE_URL"] = "sqlite:///:memory:"
            if "ENCRYPTION_KEY_PATH" not in test_config:
                app.config["ENCRYPTION_KEY_PATH"] = ":memory:"
        

    from settings_store import SettingsService
    svc = SettingsService(
        database_url=app.config["DATABASE_URL"],
        encryption_key_path=app.config["ENCRYPTION_KEY_PATH"],
    )

    from flask import send_from_directory
    @app.get("/assets/<path:filename>")
    def assets(filename: str) -> Response:
        if filename.startswith("js/"):
            return send_from_directory("static/js", filename.removeprefix("js/"))
        return send_from_directory("assets", filename)

    @app.get("/api/settings")
    def get_settings() -> Response:
        return jsonify(svc.get()), 200
    
    @app.put("/api/settings")
    def update_settings() -> Response:
        payload = request.get_json(silent=True) or {}
        updated = svc.update(payload)
        return jsonify(updated), 200
    
    @app.teardown_appcontext
    def _dispose_db(_exc: Optional[BaseException]) -> None:
        try:
            svc.engine.dispose()
        except Exception:
            pass

    @app.get("/api/test-connection")
    def test_connection() -> Response:
        """
        Test Jellyfin connectivity using persisted settings from the database.
        """
        from urllib.request import Request, urlopen
        from urllib.error import URLError, HTTPError

        settings = svc.get()
        host = (settings.get("jf_host") or "").strip()
        port = (settings.get("jf_port") or "").strip()
        token = (settings.get("jf_api_key") or "").strip()

        if not host or not port or not token:
            return jsonify({
                "ok": False,
                "status": 400,
                "message": "Missing host, port, or API key in settings."
            }), 200

        if not port.isdigit():
            return jsonify({
                "ok": False,
                "status": 400,
                "message": "Stored port must be numeric."
            }), 200

        scheme = "http"
        if host.startswith(("http://", "https://")):
            if host.startswith("https://"):
                scheme = "https"
                host = host.removeprefix("https://")
            elif host.startswith("http://"):
                scheme = "http"
                host = host.removeprefix("http://")

        url = f"{scheme}://{host}:{port}/System/Info"

        req = Request(url, method="GET")
        req.add_header("X-Emby-Token", token)
        req.add_header("Accept", "application/json")

        try:
            with urlopen(req, timeout=3.0) as resp:
                status = getattr(resp, "status", 200)
                if 200 <= status < 300:
                    return jsonify({
                        "ok": True,
                        "status": status,
                        "message": "Connection successful."
                    }), 200
                return jsonify({
                    "ok": False,
                    "status": status,
                    "message": f"Jellyfin returned status {status}."
                }), 200
        except HTTPError as he:
            return jsonify({
                "ok": False,
                "status": he.code,
                "message": f"HTTP error from Jellyfin ({he.code}): {he.reason or 'Unknown'}"
            }), 200
        except URLError as ue:
            reason = getattr(ue, "reason", "Unknown")
            return jsonify({
                "ok": False,
                "status": 0,
                "message": f"Network error: {reason}"
            }), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "status": 0,
                "message": f"Unexpected error: {str(exc)}"
            }), 200

    @app.get("/")
    def index() -> Response:
        return render_template("index.html"), 200
    
    @app.get("/users")
    def users() -> Response:
        return render_template("users.html"), 200
    
    @app.get("/libraries")
    def libraries() -> Response:
        return render_template("libraries.html"), 200
    
    @app.get("/settings")
    def settings() -> Response:
        return render_template("settings.html"), 200

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=application.config["PORT"])