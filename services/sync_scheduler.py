from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional

from services.sync_service import SyncService


@dataclass
class SyncScheduler:
    """
    Background thread that runs partial syncs on an interval.
    """
    
    sync_service: SyncService
    interval_seconds: int = 300  # 5 minutes
    
    def __post_init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start the background sync thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True
        )
        self._thread.start()
        print(f"SyncScheduler started (interval: {self.interval_seconds}s)")
    
    def stop(self) -> None:
        """Stop the background sync thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("SyncScheduler stopped")
    
    def _run_loop(self) -> None:
        """Main loop that runs partial syncs periodically."""
        while self._running:
            try:
                result = self.sync_service.sync_partial(
                    sync_users=True,
                )
                status = "SUCCESS" if result.success else "FAILED"
                print(
                    f"Scheduled sync {status}: "
                    f"{result.users_synced} users, "
                    f"{result.items_synced} items "
                    f"({result.duration_ms}ms)"
                )
            except Exception as exc:
                print(f"Scheduled sync error: {exc}")
            
            for _ in range(self.interval_seconds):
                if not self._running:
                    break
                time.sleep(1)