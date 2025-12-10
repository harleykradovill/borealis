"""
Borealis analytics data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    BigInteger,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    """
    Jellyfin user metadata.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    jellyfin_id = Column(String(128), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

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
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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
    archived = Column(Boolean, default=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    items = relationship("Item", back_populates="library")

    __table_args__ = (
        Index("idx_library_jellyfin_id", "jellyfin_id"),
        Index("idx_library_tracked", "tracked"),
        Index("idx_library_archived", "archived"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "jellyfin_id": self.jellyfin_id,
            "name": self.name,
            "type": self.type,
            "image_url": self.image_url,
            "tracked": self.tracked,
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
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
    archived = Column(Boolean, default=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    library = relationship("Library", back_populates="items")

    __table_args__ = (
        Index("idx_item_jellyfin_id", "jellyfin_id"),
        Index("idx_item_library_id", "library_id"),
        Index("idx_item_archived", "archived"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "jellyfin_id": self.jellyfin_id,
            "library_id": self.library_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "type": self.type,
            "archived": self.archived,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PlaybackActivity(Base):
    """
    Individual playback event.
    """
    __tablename__ = "playback_activity"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(128), nullable=False)
    item_id = Column(String(128), nullable=False)
    device_name = Column(String(255), nullable=True)
    client = Column(String(128), nullable=True)
    remote_endpoint = Column(String(255), nullable=True)
    activity_at = Column(BigInteger, nullable=False)
    duration_s = Column(Integer, default=0)
    username_denorm = Column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_playback_user_id", "user_id"),
        Index("idx_playback_item_id", "item_id"),
        Index("idx_playback_activity_at", "activity_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "item_id": self.item_id,
            "device_name": self.device_name,
            "client": self.client,
            "remote_endpoint": self.remote_endpoint,
            "activity_at": self.activity_at,
            "duration_s": self.duration_s,
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
            except Exception:
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