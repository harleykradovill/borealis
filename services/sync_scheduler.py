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
        """
        Initialize background sync scheduler with configurable interval.

        :param sync_service: SyncService instance to execute periodic syncs
        :param interval_seconds: Interval between syncs in seconds (default 1800)
        """
        self.sync_service = sync_service
        self.interval_seconds = int(interval_seconds)
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._pending_manual_run = False
        self._is_running = False
        self._last_started_at: int | None = None
        self._last_finished_at: int | None = None
        self._next_run_at: int | None = None

    def start(self) -> None:
        """
        Start the background sync scheduler thread.

        :returns: None
        """
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
        """
        Stop the background sync thread and wait for it to finish.

        :returns: None
        """
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join()
        logging.info("[INFO] SyncScheduler stopped")

    def _run_loop(self) -> None:
        """
        Main scheduler loop that manages sync timing and execution.

        :returns: None
        """
        run_immediately = True

        while not self._stop_event.is_set():
            should_run = False

            if run_immediately:
                should_run = True
                run_immediately = False
                with self._state_lock:
                    self._next_run_at = int(time.time())
            else:
                with self._state_lock:
                    self._next_run_at = int(time.time()) + self.interval_seconds

                woke_early = self._wake_event.wait(self.interval_seconds)
                self._wake_event.clear()

                if self._stop_event.is_set():
                    break

                if woke_early:
                    with self._state_lock:
                        if self._pending_manual_run:
                            should_run = True
                            self._pending_manual_run = False
                            self._next_run_at = int(time.time())
                else:
                    should_run = True
                    with self._state_lock:
                        self._next_run_at = int(time.time())

            if not should_run:
                continue

            started_at = int(time.time())
            with self._state_lock:
                self._is_running = True
                self._last_started_at = started_at
                self._next_run_at = None

            try:
                self.sync_service.sync_periodic()
            except Exception:
                logging.error("[ERROR] Periodic sync failed")
                traceback.print_exc()
            finally:
                finished_at = int(time.time())
                with self._state_lock:
                    self._is_running = False
                    self._last_finished_at = finished_at
                    if not self._stop_event.is_set():
                        self._next_run_at = finished_at + self.interval_seconds

    def set_interval(self, seconds: int) -> None:
        """
        Update the interval (in seconds) and reset the wait timer from now.

        :param seconds: New interval duration in seconds
        :returns: None
        :raises ValueError: Raised if seconds is not a positive integer
        """
        try:
            sec = int(seconds)
            if sec <= 0:
                raise ValueError
        except Exception:
            logging.warning("[WARN] Ignoring invalid sync interval: %s", seconds)
            return

        self.interval_seconds = sec
        with self._state_lock:
            if not self._is_running:
                self._next_run_at = int(time.time()) + sec

        self._wake_event.set()

    def trigger_periodic_now(self) -> None:
        """
        Request an immediate manual sync to run on the next cycle.

        :returns: None
        """
        with self._state_lock:
            self._pending_manual_run = True
            self._next_run_at = int(time.time())
        self._wake_event.set()
        logging.info("[INFO] Manual periodic sync requested")

    def get_status(self) -> dict:
        """
        Get current scheduler status including running state, timing, and next run info.

        :returns: Dictionary with sync scheduler status
        """
        with self._state_lock:
            return {
                "is_running": self._is_running,
                "interval_seconds": int(self.interval_seconds),
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
                "next_run_at": self._next_run_at,
                "pending_manual_run": self._pending_manual_run,
            }
