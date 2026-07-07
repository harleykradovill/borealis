"""
Database repository layer for Borealis. Provides 'Repository' class which manages
SQLAlchemy sessions and migrations, and offers upsert/list/archive helpers for users,
libraries, and items.
"""

from __future__ import annotations

import json
import logging
import time

from contextlib import contextmanager
from dataclasses import dataclass

from services.data_models import (
    Base,
    Statistics,
    Item,
    Library,
    PlaybackActivity,
    TaskLog,
    User,
)
from services.sync_aggregator import StatsAggregator

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# -------------------------
# Helpers
# -------------------------


def _now() -> int:
    """
    Return current Unix timestamp in seconds.

    :returns: Current time as integer seconds since epoch
    """
    return int(time.time())


def _safe_int(value: Any, default: int = 0) -> int:
    """
    Safely coerce a value to int, returning default on failure.

    :param value: Value to convert to integer
    :param default: Default integer to return if conversion fails (default 0)
    :returns: Converted integer or default value
    """
    try:
        return int(value)
    except Exception:
        return default


def _load_existing_by_key(
    session: Session,
    model,
    key_field,
    keys: List[Any],
) -> Dict[Any, Any]:
    """
    Load existing ORM rows keyed by a specific column.

    :param session: Active SQL session
    :param model: SQLAlchemy model class to query
    :param key_field: Column field to use as dictionary key
    :param keys: List of values to filter rows by
    :returns: Dictionary mapping key values to ORM row instances
    """
    if not keys:
        return {}

    rows = session.query(model).filter(key_field.in_(keys)).all()
    return {getattr(r, key_field.key): r for r in rows}


