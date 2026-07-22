import pytest
from unittest.mock import MagicMock, patch
from services.discord_notifications import DiscordNotificationService


@pytest.fixture()
def mock_settings_svc():
    """
    Mock for the SettingsService.

    :returns: MagicMock instance
    """
    return MagicMock()


@pytest.fixture()
def mock_jellyfin_client():
    """
    Mock for the JellyfinClient.

    :returns: MagicMock instance
    """
    return MagicMock()


@pytest.fixture()
def mock_sync_svc():
    """
    Mock for the SyncService.

    :returns: MagicMock instance
    """
    return MagicMock()


@pytest.fixture()
def mock_scheduler():
    """
    Mock for the sync scheduler.

    :returns: MagicMock instance
    """
    return MagicMock()


@pytest.fixture()
def service(mock_settings_svc, mock_jellyfin_client, mock_sync_svc, mock_scheduler):
    """
    Build a DiscordNotificationService with mocked dependencies.

    :returns: DiscordNotificationService instance
    """
    return DiscordNotificationService(
        svc=mock_settings_svc,
        jellyfin_client=mock_jellyfin_client,
        sync=mock_sync_svc,
        scheduler=mock_scheduler,
        poll_interval=1,
    )


def test_start_starts_thread(service: DiscordNotificationService) -> None:
    """
    Verify start creates and starts a daemon thread.

    :returns: None
    """
    service.start()
    assert service._thread is not None
    assert service._thread.is_alive()
    assert service._thread.daemon is True
    service.stop()


def test_stop_terminates_thread(service: DiscordNotificationService) -> None:
    """
    Verify stop signals the event and joins the thread.

    :returns: None
    """
    service.start()
    service.stop()
    assert not service._thread.is_alive()
    assert service._stop_event.is_set()


def test_should_notify_returns_true_when_enabled() -> None:
    """
    Verify _should_notify returns True when the trigger is enabled.

    :returns: None
    """
    settings = {"discord_triggers": {"playback_start": True}}
    svc = DiscordNotificationService(
        svc=MagicMock(),
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    assert svc._should_notify(settings, "playback_start") is True


def test_should_notify_returns_false_when_disabled() -> None:
    """
    Verify _should_notify returns False when the trigger is disabled.

    :returns: None
    """
    settings = {"discord_triggers": {"playback_start": False}}
    svc = DiscordNotificationService(
        svc=MagicMock(),
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    assert svc._should_notify(settings, "playback_start") is False


def test_should_notify_parses_json_string() -> None:
    """
    Verify _should_notify handles triggers stored as a JSON string.

    :returns: None
    """
    settings = {"discord_triggers": '{"playback_start": true}'}
    svc = DiscordNotificationService(
        svc=MagicMock(),
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    assert svc._should_notify(settings, "playback_start") is True


def test_build_playback_embed_defaults_for_missing_fields() -> None:
    """
    Verify embed uses fallback values when session fields are missing.

    :returns: None
    """
    svc = DiscordNotificationService(
        svc=MagicMock(),
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    embed = svc._build_playback_embed({}, "playback_start")
    assert embed["fields"][0] == {"name": "User", "value": "Unknown User"}
    assert embed["fields"][1] == {"name": "Item", "value": "Unknown Item"}


def test_build_sync_embed_defaults_for_missing_fields() -> None:
    """
    Verify sync embed handles missing result fields gracefully.

    :returns: None
    """
    svc = DiscordNotificationService(
        svc=MagicMock(),
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    embed = svc._build_sync_embed({})
    assert embed["title"] == "Sync Failed"
    assert embed["fields"][0]["value"] == "0.0s"


def test_get_discord_config_extracts_fields() -> None:
    """
    Verify _get_discord_config extracts webhook_url, username, avatar_url.

    :returns: None
    """
    settings = {
        "discord_url": "https://discord.com/webhook/abc",
        "discord_username": "Borealis Bot",
        "discord_avatar": "https://example.com/avatar.png",
    }
    svc = DiscordNotificationService(
        svc=MagicMock(),
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    config = svc._get_discord_config(settings)
    assert config["webhook_url"] == "https://discord.com/webhook/abc"
    assert config["username"] == "Borealis Bot"
    assert config["avatar_url"] == "https://example.com/avatar.png"


def test_extract_trigger_config_dict(mock_settings_svc) -> None:
    """
    Verify _extract_trigger_config returns dict when triggers is a dict.

    :returns: None
    """
    mock_settings_svc.get.return_value = {"discord_triggers": {"playback_start": True}}
    svc = DiscordNotificationService(
        svc=mock_settings_svc,
        jellyfin_client=MagicMock(),
        sync=MagicMock(),
        scheduler=MagicMock(),
    )
    assert svc._extract_trigger_config() == {"playback_start": True}


def test_check_playback_changes_detects_start(
    service: DiscordNotificationService, mock_jellyfin_client, mock_settings_svc
) -> None:
    """
    Verify a new session triggers a playback_start notification.

    :returns: None
    """
    mock_settings_svc.get.return_value = {"discord_triggers": {"playback_start": True}}
    mock_jellyfin_client.sessions.return_value = {
        "ok": True,
        "data": [
            {
                "UserId": "u1",
                "UserName": "Alice",
                "NowPlayingItem": {"Id": "i1", "Name": "Movie"},
            }
        ],
    }

    with patch.object(service, "_notify_playback") as mock_notify:
        service._check_playback_changes({"discord_triggers": {"playback_start": True}})
        mock_notify.assert_called_once()
        args = mock_notify.call_args[0]
        assert args[2] == "playback_start"


def test_check_playback_changes_detects_stop(
    service: DiscordNotificationService, mock_jellyfin_client
) -> None:
    """
    Verify a removed session triggers a playback_stop notification.

    :returns: None
    """
    service._last_sessions = {
        ("u1", "i1"): {
            "UserId": "u1",
            "UserName": "Alice",
            "NowPlayingItem": {"Id": "i1", "Name": "Movie"},
        }
    }
    mock_jellyfin_client.sessions.return_value = {"ok": True, "data": []}

    with patch.object(service, "_notify_playback") as mock_notify:
        service._check_playback_changes({"discord_triggers": {"playback_stop": True}})
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][2] == "playback_stop"
