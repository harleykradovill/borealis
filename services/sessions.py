"""
Background service to poll Jellyfin sessions and cache sanitized active sessions.
Sanitizes now-playing payloads for the UI and optionally resolves episode series
names via the repository.
"""

import logging
from threading import Event, Thread
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionsService:
    def __init__(
        self,
        jellyfin_client: Any,
        sync_interval: int = 5,
        repository: Optional[Any] = None,
    ) -> None:
        """
        Initialize sessions service.

        :param jellyfin_client: JellyfinClient instance
        :param sync_interval: Seconds between syncs (default 5)
        :param repository: Optional repo instance for series name resolution
        """
        self._client = jellyfin_client
        self._sync_interval = sync_interval
        self._repository = repository
        self._thread: Optional[Thread] = None
        self._stop_event = Event()
        self._last_sessions: List[Dict[str, Any]] = []

    def start(self) -> None:
        """
        Start background sync thread.

        :returns: None
        """
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = Thread(target=self._sync_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Stop background sync thread.

        :returns: None
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("[INFO] Sessions service stopped")

    def get_sessions(self) -> List[Dict[str, Any]]:
        """
        Get cached active sessions from last sync.

        :returns: List of session dictionaries with sanitized session data
        """
        return self._last_sessions.copy()

    def _sync_loop(self) -> None:
        """
        Background thread loop that periodically fetches and caches sessions.

        :returns: None (runs until stop event is set)
        """
        while not self._stop_event.is_set():
            try:
                self._fetch_sessions()
            except Exception as exc:
                logger.error(f"[ERROR] Sessions sync error: {exc}")

            self._stop_event.wait(self._sync_interval)

    def _fetch_sessions(self) -> None:
        """
        Fetch and cache active sessions from Jellyfin.

        :returns: None
        :raises Exception: Logs errors, continues operation on failure
        """
        result = self._client.sessions()
        if not result.get("ok"):
            self._last_sessions = []
            return

        data = result.get("data", [])
        if not isinstance(data, list):
            self._last_sessions = []
            return

        playing_sessions = [s for s in data if s.get("NowPlayingItem")]

        sanitized = self._sanitize_sessions(playing_sessions)

        sanitized.sort(key=lambda x: (x.get("UserName") or "", x.get("Id") or ""))
        self._last_sessions = sanitized

    def _sanitize_sessions(
        self, sessions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Reduces session objects to essential fields for frontend display.

        :param sessions: List of raw session dictionaries from Jellyfin API
        :returns: List of sanitized session dicts with core metadata and resolved episode series names
        """
        root_keys = {
            "Id",
            "UserId",
            "UserName",
            "Client",
            "DeviceName",
            "RemoteEndPoint",
            "PlayState",
            "NowPlayingItem",
            "TranscodingInfo",
        }
        item_keys = {"Name", "RunTimeTicks", "Id", "Type", "ImageTags"}

        sanitized = []
        for s in sessions:
            clean = {k: s[k] for k in root_keys if k in s}

            item = clean.get("NowPlayingItem")
            if isinstance(item, dict):
                image_tags = item.get("ImageTags") or {}
                clean_item = {k: item[k] for k in item_keys if k in item}
                if image_tags.get("Primary"):
                    clean_item["PrimaryImageTag"] = image_tags["Primary"]
                clean["NowPlayingItem"] = clean_item

                episode_name = (clean_item.get("Name") or "").strip()
                series_name = self._resolve_episode_series_name(clean_item)

                if series_name and episode_name:
                    clean_item["Name"] = f"{series_name} - {episode_name}"
                elif series_name:
                    clean_item["Name"] = series_name

            sanitized.append(clean)
        return sanitized

    def _resolve_episode_series_name(
        self, now_playing_item: Dict[str, Any]
    ) -> Optional[str]:
        """
        Resolve series name for episode items using repository lookup.

        :param now_playing_item: Session now_playing_item dict from Jellyfin
        :returns: Series name string or None of not an episode, no repo, or lookup fails
        """
        if not self._repository:
            return None

        item_type = (now_playing_item.get("Type") or "").lower()
        if item_type != "episode":
            return None

        item_id = now_playing_item.get("Id")
        if not item_id:
            return None

        try:
            return self._repository.get_series_or_item_name(item_id)
        except Exception as exc:
            logger.warning(
                f"[WARN] Failed to resolve episode series name for {item_id}: {exc}"
            )
            return None
