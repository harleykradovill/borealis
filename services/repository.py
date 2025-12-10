from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from services.data_models import (
    Base,
    User,
    Library,
    Item,
    PlaybackActivity,
    TaskLog
)


@dataclass
class Repository:
    """
    Data access layer for all Borealis entities.
    """

    database_url: str = "sqlite:///borealis_data.db"

    def __post_init__(self) -> None:
        self.engine = create_engine(self.database_url, future=True)
        self.SessionLocal = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )
        Base.metadata.create_all(self.engine)

    @contextmanager
    def _session(self):
        """Context manager for database sessions with auto-commit."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # Users

    def upsert_users(self, user_dicts: List[Dict[str, Any]]) -> int:
        """
        Upsert users by jellyfin_id. Updates name and admin status.
        """
        if not user_dicts:
            return 0

        count = 0
        now = int(time.time())

        with self._session() as session:
            for data in user_dicts:
                jf_id = data.get("jellyfin_id")
                if not jf_id:
                    continue

                user = session.query(User).filter_by(
                    jellyfin_id=jf_id
                ).first()

                if user:
                    user.name = data.get("name", user.name)
                    user.is_admin = data.get("is_admin", user.is_admin)
                    user.archived = False
                    user.updated_at = now
                else:
                    user = User(
                        jellyfin_id=jf_id,
                        name=data.get("name", "Unknown"),
                        is_admin=data.get("is_admin", False),
                        archived=False,
                        created_at=now,
                        updated_at=now,
                    )

                session.merge(user)
                count += 1

        return count

    def archive_missing_users(
        self, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark users as archived if not in active list.
        """
        if not active_jellyfin_ids:
            return 0

        with self._session() as session:
            result = (
                session.query(User)
                .filter(User.jellyfin_id.notin_(active_jellyfin_ids))
                .filter(User.archived == False)
                .update({"archived": True}, synchronize_session=False)
            )
            return result

    def list_users(
        self, include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all users as dictionaries.
        """
        with self._session() as session:
            query = session.query(User)
            if not include_archived:
                query = query.filter(User.archived == False)
            return [u.to_dict() for u in query.all()]

    # Libraries

    def upsert_libraries(
        self, library_dicts: List[Dict[str, Any]]
    ) -> int:
        """
        Upsert libraries by jellyfin_id.
        """
        if not library_dicts:
            return 0

        count = 0
        now = int(time.time())

        with self._session() as session:
            for data in library_dicts:
                jf_id = data.get("jellyfin_id")
                if not jf_id:
                    continue

                lib = session.query(Library).filter_by(
                    jellyfin_id=jf_id
                ).first()

                if lib:
                    lib.name = data.get("name", lib.name)
                    lib.type = data.get("type", lib.type)
                    lib.image_url = data.get("image_url", lib.image_url)
                    lib.archived = False
                    lib.updated_at = now
                else:
                    lib = Library(
                        jellyfin_id=jf_id,
                        name=data.get("name", "Unknown"),
                        type=data.get("type"),
                        image_url=data.get("image_url"),
                        tracked=False,
                        archived=False,
                        created_at=now,
                        updated_at=now,
                    )

                session.merge(lib)
                count += 1

        return count

    def archive_missing_libraries(
        self, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark libraries as archived if not in active list.
        """
        if not active_jellyfin_ids:
            return 0

        with self._session() as session:
            result = (
                session.query(Library)
                .filter(Library.jellyfin_id.notin_(active_jellyfin_ids))
                .filter(Library.archived == False)
                .update({"archived": True}, synchronize_session=False)
            )
            return result

    def list_libraries(
        self, include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries as dictionaries.
        """
        with self._session() as session:
            query = session.query(Library)
            if not include_archived:
                query = query.filter(Library.archived == False)
            return [lib.to_dict() for lib in query.all()]

    def set_library_tracked(
        self, jellyfin_id: str, tracked: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Update the tracked flag for a library.
        """
        with self._session() as session:
            lib = session.query(Library).filter_by(
                jellyfin_id=jellyfin_id
            ).first()
            if not lib:
                return None

            lib.tracked = bool(tracked)
            session.merge(lib)
            session.commit()
            session.refresh(lib)
            return lib.to_dict()

    # Items

    def upsert_items(self, item_dicts: List[Dict[str, Any]]) -> int:
        """
        Upsert media items by jellyfin_id.
        """
        if not item_dicts:
            return 0

        count = 0
        now = int(time.time())

        with self._session() as session:
            for data in item_dicts:
                jf_id = data.get("jellyfin_id")
                lib_id = data.get("library_id")
                if not jf_id or lib_id is None:
                    continue

                item = session.query(Item).filter_by(
                    jellyfin_id=jf_id
                ).first()

                if item:
                    item.name = data.get("name", item.name)
                    item.type = data.get("type", item.type)
                    item.parent_id = data.get("parent_id", item.parent_id)
                    item.archived = False
                    item.updated_at = now
                else:
                    item = Item(
                        jellyfin_id=jf_id,
                        library_id=lib_id,
                        parent_id=data.get("parent_id"),
                        name=data.get("name", "Unknown"),
                        type=data.get("type"),
                        archived=False,
                        created_at=now,
                        updated_at=now,
                    )

                session.merge(item)
                count += 1

        return count

    def archive_missing_items(
        self, library_id: int, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark items as archived if not in active list for a library.
        """
        if not active_jellyfin_ids:
            return 0

        with self._session() as session:
            result = (
                session.query(Item)
                .filter(Item.library_id == library_id)
                .filter(Item.jellyfin_id.notin_(active_jellyfin_ids))
                .filter(Item.archived == False)
                .update({"archived": True}, synchronize_session=False)
            )
            return result

    # Playback Activity

    def insert_playback_events(
        self, event_dicts: List[Dict[str, Any]]
    ) -> int:
        """
        Insert playback activity records.
        """
        if not event_dicts:
            return 0

        count = 0
        with self._session() as session:
            for data in event_dicts:
                event = PlaybackActivity(
                    user_id=data.get("user_id", ""),
                    item_id=data.get("item_id", ""),
                    device_name=data.get("device_name"),
                    client=data.get("client"),
                    remote_endpoint=data.get("remote_endpoint"),
                    activity_at=data.get("activity_at", int(time.time())),
                    duration_s=data.get("duration_s", 0),
                    username_denorm=data.get("username_denorm"),
                )
                session.add(event)
                count += 1

        return count

    # Task Logging

    def create_task_log(
        self, name: str, task_type: str, execution_type: str
    ) -> int:
        """
        Create a new task log entry with RUNNING status.
        """
        now = int(time.time())
        with self._session() as session:
            task = TaskLog(
                name=name,
                type=task_type,
                execution_type=execution_type,
                started_at=now,
                result="RUNNING",
                duration_ms=0,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task.id

    def complete_task_log(
        self,
        task_id: int,
        result: str,
        log_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark a task log as complete with result.
        """
        import json

        now = int(time.time())
        with self._session() as session:
            task = session.query(TaskLog).filter_by(id=task_id).first()
            if not task:
                return

            task.finished_at = now
            task.duration_ms = (now - task.started_at) * 1000
            task.result = result

            if log_data:
                task.log_json = json.dumps(log_data)

            session.merge(task)