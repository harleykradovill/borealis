import json
import logging
import time
import threading

from flask import Blueprint, Response, jsonify, request, current_app, stream_with_context

def create_analytics_blueprint(*, svc, repo, sync):
    bp = Blueprint("analytics_api", __name__, url_prefix="/api")

    def _build_sync_progress_payload() -> dict:
        """
        Build a normalized sync-progress payload
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

    @bp.get("/analytics/stats/users")
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
        
    @bp.get("/analytics/stats/dashboard")
    def api_analytics_stats_dashboard() -> Response:
        """
        Retrieve watch statistics for dashboard.
        """
        try:
            section_keys = [
                "top_users_by_plays",
                "top_items_by_plays",
                "top_libraries_by_plays",
                "top_users_by_watch_time",
                "most_active_weekdays",
                "recently_watched",
            ]

            rows_by_key = repo.get_dashboard_stats_map(
                section_keys=section_keys
            )

            sections = {}
            latest_updated_at = 0

            for key in section_keys:
                row = rows_by_key.get(key)
                if row:
                    sections[key] = row.get("payload", [])
                    latest_updated_at = max(
                        latest_updated_at,
                        int(row.get("updated_at") or 0),
                    )
                else:
                    sections[key] = []

            return jsonify({
                "ok": True,
                "data": {
                    "limit": 5,
                    "generated_at": latest_updated_at or None,
                    "sections": sections,
                },
            }), 200

        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": (
                    f"Failed to fetch dashboard stats: {str(exc)}"
                ),
            }), 500
        
    @bp.get("/analytics/items/added-last-30-days")
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
                counts_by_lib[lib["jellyfin_id"]] = {d: 0 for d in dates}

            from services.data_models import Item
            with repo._session() as session:
                rows = (
                    session.query(Item.library_id, Item.date_created)
                    .filter(Item.date_created.isnot(None))
                    .filter(Item.date_created >= cutoff)
                    .all()
                )

                for library_id, date_created in rows:
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
        
    @bp.get("/analytics/stats/libraries")
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
        
    @bp.get("/analytics/server/sync-progress/stream")
    def api_analytics_server_sync_progress_stream() -> Response:
        """
        Stream sync-progress updates
        """
        def event_stream():
            last_payload = None
            heartbeat_every = 15
            last_heartbeat = time.time()

            while True:
                payload = _build_sync_progress_payload()
                payload_json = json.dumps(payload, separators=(",", ":"))

                if payload_json != last_payload:
                    yield f"event: sync_progress\ndata: {payload_json}\n\n"
                    last_payload = payload_json

                now = time.time()
                if now - last_heartbeat >= heartbeat_every:
                    yield "event: heartbeat\ndata: {}\n\n" # Keep browser connections alive
                    last_heartbeat = now

                time.sleep(1)

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return Response(stream_with_context(event_stream()), headers=headers)
    
    @bp.get("/analytics/task-logs")
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

    @bp.get("/analytics/activitylog")
    def api_analytics_activity_log() -> Response:
        """
        Retrieve paginated activity log entries.
        """
        try:
            page = request.args.get("page", 1, type=int) or 1
            per_page = request.args.get("per_page", 25, type=int) or 25
            user_ids_raw = request.args.get("user_ids", "", type=str) or ""

            include_users_raw = (
                request.args.get("include_users", "true", type=str) or "true"
            )
            include_total_raw = (
                request.args.get("include_total", "true", type=str) or "true"
            )

            page = max(1, int(page))
            per_page = max(1, min(1000, int(per_page)))

            user_ids = [
                user_id.strip()
                for user_id in user_ids_raw.split(",")
                if user_id and user_id.strip()
            ]

            disabled_values = {"0", "false", "no", "off"}
            include_users = (
                include_users_raw.strip().lower() not in disabled_values
            )
            include_total = (
                include_total_raw.strip().lower() not in disabled_values
            )

            res = repo.get_activity_logs(
                page=page,
                per_page=per_page,
                user_ids=user_ids or None,
                include_users=include_users,
                include_total=include_total,
            )
            return jsonify({"ok": True, "data": res}), 200
        except Exception as exc:
            return jsonify({
                "ok": False,
                "message": f"Failed to fetch activity logs: {str(exc)}"
            }), 500
        
    @bp.get("/analytics/sessions")
    def api_analytics_sessions() -> Response:
        """
        Retrieve active sessions from the sessions service.
        """
        sessions_svc = getattr(current_app, "sessions_service", None)
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
    
    return bp