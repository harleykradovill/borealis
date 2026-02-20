"""
Provides an application factory that constructs and configures a
Flask instance used to server the Borealis site.
"""

import json
import logging
from typing import Optional, Dict
import time
from functools import wraps
from flask import redirect

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
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.CRITICAL) # Disable annoying flask logs


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
    app.config['TEMPLATES_AUTO_RELOAD'] = True #TODO: TURN OFF IN PROD

    logging.info("-=-=-=-=-=-=-=-=-=-=-=-=-")
    logging.info("         Borealis        ")
    logging.info("-=-=-=-=-=-=-=-=-=-=-=-=-")
    logging.info("Starting Up")

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
        repository=repo,
        settings_service=svc
    )

    from services.sync_scheduler import SyncScheduler

    current_settings = svc.get()
    initial_interval = int(current_settings.get("sync_interval") or 1800)

    sync_scheduler = SyncScheduler(
        sync_service=sync,
        interval_seconds=initial_interval
    )

    app.sync_scheduler = sync_scheduler

    from services.sessions import SessionsService

    sessions_svc = SessionsService(
        jellyfin_client=jf,
        sync_interval=5
    )
    app.sessions_service = sessions_svc
    
    has_server = bool(
        current_settings.get("jf_host")
        and current_settings.get("jf_port")
        and current_settings.get("jf_api_key")
    )

    if not app.config.get("DEBUG") and has_server:
        sync_scheduler.start()
        sessions_svc.start()

    import atexit

    def cleanup():
        """
        Cleanup function called when app shuts down.
        """
        try:
            sched = getattr(app, "sync_scheduler", None)
            if sched:
                sched.stop()
        except Exception:
            pass
        try:
            sessions = getattr(app, "sessions_service", None)
            if sessions:
                sessions.stop()
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

    def require_server(f):
        """
        Decorator that redirects to setup if no server is configured.
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            settings = svc.get()
            has_server = (
                settings.get("jf_host")
                and settings.get("jf_port")
                and settings.get("jf_api_key")
            )
            if not has_server:
                return redirect("/setup")
            return f(*args, **kwargs)
        return decorated_function

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
        data = svc.get()

        def _mask_key(k):
            if not k:
                return None
            try:
                if len(k) <= 8:
                    return "*" * max(4, len(k))
                return f"{k[:4]}…{k[-4:]}"
            except Exception:
                return None

        data["jf_api_key"] = _mask_key(data.get("jf_api_key"))
        return jsonify(data), 200

    @app.put("/api/settings")
    def update_settings() -> Response:
        payload = request.get_json(silent=True) or {}

        current_settings = svc.get()
        had_server = (
            current_settings.get("jf_host")
            and current_settings.get("jf_port")
            and current_settings.get("jf_api_key")
        )

        updated = svc.update(payload)

        has_server = (
            updated.get("jf_host")
            and updated.get("jf_port")
            and updated.get("jf_api_key")
        )

        try:
            new_interval = updated.get("sync_interval")
            sched = getattr(app, "sync_scheduler", None)
            if sched and new_interval:
                if hasattr(sched, "set_interval"):
                    sched.set_interval(int(new_interval))
                elif hasattr(sched, "interval_seconds"):
                    sched.interval_seconds = int(new_interval)
        except Exception:
            logging.exception("[ERROR] Failed to apply sync_interval to scheduler")

        if not had_server and has_server:
            ts = int(time.time())
            svc.set_last_activity_log_sync(ts)

            import threading

            def run_initial_sync():
                try:
                    sync.sync_initial()
                except Exception as exc:
                    logging.error(
                        "[ERROR] Initial sync failed: %s",
                        exc,
                        exc_info=True
                    )

            sync_thread = threading.Thread(
                target=run_initial_sync,
                daemon=True
            )
            sync_thread.start()

            sessions_svc = getattr(app, "sessions_service", None)
            if sessions_svc and not app.config.get("DEBUG"):
                sessions_svc.start()

        return jsonify(updated), 200

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

    @app.post("/api/test-connection-with-credentials")
    def test_connection_with_credentials() -> Response:
        """
        Test Jellyfin connectivity with provided credentials.
        """
        from urllib.request import Request, urlopen
        from urllib.error import URLError, HTTPError

        payload = request.get_json(silent=True) or {}
        host = (payload.get("jf_host") or "").strip()
        port = (payload.get("jf_port") or "").strip()
        token = (payload.get("jf_api_key") or "").strip()

        if not host or not port or not token:
            return jsonify({
                "ok": False,
                "status": 400,
                "message": (
                    "Missing host, port, or API key."
                )
            }), 200

        if not port.isdigit():
            return jsonify({
                "ok": False,
                "status": 400,
                "message": "Port must be numeric."
            }), 200

        # Parse host to handle http:// or https:// prefixes
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
                    response_data = json.loads(resp.read().decode('utf-8'))
                    server_name = response_data.get("ServerName", "")
                    server_version = response_data.get("Version", "")
                    return jsonify({
                        "ok": True,
                        "status": status,
                        "message": "Connection successful.",
                        "server_name": server_name,
                        "server_version": server_version
                    }), 200
                return jsonify({
                    "ok": False,
                    "status": status,
                    "message": (
                        f"Jellyfin returned status {status}."
                    )
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
    @require_server
    def index() -> Response:
        return render_template("index.html"), 200

    @app.get("/setup")
    def setup() -> Response:
        return render_template("setup.html"), 200

    @app.get("/users")
    @require_server
    def users() -> Response:
        return render_template("users.html"), 200

    @app.get("/libraries")
    @require_server
    def libraries() -> Response:
        return render_template("libraries.html"), 200

    @app.get("/activitylog")
    @require_server
    def activitylog() -> Response:
        return render_template("activitylog.html"), 200

    @app.get("/settings")
    @require_server
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
    @app.post("/api/jellyfin/libraries")
    def api_jf_libraries() -> Response:
        """
        Fetches libraries with item counts and upserts to repository.
        Accepts credentials in POST body for setup flow.
        """
        payload = request.get_json(silent=True) or {}
        host = (payload.get("jf_host") or "").strip()
        port = (payload.get("jf_port") or "").strip()
        token = (payload.get("jf_api_key") or "").strip()

        use_temp_client = bool(host and port and token)

        if use_temp_client:
            from services.jellyfin import JellyfinClient

            class TempSettings:
                def get(self):
                    return {
                        "jf_host": host,
                        "jf_port": port,
                        "jf_api_key": token,
                    }

            temp_jf = JellyfinClient(TempSettings())
            result = temp_jf.libraries()
        else:
            result = jf.libraries()

        data = result.get("data")
        if result and result.get("ok"):
            if isinstance(data, dict) and isinstance(
                data.get("Items"), list
            ):
                flat = data["Items"]
            elif isinstance(data, list):
                flat = data
            else:
                flat = []

            def _is_media_library(lib: dict) -> bool:
                t = (lib.get("CollectionType") or lib.get("Type") or "")
                t_norm = str(t).strip().lower()
                if not t_norm:
                    return False
                return any(k in t_norm for k in ("movies", "tvshows"))

            filtered = [l for l in flat if _is_media_library(l)]
            result["data"] = filtered

            if not use_temp_client:
                try:
                    import concurrent.futures

                    id_map = [
                        (idx, lib.get("Id"))
                        for idx, lib in enumerate(flat)
                        if lib.get("Id")
                    ]

                    if id_map:
                        max_workers = min(8, len(id_map))
                        with concurrent.futures.ThreadPoolExecutor(
                            max_workers=max_workers
                        ) as ex:
                            future_to_idx = {
                                ex.submit(jf.library_stats, jf_id): idx
                                for idx, jf_id in id_map
                            }

                            for fut in concurrent.futures.as_completed(
                                future_to_idx, timeout=None
                            ):
                                idx = future_to_idx.get(fut)
                                try:
                                    stats = fut.result(timeout=5)
                                    flat[idx]["ItemCount"] = (
                                        stats.get("item_count", 0)
                                        if isinstance(
                                            stats, dict
                                        ) and stats.get("ok")
                                        else 0
                                    )
                                except Exception:
                                    flat[idx]["ItemCount"] = 0
                except Exception:
                    for lib in flat:
                        lib_id = lib.get("Id")
                        if lib_id:
                            stats = jf.library_stats(lib_id)
                            lib["ItemCount"] = (
                                stats.get("item_count", 0)
                                if stats.get("ok")
                                else 0
                            )

                try:
                    from services.mappers import map_libraries

                    mapped = map_libraries(filtered)
                    repo.upsert_libraries(mapped)
                except Exception:
                    pass

        return jsonify(result), 200

    @app.post("/api/sync/libraries-only")
    def api_sync_libraries_only() -> Response:
        """
        Sync only library metadata without fetching item counts.
        Used during initial setup for faster library discovery.
        """
        try:
            result = jf.libraries()

            data = result.get("data")
            if not result.get("ok"):
                return jsonify({
                    "ok": False,
                    "message": "Failed to fetch libraries from Jellyfin"
                }), 200

            if isinstance(data, dict) and isinstance(
                data.get("Items"), list
            ):
                flat = data["Items"]
            elif isinstance(data, list):
                flat = data
            else:
                flat = []

            def _is_media_library(lib: dict) -> bool:
                t = (lib.get("CollectionType") or lib.get("Type") or "")
                t_norm = str(t).strip().lower()
                if not t_norm:
                    return False
                return any(k in t_norm for k in ("movies", "tvshows"))

            filtered = [l for l in flat if _is_media_library(l)]

            try:
                from services.mappers import map_libraries
                mapped = map_libraries(filtered)
                repo.upsert_libraries(mapped)
            except Exception:
                pass

            return jsonify({
                "ok": True,
                "data": filtered
            }), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Error syncing libraries: {str(exc)}"
            }), 500

    @app.get("/api/analytics/users")
    def api_analytics_users() -> Response:
        """
        Retrieve all users from repository.
        """
        return jsonify({"ok": True, "data": repo.list_users()}), 200
    
    @app.get("/api/analytics/stats/users")
    def api_analytics_stats_users() -> Response:
        """
        Retrieve all users with their play statistics.
        """
        try:
            users = repo.get_users_with_stats(include_archived=False)
            return jsonify({
                "ok": True,
                "data": users
            }), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch users: {str(exc)}"
            }), 500

    @app.get("/api/analytics/libraries")
    def api_analytics_libraries() -> Response:
        """
        Retrieve all libraries from repository.
        """
        settings = svc.get()

        if not (
            settings.get("jf_host")
            and settings.get("jf_port")
            and settings.get("jf_api_key")
        ):
            return jsonify({
                "ok": True,
                "data": []
            }), 200

        try:
            libraries = repo.list_libraries(include_archived=False)

            for lib in libraries:
                jf_id = lib.get("jellyfin_id")
                if not jf_id:
                    lib["item_count"] = 0
                    continue

                t = (lib.get("type") or "").strip().lower()
                if "tvshows" in t:
                    items_res = jf.library_items(jf_id)
                    if items_res.get("ok"):
                        items = items_res.get("data", {}).get("Items", []) or []
                        series = sum(1 for it in items if (it.get("Type") or "").lower() == "series")
                        episodes = sum(1 for it in items if (it.get("Type") or "").lower() == "episode")
                        lib["series_count"] = series
                        lib["episode_count"] = episodes
                        lib["item_count"] = series + episodes
                    else:
                        lib["series_count"] = 0
                        lib["episode_count"] = 0
                        lib["item_count"] = 0
                else:
                    stats = jf.library_stats(jf_id)
                    lib["item_count"] = stats.get("item_count", 0) if stats.get("ok") else 0

            return jsonify({
                "ok": True,
                "data": libraries
            }), 200

        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch libraries: {str(exc)}"
            }), 500

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
    
    @app.get("/api/analytics/items/added-last-30-days")
    def api_analytics_items_added_last_30_days() -> Response:
        """
        Return items added per library for the last 30 days.
        """
        try:
            from datetime import datetime, timedelta

            days = 30
            now = int(time.time())
            cutoff = now - days * 24 * 60 * 60

            dates = []
            today = datetime.utcnow().date()
            for i in range(days - 1, -1, -1):
                dates.append((today - timedelta(days=i)).isoformat())

            libraries = repo.list_libraries(include_archived=False)
            id_map = {lib["id"]: lib for lib in libraries}

            counts_by_lib = {}
            for lib in libraries:
                counts_by_lib[lib["jellyfin_id"]] = Object = {d: 0 for d in dates}

            from services.data_models import Item
            with repo._session() as session:
                rows = (
                    session.query(Item.jellyfin_id, Item.library_id, Item.date_created)
                    .filter(Item.date_created != None)
                    .filter(Item.date_created >= cutoff)
                    .all()
                )

                for jellyfin_item_id, library_id, date_created in rows:
                    try:
                        ts = int(date_created)
                    except Exception:
                        continue
                    date_str = datetime.utcfromtimestamp(ts).date().isoformat()
                    lib = id_map.get(library_id)
                    if not lib:
                        continue
                    jf_lib_id = lib["jellyfin_id"]
                    if date_str in counts_by_lib.get(jf_lib_id, {}):
                        counts_by_lib[jf_lib_id][date_str] += 1

            payload = {
                "dates": dates,
                "libraries": [
                    {
                        "jellyfin_id": jf,
                        "name": next((l["name"] for l in libraries if l["jellyfin_id"] == jf), None),
                        "counts": [counts_by_lib[jf].get(d, 0) for d in dates],
                    }
                    for jf in counts_by_lib.keys()
                ],
            }

            return jsonify({"ok": True, "data": payload}), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to build items-added data: {str(exc)}"
            }), 500

    @app.post("/api/sync")
    def api_sync() -> Response:
        """
        Trigger a manual sync operation.
        """
        payload = request.get_json(silent=True) or {}
        sync_type = payload.get("type", "full")
        auto_track = bool(payload.get("auto_track", False))

        result = sync.sync_metadata(auto_track=auto_track)

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

    @app.get("/api/analytics/server/sync-progress")
    def api_analytics_server_sync_progress() -> Response:
        """
        Get the current progress of initial activity log sync.
        """
        try:
            task = repo.get_latest_sync_task()

            if not task or task["result"] != "RUNNING":
                return jsonify({
                    "ok": True,
                    "syncing": False,
                    "processed_events": 0,
                    "total_events": 0
                }), 200

            import json
            log_data = {}
            if task.get("log_json"):
                try:
                    log_data = json.loads(task["log_json"])
                except Exception:
                    pass

            processed = log_data.get("items_synced", 0)
            total = log_data.get("total_events", 1)

            return jsonify({
                "ok": True,
                "syncing": True,
                "processed_events": processed,
                "total_events": total
            }), 200

        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch sync progress: {str(exc)}"
            }), 500

    @app.get("/api/analytics/task-logs")
    def api_analytics_task_logs() -> Response:
        """
        Retrieve recent task log entries.
        """
        try:
            limit = request.args.get("limit", 50, type=int)
            if limit < 1 or limit > 500:
                limit = 50

            logs = repo.get_task_logs(limit=limit)
            return jsonify({"ok": True, "data": logs}), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch task logs: {str(exc)}"
            }), 500

    @app.get("/api/analytics/activitylog")
    def api_analytics_activity_log() -> Response:
        """
        Retrieve paginated activity log entries.
        """
        try:
            page = request.args.get("page", 1, type=int) or 1
            per_page = request.args.get("per_page", 25, type=int) or 25

            page = max(1, int(page))
            per_page = max(1, min(1000, int(per_page)))

            res = repo.get_activity_logs(page=page, per_page=per_page)
            return jsonify({"ok": True, "data": res}), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch activity logs: {str(exc)}"
            }), 500
        
    @app.get("/api/analytics/sessions")
    def api_analytics_sessions() -> Response:
        """
        Retrieve active sessions from the sessions service.
        """
        sessions_svc = getattr(app, "sessions_service", None)
        if not sessions_svc:
            return jsonify({
                "ok": False,
                "message": "Sessions service not available"
            }), 500

        sessions = sessions_svc.get_sessions()
        return jsonify({
            "ok": True,
            "data": sessions
        }), 200

    logging.info("\033[92mStartup Complete. Running sync tasks")
    logging.info("Access Borealis at http://localhost:2929/\033[0m")

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host="127.0.0.1",
        port=application.config["PORT"]
    )