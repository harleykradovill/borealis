import pytest
from unittest.mock import MagicMock
from services.sessions import SessionsService


@pytest.fixture()
def mock_client():
    """
    Mock for the JellyfinClient.

    :returns: MagicMock instance
    """
    return MagicMock()


@pytest.fixture()
def mock_repo():
    """
    Mock for the Repository.

    :returns: MagicMock instance
    """
    return MagicMock()


@pytest.fixture()
def service(mock_client, mock_repo):
    """
    Build a SessionsService with mocked dependencies.

    :returns: SessionsService instance
    """
    return SessionsService(
        jellyfin_client=mock_client,
        repository=mock_repo,
        sync_interval=1,
    )


def test_get_sessions_initial(service: SessionsService) -> None:
    """
    Ensure get_sessions returns an empty list initially.

    :returns: None
    """
    assert service.get_sessions() == []


def test_fetch_sessions_success(service: SessionsService, mock_client) -> None:
    """
    Verify fetch_sessions updates cache with sanitized data on success.

    :returns: None
    """
    mock_client.sessions.return_value = {
        "ok": True,
        "data": [
            {
                "Id": "s1",
                "UserName": "User1",
                "NowPlayingItem": {
                    "Id": "i1",
                    "Name": "Movie 1",
                    "Type": "Movie",
                    "ImageTags": {"Primary": "tag1"},
                    "RunTimeTicks": 1000,
                },
                "Client": "Web",
                "DeviceName": "PC",
                "RemoteEndPoint": "1.2.3.4",
                "PlayState": "Playing",
                "TranscodingInfo": {},
            },
        ],
    }
    service._fetch_sessions()
    sessions = service.get_sessions()
    assert len(sessions) == 1
    assert sessions[0]["UserName"] == "User1"
    assert sessions[0]["NowPlayingItem"]["Name"] == "Movie 1"
    assert sessions[0]["NowPlayingItem"]["PrimaryImageTag"] == "tag1"


def test_fetch_sessions_failure(service: SessionsService, mock_client) -> None:
    """
    Verify fetch_sessions clears cache on API failure.

    :returns: None
    """
    # First set some data to ensure it gets cleared
    service._last_sessions = [{"Id": "s1"}]

    # Mock API failure
    mock_client.sessions.return_value = {"ok": False}
    service._fetch_sessions()
    assert service.get_sessions() == []


def test_fetch_sessions_invalid_data(service: SessionsService, mock_client) -> None:
    """
    Verify fetch_sessions clears cache when data is not a list.

    :returns: None
    """
    service._last_sessions = [{"Id": "s1"}]
    mock_client.sessions.return_value = {"ok": True, "data": "not a list"}
    service._fetch_sessions()
    assert service.get_sessions() == []


def test_fetch_sessions_sorting(service: SessionsService, mock_client) -> None:
    """
    Verify sessions are sorted by UserName then Id.

    :returns: None
    """
    mock_client.sessions.return_value = {
        "ok": True,
        "data": [
            {"Id": "z", "UserName": "B", "NowPlayingItem": {"Id": "i1"}},
            {"Id": "a", "UserName": "A", "NowPlayingItem": {"Id": "i2"}},
            {"Id": "b", "UserName": "B", "NowPlayingItem": {"Id": "i3"}},
        ],
    }
    service._fetch_sessions()
    sessions = service.get_sessions()
    assert sessions[0]["UserName"] == "A"
    assert sessions[1]["Id"] == "b"
    assert sessions[2]["Id"] == "z"


def test_sanitize_sessions_episode_resolution(
    service: SessionsService, mock_repo
) -> None:
    """
    Verify episode series names are resolved via repository.

    :returns: None
    """
    sessions = [
        {
            "Id": "s1",
            "NowPlayingItem": {
                "Id": "e1",
                "Name": "Episode 1",
                "Type": "Episode",
            },
        }
    ]
    mock_repo.get_series_or_item_name.return_value = "Series A"

    sanitized = service._sanitize_sessions(sessions)
    assert sanitized[0]["NowPlayingItem"]["Name"] == "Series A - Episode 1"
    mock_repo.get_series_or_item_name.assert_called_with("e1")


def test_sanitize_sessions_no_repo(mock_client) -> None:
    """
    Verify episode names remain unchanged when no repository is provided.

    :returns: None
    """
    service = SessionsService(jellyfin_client=mock_client, repository=None)
    sessions = [
        {
            "Id": "s1",
            "NowPlayingItem": {
                "Id": "e1",
                "Name": "Episode 1",
                "Type": "Episode",
            },
        }
    ]
    sanitized = service._sanitize_sessions(sessions)
    assert sanitized[0]["NowPlayingItem"]["Name"] == "Episode 1"


def test_sanitize_sessions_non_episode(service: SessionsService, mock_repo) -> None:
    """
    Verify non-episode items do not trigger repository lookup.

    :returns: None
    """
    sessions = [
        {
            "Id": "s1",
            "NowPlayingItem": {
                "Id": "m1",
                "Name": "Movie 1",
                "Type": "Movie",
            },
        }
    ]
    sanitized = service._sanitize_sessions(sessions)
    assert sanitized[0]["NowPlayingItem"]["Name"] == "Movie 1"
    mock_repo.get_series_or_item_name.assert_not_called()


def test_start_stop(service: SessionsService) -> None:
    """
    Verify start and stop manage the background thread.

    :returns: None
    """
    service.start()
    assert service._thread is not None
    assert service._thread.is_alive()
    service.stop()
    assert not service._thread.is_alive()
