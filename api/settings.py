from datetime import datetime
import json
import logging
import threading
import time
import os

from flask import Blueprint, Response, current_app, jsonify, request, make_response

HTTP_PREFIX = "http://"
HTTPS_PREFIX = "https://"


def create_settings_blueprint(*, svc, repo, sync):
    """
    Create the settings API blueprints with routes for configuration and sync management.

    :param svc: SettingsService instance
    :param repo: Repository database for users, libraries, items, activity logs
    :param sync: SyncService coordinating metadata syncs with Jellyfin
    :returns: Configured Flask blueprint
    """
    bp = Blueprint("settings_api", __name__, url_prefix="/api")

    def _build_sync_progress_payload() -> dict:
        """
        Build a normalized sync-progress payload from latest sync log.

        :returns: Dictionary containing sync state with ok, syncing, phase, sync_id, processed_events,
        total_events, message
        """
        log = repo.get_latest_sync_log()

        if not log:
            return {
                "ok": True,
                "syncing": False,
                "phase": "idle",
                "sync_id": None,
                "processed_events": 0,
                "total_events": 0,
                "message": "",
            }

        result = (log.get("result") or "").upper()
        sync_id = log.get("id")

        log_data = {}
        raw_log = log.get("log_json")
        if raw_log:
            try:
                log_data = json.loads(raw_log)
            except Exception:
                log_data = {}

        step = int(log_data.get("step") or 0)
        step_total = int(log_data.get("step_total") or 0)

        processed = step if step > 0 else int(log_data.get("items_synced") or 0)
        total = step_total if step_total > 0 else int(log_data.get("total_events") or 0)

        phase_from_log = str(log_data.get("phase") or "").strip().lower()
        message_from_log = str(log_data.get("message") or "").strip()

        if result == "RUNNING":
            phase = (
                phase_from_log
                if phase_from_log in {"starting", "running"}
                else "running"
            )
            return {
                "ok": True,
                "syncing": True,
                "phase": phase,
                "sync_id": sync_id,
                "processed_events": processed,
                "total_events": total,
                "message": message_from_log or "Sync in progress",
            }

        default_phase = "complete" if result == "SUCCESS" else "failed"
        phase = (
            phase_from_log
            if phase_from_log in {"complete", "failed"}
            else default_phase
        )
        return {
            "ok": True,
            "syncing": False,
            "phase": phase,
            "sync_id": sync_id,
            "processed_events": processed,
            "total_events": total,
            "message": message_from_log
            or ("Sync complete" if phase == "complete" else "Sync failed"),
        }

    @bp.post("/test-connection-with-credentials")
    def test_connection_with_credentials() -> Response:
        """
        Test Jellyfin connectivity with provided credentials.

        :returns: JSON response with connection result (ok, status code, server_name, server_version), or error details
        """
        from urllib.request import Request, urlopen
        from urllib.error import URLError, HTTPError

        payload = request.get_json(silent=True) or {}
        host = (payload.get("jf_host") or "").strip()
        port = (payload.get("jf_port") or "").strip()
        token = (payload.get("jf_api_key") or "").strip()

        if not host or not port or not token:
            return make_response(
                jsonify(
                    {
                        "ok": False,
                        "status": 400,
                        "message": ("Missing host, port, or API key."),
                    }
                ),
                200,
            )

        if not port.isdigit():
            return make_response(
                jsonify(
                    {"ok": False, "status": 400, "message": "Port must be numeric."}
                ),
                200,
            )

        # Parse host to handle http:// or https:// prefixes
        scheme = "http"
        if host.startswith((HTTP_PREFIX, HTTPS_PREFIX)):
            if host.startswith(HTTPS_PREFIX):
                scheme = "https"
                host = host.removeprefix(HTTPS_PREFIX)
            elif host.startswith(HTTP_PREFIX):
                scheme = "http"
                host = host.removeprefix(HTTP_PREFIX)

        url = f"{scheme}://{host}:{port}/System/Info"

        req = Request(url, method="GET")
        req.add_header("Authorization", f'MediaBrowser Token="{token}"')
        req.add_header("Accept", "application/json")

        try:
            with urlopen(req, timeout=3.0) as resp:
                status = getattr(resp, "status", 200)
                if 200 <= status < 300:
                    response_data = json.loads(resp.read().decode("utf-8"))
                    server_name = response_data.get("ServerName", "")
                    server_version = response_data.get("Version", "")
                    return make_response(
                        jsonify(
                            {
                                "ok": True,
                                "status": status,
                                "message": "Connection successful.",
                                "server_name": server_name,
                                "server_version": server_version,
                            }
                        ),
                        200,
                    )
                return make_response(
                    jsonify(
                        {
                            "ok": False,
                            "status": status,
                            "message": (f"Jellyfin returned status {status}."),
                        }
                    ),
                    200,
                )
        except HTTPError as he:
            return make_response(
                jsonify(
                    {
                        "ok": False,
                        "status": he.code,
                        "message": (
                            f"HTTP error from Jellyfin ({he.code}): "
                            f"{he.reason or 'Unknown'}"
                        ),
                    }
                ),
                200,
            )
        except URLError as ue:
            reason = getattr(ue, "reason", "Unknown")
            return make_response(
                jsonify(
                    {"ok": False, "status": 0, "message": f"Network error: {reason}"}
                ),
                200,
            )
        except Exception:
            return make_response(
                jsonify({"ok": False, "status": 0, "message": "Unexpected error"}),
                200,
            )

    @bp.get("/settings")
    def get_settings() -> Response:
        """
        Retrieve current Jellyfin settings and app preferences.

        :returns: JSON response containing all settings with masked sensistive data
        """
        data = svc.get()

        def _mask_key(k):
            """
            Masks a key by replacing all but the first four characters with asterisks.

            :param k: The key to mask
            :returns: The masked key
            """
            if not k:
                return None
            try:
                if len(k) <= 4:
                    return "*" * len(k)
                return f"{k[:4]}{'*' * (len(k) - 4)}"
            except Exception:
                return None

        data["jf_api_key"] = _mask_key(data.get("jf_api_key"))
        return make_response(jsonify(data), 200)

    @bp.put("/settings")
    def update_settings() -> Response:
        """
        Update application settings with provided values.

        :returns: JSON response containing updated settings
        """
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
        current_app.config["HAS_SERVER_CONFIGURED"] = bool(has_server)

        try:
            new_interval = updated.get("sync_interval")
            sched = getattr(current_app, "sync_scheduler", None)
            if sched and new_interval:
                if hasattr(sched, "set_interval"):
                    sched.set_interval(int(new_interval))
                elif hasattr(sched, "interval_seconds"):
                    sched.interval_seconds = int(new_interval)
        except Exception:
            logging.exception("[ERROR] Failed to apply sync_interval to scheduler")

        sync_enabled = updated.get("sync_enabled")

        sched = getattr(current_app, "sync_scheduler", None)
        if sched and sync_enabled is not None:
            if sync_enabled:
                if not sched._thread or not sched._thread.is_alive():
                    sched.start()
            else:
                sched.stop()

        if not had_server and has_server:
            ts = int(time.time())
            svc.set_last_activity_log_sync(ts)

            def run_initial_sync():
                """
                Run the initial sync process.

                :returns: None
                """
                try:
                    sync.sync_initial()
                except Exception as exc:
                    logging.exception(
                        "[ERROR] Initial sync failed: %s", exc, exc_info=True
                    )

            sync_thread = threading.Thread(target=run_initial_sync, daemon=True)
            sync_thread.start()

            sessions_svc = getattr(current_app, "sessions_service", None)
            if sessions_svc and not current_app.config.get("DEBUG"):
                sessions_svc.start()

        return make_response(jsonify(updated), 200)

    @bp.get("/settings/sync-status")
    def get_sync_status() -> Response:
        """
        Retrieve current sync scheduler status including next run and interval.

        :returns: JSON response with syncing flag, next sync timestamp, and interval in seconds
        """
        sched = getattr(current_app, "sync_scheduler", None)
        sched_status = (
            sched.get_status() if sched and hasattr(sched, "get_status") else {}
        )

        progress = _build_sync_progress_payload()
        syncing = bool(progress.get("syncing")) or bool(sched_status.get("is_running"))

        return make_response(
            jsonify(
                {
                    "ok": True,
                    "syncing": syncing,
                    "next_scheduled_sync_at": sched_status.get("next_run_at"),
                    "interval_seconds": sched_status.get("interval_seconds"),
                }
            ),
            200,
        )

    @bp.get("/analytics/server/sync-progress")
    def api_analytics_server_sync_progress() -> Response:
        """
        Get the current progress of the active or most recent sync log.

        :returns: JSON response with sync state payload, or error details with HTTP 500
        """
        try:
            return make_response(jsonify(_build_sync_progress_payload()), 200)
        except Exception:
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch sync progress"}),
                500,
            )

    @bp.post("/sync/periodic")
    def api_sync_periodic() -> Response:
        """
        Trigger the same sync path used by interval scheduling and reset timer.

        :returns: None
        """
        sched = getattr(current_app, "sync_scheduler", None)
        if sched and hasattr(sched, "trigger_periodic_now"):
            sched.trigger_periodic_now()
            return make_response(
                jsonify({"ok": True, "message": "Periodic sync started; timer reset."}),
                200,
            )

        import threading

        def run_sync():
            """
            Run a manual sync process.

            :returns: None
            """
            try:
                sync.sync_periodic()
            except Exception:
                logging.exception("[ERROR] Manual periodic sync failed")

        threading.Thread(target=run_sync, daemon=True).start()
        return make_response(
            jsonify({"ok": True, "message": "Periodic sync started."}), 200
        )

    @bp.get("/database/info")
    def get_database_info() -> Response:
        """
        Retrieve Borealis database information.

        :returns: JSON response with database version, size in bytes, creation time, and last modified time
        """

        db_url = current_app.config.get("DATABASE_URL", "sqlite:///borealis.db")

        if db_url.startswith("sqlite:///"):
            db_path = db_url.removeprefix("sqlite:///")
        elif db_url.startswith("sqlite://"):
            db_path = db_url.removeprefix("sqlite://")
        else:
            db_path = db_url

        try:
            if not os.path.exists(db_path):
                return make_response(
                    jsonify(
                        {
                            "ok": False,
                            "message": "Database file not found.",
                        }
                    ),
                    404,
                )

            stat = os.stat(db_path)

            size_bytes = stat.st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024**2:
                size_str = f"{size_bytes / 1024:.2f} KB"
            elif size_bytes < 1024**3:
                size_str = f"{size_bytes / (1024 ** 2):.2f} MB"
            else:
                size_str = f"{size_bytes / (1024 ** 3):.2f} GB"

            created_at = datetime.fromtimestamp(stat.st_ctime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            modified_at = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            alembic_version = None
            # try:
            #    with repo._session() as session:
            #        result = session.execute(
            #            text("SELECT version_num FROM alembic_version LIMIT 1")
            #        )
            #        row = result.fetchone()
            #        alembic_version = row[0] if row else None
            # except Exception as e:
            #    logging.warning(f"[WARN] Failed to get alembic version: {e}")
            #    alembic_version = "Error getting database version."

            return make_response(
                jsonify(
                    {
                        "ok": True,
                        "alembic_version": alembic_version,
                        "size": size_str,
                        "size_bytes": size_bytes,
                        "created_at": created_at,
                        "modified_at": modified_at,
                    }
                ),
                200,
            )

        except Exception:
            logging.exception("[ERROR] Failed to retrieve database info")
            return make_response(
                jsonify(
                    {
                        "ok": False,
                        "message": "Failed to retrieve database info",
                    }
                ),
                500,
            )

    return bp
