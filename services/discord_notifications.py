"""
Service that communicates with Discord webhooks to send notifications
about Jellyfin and Borealis itself.
"""

import json
import logging
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class DiscordNotificationService:
    """
    Background service that polls Jellyfin for playback events, and receives sync
    completion callbacks. Forwards notifications to a Discord webhook.
    """

    def __init__(
        self,
        svc: Any,
        jellyfin_client: Any,
        sync: Any,
        scheduler: Any,
        poll_interval: int = 5,
    ) -> None:
        """
        Initialize the Discord notification service.

        :param svc: SettingsService instance
        :param jellyfin_client: Client used to query Jellyfin for session data
        :param sync: SyncService instance
        :param poll_interval: How often to poll Jellyfin in seconds
        """
        self._settings_svc = svc
        self._jellyfin_client = jellyfin_client
        self._sync_svc = sync
        self._scheduler = scheduler
        self._poll_interval = poll_interval
        self._thread: Optional[Thread] = None
        self._stop_event = Event()
        self._last_sessions: Dict[Any, Any] = {}
        self._last_sync_check_time = 0
        self._last_sync_result: Optional[Any] = None

    def start(self) -> None:
        """
        Start the background polling thread.

        :returns: None
        """
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        Stop the background polling thread and clean up resources.

        :returns: None
        """
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=2)
        logger.info("[INFO] Discord Notifications service stopped")

    def _poll_loop(self) -> None:
        """
        Main loop to call _check_playback_changes and sleep for poll_interval.

        :returns: None
        """
        while not self._stop_event.is_set():
            try:
                settings = self._settings_svc.get()
                if settings.get("discord_enabled", False):
                    self._check_playback_changes(settings)
                    self._check_sync_completion(settings)
            except Exception as error:
                logger.exception(f"[ERROR] Discord Notification poll error: {error}")

            self._stop_event.wait(self._poll_interval)

    def _check_playback_changes(self, settings: Dict[str, Any]) -> None:
        """
        Compare the current Jellyfin sessions with _last_sessions to detect
        start/stop transitions, then trigger Discord notifications as needed.

        :returns: None
        """
        result = self._jellyfin_client.sessions()
        if not result.get("ok"):
            self._last_sessions = {}
            return

        data = result.get("data", [])
        if not isinstance(data, list):
            self._last_sessions = {}
            return

        current_sessions = {
            (s.get("UserId"), s.get("NowPlayingItem", {}).get("Id")): s
            for s in data
            if s.get("NowPlayingItem")
        }

        # Playback starts
        for key in current_sessions.keys() - self._last_sessions.keys():
            session = current_sessions[key]
            if self._should_notify(settings, "playback_start"):
                self._notify_playback(settings, session, "playback_start")

        # Playback stops
        for key in self._last_sessions.keys() - current_sessions.keys():
            session = self._last_sessions[key]
            if self._should_notify(settings, "playback_stop"):
                self._notify_playback(settings, session, "playback_stop")

        self._last_sessions = current_sessions

    def _check_sync_completion(self, settings: Dict[str, Any]) -> None:
        """
        Poll sync scheduler for completion and send notification if sync finished.

        :returns: None
        """
        try:
            status = self._scheduler.get_status()
            if status.get("_is_running"):
                return

            last_finished = status.get("_last_finished_at")
            if not last_finished or last_finished <= self._last_sync_check_time:
                return

            self._last_sync_check_time = last_finished

            repo = self._sync_svc.repository
            try:
                recent_task = repo.engine.execute(
                    "SELECT log_json FROM task_logging WHERE type='sync' "
                    "ORDER BY finished_at DESC LIMIT 1"
                ).fetchone()
                if recent_task and recent_task[0]:
                    result_data = json.loads(recent_task[0])
                    if self._should_notify(
                        settings, f"sync_{result_data.get('phase', 'failed')}"
                    ):
                        embed = self._build_sync_embed(result_data)
                        self._send_webhook(settings, embed)
            except Exception as error:
                logger.warning(f"[WARN] Could not fetch sync result: {error}")

        except Exception as error:
            logger.warning(f"[WARN] Sync completion check failed: {error}")

    def _send_webhook(
        self, settings: Dict[str, Any], embed_dict: Dict[str, Any]
    ) -> None:
        """
        Send a Discord webhook payload containing the supplied embed.

        :param settings: Settings dict
        :param embed_dict: Dict representing a Discord embed object
        """
        config = self._get_discord_config(settings)
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            return

        payload = {"embeds": [embed_dict]}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = Request(webhook_url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", "Borealis/1.0")

            with urlopen(req, timeout=5.0) as resp:
                status = getattr(resp, "status", 200)
                if not (200 <= status < 300):
                    logger.warning(f"[WARN] Discord webhook returned status {status}")
        except HTTPError as he:
            logger.warning(f"[WARN] Discord webhook HTTP error: {he.code}")
        except URLError as ue:
            logger.warning(f"[WARN] Discord webhook network error: {ue}")
        except Exception as error:
            logger.exception(f"[ERROR] Failed to send Discord webhook: {error}")

    def _should_notify(self, settings: Dict[str, Any], trigger: str) -> bool:
        """
        Determine whether a specific trigger is enabled in settings.

        :param settings: Settings dict
        :param trigger: Trigger identifier
        :returns: True if enabled, False otherwise
        """
        triggers = settings.get("discord_triggers", {})
        if isinstance(triggers, str):
            try:
                triggers = json.loads(triggers)
            except Exception:
                return False
        return triggers.get(trigger, False) if isinstance(triggers, dict) else False

    def _build_playback_embed(
        self, session: Dict[str, Any], event_type: str
    ) -> Dict[str, Any]:
        """
        Build a discord embed dict describing a playback event.

        :param session: Jellyfin session object with NowPlayingItem
        :param event_type: Type of playback event ("play", "stop", "pause")
        :returns: Dict ready to be sent as a Discord embed
        """
        user_name = session.get("UserName", "Unknown User")
        item = session.get("NowPlayingItem", {})
        item_name = item.get("Name", "Unknown Item")

        color = {
            "playback_start": 3184916,
            "playback_stop": 9377302,
            "playback_pause": 16776960,
        }.get(event_type, 9807270)

        event_label = {
            "playback_start": "Playback Started",
            "playback_stop": "Playback Stopped",
            "playback_pause": "Playback Paused",
        }.get(event_type, "Playback Event")

        return {
            "title": event_label,
            "color": color,
            "fields": [
                {"name": "User", "value": user_name},
                {"name": "Item", "value": item_name},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _build_sync_embed(self, result: Any) -> Dict[str, Any]:
        """
        Build a Discord embed dictionary describing a sync result.

        :param result: Object containing sync outcome
        :returns: Dict ready to be sent as a Discord embed
        """
        phase = result.get("phase", "unknown")
        success = phase == "complete"

        title = "Sync Complete" if success else "Sync Failed"
        color = 3066993 if success else 15158332

        duration_ms = result.get("duration_ms", 0)
        duration_sec = duration_ms / 1000.0
        duration_str = f"{duration_sec:.1f}s"

        users = result.get("users_synced", 0)
        libraries = result.get("libraries_synced", 0)
        items = result.get("items_synced", 0)

        description = f"Users: {users} | Libraries: {libraries} | Items: {items}"
        if result.get("errors"):
            description += f"\n {len(result['errors'])} error(s)"

        return {
            "title": title,
            "description": description,
            "color": color,
            "fields": [{"name": "Duration", "value": duration_str, "inline": True}],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _is_discord_enabled(self) -> bool:
        """
        Check if Discord notifications are enabled in settings.

        :returns: True if enabled, False otherwise
        """
        try:
            settings = self._settings_svc.get()
            return settings.get("discord_enabled", False)
        except Exception:
            return False

    def _extract_trigger_config(self) -> Dict[str, bool]:
        """
        Parse the JSON trigger config from the settings service.

        :returns: Mapping of trigger names to bool indicating whether each is enabled.
        """
        try:
            settings = self._settings_svc.get()
            triggers = settings.get("discord_triggers", {})
            if isinstance(triggers, str):
                triggers = json.loads(triggers)
            return triggers if isinstance(triggers, dict) else {}
        except Exception as error:
            logger.exception(f"[ERROR] Failed to extract trigger config: {error}")
            return {}

    def _get_discord_config(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract Discord webhook config from settings.

        :param settings: Settings dict
        :returns: Dict containing webhook_url, username, and avatar_url
        """
        return {
            "webhook_url": settings.get("discord_url"),
            "username": settings.get("discord_username"),
            "avatar_url": settings.get("discord_avatar"),
        }

    def _notify_playback(
        self, settings: Dict[str, Any], session: Dict[str, Any], event: str
    ) -> None:
        """
        Send a playback notification.

        :param settings: Settings dict
        :param session: Jellyfin session object
        :param event: Playback event ("playback_start" or "playback_stop")
        """
        embed = self._build_playback_embed(session, event)
        self._send_webhook(settings, embed)
