from datetime import datetime, timedelta, timezone
import concurrent.futures
import json
import logging
import time

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    stream_with_context,
    make_response,
    send_from_directory,
)

logger = logging.getLogger(__name__)

_last_sync_state = {"syncing": False}


def create_api_blueprint(*, repo, sync, jf):
    """
    Create the API blueprint and register all analytics routes.

    :param svc: SettingsService instance
    :param repo: Repository database for users, libraries, items, activity logs
    :param sync: SyncService coordinating metadata syncs with Jellyfin
    :returns: Configured Flask blueprint
    """
    bp = Blueprint("analytics_api", __name__, url_prefix="/api")

    def _build_sync_progress_payload() -> dict:
        """
        Build a normalized sync-progress payload from latest sync log.

        :returns: Dictionary containing sync state with ok, syncing, phase, sync_id, processed_events,
        total_events, message, sync_complete
        """
        log = repo.get_latest_sync_log()

        if not log:
            payload = {
                "ok": True,
                "syncing": False,
                "phase": "idle",
                "sync_id": None,
                "processed_events": 0,
                "total_events": 0,
                "message": "",
                "sync_complete": False,
            }
            return payload

        result = (log.get("result") or "").upper()
        sync_id = log.get("id")

        log_data = {}
        raw_log = log.get("log_json")
        if raw_log:
            try:
                log_data = json.loads(raw_log)
            except Exception as e:
                logger.warning(
                    f"[WARN] Failed to parse sync log JSON for sync_id {sync_id}: {str(e)}"
                )
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
            payload = {
                "ok": True,
                "syncing": True,
                "phase": phase,
                "sync_id": sync_id,
                "processed_events": processed,
                "total_events": total,
                "message": message_from_log or "Sync in progress",
                "sync_complete": False,
            }
            _last_sync_state["syncing"] = True
            return payload

        if phase_from_log in {"complete", "failed"}:
            phase = phase_from_log
        else:
            phase = "complete" if result == "SUCCESS" else "failed"

        # Detect sync completion: was syncing, now complete/failed
        sync_complete = _last_sync_state.get("syncing") is True and phase in {
            "complete",
            "failed",
        }
        _last_sync_state["syncing"] = False

        payload = {
            "ok": True,
            "syncing": False,
            "phase": phase,
            "sync_id": sync_id,
            "processed_events": processed,
            "total_events": total,
            "message": message_from_log
            or ("Sync complete" if phase == "complete" else "Sync failed"),
            "sync_complete": sync_complete,
        }
        return payload

    @bp.get("/jellyfin/items/<item_id>/images/primary")
    def api_jellyfin_item_primary_image(item_id: str) -> Response:
        """
        Proxy Jellyfin primary item image to the frontend.

        :param item_id: ID of the Jellyfin item
        :returns: Flask response containing the primary image or an error response
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

    @bp.get("/jellyfin/users/<user_id>/images/primary")
    def api_jellyfin_user_primary_image(user_id: str) -> Response:
        """
        Proxy Jellyfin primary user image to the frontend.

        :param user_id: ID of the Jellyfin user
        :returns: Flask response containing the primary image or an error response
        """
        tag = (request.args.get("tag") or "").strip() or None
        result = jf.user_primary_image(user_id=user_id, tag=tag)

        if not result.get("ok"):
            return send_from_directory("assets", "icons/profile_small.png")

        return Response(
            result.get("body", b""),
            status=result.get("status", 200),
            mimetype=result.get("content_type", "image/jpeg"),
            headers={"Cache-Control": "public, max-age=300"},
        )

    @bp.get("/analytics/stats/dashboard")
    def api_analytics_stats_dashboard() -> Response:
        """
        Retrieve watch statistics for dashboard statistics sections.

        :returns: JSON response with section_key-mapped payloads and HTTP 200, or error details with HTTP 500
        """
        try:
            section_keys = [
                "top_users_by_plays",
                "top_items_by_plays",
                "top_libraries_by_plays",
                "top_users_by_watch_time",
                "most_active_weekdays",
                "recently_watched",
                "resolutions",
                "video_codecs",
                "audio_codecs",
                "most_popular_genres",
                "largest_items",
            ]

            rows_by_key = repo.get_statistics_map(section_keys=section_keys)

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

            return make_response(
                jsonify(
                    {
                        "ok": True,
                        "data": {
                            "limit": 5,
                            "generated_at": latest_updated_at or None,
                            "sections": sections,
                        },
                    }
                ),
                200,
            )

        except Exception:
            logger.exception("[ERROR] Failed to fetch dashboard stats")
            return make_response(
                jsonify(
                    {
                        "ok": False,
                        "message": ("Failed to fetch dashboard stats"),
                    }
                ),
                500,
            )

    @bp.get("/analytics/stats/glance")
    def api_analytics_stats_glance() -> Response:
        """
        Retrieve at-a-glance totals for the index dashboard.

        :returns: JSON response with totals and HTTP 200, or error details with HTTP 500
        """
        try:
            totals = repo.get_glance_totals()

            sessions_svc = getattr(current_app, "sessions_service", None)
            sessions = sessions_svc.get_sessions() if sessions_svc else []
            active_sessions = len(sessions or [])

            return make_response(
                jsonify(
                    {
                        "ok": True,
                        "data": {
                            "active_sessions": active_sessions,
                            **totals,
                        },
                    }
                ),
                200,
            )
        except Exception:
            logger.exception("[ERROR] Failed to fetch glance totals")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch glance totals"}),
                500,
            )

    @bp.get("/analytics/activity-summary")
    def api_analytics_activity_summary() -> Response:
        """
        Return the global start/stop playback counts.

        :returns: JSON response with start and stop counts
        """
        try:
            totals = repo.get_playback_type_totals()
            return make_response(jsonify({"ok": True, "data": totals}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch activity summary")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch activity summary"}),
                500,
            )

    @bp.get("/analytics/items/added-last-30-days")
    def api_analytics_items_added_last_30_days() -> Response:
        """
        Count items added per library for each of the last 30 days.

        :returns: JSON response with date array and per-library counts with HTTP 200, or error details with HTTP 500
        """
        try:
            days = 30
            now = int(time.time())
            cutoff = now - days * 24 * 60 * 60

            dates = []
            today = datetime.now(timezone.utc).date()
            for i in range(days - 1, -1, -1):
                dates.append((today - timedelta(days=i)).isoformat())

            libraries = repo.list_libraries(include_archived=False)
            id_map = {lib["id"]: lib for lib in libraries}

            counts_by_lib = {}
            for lib in libraries:
                counts_by_lib[lib["jellyfin_id"]] = dict.fromkeys(dates, 0)

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
                    date_str = (
                        datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
                    )
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
                        "name": next(
                            (l["name"] for l in libraries if l["jellyfin_id"] == jf),
                            None,
                        ),
                        "counts": [counts_by_lib[jf].get(d, 0) for d in dates],
                    }
                    for jf in counts_by_lib.keys()
                ],
            }

            return make_response(jsonify({"ok": True, "data": payload}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to build items-added data")
            return make_response(
                jsonify({"ok": False, "message": "Failed to build items-added data"}),
                500,
            )

    @bp.get("/analytics/stats/libraries")
    def api_analytics_stats_libraries() -> Response:
        """
        Retrieve all libraries with their play count statistics.

        :returns: JSON response with library records and HTTP 200, or error details with HTTP 500
        """
        try:
            stats = repo.get_library_stats(include_archived=False)
            return make_response(jsonify({"ok": True, "data": stats}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch library stats")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch library stats"}),
                500,
            )

    @bp.get("/analytics/server/sync-progress/stream")
    def api_analytics_server_sync_progress_stream() -> Response:
        """
        Stream sync-progress updates as Server-Sent events to clients.

        :returns: Streaming Response with text/event-stream MIME type
        """

        def event_stream():
            """
            Stream sync-progress updates as Server-Sent events to clients.

            :returns: Streaming response with text/event-stream MIME type
            """
            last_payload = None
            heartbeat_every = 15
            last_heartbeat = time.time()

            while True:
                try:
                    payload = _build_sync_progress_payload()
                    payload_json = json.dumps(payload, separators=(",", ":"))

                    if payload_json != last_payload:
                        yield f"event: sync_progress\ndata: {payload_json}\n\n"
                        last_payload = payload_json

                    now = time.time()
                    if now - last_heartbeat >= heartbeat_every:
                        yield "event: heartbeat\ndata: {}\n\n"
                        last_heartbeat = now

                    time.sleep(1)
                except Exception as e:
                    logger.exception("[ERROR] Exception in sync progress stream")
                    yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                    time.sleep(1)

        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return Response(stream_with_context(event_stream()), headers=headers)

    @bp.get("/analytics/sync-logs")
    def api_analytics_sync_logs() -> Response:
        """
        Retrieve recent sync log entries with pagination and bounded result limit of 1-500.

        :returns: JSON response with the sync log records with HTTP 500, or error details with HTTP 500
        """
        try:
            limit = request.args.get("limit", 50, type=int)
            if limit < 1 or limit > 500:
                limit = 50

            logs = repo.get_sync_logs(limit=limit)
            return make_response(jsonify({"ok": True, "data": logs}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch sync logs")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch sync logs"}), 500
            )

    @bp.get("/analytics/activitylog")
    def api_analytics_activity_log() -> Response:
        """
        Retrieve paginated activity log entries with optional per-user filtering.

        :returns: JSON response with pagnated activity records with HTTP 200, or error details with HTTP 500
        """
        try:
            page = request.args.get("page", 1, type=int) or 1
            per_page = request.args.get("per_page", 25, type=int) or 25
            user_ids_raw = request.args.get("user_ids", "", type=str) or ""

            search = request.args.get("search", "", type=str) or ""

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
            include_users = include_users_raw.strip().lower() not in disabled_values
            include_total = include_total_raw.strip().lower() not in disabled_values

            res = repo.get_activity_logs(
                page=page,
                per_page=per_page,
                user_ids=user_ids or None,
                search=search or None,
                include_users=include_users,
                include_total=include_total,
            )
            return make_response(jsonify({"ok": True, "data": res}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch activity logs")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch activity logs"}),
                500,
            )

    @bp.get("/analytics/sessions")
    def api_analytics_sessions() -> Response:
        """
        Retrieve active sessions from the sessions service.

        :returns: JSON response with session records with HTTP 200, or service-unavailable error with HTTP 500
        """
        sessions_svc = getattr(current_app, "sessions_service", None)
        if not sessions_svc:
            return make_response(
                jsonify({"ok": False, "message": "Sessions service not available"}),
                500,
            )

        sessions = sessions_svc.get_sessions()
        return make_response(jsonify({"ok": True, "data": sessions}), 200)

    @bp.get("/jellyfin/libraries")
    @bp.post("/jellyfin/libraries")
    def api_jf_libraries() -> Response:
        """
        Fetches libraries with item counts and upserts to repository.
        Accepts credentials in POST body for setup flow.
        """
        try:
            payload = request.get_json(silent=True) or {}
            host = (payload.get("jf_host") or "").strip()
            port = (payload.get("jf_port") or "").strip()
            token = (payload.get("jf_api_key") or "").strip()

            use_temp_client = bool(host and port and token)

            if use_temp_client:
                from services.jellyfin import JellyfinClient

                class TempSettings:
                    """
                    Temporary settings class for JellyfinClient initialization.
                    """

                    def get(self):
                        """
                        Return a dictionary of temporary settings.

                        :returns: Dictionary with jf_host, jf_port, and jf_api_key
                        """
                        return {
                            "jf_host": host,
                            "jf_port": port,
                            "jf_api_key": token,
                        }

                temp_jf = JellyfinClient(TempSettings())
                result = temp_jf.libraries()
            else:
                result = jf.libraries()

            if not isinstance(result, dict) or not result.get("ok"):
                return make_response(
                    jsonify({"ok": False, "message": "Failed to retrieve libraries"}),
                    200,
                )

            data = result.get("data")
            if isinstance(data, dict) and isinstance(data.get("Items"), list):
                flat = data["Items"]
            elif isinstance(data, list):
                flat = data
            else:
                flat = []

            def _is_media_library(lib: dict) -> bool:
                """
                Determine if a library is a media library.

                :param lib: Dictionary representing a Jellyfin library
                :returns: True if the library is a media library, False otherwise
                """
                t = lib.get("CollectionType") or lib.get("Type") or ""
                t_norm = str(t).strip().lower()
                if not t_norm:
                    return False
                return any(k in t_norm for k in ("movies", "tvshows"))

            filtered = [l for l in flat if _is_media_library(l)]

            if not use_temp_client:
                try:
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
                                        if isinstance(stats, dict) and stats.get("ok")
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
                                stats.get("item_count", 0) if stats.get("ok") else 0
                            )

                try:
                    from services.mappers import map_libraries

                    mapped = map_libraries(filtered)
                    repo.upsert_libraries(mapped)
                except Exception:
                    logger.exception("[ERROR] Failed to map/upsert libraries")

            return make_response(jsonify({"ok": True, "data": filtered}), 200)

        except Exception:
            logger.exception("[ERROR] Failed to retrieve libraries")
            return make_response(
                jsonify(
                    {
                        "ok": False,
                        "message": "An error occurred while retrieving libraries",
                    }
                ),
                400,
            )

    @bp.get("/analytics/user/<user_id>/recent-activity")
    def api_user_recent_activity(user_id: str) -> Response:
        """
        Get recent playback activities for a user with calculated watch duration.

        :returns: JSON response with recent activity records including date, media name, and duration watched
        """
        try:
            limit = request.args.get("limit", 8, type=int)
            limit = max(1, min(100, limit))

            from services.data_models import PlaybackActivity, Item
            from sqlalchemy import and_

            activities = []
            with repo._session() as session:
                stop_events = (
                    session.query(
                        PlaybackActivity.id,
                        PlaybackActivity.user_id,
                        PlaybackActivity.item_id,
                        PlaybackActivity.activity_at,
                        PlaybackActivity.event_name,
                        PlaybackActivity.playback_type,
                    )
                    .filter(
                        PlaybackActivity.user_id == user_id,
                        PlaybackActivity.playback_type == "VideoPlaybackStopped",
                    )
                    .order_by(PlaybackActivity.activity_at.desc())
                    .limit(limit)
                    .all()
                )

                for (
                    _,
                    usr_id,
                    item_id,
                    stop_ts,
                    event_name,
                    playback_type,
                ) in stop_events:
                    start_event = (
                        session.query(PlaybackActivity.activity_at)
                        .filter(
                            PlaybackActivity.user_id == usr_id,
                            PlaybackActivity.item_id == item_id,
                            PlaybackActivity.playback_type == "VideoPlayback",
                            PlaybackActivity.activity_at < stop_ts,
                        )
                        .order_by(PlaybackActivity.activity_at.desc())
                        .first()
                    )

                    start_ts = start_event[0] if start_event else stop_ts
                    duration = int(stop_ts or 0) - int(start_ts or 0)

                    if duration < 0:
                        duration = 0

                    item = (
                        session.query(Item.name, Item.runtime_seconds)
                        .filter(Item.jellyfin_id == item_id)
                        .first()
                    )

                    item_name = item[0] if item else "Unknown"
                    runtime = int(item[1] or 0) if item else 0

                    if duration > 12 * 60 * 60:
                        duration = 0
                    elif runtime > 0:
                        duration = min(duration, runtime)

                    activities.append(
                        {
                            "item_id": item_id,
                            "item_name": item_name,
                            "event_name": event_name,
                            "playback_type": playback_type,
                            "activity_at": int(stop_ts or 0),
                            "duration_watched_seconds": max(0, duration),
                        }
                    )

            return make_response(jsonify({"ok": True, "data": activities}), 200)

        except Exception:
            logger.exception("[ERROR] Failed to fetch user recent activity")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch recent activity"}),
                500,
            )

    @bp.get("/analytics/users")
    def api_analytics_users() -> Response:
        """
        Retrieve list of non-archived users with ID and name.

        :returns: JSON response with user records and HTTP 200, or error details with HTTP 500
        """
        try:
            users = repo.list_users(include_archived=False)
            data = [
                {"user_id": user["jellyfin_id"], "name": user.get("name", "Unknown")}
                for user in users
            ]
            return make_response(jsonify({"ok": True, "data": data}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch users")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch users"}),
                500,
            )

    @bp.get("/analytics/user/<user_id>/stats/libraries")
    def api_user_stats_libraries(user_id: str) -> Response:
        """
        Retrieve top libraries for a specific user by play count.

        :returns: JSON response with user's top libraries and HTTP 200, or error details with HTTP 500
        """
        try:
            from services.statistics import StatisticsBuilder
            from services.data_models import User

            with repo._session() as session:
                user = session.query(User).filter(User.jellyfin_id == user_id).first()
                if not user:
                    return make_response(
                        jsonify({"ok": False, "message": "User not found"}), 404
                    )

                result = StatisticsBuilder.top_libraries_by_user(session, limit=5)
                user_data = next(
                    (u for u in result if u.get("user_id") == user_id), None
                )

                if not user_data:
                    return make_response(
                        jsonify({"ok": True, "data": {"libraries": []}}), 200
                    )

                return make_response(jsonify({"ok": True, "data": user_data}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch user library stats")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch user library stats"}),
                500,
            )

    @bp.get("/analytics/user/<user_id>/stats/items")
    def api_user_stats_items(user_id: str) -> Response:
        """
        Retrieve top items for a specific user by play count.

        :returns: JSON response with user's top items and HTTP 200, or error details with HTTP 500
        """
        try:
            from services.statistics import StatisticsBuilder
            from services.data_models import User

            with repo._session() as session:
                user = session.query(User).filter(User.jellyfin_id == user_id).first()
                if not user:
                    return make_response(
                        jsonify({"ok": False, "message": "User not found"}), 404
                    )

                result = StatisticsBuilder.top_items_by_user(session, limit=5)
                user_data = next(
                    (u for u in result if u.get("user_id") == user_id), None
                )

                if not user_data:
                    return make_response(
                        jsonify({"ok": True, "data": {"items": []}}), 200
                    )

                return make_response(jsonify({"ok": True, "data": user_data}), 200)
        except Exception:
            logger.exception("[ERROR] Failed to fetch user item stats")
            return make_response(
                jsonify({"ok": False, "message": "Failed to fetch user item stats"}),
                500,
            )

    return bp
