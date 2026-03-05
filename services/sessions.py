"""
Service for periodically syncing active Jellyfin sessions.
Decoupled from activity log syncing.
"""

from typing import Any, Dict, List, Optional
from threading import Thread, Event
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
            if s.get("NowPlayingItem")
        ]
        
        sanitized = self._sanitize_sessions(playing_sessions)

        sanitized.sort(
            key=lambda x: (x.get("UserName") or "", x.get("Id") or "")
        )
        self._last_sessions = sanitized

    def _sanitize_sessions(
        self,
        sessions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Reduces session objects to essential fields for frontend display.
        """
        root_keys = {
            "Id", "UserName", "Client", "DeviceName", "RemoteEndPoint",
            "PlayState", "NowPlayingItem", "TranscodingInfo"
        }
        item_keys = {"Name", "RunTimeTicks", "Id", "Type"}

        sanitized = []
        for s in sessions:
            clean = {k: s[k] for k in root_keys if k in s}

            item = clean.get("NowPlayingItem")
            if isinstance(item, dict):
                clean["NowPlayingItem"] = {
                    k: item[k] for k in item_keys if k in item
                }

            sanitized.append(clean)
        return sanitized

    def _update_cache(self) -> None:
        """
        Polls Jellyfin for sessions and updates the sanitized cache.
        """
        result = self.jellyfin_client.sessions()
        if result.get("ok"):
            raw_data = result.get("data", [])
            self._cached_sessions = self._sanitize_sessions(raw_data)