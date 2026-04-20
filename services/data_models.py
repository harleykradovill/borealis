"""
Borealis analytics data.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

from typing import Any, Dict, Optional

Base = declarative_base()

class User(Base):
    """
    Persisted Jellyfin user account and aggregate viewing statistics.
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
        """
        Serialize the user record for API responses.

        :returns: Dictionary containing user ID, role, playback totals, and last seen
        """
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
    Persisted Jellyfin library with playback, file, and storage aggregates.
    """
    __tablename__ = "libraries"

    id = Column(Integer, primary_key=True)
    jellyfin_id = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    type = Column(String(64), nullable=True)
    image_url = Column(String(1024), nullable=True)
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
        """
        Serialize the library record for API responses.

        :returns: Dictionary containing library ID, media totals, playback totals, storage size, and archive state
        """
        return {
            "id": self.id,
            "jellyfin_id": self.jellyfin_id,
            "name": self.name,
            "type": self.type,
            "image_url": self.image_url,
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
    Persisted Jellyfin media items linked to a parent library.
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
        """
        Serialize the media item record for API responses.

        :returns: Dictionary containing item ID, library iD, playback stats, runtime, size, and archive state
        """
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
    Persisted playback activity event sourced from the Jellyfin activity log.
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
        Serialize a playback activity event for API responses.

        :returns: Dictionary containing log ID, user & item ID, event name, timestamp, and username
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
    Persisted background task execution record for sync and maintenance jobs.
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
        """
        Serialize a task log entry for API responses.

        :returns: Dictionary containing task metadata, timing, result, and log payload
        """
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
    """
    Persisted Borealis application and Jellyfin connection settings.
    """
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
        Serialize settings values and optionally decrypt the API key.

        :param fernet: Optional fernet instance used to decrypt stored Jellyfin API key
        :returns: Dictionary containing general settings, Jellyfin settings and metadata, and sync interval
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
    
class DashboardStat(Base):
    """
    Persisted cached dashboard section payload and last update timestamp.
    """
    __tablename__ = "dashboard_stats"

    id = Column(Integer, primary_key=True)
    section_key = Column(String(64), nullable=False, unique=True)
    payload_json = Column(Text, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index("idx_dashboard_stats_section_key", "section_key"),
        Index("idx_dashboard_stats_updated_at", "updated_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize a dashboard statistics section for API responses.

        :returns: Dictionary containing section key, payload list, and last update timestamp
        """
        payload = []
        try:
            payload = json.loads(self.payload_json) if self.payload_json else []
        except json.JSONDecodeError:
            payload = []

        return {
            "id": self.id,
            "section_key": self.section_key,
            "payload": payload,
            "updated_at": self.updated_at,
        }