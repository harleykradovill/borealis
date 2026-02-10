"""
Service for periodically syncing active Jellyfin sessions.
Decoupled from activity log syncing.
"""

from typing import Any, Dict, List, Optional
from threading import Thread, Event
import time
import logging

logger = logging.getLogger(__name__)


class SessionsService:
    """Manages periodic collection of active Jellyfin sessions."""

    def __init__(
        self,
        jellyfin_client: Any,
        sync_interval: int = 5
    ) -> None:
        """
        Initialize sessions service.

        :param jellyfin_client: JellyfinClient instance
        :param sync_interval: Seconds between syncs (default 5)
        """
        self._client = jellyfin_client
        self._sync_interval = sync_interval
        self._thread: Optional[Thread] = None
        self._stop_event = Event()
        self._last_sessions: List[Dict[str, Any]] = []

    def start(self) -> None:
        """Start background sync thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        logger.info("[INFO] Sessions service started")

    def stop(self) -> None:
        """Stop background sync thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("[INFO] Sessions service stopped")

    def get_sessions(self) -> List[Dict[str, Any]]:
        """Get cached active sessions."""
        return self._last_sessions.copy()

    def _sync_loop(self) -> None:
        """Background thread loop for periodic syncing."""
        while not self._stop_event.is_set():
            try:
                self._fetch_sessions()
            except Exception as exc:
                logger.error(f"[ERROR] Sessions sync error: {exc}")

            self._stop_event.wait(self._sync_interval)

    def _fetch_sessions(self) -> None:
        """Fetch and cache active sessions from Jellyfin."""
        result = self._client.sessions()
        if not result.get("ok"):
            self._last_sessions = []
            return

        data = result.get("data", [])
        if not isinstance(data, list):
            self._last_sessions = []
            return

        playing_sessions = [
            s for s in data
            if s.get("NowPlayingItem") and
            s.get("PlayState", {}).get("IsPaused") is False
        ]
        playing_sessions.sort(
            key=lambda x: (x.get("UserName") or "", x.get("Id") or "")
        )
        self._last_sessions = playing_sessions