from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from services.settings_store import SettingsService


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> str:
    """
    Create a temporary SQLite database file path.

    :returns: SQLite file path as a string
    """
    return str(tmp_path / "settings_test.db")


@pytest.fixture()
def temp_key_path(tmp_path: Path) -> str:
    """
    Create a temporary key file path.

    :returns: key file path as a string
    """
    return str(tmp_path / "settings_test.key")


@pytest.fixture()
def service(temp_db_path: str, temp_key_path: str) -> SettingsService:
    """
    Build a SettingsService for a temp DB and key path.

    :returns: SettingsService instance
    """
    return SettingsService(
        database_url=f"sqlite:///{temp_db_path}",
        encryption_key_path=temp_key_path,
    )


def test_get_creates_row(service: SettingsService) -> None:
    """
    Ensure get() creates a row and returns a dict.

    :returns: None
    """
    settings = service.get()
    assert isinstance(settings, dict)


def test_update_persists_plain_fields(service: SettingsService) -> None:
    """
    Verify plain settings fields are persisted.

    :returns: None
    """
    updated = service.update(
        {
            "hour_format": "24",
            "language": "en",
            "jf_host": "localhost",
            "jf_port": "8096",
            "jf_server_name": "Test Server",
            "jf_server_version": "10.9.0",
            "sync_interval": 120,
        }
    )
    assert updated["hour_format"] == "24"
    assert updated["language"] == "en"
    assert updated["jf_host"] == "localhost"
    assert updated["jf_port"] == "8096"
    assert updated["jf_server_name"] == "Test Server"
    assert updated["jf_server_version"] == "10.9.0"
    assert updated["sync_interval"] == 120


def test_update_encrypts_and_decrypts_api_key(
    service: SettingsService,
) -> None:
    """
    Verify jf_api_key is encrypted at rest and decrypted on read.

    :returns: None
    """
    service.update({"jf_api_key": "secret"})
    fetched = service.get()
    assert fetched["jf_api_key"] == "secret"


def test_update_clears_api_key(service: SettingsService) -> None:
    """
    Verify jf_api_key can be cleared.

    :returns: None
    """
    service.update({"jf_api_key": "secret"})
    service.update({"jf_api_key": ""})
    fetched = service.get()
    assert fetched["jf_api_key"] in ("", None)


def test_last_activity_log_sync_roundtrip(
    service: SettingsService,
) -> None:
    """
    Verify last_activity_log_sync persists and returns.

    :returns: None
    """
    service.set_last_activity_log_sync(1700000000)
    assert service.get_last_activity_log_sync() == 1700000000


def test_load_or_create_key_creates_file(temp_db_path: str, temp_key_path: str) -> None:
    """
    Verify a key file is created when missing.

    :returns: None
    """
    key_file = Path(temp_key_path)
    assert not key_file.exists()
    SettingsService(
        database_url=f"sqlite:///{temp_db_path}",
        encryption_key_path=temp_key_path,
    )
    assert key_file.exists()
    assert key_file.read_bytes()


def test_in_memory_key_does_not_touch_disk(temp_db_path: str, tmp_path: Path) -> None:
    """
    Verify :memory: skips writing key file.

    :returns: None
    """
    key_path = tmp_path / "should_not_exist.key"
    SettingsService(
        database_url=f"sqlite:///{temp_db_path}",
        encryption_key_path=":memory:",
    )
    assert not key_path.exists()


def test_invalid_token_returns_none(temp_db_path: str, temp_key_path: str) -> None:
    """
    Verify invalid token returns None for jf_api_key.

    :returns: None
    """
    service_a = SettingsService(
        database_url=f"sqlite:///{temp_db_path}",
        encryption_key_path=temp_key_path,
    )
    service_a.update({"jf_api_key": "secret"})

    other_key_path = str(Path(temp_key_path).with_suffix(".other"))
    Path(other_key_path).write_bytes(Fernet.generate_key())
    service_b = SettingsService(
        database_url=f"sqlite:///{temp_db_path}",
        encryption_key_path=other_key_path,
    )

    fetched = service_b.get()
    assert fetched["jf_api_key"] is None
