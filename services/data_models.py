"""
Borealis analytics data.
"""

from __future__ import annotations
from typing import Dict, Any, Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    BigInteger,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship
from cryptography.fernet import Fernet, InvalidToken

Base = declarative_base()

class User(Base):
    """
    Jellyfin user account.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    jellyfin_id = Column(String(128), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    last_watched_item_name = Column(String(512), nullable=True)
    last_device = Column(String(255), nullable=True)
    total_plays = Column(Integer, default=0)
    total_watch_time_seconds = Column(Integer, default=0)
    last_seen_at = Column(BigInteger, nullable=True)
    archived = Column(Boolean, default=False)

    __table_args__ = (
        Index("idx_user_jellyfin_id", "jellyfin_id"),
        Index("idx_user_archived", "archived"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "jellyfin_id": self.jellyfin_id,
            "name": self.name,
            "is_admin": self.is_admin,
            "last_watched_item_name": self.last_watched_item_name,
            "last_device": self.last_device,
            "total_plays": self.total_plays,
            "total_watch_time_seconds": self.total_watch_time_seconds,
            "last_seen_at": self.last_seen_at,
        }


class Library(Base):
    """
    Jellyfin library/media folder.
    """
    __tablename__ = "libraries"

    id = Column(Integer, primary_key=True)
    jellyfin_id = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    type = Column(String(64), nullable=True)
    image_url = Column(String(1024), nullable=True)
    tracked = Column(Boolean, default=False)
    total_plays = Column(Integer, default=0)
    archived = Column(Boolean, default=False)
    total_time_seconds = Column(BigInteger, default=0)
    total_files = Column(Integer, default=0)
    size_bytes = Column(BigInteger, default=0)
    total_playback_seconds = Column(BigInteger, default=0)
    last_played_item_name = Column(String(512), nullable=True)

    items = relationship("Item", back_populates="library")

    __table_args__ = (
        Index("idx_library_jellyfin_id", "jellyfin_id"),
        Index("idx_library_archived", "archived"),
        Index("idx_library_total_plays", "total_plays"),
        Index("idx_library_total_time_seconds", "total_time_seconds"),
        Index("idx_library_size_bytes", "size_bytes"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "jellyfin_id": self.jellyfin_id,
            "name": self.name,
            "type": self.type,
            "image_url": self.image_url,
            "tracked": self.tracked,
            "total_plays": self.total_plays,
            "total_time_seconds": self.total_time_seconds,
            "total_files": self.total_files,
            "size_bytes": self.size_bytes,
            "total_playback_seconds": self.total_playback_seconds,
            "last_played_item_name": self.last_played_item_name,
            "archived": self.archived,
        }


class Item(Base):
    """
    Individual media items.
    """
    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    jellyfin_id = Column(String(128), nullable=False, unique=True)
    library_id = Column(
        Integer,
        ForeignKey("libraries.id", ondelete="CASCADE"),
        nullable=False
    )
    parent_id = Column(String(128), nullable=True)
    name = Column(String(512), nullable=False)
    type = Column(String(64), nullable=True)
    play_count = Column(Integer, default=0)
    archived = Column(Boolean, default=False)
    runtime_seconds = Column(Integer, default=0)
    size_bytes = Column(BigInteger, default=0)
    date_created = Column(BigInteger, nullable=True)

    library = relationship("Library", back_populates="items")

    __table_args__ = (
        Index("idx_item_jellyfin_id", "jellyfin_id"),
        Index("idx_item_library_id", "library_id"),
        Index("idx_item_archived", "archived"),
        Index("idx_item_play_count", "play_count"),
        Index("idx_item_runtime_seconds", "runtime_seconds"),
        Index("idx_item_size_bytes", "size_bytes"),
        Index("idx_date_created", "date_created")
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "jellyfin_id": self.jellyfin_id,
            "library_id": self.library_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "type": self.type,
            "play_count": self.play_count,
            "runtime_seconds": self.runtime_seconds,
            "size_bytes": self.size_bytes,
            "archived": self.archived,
            "date_created": self.date_created,
        }


class PlaybackActivity(Base):
    """
    Individual playback event.
    """
    __tablename__ = "playback_activity"

    id = Column(Integer, primary_key=True)
    activity_log_id = Column(
        Integer,
        nullable=False,
        unique=True
    )
    user_id = Column(String(128), nullable=False)
    item_id = Column(String(128), nullable=False)
    event_name = Column(String(512), nullable=True)
    activity_at = Column(BigInteger, nullable=False)
    username_denorm = Column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_playback_activity_log_id", "activity_log_id"),
        Index("idx_playback_user_id", "user_id"),
        Index("idx_playback_item_id", "item_id"),
        Index("idx_playback_activity_at", "activity_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to dictionary for API responses.
        """
        return {
            "id": self.id,
            "activity_log_id": self.activity_log_id,
            "user_id": self.user_id,
            "item_id": self.item_id,
            "event_name": self.event_name,
            "activity_at": self.activity_at,
            "username_denorm": self.username_denorm,
        }


class TaskLog(Base):
    """
    Records sync operations and other background tasks.
    """
    __tablename__ = "task_logging"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(String(64), nullable=False)
    execution_type = Column(String(32), nullable=False)
    duration_ms = Column(Integer, default=0)
    started_at = Column(BigInteger, nullable=False)
    finished_at = Column(BigInteger, nullable=True)
    result = Column(String(32), nullable=False)
    log_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_task_started_at", "started_at"),
        Index("idx_task_result", "result"),
    )

    def to_dict(self) -> Dict[str, Any]:
        import json
        log_data = None
        if self.log_json:
            try:
                log_data = json.loads(self.log_json)
            except json.JSONDecodeError:
                log_data = self.log_json

        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "execution_type": self.execution_type,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "log": log_data,
        }
    
class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    hour_format = Column(String(4), default="12")
    language = Column(String(8), default="en")
    jf_host = Column(String(255), default="127.0.0.1")
    jf_port = Column(String(8), default="8096")
    jf_api_key_encrypted = Column(String(4096), nullable=True)
    jf_server_name = Column(String(4096), nullable=True)
    jf_server_version = Column(String(4096), nullable=True)
    last_activity_log_sync = Column(Integer, nullable=True)
    sync_interval = Column(Integer, default=1800)

    def to_dict(self, fernet: Optional[Fernet] = None) -> Dict[str, Any]:
        """
        Convert to dict. If fernet provided, decrypt jf_api_key.
        """
        api_key_plain = None

        if fernet and self.jf_api_key_encrypted:
            try:
                api_key_plain = fernet.decrypt(
                    self.jf_api_key_encrypted.encode("utf-8")
                ).decode("utf-8")
            except InvalidToken:
                api_key_plain = None

        return {
            "hour_format": self.hour_format,
            "language": self.language,
            "jf_host": self.jf_host,
            "jf_port": self.jf_port,
            "jf_api_key": api_key_plain,
            "jf_server_name": self.jf_server_name,
            "jf_server_version": self.jf_server_version,
            "sync_interval": self.sync_interval,
        }