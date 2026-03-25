from __future__ import annotations

import time
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

from services.data_models import (
    Base,
    User,
    Library,
    Item,
    PlaybackActivity,
    TaskLog,
    DashboardStat,
)
from services.stats_aggregator import StatsAggregator
from services.settings_store import Settings


# -------------------------
# Helpers
# -------------------------

def _now() -> int:
    """Return current Unix timestamp in seconds."""
    return int(time.time())


def _safe_int(value: Any, default: int = 0) -> int:
    """
    Safely coerce a value to int, returning default on failure.
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
    """
    if not keys:
        return {}

    rows = session.query(model).filter(key_field.in_(keys)).all()
    return {getattr(r, key_field.key): r for r in rows}

@dataclass
class Repository:
    """
    Data access layer for all Borealis entities.
    """

    database_url: str = "sqlite:///borealis.db"

    def __post_init__(self) -> None:
        self.engine = create_engine(self.database_url, future=True)
        self.SessionLocal = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )
        Base.metadata.create_all(self.engine)

    @contextmanager
    def _session(self):
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

    def get_latest_sync_task(
        self
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve the most recent sync task log entry.
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

    # -------------------------
    # Users
    # -------------------------

    def upsert_users(self, user_dicts: List[Dict[str, Any]]) -> int:
        """
        Upsert users by jellyfin_id. Updates name and admin status.
        """
        if not user_dicts:
            return 0

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
                    user.archived = False
                else:
                    user = User(
                        jellyfin_id=jf_id,
                        name=data.get("name", "Unknown"),
                        is_admin=data.get("is_admin", False),
                        archived=False,
                    )
                    session.add(user)

                processed += 1

            return processed

    def archive_missing_users(
        self, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark users as archived if not in active list.
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

    def list_users(
        self, include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all users as dictionaries.
        """
        with self._session() as session:
            query = session.query(User)
            if not include_archived:
                query = query.filter(User.archived.is_(False))
            return [u.to_dict() for u in query.all()]
        
    def get_users_with_stats(
        self, include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        with self._session() as session:
            users = session.query(User).filter(
                User.archived.is_(False) if not include_archived
                else True
            ).all()
    
            results = []
            for user in users:
                total_plays = session.query(
                    func.count(PlaybackActivity.id)
                ).filter(
                    PlaybackActivity.user_id == user.jellyfin_id
                ).scalar() or 0
    
                total_seconds = session.query(
                    func.sum(Item.runtime_seconds)
                ).join(
                    PlaybackActivity,
                    PlaybackActivity.item_id == Item.jellyfin_id
                ).filter(
                    PlaybackActivity.user_id == user.jellyfin_id
                ).scalar() or 0
    
                last_activity = session.query(
                    PlaybackActivity, Item
                ).join(
                    Item,
                    PlaybackActivity.item_id == Item.jellyfin_id
                ).filter(
                    PlaybackActivity.user_id == user.jellyfin_id
                ).order_by(
                    PlaybackActivity.activity_at.desc()
                ).first()
    
                item_name = last_activity[1].name if last_activity else None
                last_activity_ts = (
                    last_activity[0].activity_at if last_activity else None
                )
    
                results.append({
                    "id": user.id,
                    "jellyfin_id": user.jellyfin_id,
                    "name": user.name,
                    "is_admin": user.is_admin,
                    "total_plays": int(total_plays),
                    "total_watch_time_seconds": int(total_seconds or 0),
                    "last_watched_item_name": item_name,
                    "last_device": user.last_device,
                    "last_seen_at": last_activity_ts,
                })
    
            return results

    # -------------------------
    # Libraries
    # -------------------------

    def upsert_libraries(
        self, library_dicts: List[Dict[str, Any]]
    ) -> int:
        """
        Upsert libraries by jellyfin_id.
        """
        if not library_dicts:
            return 0

        with self._session() as session:
            existing = _load_existing_by_key(
                session,
                Library,
                Library.jellyfin_id,
                [d.get("jellyfin_id") for d in library_dicts if d.get("jellyfin_id")],
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

    def archive_missing_libraries(
        self, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark libraries as archived if not in active list.
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

    def list_libraries(
        self, include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries as dictionaries.
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
        """
        if not item_dicts:
            return 0

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
                        )
                    )

                processed += 1

            return processed

    def archive_missing_items(
        self, library_id: int, active_jellyfin_ids: List[str]
    ) -> int:
        """
        Mark items as archived if not in active list for a library.
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

    def get_series_name_for_episode(self, episode_jellyfin_id: str) -> Optional[str]:
        """
        Resolve Episode -> Season -> Series and return the series name.
        """
        if not episode_jellyfin_id:
            return None
    
        with self._session() as session:
            episode = (
                session.query(Item)
                .filter(Item.jellyfin_id == episode_jellyfin_id)
                .first()
            )
            if not episode:
                return None
    
            if (episode.type or "").lower() != "episode":
                return None
    
            if not episode.parent_id:
                return None
    
            season = (
                session.query(Item)
                .filter(Item.jellyfin_id == episode.parent_id)
                .first()
            )
            if not season or not season.parent_id:
                return None
    
            series = (
                session.query(Item)
                .filter(Item.jellyfin_id == season.parent_id)
                .first()
            )
            if not series:
                return None
    
            if (series.type or "").lower() != "series":
                return None
    
            return series.name

    # -------------------------
    # Stats & Activity
    # -------------------------

    def refresh_play_stats(self) -> Dict[str, int]:
        """
        Refresh all denormalized play count statistics from
        PlaybackActivity records.
        """
        with self._session() as session:
            return StatsAggregator.refresh_all_stats(session)

    def get_top_items_by_plays(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most played items across all libraries.
        """
        with self._session() as session:
            return StatsAggregator.get_top_items_by_plays(session, limit)

    def get_top_users_by_plays(
        self, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most active users by total play count.
        """
        with self._session() as session:
            return StatsAggregator.get_top_users_by_plays(session, limit)

    def get_library_stats(
        self, include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries with their play count statistics.
        """
        with self._session() as session:
            return StatsAggregator.get_library_stats(
                session,
                include_archived=include_archived,
            )
        
    # -------------------------
    # Dashboard Watch Statistics
    # -------------------------

    def upsert_dashboard_stat(
        self, section_key: str, payload: Any
    ) -> Dict[str, Any]:
        """
        Insert or update one dashboard stats section payload.
        """
        if not section_key:
            raise ValueError("section_key is required")

        payload_json = json.dumps(payload if payload is not None else [])

        with self._session() as session:
            row = (
                session.query(DashboardStat)
                .filter(DashboardStat.section_key == section_key)
                .first()
            )

            now = _now()
            if row:
                row.payload_json = payload_json
                row.updated_at = now
            else:
                row = DashboardStat(
                    section_key=section_key,
                    payload_json=payload_json,
                    updated_at=now,
                )
                session.add(row)
                session.flush()

            return row.to_dict()

    def get_dashboard_stats(
        self, section_keys: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve dashboard stats rows, optionally filtered by section.
        """
        with self._session() as session:
            query = session.query(DashboardStat)

            if section_keys:
                query = query.filter(
                    DashboardStat.section_key.in_(section_keys)
                )

            rows = query.order_by(DashboardStat.section_key.asc()).all()
            return [row.to_dict() for row in rows]

    def get_dashboard_stats_map(
        self, section_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Retrieve dashboard stats keyed by section_key.
        """
        rows = self.get_dashboard_stats(section_keys=section_keys)
        return {row["section_key"]: row for row in rows}
    
    def refresh_dashboard_stats(self, limit: int = 5) -> Dict[str, int]:
        """
        Rebuild and persist all dashboard stat sections.
        """
        from services.dashboard_stats import DashboardStatsBuilder

        with self._session() as session:
            sections = DashboardStatsBuilder.build_all(
                session=session,
                limit=limit,
            )

        for section_key, payload in sections.items():
            self.upsert_dashboard_stat(section_key, payload)

        return {"sections_updated": len(sections)}

    # -------------------------
    # Playback Activity
    # -------------------------

    def insert_playback_events(
        self, event_dicts: List[Dict[str, Any]]
    ) -> int:
        """
        Insert playback activity records.
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
                    pa.event_name = d.get("event_name", pa.event_name)
                    pa.activity_at = d.get("activity_at", pa.activity_at)
                    pa.username_denorm = d.get(
                        "username_denorm", pa.username_denorm
                    )
                else:
                    session.add(
                        PlaybackActivity(
                            activity_log_id=act_id,
                            user_id=d.get("user_id"),
                            item_id=d.get("item_id"),
                            event_name=d.get("event_name"),
                            activity_at=d.get("activity_at") or _now(),
                            username_denorm=d.get("username_denorm"),
                        )
                    )

                processed += 1

            return processed

    def get_activity_logs(
        self, page: int = 1, per_page: int = 50
    ) -> Dict[str, Any]:
        """
        Return paginated activity logs ordered by newest first.
        """
        page = max(1, int(page or 1))
        per_page = max(1, min(1000, int(per_page or 50)))
        offset = (page - 1) * per_page

        with self._session() as session:
            total = session.query(func.count(PlaybackActivity.id)).scalar() or 0
            rows = (
                session.query(PlaybackActivity)
                .order_by(
                    PlaybackActivity.activity_at.desc(),
                    PlaybackActivity.id.desc(),
                )
                .offset(offset)
                .limit(per_page)
                .all()
            )

            return {
                "ok": True,
                "items": [r.to_dict() for r in rows],
                "page": page,
                "per_page": per_page,
                "total": int(total),
            }

    # -------------------------
    # Task Logging
    # -------------------------

    def create_task_log(
        self, name: str, task_type: str, execution_type: str
    ) -> int:
        """
        Create a new task log entry with RUNNING status.
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
        Mark a task log as complete with result.
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
