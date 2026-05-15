"""
Provides an application factory that constructs and configures a
Flask instance used to server the Borealis site.
"""

import logging
import atexit
from typing import Optional, Dict
from functools import wraps
from flask import redirect
from api.settings import create_settings_blueprint
from api.analytics import create_analytics_blueprint

logger = logging.getLogger(__name__)

try:
    from flask import (
        Flask,
        Response,
        render_template,
        request,
        send_from_directory,
        make_response,
    )
except ImportError as exc:
    raise RuntimeError(
        "Flask is required to run the local config site. "
        "Install with: pip install Flask"
    ) from exc


def create_app(test_config: Optional[Dict] = None) -> "Flask":
    """
    Create and configure the Borealis Flask application.
    """
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO)
    logger.setLevel(logging.INFO)
    logging.getLogger("werkzeug").setLevel(
        logging.CRITICAL
    )  # Disable annoying flask logs

    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    @app.errorhandler(404)
    def not_found(e):
        return make_response(render_template("404.html"), 404)

    app.config.setdefault("DEBUG", False)
    app.config.setdefault("PORT", 2929)
    app.config.setdefault("DATABASE_URL", "sqlite:///borealis.db")
    app.config.setdefault("ENCRYPTION_KEY_PATH", "secret.key")
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # NOTE: TURN OFF IN PROD

    logging.info("-=-=-=-=-=-=-=-=-=-=-=-=-")
    logging.info("         Borealis        ")
    logging.info("-=-=-=-=-=-=-=-=-=-=-=-=-")

    if test_config:
        app.config.update(test_config)
        if app.config.get("DEBUG", False):
            if "DATABASE_URL" not in test_config:
                app.config["DATABASE_URL"] = "sqlite:///:memory:"
            if "ENCRYPTION_KEY_PATH" not in test_config:
                app.config["ENCRYPTION_KEY_PATH"] = ":memory:"

    from services.settings_store import SettingsService

    svc = SettingsService(
        database_url=app.config["DATABASE_URL"],
        encryption_key_path=app.config["ENCRYPTION_KEY_PATH"],
    )

    from services.repository import Repository

    repo = Repository(database_url=app.config["DATABASE_URL"])

    from services.jellyfin import create_client

    jf = create_client(svc)

    from services.sync_service import SyncService

    sync = SyncService(jellyfin_client=jf, repository=repo, settings_service=svc)

    from services.sync_scheduler import SyncScheduler

    def _has_server_config(settings: Dict) -> bool:
        """
        Check whether required Jellyfin server settings exist.

        :param settings: Settings dictionary
        :returns: True when host, port, and API key are present
        """
        return bool(
            settings.get("jf_host")
            and settings.get("jf_port")
            and settings.get("jf_api_key")
        )

    current_settings = svc.get()
    initial_interval = int(current_settings.get("sync_interval") or 1800)

    sync_scheduler = SyncScheduler(sync_service=sync, interval_seconds=initial_interval)

    app.sync_scheduler = sync_scheduler

    ## Blueprints

    app.register_blueprint(create_settings_blueprint(svc=svc, repo=repo, sync=sync))
    app.register_blueprint(
        create_analytics_blueprint(repo=repo, sync=sync, jf=jf, svc=svc)
    )

    from services.sessions import SessionsService

    sessions_svc = SessionsService(
        jellyfin_client=jf,
        sync_interval=5,
        respository=repo,
    )
    app.sessions_service = sessions_svc

    has_server = _has_server_config(current_settings)
    app.config["HAS_SERVER_CONFIGURED"] = has_server

    if not app.config.get("DEBUG") and has_server:
        sync_scheduler.start()
        sessions_svc.start()

    def cleanup():
        """
        Stop background services and release repo resources on shutdown.

        :returns: None
        :raises Exception: Logs and supresses internal shutdown errors
        """
        sched = getattr(app, "sync_scheduler", None)
        if sched:
            try:
                sched.stop()
            except Exception:
                logger.exception("[ERROR] Failed to stop sync scheduler during cleanup")

        sessions = getattr(app, "sessions_service", None)
        if sessions:
            try:
                sessions.stop()
            except Exception:
                logger.exception(
                    "[ERROR] Failed to stop sessions service during cleanup"
                )

        try:
            repo.engine.dispose()
        except Exception:
            logger.exception(
                "[ERROR] Failed to dispose repository engine during cleanup"
            )

    atexit.register(cleanup)

    def require_server(f):
        """
        Ensure Jellyfin server credentials exist before serving protected routes.

        :param f: Route handler function to wrap
        :returns: Wrapped route handler that redirects to setup when unconfigured
        :raises Exception: Propagates exceptions raised by the wrapped handler
        """

        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not bool(app.config.get("HAS_SERVER_CONFIGURED")):
                return redirect("/setup")
            return f(*args, **kwargs)

        return decorated_function

    @app.get("/assets/<path:filename>")
    def assets(filename: str) -> Response:
        """
        Serve static JavaScript and packaged asset files by request path.

        :param filename: Relative asset path from the /assets route
        :returns: Flask response containing the requested file
        :raises NotFound: Returns by Flask if the asset path does not exist
        """
        if filename.startswith("js/"):
            return send_from_directory("static/js", filename.removeprefix("js/"))
        return send_from_directory("assets", filename)

    @app.get("/")
    @require_server
    def index() -> Response:
        return make_response(render_template("index.html"), 200)

    @app.get("/setup")
    def setup() -> Response:
        return make_response(render_template("setup.html"), 200)

    @app.get("/libraries")
    @require_server
    def libraries() -> Response:
        return make_response(render_template("libraries.html"), 200)

    @app.get("/playbackactivity")
    @require_server
    def playbackactivity() -> Response:
        return make_response(render_template("playbackactivity.html"), 200)

    @app.get("/settings")
    @require_server
    def settings() -> Response:
        return make_response(render_template("settings.html"), 200)

    @app.get("/api/jellyfin/items/<item_id>/images/primary")
    def api_jellyfin_item_primary_image(item_id: str) -> Response:
        """
        Proxy Jellyfin primary item image to the frontend.
        """
        tag = (request.args.get("tag") or "").strip() or None
        result = jf.item_primary_image(item_id=item_id, tag=tag)

        if not result.get("ok"):
            return Response(status=result.get("status", 500))

        return Response(
            result.get("body", b""),
            status=result.get("status", 200),
            mimetype=result.get("content_type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=300"},
        )

    logging.info("\033[92mStartup Complete. Running sync tasks")
    logging.info("Access Borealis at http://localhost:2929/\033[0m")

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=application.config["PORT"])
