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
    
    def sync_partial(
        self,
        sync_users: bool = True,
    ) -> SyncResult:
        """
        Perform a partial sync focusing on recent changes.
        """
        start_time = time.time()
        errors: List[str] = []
        users_count = 0
        items_count = 0
        
        task_id = self.repository.create_task_log(
            name="Partial Sync",
            task_type="sync",
            execution_type="partial"
        )
        
        try:
            if sync_users:
                users_result = self.jellyfin_client.users()
                if users_result.get("ok"):
                    users_data = users_result.get("data", [])
                    if isinstance(users_data, list):
                        mapped_users = map_users(users_data)
                        users_count = self.repository.upsert_users(
                            mapped_users
                        )
                else:
                    errors.append(
                        f"Users sync failed: "
                        f"{users_result.get('message')}"
                    )
            
            duration_ms = int((time.time() - start_time) * 1000)
            result = SyncResult(
                success=len(errors) == 0,
                duration_ms=duration_ms,
                users_synced=users_count,
                libraries_synced=0,
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
            error_msg = f"Unexpected error: {str(exc)}"
            errors.append(error_msg)
            print(f"DEBUG: {error_msg}")
            print(f"TRACEBACK: {traceback.format_exc()}")
            
            result = SyncResult(
                success=False,
                duration_ms=duration_ms,
                users_synced=users_count,
                libraries_synced=0,
                items_synced=items_count,
                errors=errors,
            )
            
            self.repository.complete_task_log(
                task_id=task_id,
                result="FAILED",
                log_data=result.to_dict(),
            )
            
            return result