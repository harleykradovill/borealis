"""
Sync orchestrator for Jellyfin ingestion. Defines SyncResult and SyncService to coordinate
metadata sync, full and incremental activity-log ingestions, initial/periodic sync workflows,
progress reporting, and dashboard cache refreshes.
"""

from __future__ import annotations

import logging
import time
import traceback

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.jellyfin import JellyfinClient
from services.mappers import (
    map_items,
    map_libraries,
    map_playback_events,
    map_users,
)
from services.repository import Repository


@dataclass
class SyncResult:
    """
    Structured result from a sync operation.
    """

    success: bool
    duration_ms: int
    users_synced: int
    libraries_synced: int
    items_synced: int
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert SyncResult data class to dictionary.

        :returns: Dictionary containing success status, duration, sync counts, and errors
        """
        return {
            "success": self.success,
            "duration_ms": self.duration_ms,
            "users_synced": self.users_synced,
            "libraries_synced": self.libraries_synced,
            "items_synced": self.items_synced,
            "errors": self.errors,
        }


@dataclass
class SyncService:
    jellyfin_client: JellyfinClient
    repository: Repository
    settings_service: Any
    _sync_callbacks: List[callable] = field(default_factory=list)

    def register_sync_callback(self, callback: callable) -> None:
        """
        Register a callback to be invoked when sync completes.

        :param callback: Callable(result: SyncResult) -> None
        """
        if callback and callable(callback):
            self._sync_callbacks.append(callback)

    def _invoke_sync_callbacks(self, result: SyncResult) -> None:
        """
        Invoke all registered sync callbacks.

        :param result: SyncResult from the completed sync
        """
        for callback in self._sync_callbacks:
            try:
                callback(result)
            except Exception as error:
                logging.exception(f"[ERROR] Sync callback failed: {error}")

    def _build_result(
        self,
        start_time: float,
        errors: List[str],
        users_synced: int = 0,
        libraries_synced: int = 0,
        items_synced: int = 0,
        success: Optional[bool] = None,
    ) -> SyncResult:
        """
        Build a SyncResult with computed duration.

        :param start_time: Epoch time when the operation started
        :param errors: Error messages collected during the operation
        :param users_synced: Number of users synced
        :param libraries_synced: Number of libraries synced
        :param items_synced: Number of items/events synced
        :param success: Optional explicit success value
        :returns: SyncResult instance for the operation
        """
        duration_ms = int((time.time() - start_time) * 1000)
        result_success = success if success is not None else (len(errors) == 0)
        return SyncResult(
            success=result_success,
            duration_ms=duration_ms,
            users_synced=users_synced,
            libraries_synced=libraries_synced,
            items_synced=items_synced,
            errors=errors,
        )

    def _update_sync_progress(
        self, sync_id: Optional[int], progress: Dict[str, Any]
    ) -> None:
        """
        Update sync progress when a sync id is available.

        :param sync_id: Sync log identifier or None
        :param progress: Progress payload to store in the sync log
        :returns: None
        """
        if sync_id is None:
            return
        self.repository.update_sync_log_progress(sync_id, progress)

    def _build_user_lookup(self) -> Dict[str, str]:
        """
        Build a lookup table from Jellyfin user id to display name.

        :returns: Mapping of Jellyfin user id to username
        """
        users = self.repository.list_users(include_archived=True)
        return {u["jellyfin_id"]: u["name"] for u in users}

    @staticmethod
    def _is_media_library(lib: Dict[str, Any]) -> bool:
        """
        Determine if a library is a media library.

        :param lib: Dictionary representing a Jellyfin media library
        :returns: True if the library is a media library, False otherwise
        """
        t = lib.get("CollectionType") or lib.get("Type") or ""
        t_norm = str(t).strip().lower()
        if not t_norm:
            return False
        return any(k in t_norm for k in ("movies", "tvshows"))

    def _sync_users(self, errors: List[str]) -> int:
        """
        Sync users and archive missing ones.

        :param errors: Error list to append messages to
        :returns: Count of users synced
        """
        users_result = self.jellyfin_client.users()
        if users_result.get("ok"):
            users_data = users_result.get("data", [])
            if isinstance(users_data, list):
                mapped_users = map_users(users_data)
                users_count = self.repository.upsert_users(mapped_users)

                active_ids = [u["jellyfin_id"] for u in mapped_users]
                self.repository.archive_missing_users(active_ids)

                return users_count
            return 0

        errors.append(f"Users sync failed: {users_result.get('message')}")
        return 0

    def _sync_libraries_and_items(self, errors: List[str]) -> Dict[str, int]:
        """
        Sync libraries and items for each library.

        :param errors: Error list to append messages to
        :returns: Dictionary containing libraries and items counts
        """
        libs_result = self.jellyfin_client.libraries()
        if not libs_result.get("ok"):
            errors.append(f"Libraries sync failed: {libs_result.get('message')}")
            return {"libraries": 0, "items": 0}

        libs_data = libs_result.get("data")

        if isinstance(libs_data, dict):
            libs_list = libs_data.get("Items", [])
        elif isinstance(libs_data, list):
            libs_list = libs_data
        else:
            libs_list = []

        filtered_libs = [l for l in libs_list if self._is_media_library(l)]

        mapped_libs = map_libraries(filtered_libs)
        libraries_count = self.repository.upsert_libraries(mapped_libs)

        active_lib_ids = [lib["jellyfin_id"] for lib in mapped_libs]
        self.repository.archive_missing_libraries(active_lib_ids)

        time.sleep(1.5)

        libraries = self.repository.list_libraries(include_archived=False)
        items_count = 0

        for lib in libraries:
            lib_jf_id = lib["jellyfin_id"]
            lib_internal_id = lib["id"]

            items_result = self.jellyfin_client.library_items(lib_jf_id)

            if items_result.get("ok"):
                items_data = items_result.get("data", {})
                if isinstance(items_data, dict):
                    items_list = items_data.get("Items", [])
                else:
                    items_list = []

                try:
                    mapped_items = map_items(items_list, lib_internal_id)
                    count = self.repository.upsert_items(mapped_items)
                    items_count += count

                    active_item_ids = [it["jellyfin_id"] for it in mapped_items]
                    self.repository.archive_missing_items(
                        lib_internal_id, active_item_ids
                    )

                except Exception:
                    traceback.print_exc()
                    errors.append(
                        f"Items processing failed for library {lib.get('name') or lib_jf_id}"
                    )

            else:
                errors.append(
                    f"Items sync failed for library "
                    f"{lib['name']}: "
                    f"{items_result.get('message')}"
                )

        return {"libraries": libraries_count, "items": items_count}

    def sync_metadata(self) -> SyncResult:
        """
        Perform a full metadata sync: users → libraries → items.

        :param sync_id: Optional sync log id for progress reporting
        :returns: SyncResult with success status, duration, and sync counts
        """
        start_time = time.time()
        errors: List[str] = []
        users_count = 0
        libraries_count = 0
        items_count = 0

        try:
            users_count = self._sync_users(errors)

            counts = self._sync_libraries_and_items(errors)
            libraries_count = counts["libraries"]
            items_count = counts["items"]

            result = self._build_result(
                start_time,
                errors,
                users_synced=users_count,
                libraries_synced=libraries_count,
                items_synced=items_count,
            )

            return result

        except Exception:
            errors.append("Unexpected error")

            result = self._build_result(
                start_time,
                errors,
                users_synced=users_count,
                libraries_synced=libraries_count,
                items_synced=items_count,
            )

            return result

    def sync_activity_log_full(self) -> SyncResult:
        """
        Perform initial full activity log sync from Jellyfin to capture all historical playback data.

        :returns: SyncResult with events synced count and any errors encountered
        """
        logging.info("[INFO] Starting Full Activity Log Sync")

        start_time = time.time()
        errors: List[str] = []
        events_count = 0
        total_events = 0

        try:
            user_lookup = self._build_user_lookup()

            page_size = 1000
            start_index = 0
            total_fetched = 0
            latest_event_ts: Optional[int] = None

            while True:
                activity_result = self.jellyfin_client.get_activity_log(
                    start_index=start_index,
                    limit=page_size,
                    has_user_id=True,
                )

                if not activity_result.get("ok"):
                    error_msg = (
                        f"Failed to fetch activity log at index "
                        f"{start_index}: "
                        f"{activity_result.get('message')}"
                    )
                    errors.append(error_msg)
                    break

                data = activity_result.get("data", {})
                if not isinstance(data, dict):
                    error_msg = f"Activity log returned non-dict: {type(data)}"
                    errors.append(error_msg)
                    break

                items = data.get("Items", [])
                if not items:
                    break

                reported_total = int(data.get("TotalRecordCount") or 0)
                if reported_total > 0:
                    total_events = reported_total
                elif total_events <= 0:
                    total_events = total_fetched + len(items)

                playback_events = [
                    item
                    for item in items
                    if item.get("Type") in {"VideoPlayback", "VideoPlaybackStopped"}
                ]

                if playback_events:
                    mapped_events = map_playback_events(
                        playback_events,
                        user_lookup=user_lookup,
                    )
                    count = self.repository.insert_playback_events(mapped_events)
                    events_count += count

                    if mapped_events:
                        page_max = max(
                            int(ev.get("activity_at") or 0) for ev in mapped_events
                        )
                        if not latest_event_ts or page_max > latest_event_ts:
                            latest_event_ts = page_max

                total_fetched += len(items)
                start_index += page_size

                if total_fetched > 500000:
                    error_msg = (
                        "Activity log exceeded 500,000 entries, "
                        "stopping to prevent overload"
                    )
                    errors.append(error_msg)
                    break

            if events_count > 0:
                play_threshold = int(
                    self.settings_service.get().get("play_threshold", 120)
                )

                self.repository.refresh_play_stats(minimum_play_seconds=play_threshold)

            if latest_event_ts:
                self.settings_service.set_last_activity_log_sync(int(latest_event_ts))
            else:
                self.settings_service.set_last_activity_log_sync(int(time.time()))

            result = self._build_result(
                start_time,
                errors,
                items_synced=events_count,
            )

            log_data = result.to_dict()
            log_data["phase"] = "complete" if result.success else "failed"
            log_data["total_events"] = int(total_events)

            logging.info("[INFO] Full Activity Log Sync Complete")
            return result

        except Exception:
            errors.append("Unexpected error")

            result = self._build_result(
                start_time,
                errors,
                items_synced=events_count,
            )

            log_data = result.to_dict()
            log_data["phase"] = "failed"
            log_data["total_events"] = int(total_events)

            return result

    def _ts_to_iso(self, ts: int) -> str:
        """
        Convert epoch seconds to Jellyfin-compatible ISO UTC string.

        :param ts: Unix timestamp in seconds
        :returns: ISO 8601 formatted UTC datetime string (YYYY-MM-DDTHH:MM:SSZ)
        """
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def sync_activity_log_incremental(
        self, minutes_back: int = 30, page_limit: int = 100
    ) -> SyncResult:
        """
        Perform incremental activity log sync for recent entries since last sync marker.

        :param minutes_back: Fallback window in minutes if no previous sync marker exists
        :param page_limit: Number of events per API request
        :returns: SyncResult with event counts and any sync errors
        """
        start_time = time.time()

        processed = 0
        errors: List[str] = []
        latest_event_ts: Optional[int] = None

        try:
            try:
                last = self.settings_service.get_last_activity_log_sync()
            except Exception:
                last = None

            if last:
                min_ts = int(last)
            else:
                min_ts = int(time.time()) - (minutes_back * 60)

            min_date = self._ts_to_iso(min_ts)
            user_lookup = self._build_user_lookup()

            start_index = 0
            page_num = 0
            while True:
                page_num += 1
                resp = self.jellyfin_client.get_activity_log(
                    start_index=start_index,
                    limit=page_limit,
                    min_date=min_date,
                    has_user_id=True,
                )
                if not resp.get("ok"):
                    errors.append(
                        f"Failed to fetch activity log page at index {start_index}"
                    )
                    logging.error(
                        "[ERROR] Jellyfin get_activity_log returned not ok for start_index=%s: %s",
                        start_index,
                        resp.get("message"),
                    )
                    break

                data = resp.get("data") or []
                if not isinstance(data, list):
                    data = data.get("Items", []) if isinstance(data, dict) else []

                if not data:
                    logging.info("[INFO] No activity entries since %s", min_date)
                    break

                playback_events = [
                    item
                    for item in data
                    if item.get("Type") in {"VideoPlayback", "VideoPlaybackStopped"}
                ]

                if playback_events:
                    mapped = map_playback_events(
                        playback_events, user_lookup=user_lookup
                    )
                    try:
                        inserted = self.repository.insert_playback_events(mapped)
                        processed += inserted
                    except Exception:
                        errors.append("Failed to insert events")
                        logging.error(
                            "[ERROR] Failed to insert mapped playback events on page %s",
                            page_num,
                        )

                    for ev in mapped:
                        ts = ev.get("activity_at")
                        if ts:
                            if latest_event_ts is None or ts > latest_event_ts:
                                latest_event_ts = ts

                if len(data) < page_limit:
                    break
                start_index += len(data)

            if latest_event_ts:
                try:
                    next_marker = int(latest_event_ts) + 1
                    self.settings_service.set_last_activity_log_sync(next_marker)
                except Exception:
                    errors.append("Failed to persist last activity marker")
                    logging.error(
                        "[ERROR] Failed to persist last_activity_log_sync=%s",
                        latest_event_ts,
                    )

            if processed > 0:
                play_threshold = int(
                    self.settings_service.get().get("play_threshold", 120)
                )

                self.repository.refresh_play_stats(minimum_play_seconds=play_threshold)

            result = self._build_result(
                start_time,
                errors,
                items_synced=processed,
            )

            return result

        except Exception:
            errors.append("Unexpected error during incremental sync")
            return self._build_result(
                start_time,
                errors,
                items_synced=processed,
                success=False,
            )

    def sync_initial(self) -> SyncResult:
        """
        Perform initial server setup sync combining full data sync
        and full activity log pull.

        :returns: SyncResult combining metrics from metadata, activity, and dashboard operations
        """
        logging.info("[INFO] Starting Initial Sync")

        start_time = time.time()
        errors: List[str] = []

        sync_id = self.repository.create_sync_log(
            name="Initial Server Setup Sync", sync_type="sync", execution_type="initial"
        )
        self._update_sync_progress(
            sync_id,
            {
                "phase": "running",
                "message": "Starting initial sync",
                "step": 1,
                "step_total": 4,
                "items_synced": 0,
                "total_events": 0,
            },
        )

        time.sleep(1)

        try:
            self._update_sync_progress(
                sync_id,
                {
                    "phase": "running",
                    "message": "Syncing metadata",
                    "step": 2,
                },
            )

            metadata_result = self.sync_metadata()
            if not metadata_result.success and metadata_result.errors:
                errors.extend(metadata_result.errors)

            self._update_sync_progress(
                sync_id,
                {
                    "phase": "running",
                    "message": "Syncing activity log",
                    "step": 3,
                },
            )

            activity_result = self.sync_activity_log_full()
            if not activity_result.success and activity_result.errors:
                errors.extend(activity_result.errors)

            time.sleep(1)

            self._update_sync_progress(
                sync_id,
                {
                    "phase": "running",
                    "message": "Refreshing statistics",
                    "step": 4,
                },
            )
            try:
                self._refresh_statistics_cache()
            except Exception:
                errors.append("Failed to refresh statistics")

            result = self._build_result(
                start_time,
                errors,
                users_synced=metadata_result.users_synced,
                libraries_synced=metadata_result.libraries_synced,
                items_synced=(
                    metadata_result.items_synced + activity_result.items_synced
                ),
                success=(metadata_result.success and activity_result.success),
            )

            log_data = result.to_dict()
            log_data["phase"] = "complete" if result.success else "failed"
            log_data["message"] = (
                "Initial sync complete" if result.success else "Initial sync failed"
            )
            log_data["step"] = 5

            self.repository.complete_sync_log(
                sync_id=sync_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=log_data,
            )

            time.sleep(1)

            self._invoke_sync_callbacks(result)

            logging.info("[INFO] Initial Sync Complete")
            return result

        except Exception:
            error_msg = "Unexpected error during initial sync"
            errors.append(error_msg)

            result = self._build_result(
                start_time,
                errors,
                users_synced=0,
                libraries_synced=0,
                items_synced=0,
                success=False,
            )

            log_data = result.to_dict()
            log_data["phase"] = "failed"
            log_data["message"] = "Initial sync failed"

            self.repository.complete_sync_log(
                sync_id=sync_id,
                result="FAILED",
                log_data=log_data,
            )

            return result

    def sync_periodic(self) -> SyncResult:
        """
        Perform periodic sync: full metadata sync (users/libraries/items),
        incremental activity log sync (if marker exists), and refresh play statistics.

        :returns: SyncResult with aggregated metrics from all sync phases
        """
        logging.info("[INFO] Starting Periodic Sync")

        start_time = time.time()
        errors: List[str] = []

        sync_id = self.repository.create_sync_log(
            name="Periodic Sync", sync_type="sync", execution_type="periodic"
        )
        self._update_sync_progress(
            sync_id,
            {
                "phase": "running",
                "message": "Starting periodic sync",
                "step": 1,
                "step_total": 4,
                "items_synced": 0,
                "total_events": 0,
            },
        )

        time.sleep(1)

        try:
            self._update_sync_progress(
                sync_id,
                {
                    "phase": "running",
                    "message": "Syncing metadata",
                    "step": 2,
                },
            )

            metadata_result = self.sync_metadata()
            if not metadata_result.success and metadata_result.errors:
                errors.extend(metadata_result.errors)

            self._update_sync_progress(
                sync_id,
                {
                    "phase": "running",
                    "message": "Syncing activity log",
                    "step": 3,
                },
            )

            time.sleep(1)

            activity_result = self.sync_activity_log_incremental()
            if not activity_result.success and activity_result.errors:
                errors.extend(activity_result.errors)

            time.sleep(1)

            self._update_sync_progress(
                sync_id,
                {
                    "phase": "running",
                    "message": "Refreshing statistics",
                    "step": 4,
                },
            )

            if activity_result.items_synced > 0:
                try:
                    self._refresh_statistics_cache()
                except Exception:
                    errors.append("Failed to refresh statistics")

            time.sleep(1)

            result = self._build_result(
                start_time,
                errors,
                users_synced=metadata_result.users_synced,
                libraries_synced=metadata_result.libraries_synced,
                items_synced=(
                    metadata_result.items_synced + activity_result.items_synced
                ),
                success=(metadata_result.success and activity_result.success),
            )

            log_data = result.to_dict()
            log_data["phase"] = "complete" if result.success else "failed"
            log_data["message"] = (
                "Periodic sync complete" if result.success else "Periodic sync failed"
            )
            log_data["step"] = 5

            self.repository.complete_sync_log(
                sync_id=sync_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=log_data,
            )

            time.sleep(1)

            self._invoke_sync_callbacks(result)

            logging.info("[INFO] Periodic Sync Complete")
            return result

        except Exception:
            error_msg = "Unexpected error during periodic sync"
            errors.append(error_msg)

            result = self._build_result(
                start_time,
                errors,
                users_synced=0,
                libraries_synced=0,
                items_synced=0,
                success=False,
            )

            log_data = result.to_dict()
            log_data["phase"] = "failed"
            log_data["message"] = "Periodic sync failed"

            self.repository.complete_sync_log(
                sync_id=sync_id,
                result="FAILED",
                log_data=log_data,
            )

            return result

    def _refresh_statistics_cache(self) -> None:
        """
        Refresh index statistics cache from local DB data.

        :returns: None
        :raises Exception: Any database errors during cache refresh
        """
        self.repository.refresh_statistics(limit=5)
