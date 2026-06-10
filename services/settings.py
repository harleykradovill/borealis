"""
Settings storage using SQLAlchemy with Fernet encryption for sensitive fields.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

from services.data_models import Base, Settings

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from typing import Any, Dict, Iterator, Optional


@dataclass
class SettingsService:
    database_url: str
    encryption_key_path: str

    def __post_init__(self) -> None:
        """
        Initialize database engine, session factory, schema, and encryption client.

        :returns: None
        """
        self.engine = create_engine(self.database_url, future=True)
        self.session_local = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        Base.metadata.create_all(self.engine)
        self.fernet = Fernet(self._load_or_create_key())

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """
        Context manager for database sessions with auto-commit.

        :returns: Yields an active SQLAlchemy Session
        :raises Exception: Re-raises any exception after rolling back the session
        """
        session: Session = self.session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _load_or_create_key(self) -> bytes:
        """
        Load a Fernet key from disk, or create one if missing.

        :returns: Fernet key bytes used for encryption and decryption
        """
        if not self.encryption_key_path or self.encryption_key_path == ":memory:":
            return Fernet.generate_key()

        key_file = Path(self.encryption_key_path)
        if key_file.exists():
            return key_file.read_bytes()

        key = Fernet.generate_key()
        try:
            key_file.write_bytes(key)
        except OSError:
            pass  # Key generated in memory, not-fatal failure
        return key

    def _get_or_create_row(self, session: Session) -> Settings:
        """
        Retrieve the single Settings row, creating if missing.

        :param session: Active SQL session
        :returns: Settings model instance
        """
        obj = session.query(Settings).first()
        if obj:
            return obj

        obj = Settings()
        session.add(obj)
        session.flush()
        return obj

    def get(self) -> Dict[str, Any]:
        """
        Retrieve current settings.

        :returns: settings dict including decrypted values when available
        :raises InvalidToken: if stored encrypted data cannot be decrypted with the key
        """
        with self._session() as session:
            settings = self._get_or_create_row(session)
            return settings.to_dict(self.fernet)

    def update(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update settings with provided values.

        :param values: partial settings payload to persist
        :returns: updated settings dict including decrypted values
        :raises ValueError: if sync_interval cannot be converted to int
        :raises TypeError: if sync_interval has an invalid type for int conversion
        :raises InvalidToken: if encrypted data cannot be decrypted
        """
        with self._session() as session:
            settings = self._get_or_create_row(session)

            if "hour_format" in values:
                settings.hour_format = str(values["hour_format"])
            if "language" in values:
                settings.language = str(values["language"])
            if "jf_host" in values:
                settings.jf_host = str(values["jf_host"])
            if "jf_port" in values:
                settings.jf_port = str(values["jf_port"])
            if "jf_api_key" in values:
                key = values["jf_api_key"]
                settings.jf_api_key_encrypted = (
                    self.fernet.encrypt(key.encode("utf-8")).decode("utf-8")
                    if key
                    else None
                )
            if "jf_server_name" in values:
                settings.jf_server_name = values["jf_server_name"]
            if "jf_server_version" in values:
                settings.jf_server_version = values["jf_server_version"]
            if "sync_interval" in values:
                settings.sync_interval = int(values["sync_interval"])

            return settings.to_dict(self.fernet)

    def set_last_activity_log_sync(self, timestamp: int) -> None:
        """
        Store the timestamp of the last successful activity log sync.

        :param timestamp: unix timestamp to persist
        :returns: None
        :raises ValueError: if timestamp cannot be converted to int
        :raises TypeError: if timestamp has an invalid type
        """
        with self._session() as session:
            settings = self._get_or_create_row(session)
            settings.last_activity_log_sync = int(timestamp)

    def get_last_activity_log_sync(self) -> Optional[int]:
        """
        Retrieve the timestamp of the last successful activity log sync.

        :returns: stored unix timestamp or None when not set yet
        """
        with self._session() as session:
            settings = session.query(Settings).first()
            return settings.last_activity_log_sync if settings else None
