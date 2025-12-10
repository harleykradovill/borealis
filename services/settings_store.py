"""
Settings storage using SQLAlchemy with Fernet encryption for sensitive fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from cryptography.fernet import Fernet, InvalidToken

Base = declarative_base()


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    hour_format = Column(String(4), default="24")
    language = Column(String(8), default="en")
    jf_host = Column(String(255), default="127.0.0.1")
    jf_port = Column(String(8), default="8096")
    jf_api_key_encrypted = Column(String(4096), nullable=True)

    def to_dict(self, fernet: Optional[Fernet] = None) -> Dict[str, Any]:
        """
        Convert to dict. If fernet provided, decrypt jf_api_key.
        """
        api_key_plain = None
        if fernet and self.jf_api_key_encrypted:
            try:
                api_key_plain = (
                    fernet.decrypt(self.jf_api_key_encrypted.encode("utf-8"))
                    .decode("utf-8")
                )
            except InvalidToken:
                api_key_plain = None

        return {
            "hour_format": self.hour_format,
            "language": self.language,
            "jf_host": self.jf_host,
            "jf_port": self.jf_port,
            "jf_api_key": api_key_plain,
        }


@dataclass
class SettingsService:
    database_url: str
    encryption_key_path: str

    def __post_init__(self) -> None:
        self.engine = create_engine(self.database_url, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self.fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        """
        Load a Fernet key from disk, or create one if it does not exist.
        """
        key_path = self.encryption_key_path
        if key_path == ":memory:" or not key_path:
            return Fernet.generate_key()

        key_file = Path(key_path)
        if key_file.exists():
            return key_file.read_bytes()
        key = Fernet.generate_key()
        try:
            key_file.write_bytes(key)
        except Exception:
            pass
        return key

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
        allowed = {"hour_format", "language", "jf_host", "jf_port", "jf_api_key"}
        clean: Dict[str, Any] = {k: v for k, v in values.items() if k in allowed}

        with self._session() as session:
            settings = self._get_or_create_row(session)
            if "hour_format" in clean and clean["hour_format"] in {"12", "24"}:
                settings.hour_format = clean["hour_format"]
            if "language" in clean and isinstance(clean["language"], str):
                settings.language = clean["language"]
            if "jf_host" in clean and isinstance(clean["jf_host"], str):
                settings.jf_host = clean["jf_host"]
            if "jf_port" in clean and isinstance(clean["jf_port"], str):
                settings.jf_port = clean["jf_port"]

            if "jf_api_key" in clean:
                api = clean["jf_api_key"]

                # Prevent accidental overwrite with masked asterisks
                if isinstance(api, str) and api == "*" * 32:
                    pass
                elif isinstance(api, str) and api.strip():
                    ciphertext = self.fernet.encrypt(api.encode("utf-8")).decode("utf-8")
                    settings.jf_api_key_encrypted = ciphertext
                else:
                    settings.jf_api_key_encrypted = None

            session.add(settings)
            session.commit()
            session.refresh(settings)
            return settings.to_dict(self.fernet)

    def _session(self) -> Session:
        return self.SessionLocal()

    def _get_or_create_row(self, session: Session) -> Settings:
        obj = session.query(Settings).first()
        if obj:
            return obj
        obj = Settings()
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj