from __future__ import annotations

import time
from datetime import datetime, timezone
import json
import traceback
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

from services.jellyfin import JellyfinClient
from services.repository import Repository
from services.mappers import (
    map_users,
    map_libraries,
    map_items,
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
    
    def sync_full(self) -> SyncResult:
        """
        Perform a full sync: users → libraries → items → reconciliation.
        """
        start_time = time.time()
        errors: List[str] = []
        users_count = 0
        libraries_count = 0
        items_count = 0
        
        task_id = self.repository.create_task_log(
            name="Full Sync",
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
                
                # Phase 3: Sync items for each tracked library
                tracked_libs = self.repository.list_libraries(
                    include_archived=False
                )
                
                for lib in tracked_libs:
                    if not lib.get("tracked"):
                        continue
                    
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
                        
                        mapped_items = map_items(
                            items_list,
                            lib_internal_id
                        )
                        count = self.repository.upsert_items(
                            mapped_items
                        )
                        items_count += count
                        
                        # Archive items not in current list
                        active_item_ids = [
                            item["jellyfin_id"]
                            for item in mapped_items
                        ]
                        self.repository.archive_missing_items(
                            lib_internal_id,
                            active_item_ids
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
        start_time = time.time()
        errors: List[str] = []
        events_count = 0

        task_id = self.repository.create_task_log(
            name="Activity Log Sync (Full)",
            task_type="sync",
            execution_type="full"
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

            while True:
                # Fetch one page of activity log
                activity_result = (
                    self.jellyfin_client.get_activity_log(
                        start_index=start_index,
                        limit=page_size,
                        has_user_id=True
                    )
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
                    # No more entries to fetch
                    break

                # Filter for playback events only
                from services.mappers import map_playback_events
                playback_events = [
                    item for item in items
                    if item.get("Type") == "VideoPlaybackStopped"
                ]

                if playback_events:
                    mapped_events = map_playback_events(
                        playback_events,
                        user_lookup=user_lookup
                    )
                    count = (
                        self.repository.insert_playback_events(
                            mapped_events
                        )
                    )
                    events_count += count

                total_fetched += len(items)
                start_index += page_size

                # Safety check to prevent infinite loops
                if total_fetched > 100000:
                    error_msg = (
                        "Activity log exceeded 100,000 entries, "
                        "stopping to prevent overload"
                    )
                    errors.append(error_msg)
                    break

            if events_count > 0:
                self.repository.refresh_play_stats()

            now = int(time.time())
            self.repository.set_last_activity_log_sync(now)

            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=len(errors) == 0,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=events_count,
                errors=errors,
            )

            self.repository.complete_task_log(
                task_id=task_id,
                result="SUCCESS" if result.success else "FAILED",
                log_data=result.to_dict(),
            )

            return result

        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Unexpected error: {str(exc)}"
            errors.append(error_msg)

            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=0,
                libraries_synced=0,
                items_synced=events_count,
                errors=errors,
            )

            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=result.to_dict(),
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
        start_time = time.time()
        task_id = self.repository.create_task_log(
            name="Activity Log Incremental",
            task_type="sync",
            execution_type="incremental"
        )

        processed = 0
        errors: List[str] = []
        latest_event_ts: Optional[int] = None

        try:
            last = self.repository.get_last_activity_log_sync()
            if last:
                min_ts = int(last)
            else:
                min_ts = int(time.time()) - (minutes_back * 60)

            min_date = self._ts_to_iso(min_ts)

            start_index = 0
            while True:
                resp = self.jellyfin_client.get_activity_log(
                    start_index=start_index,
                    limit=page_limit,
                    min_date=min_date,
                    has_user_id=True
                )

                if not resp.get("ok"):
                    errors.append(resp.get("message", "unknown error"))
                    break

                data = resp.get("data") or []
                if isinstance(data, dict):
                    page = data.get("Items", [])
                else:
                    page = data

                if not isinstance(page, list) or not page:
                    break

                from services.mappers import map_playback_events
                mapped = map_playback_events(page, user_lookup=None)

                for m in mapped:
                    ts = m.get("activity_at")
                    if isinstance(ts, int):
                        if latest_event_ts is None or ts > latest_event_ts:
                            latest_event_ts = ts

                inserted = self.repository.insert_playback_events(mapped)
                processed += inserted

                if len(page) < page_limit:
                    break
                start_index += len(page)

            if processed > 0 and latest_event_ts:
                advance_ts = int(latest_event_ts)
                try:
                    self.repository.set_last_activity_log_sync(advance_ts)
                except Exception:
                    pass

            self.repository.complete_task_log(
                task_id=task_id,
                result="SUCCESS" if not errors else "PARTIAL",
                log_data={
                    "items_synced": processed,
                    "total_events": processed,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "errors": errors,
                    "min_date_used": min_date,
                    "advanced_to": latest_event_ts if processed > 0 else None,
                },
            )

            return SyncResult(success=(not errors), duration_ms=int((time.time() - start_time) * 1000),
                              users_synced=0, libraries_synced=0, items_synced=processed, errors=errors)

        except Exception as exc:
            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data={"message": str(exc)}
            )
            return SyncResult(success=False, duration_ms=0, users_synced=0, libraries_synced=0, items_synced=0, errors=[str(exc)])
        
    def sync_initial(self) -> SyncResult:
        """
        Perform initial server setup sync combining full data sync
        and full activity log pull.
        """
        import time

        start_time = time.time()
        errors: List[str] = []

        task_id = self.repository.create_task_log(
            name="Initial Server Setup Sync",
            task_type="sync",
            execution_type="initial"
        )

        try:
            # Step 1: Sync users, libraries, and items
            full_result = self.sync_full()
            if not full_result.success and full_result.errors:
                errors.extend(full_result.errors)

            # Step 2: Sync activity log
            activity_result = (
                self.sync_activity_log_full()
            )
            if not activity_result.success and activity_result.errors:
                errors.extend(activity_result.errors)

            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=(
                    full_result.success
                    and activity_result.success
                ),
                duration_ms=duration_ms,
                users_synced=full_result.users_synced,
                libraries_synced=full_result.libraries_synced,
                items_synced=(
                    full_result.items_synced
                    + activity_result.items_synced
                ),
                errors=errors,
            )

            self.repository.complete_task_log(
                task_id=task_id,
                result=(
                    "SUCCESS" if result.success else "FAILED"
                ),
                log_data=result.to_dict(),
            )

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

            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=result.to_dict(),
            )

            return result