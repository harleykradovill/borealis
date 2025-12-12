"""
Provides an application factory that constructs and configures a
Flask instance used to server the Borealis site.
"""

from typing import Optional, Dict

try:
    from flask import Flask, Response, render_template, jsonify, request, send_from_directory
except Exception as exc:
    raise RuntimeError(
        "Flask is required to run the local config site. "
        "Install with: pip install Flask"
    ) from exc


def create_app(test_config: Optional[Dict] = None) -> "Flask":
    """
    Create and configure the Borealis Flask application.
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
    app.config.setdefault("DATA_DATABASE_URL", "sqlite:///borealis_data.db")

    if test_config:
        app.config.update(test_config)
        if app.config.get("DEBUG", False):
            if "DATABASE_URL" not in test_config:
                app.config["DATABASE_URL"] = "sqlite:///:memory:"
            if "ENCRYPTION_KEY_PATH" not in test_config:
                app.config["ENCRYPTION_KEY_PATH"] = ":memory:"
            if "DATA_DATABASE_URL" not in test_config:
                app.config["DATA_DATABASE_URL"] = "sqlite:///:memory:"

    from services.settings_store import SettingsService
    svc = SettingsService(
        database_url=app.config["DATABASE_URL"],
        encryption_key_path=app.config["ENCRYPTION_KEY_PATH"],
    )

    from services.repository import Repository
    repo = Repository(
        database_url=app.config["DATA_DATABASE_URL"]
    )

    from services.jellyfin import create_client
    jf = create_client(svc)

    from services.sync_service import SyncService
    sync = SyncService(
        jellyfin_client=jf,
        repository=repo
    )

    from services.sync_scheduler import SyncScheduler

    sync_scheduler = SyncScheduler(
        sync_service=sync,
        interval_seconds=86400
    )

    if not app.config.get("DEBUG"):
        sync_scheduler.start()

    import atexit
    
    def cleanup():
        """
        Cleanup function called when app shuts down.
        """
        try:
            sync_scheduler.stop()
        except Exception:
            pass
        try:
            svc.engine.dispose()
        except Exception:
            pass
        try:
            repo.engine.dispose()
        except Exception:
            pass
    
    atexit.register(cleanup)

    @app.get("/assets/<path:filename>")
    def assets(filename: str) -> Response:
        if filename.startswith("js/"):
            return send_from_directory(
                "static/js",
                filename.removeprefix("js/")
            )
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
        try:
            repo.engine.dispose()
        except Exception:
            pass

    @app.get("/api/test-connection")
    def test_connection() -> Response:
        """
        Test Jellyfin connectivity using persisted settings.
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
                "message": (
                    f"HTTP error from Jellyfin ({he.code}): "
                    f"{he.reason or 'Unknown'}"
                )
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

    @app.get("/api/jellyfin/system-info")
    def api_jf_system_info() -> Response:
        result = jf.system_info()
        return jsonify(result), 200

    @app.get("/api/jellyfin/users")
    def api_jf_users() -> Response:
        """
        Fetches users and upserts to repository.
        """
        result = jf.users()
        if result and result.get("ok") and isinstance(
            result.get("data"), list
        ):
            try:
                from services.mappers import map_users
                mapped = map_users(result["data"])
                repo.upsert_users(mapped)
            except Exception:
                pass
        return jsonify(result), 200

    @app.get("/api/jellyfin/libraries")
    def api_jf_libraries() -> Response:
        """
        Fetches libraries with item counts and upserts to repository.
        """
        result = jf.libraries()

        data = result.get("data")
        if result and result.get("ok"):
            if isinstance(data, dict) and isinstance(
                data.get("Items"), list
            ):
                flat = data["Items"]
                for lib in flat:
                    lib_id = lib.get("Id")
                    if lib_id:
                        stats = jf.library_stats(lib_id)
                        if stats.get("ok"):
                            lib["ItemCount"] = stats.get("item_count", 0)

                result["data"] = flat
                try:
                    from services.mappers import map_libraries
                    mapped = map_libraries(flat)
                    repo.upsert_libraries(mapped)
                except Exception:
                    pass
            elif isinstance(data, list):
                for lib in data:
                    lib_id = lib.get("Id")
                    if lib_id:
                        stats = jf.library_stats(lib_id)
                        if stats.get("ok"):
                            lib["ItemCount"] = stats.get("item_count", 0)
                try:
                    from services.mappers import map_libraries
                    mapped = map_libraries(data)
                    repo.upsert_libraries(mapped)
                except Exception:
                    pass

        return jsonify(result), 200

    @app.get("/api/analytics/users")
    def api_analytics_users() -> Response:
        """
        Retrieve all users from repository.
        """
        return jsonify({"ok": True, "data": repo.list_users()}), 200

    @app.get("/api/analytics/libraries")
    def api_analytics_libraries() -> Response:
        """
        Retrieve all libraries from repository.
        """
        return jsonify({"ok": True, "data": repo.list_libraries()}), 200

    @app.post("/api/analytics/library/<string:jellyfin_id>/tracked")
    def api_analytics_set_tracked(jellyfin_id: str) -> Response:
        """
        Update the tracked flag for a library.
        """
        payload = request.get_json(silent=True) or {}
        tracked = payload.get("tracked", None)
        if not isinstance(tracked, bool):
            return jsonify({
                "ok": False,
                "status": 400,
                "message": "tracked must be boolean"
            }), 200

        updated = repo.set_library_tracked(jellyfin_id, tracked)
        if not updated:
            return jsonify({
                "ok": False,
                "status": 404,
                "message": "Library not found"
            }), 200

        return jsonify({"ok": True, "data": updated}), 200

    @app.post("/api/sync")
    def api_sync() -> Response:
        """
        Trigger a manual sync operation.
        """
        payload = request.get_json(silent=True) or {}
        sync_type = payload.get("type", "full")

        result = sync.sync_full()

        return jsonify({
            "ok": result.success,
            "data": result.to_dict()
        }), 200
    
    @app.get("/api/analytics/stats/libraries")
    def api_analytics_stats_libraries() -> Response:
        """
        Retrieve all libraries with their play count statistics.
        """
        try:
            stats = repo.get_library_stats(include_archived=False)
            return jsonify({
                "ok": True,
                "data": stats
            }), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch library stats: {str(exc)}"
            }), 500

    @app.get("/api/analytics/stats/items")
    def api_analytics_stats_items() -> Response:
        """
        Retrieve the most played items across all libraries.
        """
        try:
            limit = request.args.get("limit", 10, type=int)
            if limit < 1 or limit > 100:
                limit = 10
            
            items = repo.get_top_items_by_plays(limit=limit)
            return jsonify({
                "ok": True,
                "data": items
            }), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch item stats: {str(exc)}"
            }), 500

    @app.get("/api/analytics/stats/users")
    def api_analytics_stats_users() -> Response:
        """
        Retrieve the most active users by total play count.
        """
        try:
            limit = request.args.get("limit", 10, type=int)
            if limit < 1 or limit > 100:
                limit = 10
            
            users = repo.get_top_users_by_plays(limit=limit)
            return jsonify({
                "ok": True,
                "data": users
            }), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch user stats: {str(exc)}"
            }), 500

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host="127.0.0.1",
        port=application.config["PORT"]
    )