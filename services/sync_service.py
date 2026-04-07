from __future__ import annotations

import time
from datetime import datetime, timezone
import traceback
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import logging

from services.jellyfin import JellyfinClient
from services.repository import Repository
from services.mappers import (
    map_users,
    map_libraries,
    map_items,
    map_playback_events
)


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
    
    def sync_metadata(self) -> SyncResult:
        """
        Perform a full sync: users → libraries → items.
        """
        logging.info("[INFO] Starting Metadata Sync")

        start_time = time.time()
        errors: List[str] = []
        users_count = 0
        libraries_count = 0
        items_count = 0
        
        task_id = self.repository.create_task_log(
            name="Metadata Sync",
            task_type="sync",
            execution_type="full"
        )
        
        try:
            # Phase 1: Sync users
            users_result = self.jellyfin_client.users()
            if users_result.get("ok"):
                users_data = users_result.get("data", [])
                if isinstance(users_data, list):
                    mapped_users = map_users(users_data)
                    users_count = self.repository.upsert_users(
                        mapped_users
                    )
                    
                    # Archive users not in current list
                    active_ids = [
                        u["jellyfin_id"] for u in mapped_users
                    ]
                    self.repository.archive_missing_users(active_ids)
            else:
                errors.append(
                    f"Users sync failed: {users_result.get('message')}"
                )
            
            # Phase 2: Sync libraries
            libs_result = self.jellyfin_client.libraries()
            if libs_result.get("ok"):
                libs_data = libs_result.get("data")
                
                # Handle both dict with Items key and direct list
                if isinstance(libs_data, dict):
                    libs_list = libs_data.get("Items", [])
                elif isinstance(libs_data, list):
                    libs_list = libs_data
                else:
                    libs_list = []

                def _is_media_library(lib: dict) -> bool:
                    t = (lib.get("CollectionType") or lib.get("Type") or "")
                    t_norm = str(t).strip().lower()
                    if not t_norm:
                        return False
                    return any(k in t_norm for k in ("movies", "tvshows"))
                
                filtered_libs = [l for l in libs_list if _is_media_library(l)]
                
                mapped_libs = map_libraries(filtered_libs)
                libraries_count = self.repository.upsert_libraries(
                    mapped_libs
                )
                
                # Archive libraries not in current list
                active_lib_ids = [
                    lib["jellyfin_id"] for lib in mapped_libs
                ]
                self.repository.archive_missing_libraries(
                    active_lib_ids
                )
                
                # Phase 3: Sync items for each library
                libraries = self.repository.list_libraries(
                    include_archived=False
                )

                for lib in libraries:
                    lib_jf_id = lib["jellyfin_id"]
                    lib_internal_id = lib["id"]

                    items_result = self.jellyfin_client.library_items(
                        lib_jf_id
                    )

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
                            self.repository.archive_missing_items(lib_internal_id, active_item_ids)

                            type_counts: Dict[str, int] = {}
                            for it in items_list:
                                t = (it.get("Type") or it.get("TypeName") or "Unknown")
                                type_counts[t] = type_counts.get(t, 0) + 1

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
            else:
                errors.append(
                    f"Libraries sync failed: "
                    f"{libs_result.get('message')}"
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=len(errors) == 0,
                duration_ms=duration_ms,
                users_synced=users_count,
                libraries_synced=libraries_count,
                items_synced=items_count,
                errors=errors,
            )
            
            self.repository.complete_task_log(
                task_id=task_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=result.to_dict(),
            )

            logging.info("[INFO] Metadata Sync Complete")
            
            return result
            
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            errors.append(f"Unexpected error: {str(exc)}")
            
            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=users_count,
                libraries_synced=libraries_count,
                items_synced=items_count,
                errors=errors,
            )
            
            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=result.to_dict(),
            )
            
            return result

    def sync_activity_log_full(self) -> SyncResult:
        """
        Perform initial full activity log sync from Jellyfin.
        """
        logging.info("[INFO] Starting Full Activity Log Sync")

        start_time = time.time()
        errors: List[str] = []
        events_count = 0
        total_events = 0

        task_id = self.repository.create_task_log(
            name="Activity Log Sync (Full)",
            task_type="sync",
            execution_type="full"
        )
        self.repository.update_task_log_progress(
            task_id,
            {
                "phase": "starting",
                "items_synced": 0,
                "total_events": 0,
            },
        )

        try:
            # Build user lookup for username denormalization
            users = self.repository.list_users(include_archived=True)
            user_lookup: Dict[str, str] = {
                u["jellyfin_id"]: u["name"] for u in users
            }

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
                    error_msg = (
                        f"Activity log returned non-dict: "
                        f"{type(data)}"
                    )
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

                    try:
                        page_max = max(
                            int(ev.get("activity_at") or 0)
                            for ev in mapped_events
                        )
                        if page_max and (
                            latest_event_ts is None or page_max > latest_event_ts
                        ):
                            latest_event_ts = page_max
                    except Exception:
                        pass

                total_fetched += len(items)
                start_index += page_size

                self.repository.update_task_log_progress(
                    task_id,
                    {
                        "phase": "running",
                        "items_synced": int(events_count),
                        "total_events": int(total_events),
                    },
                )

                if total_fetched > 500000:
                    error_msg = (
                        "Activity log exceeded 500,000 entries, "
                        "stopping to prevent overload"
                    )
                    errors.append(error_msg)
                    break

            if events_count > 0:
                self.repository.refresh_play_stats()

            if latest_event_ts:
                self.settings_service.set_last_activity_log_sync(
                    int(latest_event_ts)
                )
            else:
                self.settings_service.set_last_activity_log_sync(int(time.time()))

            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=len(errors) == 0,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=events_count,
                errors=errors,
            )

            log_data = result.to_dict()
            log_data["phase"] = "complete" if result.success else "failed"
            log_data["total_events"] = int(total_events)

            self.repository.complete_task_log(
                task_id=task_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=log_data,
            )

            logging.info("[INFO] Full Activity Log Sync Complete")
            return result

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            errors.append(f"Unexpected error: {str(exc)}")

            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=events_count,
                errors=errors,
            )

            log_data = result.to_dict()
            log_data["phase"] = "failed"
            log_data["total_events"] = int(total_events)

            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=log_data,
            )

            return result

    def _ts_to_iso(self, ts: int) -> str:
        """
        Convert epoch seconds to Jellyfin-compatible ISO UTC string.
        """
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def sync_activity_log_incremental(
        self, minutes_back: int = 30, page_limit: int = 100
    ) -> SyncResult:
        """
        Perform incremental activity log sync for recent entries.
        """
        import time

        logging.info("[INFO] Starting Incremental Activity Log Sync")

        start_time = time.time()

        processed = 0
        errors: List[str] = []
        latest_event_ts: Optional[int] = None

        try:
            try:
                last = self.settings_service.get_last_activity_log_sync()
            except Exception:
                last = None

            if not last:
                duration_ms = int((time.time() - start_time) * 1000)
                result = SyncResult(
                    success=True,
                    duration_ms=duration_ms,
                    users_synced=0,
                    libraries_synced=0,
                    items_synced=0,
                    errors=[]
                )

            if last:
                min_ts = int(last)
            else:
                min_ts = int(time.time()) - (minutes_back * 60)

            min_date = self._ts_to_iso(min_ts)
            users = self.repository.list_users(include_archived=True)
            user_lookup: Dict[str, str] = {
                u["jellyfin_id"]: u["name"] for u in users
            }

            start_index = 0
            page_num = 0
            while True:
                page_num += 1
                resp = self.jellyfin_client.get_activity_log(
                    start_index=start_index,
                    limit=page_limit,
                    min_date=min_date,
                    has_user_id=True
                )
                if not resp.get("ok"):
                    errors.append(f"Failed to fetch activity log page at index {start_index}")
                    logging.error("[ERROR] Jellyfin get_activity_log returned not ok for start_index=%s: %s", start_index, resp.get("message"))
                    break

                data = resp.get("data") or []
                if not isinstance(data, list):
                    data = data.get("Items", []) if isinstance(data, dict) else []

                if not data:
                    logging.error("[WARNING] No activity entries since %s", min_date)
                    break

                playback_events = [
                    item
                    for item in data
                    if item.get("Type") in {"VideoPlayback", "VideoPlaybackStopped"}
                ]

                if playback_events:
                    mapped = map_playback_events(playback_events, user_lookup=user_lookup)
                    try:
                        inserted = self.repository.insert_playback_events(mapped)
                        processed += inserted
                    except Exception as exc:
                        errors.append(f"Failed to insert events: {str(exc)}")
                        logging.error("[ERROR] Failed to insert mapped playback events on page %s", page_num)

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
                    logging.error("[ERROR] Failed to persist last_activity_log_sync=%s", latest_event_ts)

            if processed > 0:
                self.repository.refresh_play_stats()

            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=(len(errors) == 0),
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=processed,
                errors=errors,
            )

            logging.info("[INFO] Incremental Activity Log Sync Complete")

            return result

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            errors.append(f"Unexpected error during incremental sync: {str(exc)}")
            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=processed,
                errors=errors,
            )
            return result
        
    def sync_initial(self) -> SyncResult:
        """
        Perform initial server setup sync combining full data sync
        and full activity log pull.
        """
        logging.info("[INFO] Starting Initial Sync")

        import time

        start_time = time.time()
        errors: List[str] = []

        task_id = self.repository.create_task_log(
            name="Initial Server Setup Sync",
            task_type="sync",
            execution_type="initial"
        )
        self.repository.update_task_log_progress(
            task_id,
            {
                "phase": "starting",
                "message": "Starting initial sync",
                "step": "1/3",
                "items_synced": 0,
                "total_events": 0,
            },
        )

        try:
            # Step 1: Sync users, libraries, and items
            full_result = self.sync_metadata()
            if not full_result.success and full_result.errors:
                errors.extend(full_result.errors)

            self.repository.update_task_log_progress(
            task_id,
            {
                "phase": "running",
                "message": "Metadata sync complete, syncing activity log",
                "step": "2/3",
            },
        )

            # Step 2: Sync activity log
            activity_result = (
                self.sync_activity_log_full()
            )
            if not activity_result.success and activity_result.errors:
                errors.extend(activity_result.errors)

            self.repository.update_task_log_progress(
            task_id,
            {
                "phase": "running",
                "message": "Refreshing dashboard stats",
                "step": "3/3",
                "items_synced": int(
                    full_result.items_synced + activity_result.items_synced
                ),
                "total_events": int(activity_result.items_synced),
            },
        )

            # Step 3: Refresh dashboard stats
            try:
                self._refresh_dashboard_cache()
            except Exception as exc:
                errors.append(
                    f"Failed to refresh dashboard stats: {str(exc)}"
                )

            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=(full_result.success and activity_result.success),
                duration_ms=duration_ms,
                users_synced=full_result.users_synced,
                libraries_synced=full_result.libraries_synced,
                items_synced=(
                    full_result.items_synced + activity_result.items_synced
                ),
                errors=errors,
            )

            log_data = result.to_dict()
            log_data["phase"] = "complete" if result.success else "failed"
            log_data["message"] = (
                "Initial sync complete" if result.success else "Initial sync failed"
            )
            log_data["step"] = "3/3"

            self.repository.complete_task_log(
                task_id=task_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=log_data,
            )

            logging.info("[INFO] Initial Sync Complete")
            return result

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Unexpected error during initial sync: {str(exc)}"
            errors.append(error_msg)

            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=0,
                errors=errors,
            )

            log_data = result.to_dict()
            log_data["phase"] = "failed"
            log_data["message"] = "Initial sync failed"

            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=log_data,
            )

            return result
        
    def sync_periodic(self) -> SyncResult:
        """
        Perform periodic sync: full metadata sync (users/libraries/items),
        incremental activity log sync (if marker exists), and refresh play statistics.
        """

        logging.info("[INFO] Starting Periodic Sync")

        start_time = time.time()
        errors: List[str] = []

        task_id = self.repository.create_task_log(
            name="Periodic Sync",
            task_type="sync",
            execution_type="periodic"
        )
        self.repository.update_task_log_progress(
            task_id,
            {
                "phase": "starting",
                "message": "Starting periodic sync",
                "step": "1/4",
                "items_synced": 0,
                "total_events": 0,
            },
        )

        try:
            # Step 1: Sync users, libraries, and items
            metadata_result = self.sync_metadata()
            if not metadata_result.success and metadata_result.errors:
                errors.extend(metadata_result.errors)

            self.repository.update_task_log_progress(
                task_id,
                {
                    "phase": "running",
                    "message": "Metadata sync complete, syncing activity log",
                    "step": "2/4",
                    "items_synced": int(metadata_result.items_synced),
                },
            )

            # Step 2: Sync activity log incrementally
            activity_result = self.sync_activity_log_incremental()
            if not activity_result.success and activity_result.errors:
                errors.extend(activity_result.errors)

            self.repository.update_task_log_progress(
                task_id,
                {
                    "phase": "running",
                    "message": "Refreshing play stats",
                    "step": "3/4",
                    "items_synced": int(
                        metadata_result.items_synced + activity_result.items_synced
                    ),
                    "total_events": int(activity_result.items_synced),
                },
            )

            # Step 3: Refresh play statistics
            try:
                self.repository.refresh_play_stats()
            except Exception as exc:
                errors.append(f"Failed to refresh play stats: {str(exc)}")

            self.repository.update_task_log_progress(
                task_id,
                {
                    "phase": "running",
                    "message": "Refreshing dashboard stats",
                    "step": "4/4",
                },
            )

            # Step 4: Refresh dashboard stats
            try:
                self._refresh_dashboard_cache()
            except Exception as exc:
                errors.append(
                    f"Failed to refresh dashboard stats: {str(exc)}"
                )

            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=(metadata_result.success and activity_result.success),
                duration_ms=duration_ms,
                users_synced=metadata_result.users_synced,
                libraries_synced=metadata_result.libraries_synced,
                items_synced=(
                    metadata_result.items_synced + activity_result.items_synced
                ),
                errors=errors,
            )

            log_data = result.to_dict()
            log_data["phase"] = "complete" if result.success else "failed"
            log_data["message"] = (
                "Periodic sync complete" if result.success else "Periodic sync failed"
            )
            log_data["step"] = "4/4"

            self.repository.complete_task_log(
                task_id=task_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=log_data,
            )

            logging.info("[INFO] Periodic Sync Complete")
            return result

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Unexpected error during periodic sync: {str(exc)}"
            errors.append(error_msg)

            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=0,
                errors=errors,
            )

            log_data = result.to_dict()
            log_data["phase"] = "failed"
            log_data["message"] = "Periodic sync failed"

            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=log_data,
            )

            return result

    def _refresh_dashboard_cache(self) -> None:
        """
        Refresh index dashboard stats cache from local DB data.
        """
        self.repository.refresh_dashboard_stats(limit=5)