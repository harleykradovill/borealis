"""
Statistics aggregation service for computing analytics from
playback activity events.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

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
        Refresh all denormalized statistics in a single operation.
        """

        # ---- Item play counts ----
        play_counts = dict(
            session.query(
                PlaybackActivity.item_id,
                func.count(PlaybackActivity.id),
            )
            .filter(_stop_playback_filter())
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
            .filter(_stop_playback_filter())
            .group_by(PlaybackActivity.user_id)
            .all()
        )

        watch_seconds_by_user, watch_seconds_by_item = _calculate_watch_seconds(
            session
        )

        users_processed = 0
        if user_counts:
            users = (
                session.query(User)
                .filter(User.jellyfin_id.in_(user_counts.keys()))
                .all()
            )
            for user in users:
                new_total = int(user_counts.get(user.jellyfin_id, 0))
                if user.total_plays != new_total:
                    user.total_plays = new_total

                watch_seconds = int(
                    watch_seconds_by_user.get(user.jellyfin_id, 0)
                )
                if user.total_watch_time_seconds != watch_seconds:
                    user.total_watch_time_seconds = watch_seconds

                last_activity = (
                    session.query(PlaybackActivity)
                    .filter(
                        PlaybackActivity.user_id == user.jellyfin_id,
                        _stop_playback_filter(),
                    )
                    .order_by(PlaybackActivity.activity_at.desc())
                    .limit(1)
                    .first()
                )

                if last_activity:
                    if user.last_seen_at != last_activity.activity_at:
                        user.last_seen_at = last_activity.activity_at

                    if last_activity.event_name:
                        device = (
                            StatsAggregator
                            ._extract_device_from_event_name(
                                last_activity.event_name
                            )
                        )
                        if device and user.last_device != device:
                            user.last_device = device

                session.merge(user)
                users_processed += 1

        # ---- Library aggregates ----
        libraries_processed = 0
        libraries = session.query(Library).all()

        for lib in libraries:
            agg = (
                session.query(
                    func.count(Item.id),
                    func.coalesce(func.sum(Item.runtime_seconds), 0),
                    func.coalesce(func.sum(Item.size_bytes), 0),
                    func.coalesce(func.sum(Item.play_count), 0),
                )
                .filter(
                    Item.library_id == lib.id,
                    Item.archived.is_(False),
                )
                .one()
            )

            total_files = int(agg[0])
            total_time_seconds = int(agg[1])
            size_bytes = int(agg[2])
            total_plays = int(agg[3])

            library_item_ids = [
                row[0]
                for row in session.query(Item.jellyfin_id)
                .filter(
                    Item.library_id == lib.id,
                    Item.archived.is_(False),
                )
                .all()
            ]
            total_playback_seconds = int(
                sum(watch_seconds_by_item.get(item_id, 0) for item_id in library_item_ids)
            )

            last = (
                session.query(PlaybackActivity, Item)
                .join(Item, PlaybackActivity.item_id == Item.jellyfin_id)
                .filter(
                    Item.library_id == lib.id,
                    _stop_playback_filter(),
                )
                .order_by(PlaybackActivity.activity_at.desc())
                .limit(1)
                .first()
            )

            last_played_name: Optional[str] = (
                StatsAggregator._series_or_item_name(session, last[1])
                if last
                else None
            )

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
