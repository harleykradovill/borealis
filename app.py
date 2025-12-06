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
        static_folder="assets",
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