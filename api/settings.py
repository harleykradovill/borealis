import json
import logging
import threading
import time

from flask import Blueprint, Response, current_app, jsonify, request

"""
Create the settings API blueprints with routes for configuration and sync management.

:param svc: SettingsService instance
:param repo: Repository database for users, libraries, items, activity logs
:param sync: SyncService coordinating metadata syncs with Jellyfin
:returns: Configured Flask blueprint
"""
def create_settings_blueprint(*, svc, repo, sync):
    bp = Blueprint("settings_api", __name__, url_prefix="/api")

    def _build_sync_progress_payload() -> dict:
        """
        Build a normalized sync-progress payload from latest task log.

        :returns: Dictionary containing sync state with ok, syncing, phase, task_id, processed_events,
        total_events, message
        """
        task = repo.get_latest_sync_task()

        if not task:
            return {
                "ok": True,
                "syncing": False,
                "phase": "idle",
                "task_id": None,
                "processed_events": 0,
                "total_events": 0,
                "message": "",
            }

        result = (task.get("result") or "").upper()
        task_id = task.get("id")

        log_data = {}
        raw_log = task.get("log_json")
        if raw_log:
            try:
                log_data = json.loads(raw_log)
            except Exception:
                log_data = {}

        processed = int(log_data.get("items_synced") or 0)
        total = int(log_data.get("total_events") or 0)

        phase_from_log = str(log_data.get("phase") or "").strip().lower()
        message_from_log = str(log_data.get("message") or "").strip()
        
        if result == "RUNNING":
            phase = phase_from_log if phase_from_log in {"starting", "running"} else "running"
            return {
                "ok": True,
                "syncing": True,
                "phase": phase,
                "task_id": task_id,
                "processed_events": processed,
                "total_events": total,
                "message": message_from_log or "Sync in progress",
            }
        
        phase = phase_from_log if phase_from_log in {"complete", "failed"} else (
            "complete" if result == "SUCCESS" else "failed"
        )
        return {
            "ok": True,
            "syncing": False,
            "phase": phase,
            "task_id": task_id,
            "processed_events": processed,
            "total_events": total,
            "message": message_from_log or (
                "Sync complete" if phase == "complete" else "Sync failed"
            ),
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
    
    @bp.get("/settings")
    def get_settings() -> Response:
        """
        Retrieve current Jellyfin settings and app preferences.

        :returns: JSON response containing all settings with masked sensistive data
        """
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
    
    @bp.put("/settings")
    def update_settings() -> Response:
        """
        Update Jellyfin settings and application preferences with provided values.

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

        if not had_server and has_server:
            ts = int(time.time())
            svc.set_last_activity_log_sync(ts)

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

            sessions_svc = getattr(current_app, "sessions_service", None)
            if sessions_svc and not current_app.config.get("DEBUG"):
                sessions_svc.start()

        return jsonify(updated), 200
    
    @bp.get("/settings/sync-status")
    def get_sync_status() -> Response:
        """
        Retrieve current sync scheduler status including next run and interval.

        :returns: JSON response with syncing flag, next sync timestamp, and interval in seconds
        """
        sched = getattr(current_app, "sync_scheduler", None)
        sched_status = (
            sched.get_status()
            if sched and hasattr(sched, "get_status")
            else {}
        )
    
        progress = _build_sync_progress_payload()
        syncing = bool(progress.get("syncing")) or bool(
            sched_status.get("is_running")
        )
    
        return jsonify({
            "ok": True,
            "syncing": syncing,
            "next_scheduled_sync_at": sched_status.get("next_run_at"),
            "interval_seconds": sched_status.get("interval_seconds"),
        }), 200
    
    @bp.get("/analytics/server/sync-progress")
    def api_analytics_server_sync_progress() -> Response:
        """
        Get the current progress of the active or most recent sync task.

        :returns: JSON response with sync state payload, or error details with HTTP 500
        """
        try:
            return jsonify(_build_sync_progress_payload()), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch sync progress: {str(exc)}"
            }), 500
        
    @bp.post("/sync/periodic")
    def api_sync_periodic() -> Response:
        """
        Trigger the same sync path used by interval scheduling and reset timer.
        """
        sched = getattr(current_app, "sync_scheduler", None)
        if sched and hasattr(sched, "trigger_periodic_now"):
            sched.trigger_periodic_now()
            return jsonify({
                "ok": True,
                "message": "Periodic sync started; timer reset."
            }), 200
    
        import threading
    
        def run_sync():
            try:
                sync.sync_periodic()
            except Exception:
                logging.exception("[ERROR] Manual periodic sync failed")
    
        threading.Thread(target=run_sync, daemon=True).start()
        return jsonify({
            "ok": True,
            "message": "Periodic sync started."
        }), 200
        
    return bp