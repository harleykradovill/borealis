"""
Settings storage using SQLAlchemy with Fernet encryption for sensitive fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from cryptography.fernet import Fernet, InvalidToken

Base = declarative_base()

@dataclass
class SettingsService:
    database_url: str
    encryption_key_path: str

    def __post_init__(self) -> None:
        self.engine = create_engine(self.database_url, future=True)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        Base.metadata.create_all(self.engine)
        self.fernet = Fernet(self._load_or_create_key())

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """
        Context manager for database sessions with auto-commit.
        """
        session: Session = self.SessionLocal()
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
        Load a Fernet key from disk, or create one if it does not exist.
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
            pass
        return key

    def _get_or_create_row(self, session: Session) -> Settings:
        """
        Retrieve the single Settings row, creating it if missing.
        """
        obj = session.query(Settings).first()
        if obj:
            return obj

        obj = Settings()
        session.add(obj)
        session.flush()
        return obj

    # -------------------------
    # Public API
    # -------------------------

    def get(self) -> Dict[str, Any]:
        """
        Retrieve current settings.
        """
        with self._session() as session:
            settings = self._get_or_create_row(session)
            return settings.to_dict(self.fernet)

    def update(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update settings. Handles encryption for jf_api_key automatically.
        Unknown keys are ignored.
        """
        allowed = {
            "hour_format",
            "language",
            "jf_host",
            "jf_port",
            "jf_api_key",
            "jf_server_name",
            "jf_server_version",
            "sync_interval",
        }
        clean = {k: v for k, v in values.items() if k in allowed}

        with self._session() as session:
            settings = self._get_or_create_row(session)

            if clean.get("hour_format") in {"12", "24"}:
                settings.hour_format = clean["hour_format"]

            if isinstance(clean.get("language"), str):
                settings.language = clean["language"]

            if isinstance(clean.get("jf_host"), str):
                settings.jf_host = clean["jf_host"]

            if isinstance(clean.get("jf_port"), str):
                settings.jf_port = clean["jf_port"]

            if "sync_interval" in clean:
                try:
                    val = int(clean["sync_interval"])
                    if val > 0:
                        settings.sync_interval = val
                except Exception:
                    pass

            if "jf_api_key" in clean:
                api = clean["jf_api_key"]

                # Prevent accidental overwrite with masked value
                if isinstance(api, str) and api == "*" * 32:
                    pass
                elif isinstance(api, str) and api.strip():
                    settings.jf_api_key_encrypted = self.fernet.encrypt(
                        api.encode("utf-8")
                    ).decode("utf-8")
                else:
                    settings.jf_api_key_encrypted = None

            if isinstance(clean.get("jf_server_name"), str):
                settings.jf_server_name = clean["jf_server_name"]

            if isinstance(clean.get("jf_server_version"), str):
                settings.jf_server_version = clean["jf_server_version"]

            return settings.to_dict(self.fernet)

    def set_last_activity_log_sync(self, timestamp: int) -> None:
        """
        Store the timestamp of the last successful activity log sync.
        """
        with self._session() as session:
            settings = self._get_or_create_row(session)
            settings.last_activity_log_sync = int(timestamp)

    def get_last_activity_log_sync(self) -> Optional[int]:
        """
        Retrieve the timestamp of the last successful activity log sync.
        """
        with self._session() as session:
            settings = session.query(Settings).first()
            return settings.last_activity_log_sync if settings else None
