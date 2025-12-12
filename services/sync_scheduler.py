"""
Background scheduler that runs periodic sync operations.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional

from services.sync_service import SyncService


@dataclass
class SyncScheduler:
    """
    Background thread that runs sync operations on an interval.
    
    Handles both initial full activity log pulls and periodic
    incremental syncs for recent playback activity.
    """

    sync_service: SyncService
    interval_seconds: int = 1800  # 30 minutes

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
        print(
            f"SyncScheduler started "
            f"(interval: {self.interval_seconds}s)"
        )

    def stop(self) -> None:
        """Stop the background sync thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("SyncScheduler stopped")

    def _run_loop(self) -> None:
        """
        Main loop that runs sync operations periodically.
        """
        while self._running:
            try:
                # Check if initial activity log sync is needed
                if (
                    self.sync_service.repository
                    .is_initial_activity_log_sync_needed()
                ):
                    # Initial full sync from activity log
                    result = (
                        self.sync_service
                        .sync_activity_log_full()
                    )
                    status = (
                        "SUCCESS" if result.success else "FAILED"
                    )
                    print(
                        f"Initial activity log sync {status}: "
                        f"{result.items_synced} events "
                        f"({result.duration_ms}ms)"
                    )
                else:
                    # Incremental sync for recent activity
                    result = (
                        self.sync_service
                        .sync_activity_log_incremental(
                            minutes_back=30
                        )
                    )
                    status = (
                        "SUCCESS" if result.success else "FAILED"
                    )
                    print(
                        f"Incremental activity log sync {status}: "
                        f"{result.items_synced} events "
                        f"({result.duration_ms}ms)"
                    )
            except Exception as exc:
                print(f"Scheduled sync error: {exc}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(self.interval_seconds):
                if not self._running:
                    break
                time.sleep(1)