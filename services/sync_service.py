from __future__ import annotations

import time
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
                
                mapped_libs = map_libraries(libs_list)
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

            # Refresh stats after inserting events
            if events_count > 0:
                self.repository.refresh_play_stats()

            # Update last sync timestamp
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

    def sync_activity_log_incremental(
        self,
        minutes_back: int = 30
    ) -> SyncResult:
        """
        Perform incremental activity log sync for recent entries.
        """
        from datetime import datetime, timedelta

        start_time = time.time()
        errors: List[str] = []
        events_count = 0

        task_id = self.repository.create_task_log(
            name="Activity Log Sync (Incremental)",
            task_type="sync",
            execution_type="incremental"
        )

        try:
            # Calculate minDate for API query
            minutes_ago = datetime.utcnow() - timedelta(
                minutes=minutes_back
            )
            min_date = minutes_ago.isoformat() + "Z"

            # Build user lookup
            users = self.repository.list_users(include_archived=True)
            user_lookup: Dict[str, str] = {
                u["jellyfin_id"]: u["name"] for u in users
            }

            # Fetch recent activity log with date filter
            activity_result = (
                self.jellyfin_client.get_activity_log(
                    start_index=0,
                    limit=5000,
                    min_date=min_date,
                    has_user_id=True
                )
            )

            if not activity_result.get("ok"):
                error_msg = (
                    f"Failed to fetch recent activity log: "
                    f"{activity_result.get('message')}"
                )
                errors.append(error_msg)
            else:
                data = activity_result.get("data", {})
                if isinstance(data, dict):
                    items = data.get("Items", [])

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
                        events_count = (
                            self.repository.insert_playback_events(
                                mapped_events
                            )
                        )

            # Refresh stats after inserting events
            if events_count > 0:
                self.repository.refresh_play_stats()

            # Update last sync timestamp
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