@dataclass
class Repository:
    database_url: str = "sqlite:///borealis.db"

    def __post_init__(self) -> None:
        """
        Initialize database engine and session factory, creating all tables.

        :returns: None
        """
        self.engine = create_engine(self.database_url, future=True)
        self.session_local = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def _session(self):
        """
        Context manager for database sessions with auto-commit.

        :returns: Session context that auto-commits on success or rolls back on exceptions
        """
        session: Session = self.session_local()
        try:
            yield session
            session.commit()
        except Exception as error:
            session.rollback()
            logger.exception(f"[ERROR] Database operation failed: {error}")
            raise
        finally:
            session.close()

    # -------------------------
    # Users
    # -------------------------

    def upsert_users(self, user_dicts: List[Dict[str, Any]]) -> int:
        """
        Upsert users by jellyfin_id, updating name and admin status.

        :param user_dicts: List of user data dictionaries with jellyfin_id, name, is_admin
        :returns: Count of users processed
        """
        if not user_dicts:
            return 0

        try:
            with self._session() as session:
                existing = _load_existing_by_key(
                    session,
                    User,
                    User.jellyfin_id,
                    [d.get("jellyfin_id") for d in user_dicts if d.get("jellyfin_id")],
                )

                processed = 0
                for data in user_dicts:
                    jf_id = data.get("jellyfin_id")
                    if not jf_id:
                        continue

                    user = existing.get(jf_id)
                    if user:
                        user.name = data.get("name", user.name)
                        user.is_admin = data.get("is_admin", user.is_admin)
                        user.image_url = data.get("image_url", user.image_url)
                        user.archived = False
                    else:
                        user = User(
                            jellyfin_id=jf_id,
                            name=data.get("name", "Unknown"),
                            is_admin=data.get("is_admin", False),
                            image_url=data.get("image_url"),
                            archived=False,
                        )
                        session.add(user)

                    processed += 1

                return processed
        except Exception as error:
            logger.exception(f"[ERROR] Failed to upsert users: {error}")
            raise

    def archive_missing_users(self, active_jellyfin_ids: List[str]) -> int:
        """
        Mark users as archived if not in active list.

        :param active_jellyfin_ids: List of active Jellyfin user IDs
        :returns: Count of users marked as archived
        """
        if not active_jellyfin_ids:
            return 0

        with self._session() as session:
            return (
                session.query(User)
                .filter(User.jellyfin_id.notin_(active_jellyfin_ids))
                .filter(User.archived.is_(False))
                .update({"archived": True}, synchronize_session=False)
            )

    def get_user_by_jellyfin_id(self, jellyfin_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single user by Jellyfin ID.

        :param jellyfin_id: The Jellyfin user ID to look up
        :returns: User dictionary with id, jellyfin_id, name, is_admin, image_url, archived, and stats; or None if not found
        """
        if not jellyfin_id:
            return None

        with self._session() as session:
            user = (
                session.query(User)
                .filter(
                    User.jellyfin_id == jellyfin_id,
                    User.archived.is_(False),
                )
                .first()
            )

            if not user:
                return None

            return {
                "id": user.id,
                "jellyfin_id": user.jellyfin_id,
                "name": user.name,
                "is_admin": user.is_admin,
                "image_url": user.image_url,
                "archived": False,
                "total_plays": user.total_plays,
                "total_watch_time_seconds": user.total_watch_time_seconds,
                "last_device": user.last_device,
                "last_seen_at": user.last_seen_at,
            }

    def list_users(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieve all users as dictionaries.

        :param include_archived: Whether to include archived users (default False)
        :returns: List of user dicts with id, jellyfin_id, name, is_admin, and stats
        """
        with self._session() as session:
            query = session.query(User)
            if not include_archived:
                query = query.filter(User.archived.is_(False))
            return [u.to_dict() for u in query.all()]

    # -------------------------
    # Libraries
    # -------------------------

    def upsert_libraries(self, library_dicts: List[Dict[str, Any]]) -> int:
        """
        Upsert libraries by jellyfin_id.

        :param library_dicts: List of library data dicts with jellyfin_id, name, type, image_url
        :returns: Count of libraries processed
        """
        if not library_dicts:
            return 0

        try:
            with self._session() as session:
                existing = _load_existing_by_key(
                    session,
                    Library,
                    Library.jellyfin_id,
                    [
                        d.get("jellyfin_id")
                        for d in library_dicts
                        if d.get("jellyfin_id")
                    ],
                )

                processed = 0
                for data in library_dicts:
                    jf_id = data.get("jellyfin_id")
                    if not jf_id:
                        continue

                    lib = existing.get(jf_id)
                    if lib:
                        lib.name = data.get("name", lib.name)
                        lib.type = data.get("type", lib.type)
                        lib.image_url = data.get("image_url", lib.image_url)
                        lib.archived = False
                    else:
                        session.add(
                            Library(
                                jellyfin_id=jf_id,
                                name=data.get("name", "Unknown"),
                                type=data.get("type"),
                                image_url=data.get("image_url"),
                                archived=False,
                            )
                        )

                    processed += 1

                return processed
        except Exception as error:
            logger.exception(f"[ERROR] Failed to upsert libraries: {error}")
            raise

    def archive_missing_libraries(self, active_jellyfin_ids: List[str]) -> int:
        """
        Mark libraries as archived if not in active list.

        :param active_jellyfin_ids: List of active Jellyfin library ids
        :returns: Count of libraries marked as archived
        """
        if not active_jellyfin_ids:
            return 0

        with self._session() as session:
            return (
                session.query(Library)
                .filter(Library.jellyfin_id.notin_(active_jellyfin_ids))
                .filter(Library.archived.is_(False))
                .update({"archived": True}, synchronize_session=False)
            )

    def list_libraries(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries as dictionaries.

        :param include_archived: Whether to include archived libraries (default False)
        :returns: List of library dicts with all metadata
        """
        with self._session() as session:
            query = session.query(Library)
            if not include_archived:
                query = query.filter(Library.archived.is_(False))
            return [l.to_dict() for l in query.all()]

    # -------------------------
    # Items
    # -------------------------

    def upsert_items(self, item_dicts: List[Dict[str, Any]]) -> int:
        """
        Upsert media items by jellyfin_id.

        :param item_dicts: List of item data dicts with jellyfin_id, library_id, name, type, runtime_seconds, size_bytes
        :returns: Count of items processed
        """
        if not item_dicts:
            return 0

        try:
            with self._session() as session:
                existing = _load_existing_by_key(
                    session,
                    Item,
                    Item.jellyfin_id,
                    [d.get("jellyfin_id") for d in item_dicts if d.get("jellyfin_id")],
                )

                processed = 0
                for data in item_dicts:
                    jf_id = data.get("jellyfin_id")
                    if not jf_id:
                        continue

                    item = existing.get(jf_id)
                    if item:
                        item.parent_id = data.get("parent_id", item.parent_id)
                        item.name = data.get("name", item.name)
                        item.type = data.get("type", item.type)
                        item.archived = False
                        item.date_created = data.get("date_created", item.date_created)
                        item.runtime_seconds = _safe_int(
                            data.get("runtime_seconds"), item.runtime_seconds or 0
                        )
                        item.size_bytes = _safe_int(
                            data.get("size_bytes"), item.size_bytes or 0
                        )
                        item.video_codec = data.get("video_codec", item.video_codec)
                        item.audio_codec = data.get("audio_codec", item.audio_codec)
                        item.resolution = data.get("resolution", item.resolution)
                        item.genres = (
                            json.dumps(data.get("genres"))
                            if data.get("genres")
                            else None
                        )
                    else:
                        session.add(
                            Item(
                                jellyfin_id=jf_id,
                                library_id=data.get("library_id"),
                                parent_id=data.get("parent_id"),
                                name=data.get("name", "Unknown"),
                                type=data.get("type"),
                                runtime_seconds=_safe_int(data.get("runtime_seconds")),
                                size_bytes=_safe_int(data.get("size_bytes")),
                                archived=False,
                                date_created=data.get("date_created"),
                                video_codec=data.get("video_codec"),
                                audio_codec=data.get("audio_codec"),
                                resolution=data.get("resolution"),
                                genres=(
                                    json.dumps(data.get("genres"))
                                    if data.get("genres")
                                    else None
                                ),
                            )
                        )

                    processed += 1

                return processed
        except Exception as error:
            logger.exception(f"[ERROR] Failed to upsert items: {error}")
            raise

    def archive_missing_items(
        self, library_id: int, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark items as archived if not in active list for a library.

        :param library_id: ID of the library to filter items
        :param active_jellyfin_ids: List of active Jellyfin item IDs
        :returns: Count of items marked as archived
        """
        if not active_jellyfin_ids:
            return 0

        with self._session() as session:
            return (
                session.query(Item)
                .filter(Item.library_id == library_id)
                .filter(Item.jellyfin_id.notin_(active_jellyfin_ids))
                .filter(Item.archived.is_(False))
                .update({"archived": True}, synchronize_session=False)
            )

    def _series_name_for_episode_in_session(
        self, session: Session, episode_jellyfin_id: str
    ) -> Optional[str]:
        """
        Resolve Episode -> Season -> Series hierarchy.

        :param session: Active SQL session
        :param episode_jellyfin_id: Jellyfin ID of the episode item
        :returns: Series name string or None of episode has no series parent or lookup fails
        """
        if not episode_jellyfin_id:
            return None

        episode = (
            session.query(Item).filter(Item.jellyfin_id == episode_jellyfin_id).first()
        )
        if not episode:
            return None

        if (episode.type or "").lower() != "episode":
            return None

        if not episode.parent_id:
            return None

        season = (
            session.query(Item).filter(Item.jellyfin_id == episode.parent_id).first()
        )
        if not season or not season.parent_id:
            return None

        series = (
            session.query(Item).filter(Item.jellyfin_id == season.parent_id).first()
        )
        if not series:
            return None

        if (series.type or "").lower() != "series":
            return None

        return series.name

    def _series_or_item_name_in_session(
        self,
        session: Session,
        item_jellyfin_id: str,
    ) -> Optional[str]:
        """
        Get display name for item within session, resolving to series name for episodes.

        :param session: Active SQL session
        :param item_jellyfin_id: Jellyfin ID of the item
        :returns: Series name if item is episode, otherwise item name, or None if item not found
        """
        if not item_jellyfin_id:
            return None

        item = session.query(Item).filter(Item.jellyfin_id == item_jellyfin_id).first()
        if not item:
            return None

        if (item.type or "").lower() == "episode":
            return (
                self._series_name_for_episode_in_session(session, item_jellyfin_id)
                or item.name
            )

        return item.name

    def get_series_name_for_episode(
        self,
        episode_jellyfin_id: str,
    ) -> Optional[str]:
        """
        Retrieve series name or an episode using auto session management.

        :param episode_jellyfin_id: Jellyfin ID of the episode item
        :returns: Series name string or None if resolution fails
        """
        with self._session() as session:
            return self._series_name_for_episode_in_session(
                session, episode_jellyfin_id
            )

    def get_series_or_item_name(
        self,
        item_jellyfin_id: str,
    ) -> Optional[str]:
        """
        Retrieve display name for item using auto session management.

        :param item_jellyfin_id: Jellyfin ID of the item
        :returns: Series name for episodes or item name, or None if item not found
        """
        with self._session() as session:
            return self._series_or_item_name_in_session(session, item_jellyfin_id)

    # -------------------------
    # Stats & Activity
    # -------------------------

    def refresh_play_stats(self, minimum_play_seconds: int = 120) -> Dict[str, int]:
        """
        Refresh all denormalized play count statistics from PlaybackActivity records.

        :returns: Dictionary with counts of processed libraries, items, and users
        """
        try:
            with self._session() as session:
                return StatsAggregator.refresh_all_stats(
                    session, minimum_play_seconds=minimum_play_seconds
                )
        except Exception as error:
            logger.exception(f"[ERROR] Failed to refresh play stats: {error}")
            raise

    def get_library_stats(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries with their play count statistics.

        :param include_archived: Whether to include archived libraries (default False)
        :returns: List of library dicts with metadata, play stats, and item breakdown by type
        """
        with self._session() as session:
            return StatsAggregator.get_library_stats(
                session,
                include_archived=include_archived,
            )

    # -------------------------
    # Statistics
    # -------------------------

    def get_glance_totals(self) -> Dict[str, int]:
        """
        Aggregate at-a-glance totals for active libraries and users.

        :returns: Dictionary with total_plays, total_items, total_size_bytes, total_users
        :raises Exception: Raised when database queries fail
        """
        with self._session() as session:
            total_plays, total_items, total_size_bytes = (
                session.query(
                    func.coalesce(func.sum(Library.total_plays), 0),
                    func.coalesce(func.sum(Library.total_files), 0),
                    func.coalesce(func.sum(Library.size_bytes), 0),
                )
                .filter(Library.archived.is_(False))  # Active libraries only
                .one()
            )

            total_users = (
                session.query(func.count(User.id))
                .filter(User.archived.is_(False))  # Active users only
                .scalar()
            )

        return {
            "total_plays": int(total_plays or 0),
            "total_items": int(total_items or 0),
            "total_size_bytes": int(total_size_bytes or 0),
            "total_users": int(total_users or 0),
        }

    def upsert_statistics(self, section_key: str, payload: Any) -> Dict[str, Any]:
        """
        Insert or update one statistics section payload.

        :param section_key: Key identifying the statistics section
        :param payload: Data payload to store as JSON
        :returns: Dictionary with section_key, payload_json, and updated_at timestamp
        :raises ValueError: Raised if section_key is empty or falsy
        """
        if not section_key:
            raise ValueError("section_key is required")

        payload_json = json.dumps(payload if payload is not None else [])

        with self._session() as session:
            row = (
                session.query(Statistics)
                .filter(Statistics.section_key == section_key)
                .first()
            )

            now = _now()
            if row:
                row.payload_json = payload_json
                row.updated_at = now
            else:
                row = Statistics(
                    section_key=section_key,
                    payload_json=payload_json,
                    updated_at=now,
                )
                session.add(row)
                session.flush()

            return row.to_dict()

    def get_statistics(
        self, section_keys: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve statistics rows, optionally filtered by section.

        :param section_keys: Optional list of section keys to filter by
        :returns: List of statistics dicts ordered by section_key
        """
        with self._session() as session:
            query = session.query(Statistics)

            if section_keys:
                query = query.filter(Statistics.section_key.in_(section_keys))

            rows = query.order_by(Statistics.section_key.asc()).all()
            return [row.to_dict() for row in rows]

    def get_statistics_map(
        self, section_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Retrieve statistics keyed by section_key.

        :param section_keys: Optional list of section keys to filter by
        :returns: Dictionary mapping section_key to complete stat record
        """
        rows = self.get_statistics(section_keys=section_keys)
        return {row["section_key"]: row for row in rows}

    def refresh_statistics(self, limit: int = 5) -> Dict[str, int]:
        """
        Rebuild and persist all statistics sections.

        :param limit: Maximum items to include per section (default 5)
        :returns: Dictionary with count of sections updated
        """
        from services.statistics import StatisticsBuilder

        try:
            with self._session() as session:
                sections = StatisticsBuilder.build_all(
                    session=session,
                    limit=limit,
                    name_resolver=lambda item_id: (
                        self._series_or_item_name_in_session(session, item_id)
                    ),
                )

            for section_key, payload in sections.items():
                self.upsert_statistics(section_key, payload)

            return {"sections_updated": len(sections)}
        except Exception as error:
            logger.exception(f"[ERROR] Failed to refresh statistics: {error}")
            raise

    # -------------------------
    # Playback Activity
    # -------------------------

    def insert_playback_events(self, event_dicts: List[Dict[str, Any]]) -> int:
        """
        Insert playback activity records.

        :param event_dicts: List of event dicts with activity_log_id, user_id, item_id, event_name, activity_at, username
        :returns: Count of playback events processed
        """
        if not event_dicts:
            return 0

        with self._session() as session:
            existing = _load_existing_by_key(
                session,
                PlaybackActivity,
                PlaybackActivity.activity_log_id,
                [
                    d.get("activity_log_id")
                    for d in event_dicts
                    if d.get("activity_log_id") is not None
                ],
            )

            processed = 0
            for d in event_dicts:
                act_id = d.get("activity_log_id")
                if not act_id:
                    continue

                pa = existing.get(act_id)
                if pa:
                    pa.user_id = d.get("user_id", pa.user_id)
                    pa.item_id = d.get("item_id", pa.item_id)
                    pa.playback_type = d.get("playback_type", pa.playback_type)
                    pa.event_name = d.get("event_name", pa.event_name)
                    pa.activity_at = d.get("activity_at", pa.activity_at)
                    pa.username = d.get("username", pa.username)
                else:
                    session.add(
                        PlaybackActivity(
                            activity_log_id=act_id,
                            user_id=d.get("user_id"),
                            item_id=d.get("item_id"),
                            playback_type=d.get("playback_type"),
                            event_name=d.get("event_name"),
                            activity_at=d.get("activity_at") or _now(),
                            username=d.get("username"),
                        )
                    )

                processed += 1

            return processed

    def get_activity_logs(
        self,
        page: int = 1,
        per_page: int = 50,
        user_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        include_users: bool = True,
        include_total: bool = True,
    ) -> Dict[str, Any]:
        """
        Return paginated activity logs ordered by newest first.
        Optionally filter by user IDs.

        :param page: Page number starting at 1 (default 1)
        :param per_page: Items per page, clamped 1-1000 (default 50)
        :param user_ids: Optional list of user IDs to filter by
        :param search: Optional search string to filter by media name
        :param include_users: Whether to include user list in response (default True)
        :param include_total: Whether to include total count in response (default True)
        :returns: Dictionary with ok, items, users, selected_user_ids, page, per_page, total
        """
        page = max(1, int(page or 1))
        per_page = max(1, min(1000, int(per_page or 50)))
        offset = (page - 1) * per_page

        selected_user_ids = []
        if user_ids:
            selected_user_ids = [
                user_id.strip()
                for user_id in user_ids
                if isinstance(user_id, str) and user_id.strip()
            ]

        with self._session() as session:
            base_query = session.query(PlaybackActivity)

            if selected_user_ids:
                base_query = base_query.filter(
                    PlaybackActivity.user_id.in_(selected_user_ids)
                )

            if search:
                base_query = base_query.filter(
                    PlaybackActivity.event_name.ilike(f"%{search}%")
                )

            total = None
            if include_total:
                total = (
                    base_query.with_entities(func.count(PlaybackActivity.id)).scalar()
                    or 0
                )

            rows = (
                base_query.order_by(
                    PlaybackActivity.activity_at.desc(),
                    PlaybackActivity.id.desc(),
                )
                .offset(offset)
                .limit(per_page)
                .all()
            )

            users = []
            if include_users:
                user_rows = (
                    session.query(
                        PlaybackActivity.user_id,
                        PlaybackActivity.username,
                    )
                    .filter(PlaybackActivity.user_id.isnot(None))
                    .distinct()
                    .order_by(
                        func.lower(
                            func.coalesce(
                                PlaybackActivity.username,
                                PlaybackActivity.user_id,
                            )
                        ).asc()
                    )
                    .all()
                )

                users = [
                    {
                        "user_id": user_id,
                        "username": username,
                    }
                    for user_id, username in user_rows
                    if user_id
                ]

            return {
                "ok": True,
                "items": [r.to_dict() for r in rows],
                "users": users,
                "selected_user_ids": selected_user_ids,
                "page": page,
                "per_page": per_page,
                "total": int(total) if total is not None else None,
            }

    def get_playback_type_totals(self) -> dict:
        """
        Return the total number of start‑playback and stop‑playback events across the whole database.

        :returns: {"start": int, "stop": int}
        """
        with self._session() as session:
            start_total = (
                session.query(func.count())
                .filter(PlaybackActivity.playback_type == "VideoPlayback")
                .scalar()
            )
            stop_total = (
                session.query(func.count())
                .filter(PlaybackActivity.playback_type == "VideoPlaybackStopped")
                .scalar()
            )
        return {"start": int(start_total or 0), "stop": int(stop_total or 0)}

    # -------------------------
    # Task Logging
    # -------------------------

    def get_latest_sync_task(self) -> Optional[Dict[str, Any]]:
        """
        Retrieve the most recent sync task log entry.

        :returns: Dictionary with task metadata and log data, or None if no sync tasks exist
        """
        with self._session() as session:
            task = (
                session.query(TaskLog)
                .filter(TaskLog.type == "sync")
                .order_by(TaskLog.started_at.desc())
                .first()
            )
            if task:
                return {
                    "id": task.id,
                    "name": task.name,
                    "type": task.type,
                    "execution_type": task.execution_type,
                    "result": task.result,
                    "started_at": task.started_at,
                    "finished_at": task.finished_at,
                    "duration_ms": task.duration_ms,
                    "log_json": task.log_json,
                }
            return None

    def update_task_log_progress(
        self,
        task_id: int,
        log_data: Dict[str, Any],
    ) -> None:
        """
        Merge progress fields into a RUNNING task log entry.

        :param task_id: ID of the task log to update
        :param log_data: Dictionary of progress fields to merge
        :returns: None
        """
        if not log_data:
            return

        with self._session() as session:
            task = session.query(TaskLog).filter_by(id=task_id).first()
            if not task or task.result != "RUNNING":
                return

            current: Dict[str, Any] = {}
            if task.log_json:
                try:
                    current = json.loads(task.log_json)
                except Exception:
                    current = {}

            current.update(log_data)
            task.log_json = json.dumps(current)

    def create_task_log(self, name: str, task_type: str, execution_type: str) -> int:
        """
        Create a new task log entry with RUNNING status.

        :param name: Task name for display
        :param task_type: Type of task (e.g., "sync")
        :param execution_type: Execution mode (e.g., "full", "incremental", "initial", "periodic")
        :returns: Task ID as integer for use in updates and completion
        """
        with self._session() as session:
            task = TaskLog(
                name=name,
                type=task_type,
                execution_type=execution_type,
                duration_ms=0,
                started_at=_now(),
                finished_at=None,
                result="RUNNING",
                log_json=None,
            )
            session.add(task)
            session.flush()
            return int(task.id)

    def complete_task_log(
        self,
        task_id: int,
        result: str,
        log_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark a task log as complete with final result and optional log data.

        :param task_id: ID of the task log to complete
        :param result: Final result status ("SUCCESS" or "FAILED")
        :param log_data: Optional dictionary of final log data to persist as JSON
        :returns: None
        """
        with self._session() as session:
            task = session.query(TaskLog).filter_by(id=task_id).first()
            if not task:
                return

            now = _now()
            task.finished_at = now
            task.duration_ms = (now - task.started_at) * 1000
            task.result = result
            task.log_json = json.dumps(log_data) if log_data else None

    def get_task_logs(self, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Retrieve recent task log entries ordered by start time (newest first).

        :param limit: Maximum number of logs to return, clamped 1-500 (default 25)
        :returns: List of task log dicts with metadata and log data
        """
        limit = min(max(int(limit or 25), 1), 500)

        with self._session() as session:
            rows = (
                session.query(TaskLog)
                .order_by(TaskLog.started_at.desc())
                .limit(limit)
                .all()
            )
            return [r.to_dict() for r in rows]
