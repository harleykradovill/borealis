"""
Statistics aggregation service for computing analytics from
playback activity events.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from services.data_models import (
    User,
    Item,
    Library,
    PlaybackActivity,
)

def _playback_event_kind(event_name: Optional[str]) -> str:
    """
    Classify playback events using encoded event_name.
    """
    if not event_name:
        return "stop"
    if event_name.startswith("VideoPlaybackStopped||"):
        return "stop"
    if event_name.startswith("VideoPlayback||"):
        return "start"
    return "stop"


def _calculate_watch_seconds(
    session: Session,
) -> tuple[Dict[str, int], Dict[str, int]]:
    """
    Pair start/stop playback rows and return:
    - watch seconds by user_id
    - watch seconds by item_id
    """
    rows = (
        session.query(
            PlaybackActivity.user_id,
            PlaybackActivity.item_id,
            PlaybackActivity.activity_at,
            PlaybackActivity.event_name,
            Item.runtime_seconds,
            PlaybackActivity.id,
        )
        .outerjoin(Item, PlaybackActivity.item_id == Item.jellyfin_id)
        .filter(
            PlaybackActivity.user_id.isnot(None),
            PlaybackActivity.item_id.isnot(None),
            PlaybackActivity.activity_at.isnot(None),
        )
        .order_by(
            PlaybackActivity.user_id.asc(),
            PlaybackActivity.item_id.asc(),
            PlaybackActivity.activity_at.asc(),
            PlaybackActivity.id.asc(),
        )
        .all()
    )

    open_starts: Dict[tuple[str, str], List[int]] = {}
    by_user: Dict[str, int] = {}
    by_item: Dict[str, int] = {}

    for user_id, item_id, activity_at, event_name, runtime_seconds, _ in rows:
        user_id = str(user_id)
        item_id = str(item_id)
        ts = int(activity_at or 0)
        if ts <= 0:
            continue

        kind = _playback_event_kind(event_name)
        key = (user_id, item_id)

        if kind == "start":
            open_starts.setdefault(key, []).append(ts)
            continue
        
        starts = open_starts.get(key)
        start_ts = starts.pop() if starts else None
        if not starts:
            open_starts.pop(key, None)

        if start_ts is None:
            continue

        if ts > 1_000_000_000_000: # Normalize possible ms timestamps to seconds.
            ts //= 1000
        if start_ts > 1_000_000_000_000:
            start_ts //= 1000

        duration = ts - int(start_ts)
        if duration <= 0:
            continue

        if duration > 12 * 60 * 60: # Ignore impossible sessions.
            continue

        cap = int(runtime_seconds or 0)
        if cap > 0:
            duration = min(duration, cap)

        if duration <= 0:
            continue

        by_user[user_id] = by_user.get(user_id, 0) + duration
        by_item[item_id] = by_item.get(item_id, 0) + duration

    return by_user, by_item

def _stop_playback_filter():
    """
    Include legacy rows (no typed prefix) and typed stop rows.
    """
    return or_(
        PlaybackActivity.event_name.is_(None),
        ~PlaybackActivity.event_name.like("VideoPlayback||%"),
        PlaybackActivity.event_name.like("VideoPlaybackStopped||%"),
    )

class StatsAggregator:

    @staticmethod
    def refresh_all_stats(session: Session) -> Dict[str, int]:
        """
        Refresh denormalized user, item, and library play statistics.

        :param session: Active SQL session
        :returns: Counts of processed libraries, items, and users
        :raises Exception: Propagates database/query errors from SQLAlchemy
        """

        stop_filter = _stop_playback_filter()

        # ---- Item play counts ----
        play_counts = dict(
            session.query(
                PlaybackActivity.item_id,
                func.count(PlaybackActivity.id),
            )
            .filter(stop_filter)
            .group_by(PlaybackActivity.item_id)
            .all()
        )

        items_processed = 0
        if play_counts:
            items = (
                session.query(Item)
                .filter(Item.jellyfin_id.in_(play_counts.keys()))
                .all()
            )
            for item in items:
                new_count = int(play_counts.get(item.jellyfin_id, 0))
                if item.play_count != new_count:
                    item.play_count = new_count
                items_processed += 1

        # ---- User play counts ----
        user_counts = dict(
            session.query(
                PlaybackActivity.user_id,
                func.count(PlaybackActivity.id),
            )
            .filter(stop_filter)
            .group_by(PlaybackActivity.user_id)
            .all()
        )

        watch_seconds_by_user, watch_seconds_by_item = _calculate_watch_seconds(
            session
        )

        users_processed = 0
        user_ids = [uid for uid in user_counts.keys() if uid]
        if user_ids:
            users = (
                session.query(User)
                .filter(User.jellyfin_id.in_(user_ids))
                .all()
            )

            latest_user_ts = (
                session.query(
                    PlaybackActivity.user_id.label("user_id"),
                    func.max(PlaybackActivity.activity_at).label(
                        "max_activity_at"
                    ),
                )
                .filter(
                    PlaybackActivity.user_id.in_(user_ids),
                    stop_filter,
                )
                .group_by(PlaybackActivity.user_id)
                .subquery()
            )

            latest_user_rows = (
                session.query(
                    PlaybackActivity.user_id,
                    PlaybackActivity.activity_at,
                    PlaybackActivity.event_name,
                    PlaybackActivity.id,
                )
                .join(
                    latest_user_ts,
                    and_(
                        PlaybackActivity.user_id == latest_user_ts.c.user_id,
                        PlaybackActivity.activity_at
                        == latest_user_ts.c.max_activity_at,
                    ),
                )
                .order_by(PlaybackActivity.id.desc())
                .all()
            )

            latest_user_by_id: Dict[str, Dict[str, Any]] = {}
            for user_id, activity_at, event_name, _ in latest_user_rows:
                if user_id and user_id not in latest_user_by_id:
                    latest_user_by_id[user_id] = {
                        "activity_at": activity_at,
                        "event_name": event_name,
                    }

            for user in users:
                new_total = int(user_counts.get(user.jellyfin_id, 0))
                if user.total_plays != new_total:
                    user.total_plays = new_total

                watch_seconds = int(
                    watch_seconds_by_user.get(user.jellyfin_id, 0)
                )
                if user.total_watch_time_seconds != watch_seconds:
                    user.total_watch_time_seconds = watch_seconds

                latest = latest_user_by_id.get(user.jellyfin_id)
                if latest:
                    latest_ts = latest.get("activity_at")
                    if user.last_seen_at != latest_ts:
                        user.last_seen_at = latest_ts

                    event_name = latest.get("event_name")
                    if event_name:
                        device = StatsAggregator._extract_device_from_event_name(
                            str(event_name)
                        )
                        if device and user.last_device != device:
                            user.last_device = device

                session.merge(user)
                users_processed += 1

        # ---- Library aggregates ----
        libraries_processed = 0
        libraries = session.query(Library).all()

        lib_agg_rows = (
            session.query(
                Item.library_id,
                func.count(Item.id),
                func.coalesce(func.sum(Item.runtime_seconds), 0),
                func.coalesce(func.sum(Item.size_bytes), 0),
                func.coalesce(func.sum(Item.play_count), 0),
            )
            .filter(Item.archived.is_(False))
            .group_by(Item.library_id)
            .all()
        )
        lib_agg_by_id = {
            int(library_id): (
                int(total_files or 0),
                int(total_time_seconds or 0),
                int(size_bytes or 0),
                int(total_plays or 0),
            )
            for (
                library_id,
                total_files,
                total_time_seconds,
                size_bytes,
                total_plays,
            ) in lib_agg_rows
            if library_id is not None
        }

        lib_item_rows = (
            session.query(Item.library_id, Item.jellyfin_id)
            .filter(Item.archived.is_(False))
            .all()
        )
        lib_item_ids: Dict[int, List[str]] = {}
        for library_id, jellyfin_id in lib_item_rows:
            if library_id is None or not jellyfin_id:
                continue
            lib_item_ids.setdefault(int(library_id), []).append(jellyfin_id)

        latest_lib_ts = (
            session.query(
                Item.library_id.label("library_id"),
                func.max(PlaybackActivity.activity_at).label("max_activity_at"),
            )
            .join(Item, PlaybackActivity.item_id == Item.jellyfin_id)
            .filter(stop_filter)
            .group_by(Item.library_id)
            .subquery()
        )

        latest_lib_rows = (
            session.query(
                Item.library_id,
                Item.jellyfin_id,
                Item.name,
                Item.type,
                Item.parent_id,
                PlaybackActivity.id,
            )
            .join(PlaybackActivity, PlaybackActivity.item_id == Item.jellyfin_id)
            .join(
                latest_lib_ts,
                and_(
                    Item.library_id == latest_lib_ts.c.library_id,
                    PlaybackActivity.activity_at
                    == latest_lib_ts.c.max_activity_at,
                ),
            )
            .order_by(PlaybackActivity.id.desc())
            .all()
        )

        latest_item_by_library: Dict[int, Dict[str, Any]] = {}
        for (
            library_id,
            jellyfin_id,
            item_name,
            item_type,
            parent_id,
            _,
        ) in latest_lib_rows:
            if library_id is None:
                continue
            lid = int(library_id)
            if lid not in latest_item_by_library:
                latest_item_by_library[lid] = {
                    "jellyfin_id": jellyfin_id,
                    "name": item_name,
                    "type": (item_type or "").lower(),
                    "parent_id": parent_id,
                }

        episode_parent_ids = list(
            {
                meta["parent_id"]
                for meta in latest_item_by_library.values()
                if meta.get("type") == "episode" and meta.get("parent_id")
            }
        )

        season_rows = (
            session.query(Item.jellyfin_id, Item.parent_id)
            .filter(Item.jellyfin_id.in_(episode_parent_ids))
            .all()
            if episode_parent_ids
            else []
        )
        season_to_series = {
            season_id: series_id
            for season_id, series_id in season_rows
            if season_id and series_id
        }

        series_ids = list(set(season_to_series.values()))
        series_rows = (
            session.query(Item.jellyfin_id, Item.name)
            .filter(Item.jellyfin_id.in_(series_ids))
            .all()
            if series_ids
            else []
        )
        series_name_by_id = {
            series_id: series_name
            for series_id, series_name in series_rows
            if series_id
        }

        last_played_name_by_library: Dict[int, Optional[str]] = {}
        for library_id, meta in latest_item_by_library.items():
            if meta.get("type") == "episode":
                season_id = meta.get("parent_id")
                series_id = season_to_series.get(season_id or "")
                last_played_name_by_library[library_id] = (
                    series_name_by_id.get(series_id or "")
                    or meta.get("name")
                )
            else:
                last_played_name_by_library[library_id] = meta.get("name")

        for lib in libraries:
            total_files, total_time_seconds, size_bytes, total_plays = (
                lib_agg_by_id.get(lib.id, (0, 0, 0, 0))
            )

            total_playback_seconds = int(
                sum(
                    watch_seconds_by_item.get(item_id, 0)
                    for item_id in lib_item_ids.get(lib.id, [])
                )
            )

            last_played_name = last_played_name_by_library.get(lib.id)

            changed = False
            if lib.total_files != total_files:
                lib.total_files = total_files
                changed = True
            if lib.total_time_seconds != total_time_seconds:
                lib.total_time_seconds = total_time_seconds
                changed = True
            if lib.size_bytes != size_bytes:
                lib.size_bytes = size_bytes
                changed = True
            if lib.total_playback_seconds != total_playback_seconds:
                lib.total_playback_seconds = total_playback_seconds
                changed = True
            if lib.total_plays != total_plays:
                lib.total_plays = total_plays
                changed = True
            if lib.last_played_item_name != last_played_name:
                lib.last_played_item_name = last_played_name
                changed = True

            if changed:
                session.merge(lib)

            libraries_processed += 1

        session.commit()

        return {
            "libraries_processed": libraries_processed,
            "items_processed": items_processed,
            "users_processed": users_processed,
        }

    @staticmethod
    def get_top_items_by_plays(
        session: Session,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most played items across all libraries.
        """
        rows = (
            session.query(Item, Library)
            .join(Library, Item.library_id == Library.id)
            .order_by(Item.play_count.desc())
            .limit(limit)
            .all()
        )

        out: List[Dict[str, Any]] = []
        for item, library in rows:
            out.append({
                "item_id": item.jellyfin_id,
                "name": item.name,
                "type": item.type,
                "play_count": int(item.play_count or 0),
                "library_id": library.id,
                "library_name": library.name,
            })
        return out

    @staticmethod
    def get_top_users_by_plays(
        session: Session,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most active users by play count.
        """
        users = (
            session.query(User)
            .order_by(User.total_plays.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "user_id": u.jellyfin_id,
                "name": u.name,
                "total_plays": int(u.total_plays or 0),
            }
            for u in users
        ]

    @staticmethod
    def get_library_stats(
        session: Session,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries with their play counts.
        """
        query = session.query(Library)
        if not include_archived:
            query = query.filter(Library.archived.is_(False))

        out: List[Dict[str, Any]] = []
        for lib in query.all():
            series_count = 0
            episode_count = 0

            rows = (
                session.query(
                    func.lower(Item.type),
                    func.count(Item.id),
                )
                .filter(
                    Item.library_id == lib.id,
                    Item.archived.is_(False),
                )
                .group_by(func.lower(Item.type))
                .all()
            )

            for item_type, cnt in rows:
                if item_type == "series":
                    series_count = int(cnt)
                elif item_type == "episode":
                    episode_count = int(cnt)

            out.append({
                "id": lib.id,
                "jellyfin_id": lib.jellyfin_id,
                "name": lib.name,
                "type": lib.type,
                "image_url": lib.image_url,
                "total_plays": lib.total_plays,
                "total_time_seconds": lib.total_time_seconds,
                "total_files": lib.total_files,
                "size_bytes": lib.size_bytes,
                "total_playback_seconds": lib.total_playback_seconds,
                "last_played_item_name": lib.last_played_item_name,
                "archived": lib.archived,
                "item_count": int(lib.total_files or 0),
                "series_count": series_count,
                "episode_count": episode_count,
            })

        return out
    
    @staticmethod
    def _extract_device_from_event_name(event_name: str) -> str | None:
        """
        Extract device name from playback event_name string.
        """
        if not event_name or " on " not in event_name:
            return None

        parts = event_name.rsplit(" on ", 1)
        if len(parts) == 2:
            device = parts[1].strip()
            return device if device else None

        return None
    
    @staticmethod
    def _series_name_for_episode(
        session: Session,
        episode: Item,
    ) -> Optional[str]:
        if not episode or (episode.type or "").lower() != "episode":
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
    
    
    @staticmethod
    def _series_or_item_name(
        session: Session,
        item: Item,
    ) -> Optional[str]:
        if not item:
            return None
    
        if (item.type or "").lower() == "episode":
            return StatsAggregator._series_name_for_episode(session, item) or item.name
    
        return item.name
