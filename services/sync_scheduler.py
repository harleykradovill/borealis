"""
Background scheduler that runs periodic sync operations.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback


class SyncScheduler:
    """
    Background thread that runs sync operations on an interval.

    Behavior:
    - Every interval: run a lightweight full sync (users/libraries/items).
    - Only run incremental activity-log sync if a last-activity marker exists.
    """

    def __init__(self, sync_service, interval_seconds: int = 1800):
        self.sync_service = sync_service
        self.interval_seconds = int(interval_seconds)
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._pending_manual_run = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="SyncScheduler",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background sync thread."""
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join()
        logging.info("[INFO] SyncScheduler stopped")

    def _run_loop(self) -> None:
        logging.info(
            "[INFO] SyncScheduler loop starting (interval=%s seconds)",
            self.interval_seconds,
        )
    
        run_immediately = True
    
        while not self._stop_event.is_set():
            should_run = False
    
            if run_immediately:
                should_run = True
                run_immediately = False
            else:
                woke_early = self._wake_event.wait(self.interval_seconds)
                self._wake_event.clear()
    
                if self._stop_event.is_set():
                    break
                
                if woke_early:
                    with self._state_lock:
                        if self._pending_manual_run:
                            should_run = True
                            self._pending_manual_run = False
                else:
                    should_run = True
    
            if not should_run:
                continue
            
            try:
                self.sync_service.sync_periodic()
            except Exception:
                logging.error("[ERROR] Periodic sync failed")
                traceback.print_exc()

    def set_interval(self, seconds: int) -> None:
        """
        Update the interval (in seconds) and reset the wait timer from now.
        """
        try:
            sec = int(seconds)
            if sec <= 0:
                raise ValueError
        except Exception:
            logging.warning("[WARN] Ignoring invalid sync interval: %s", seconds)
            return

        self.interval_seconds = sec
        self._wake_event.set()
        logging.info("[INFO] Sync interval updated to %s seconds", sec)

    def trigger_periodic_now(self) -> None:
        with self._state_lock:
            self._pending_manual_run = True
        self._wake_event.set()
        logging.info("[INFO] Manual periodic sync requested")
