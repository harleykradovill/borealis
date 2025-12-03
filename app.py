from typing import Optional, Dict

try:
    from flask import Flask, Response, render_template
except Exception as exc:  # explicit runtime import error handling
    raise RuntimeError(
        "Flask is required to run the local config site. "
        "Install with: pip install Flask"
    ) from exc


def create_app(test_config: Optional[Dict] = None) -> "Flask":
    app = Flask(
        __name__,
        static_folder="assets",
        template_folder="templates",
    )

    if test_config:
        app.config.update(test_config)
    else:
        app.config.setdefault("DEBUG", False)
        app.config.setdefault("PORT", 2929)

    @app.get("/")
    def index() -> Response:
        return render_template("index.html"), 200

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=application.config["PORT"])