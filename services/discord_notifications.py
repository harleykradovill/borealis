"""
Service that communicates with Discord webhooks to send notifications
about Jellyfin and Borealis itself.
"""

from typing import Any, Dict, List, Optional


def _is_playback_trigger_enabled(trigger_name: str) -> bool:
    """
    Check if a specific playback trigger is enabled in settings.

    :param trigger_name: Name of the trigger to check
    :returns: True if trigger is enabled, False otherwise
    """
    pass


def _extract_trigger_config() -> Dict[str, bool]:
    """
    Parse the JSON trigger config from the settings service.

    :returns: Mapping of trigger names to bool indicating whether each is enabled.
    """
    pass


def _get_discord_config() -> Dict[str, Any]:
    """
    Extract Discord webhook config (URL, username, avatar url) from settings.

    :returns: Dict containing webhook_url, username, and avatar_url
    """
    pass


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
        poll_interval: int = 5,
    ) -> None:
        """
        Initialize the Discord notification service.

        :param svc: SettingsService instance
        :param jellyfin_client: Client used to query Jellyfin for session data
        :param sync: SyncService instance
        :param poll_interval: How often to poll Jellyfin in seconds
        """
        pass

    def start(self) -> None:
        """
        Start the background polling thread.

        :returns: None
        """
        pass

    def stop(self) -> None:
        """
        Stop the background polling thread and clean up resources.

        :returns: None
        """
        pass

    def _poll_loop(self) -> None:
        """
        Main loop to call _check_playback_changes and sleep for poll_interval.

        :returns: None
        """
        pass

    def _check_playback_changes(self) -> None:
        """
        Compare the current Jellyfin sessions with _last_sessions to detect
        start/stop transitions, then trigger Discord notifications as needed.

        :returns: None
        """
        pass

    def _send_webhook(self, embed_dict: Dict[str, Any]) -> None:
        """
        Send a Discord webhook payload containing the supplied embed.

        :param embed_dict: Dict representing a Discord embed object
        """
        pass

    def _should_notify_playback(self, event_type: str) -> bool:
        """
        Determine whether a playback even of the given type should generate a notification.

        :param event_type: Playback even identifier ("play", "pause", "stop")
        :returns: True if the event is enabled, False otherwise
        """
        pass

    def _should_notify_sync(self, sync_type: str) -> bool:
        """
        Determine whether a sync completion event of the given type should generate a notification.

        :param sync_type: Sync event identifier ("full", "periodic")
        :returns: True if the sync type is enabled, False otherwise
        """
        pass

    def _build_playback_embed(
        self, user: Any, item: Any, event_type: str
    ) -> Dict[str, Any]:
        """
        Build a discord embed dict describing a playback event.

        :param user: Jellyfin user object
        :param item: Media item associated with event
        :param event_type: Type of playback event ("play", "stop", "pause")
        :returns: Dict ready to be sent as a Discord embed
        """
        pass

    def _build_sync_embed(self, result: Any) -> Dict[str, Any]:
        """
        Build a Discord embed dictionary describing a sync result.

        :param result: Object containing sync outcome
        :returns: Dict ready to be sent as a Discord embed
        """
        pass

    _last_sessions: List[Any] = []
