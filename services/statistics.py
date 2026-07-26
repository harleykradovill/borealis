"""
Build statistics sections from persistent models and playback activity.
Computes top users/items/libraries, watch-time leaders, most-active weekdays, recently watched items,
and resolution breakdowns.
"""

from __future__ import annotations

from services.data_models import Item, Library, PlaybackActivity, User

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from typing import Any, Callable, Dict, List, Optional

import calendar
from collections import Counter, defaultdict
import json

SECTION_TOP_USERS = "top_users_by_plays"
SECTION_TOP_ITEMS = "top_items_by_plays"
SECTION_TOP_LIBRARIES = "top_libraries_by_plays"
SECTION_WATCH_TIME_BY_USER = "top_users_by_watch_time"
SECTION_MOST_ACTIVE_DAY = "most_active_weekdays"
SECTION_RECENTLY_WATCHED = "recently_watched"
SECTION_RESOLUTIONS = "resolutions"
SECTION_VIDEO_CODECS = "video_codecs"
SECTION_AUDIO_CODECS = "audio_codecs"
SECTION_MOST_POPULAR_GENRES = "most_popular_genres"
SECTION_TOP_LIBRARIES_BY_USER = "top_libraries_by_user"
SECTION_TOP_ITEMS_BY_USER = "top_items_by_user"
SECTION_LARGEST_ITEMS = "largest_items"

_RESOLUTION_TIER = [
    (360, "360p"),
    (480, "480p"),
    (720, "720p"),
    (1080, "1080p"),
    (1200, "1200p"),
    (1440, "1440p"),
    (1600, "1600p"),
    (2160, "4K"),
]


def _sqlite_weekday_expr():
    """
    Build a SQL expression for Monday-based weekday indexing.

    :returns: SQL expression that maps SQL Sunday = 0..Saturday=6 to Monday=0..Sunday=6
    """
    w = func.cast(
        func.strftime(
            "%w",
            func.datetime(PlaybackActivity.activity_at, "unixepoch"),
        ),
        Integer,
    )
    return (w + 6) % 7


def _normalize_resolution(raw: str) -> str:
    """
    Map a raw resolution string (e.g. '1920x1080') to a common name.

    :param raw: Raw resolution value from the database
    :returns: Normalized resolution name (e.g. '1080p', '4K')
    """
    known = {name for _, name in _RESOLUTION_TIER}
    if raw in known:
        return raw

    try:
        height = int(raw.split("x", 1)[1].strip())
    except (ValueError, IndexError, AttributeError):
        return raw

    for threshold, name in _RESOLUTION_TIER:
        if height <= threshold:
            return name
    return "8K"


class StatisticsBuilder:
    """
    Build statistic sections from database models.
    """

    @staticmethod
    def build_all(
        session: Session,
        limit: int = 5,
        name_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Build all statistic sections in one call.

        :param session: Active SQL session
        :param limit: Max records per section, clamped to at least 1
        :param name_resolver: Optional callable to resolve item names by ID
        :returns: Mapping of section keys to statistic row dicts
        :raises ValueError: Raised when limit cannot be converted to int
        :raises TypeError: Raised when limit type is not convertible to int
        """
        n = max(1, int(limit or 5))
        return {
            SECTION_TOP_USERS: StatisticsBuilder.top_users_by_plays(session, n),
            SECTION_TOP_ITEMS: StatisticsBuilder.top_items_by_plays(session, n),
            SECTION_TOP_LIBRARIES: (
                StatisticsBuilder.top_libraries_by_plays(session, n)
            ),
            SECTION_WATCH_TIME_BY_USER: (
                StatisticsBuilder.top_users_by_watch_time(session, n)
            ),
            SECTION_MOST_ACTIVE_DAY: StatisticsBuilder.most_active_weekdays(session, n),
            SECTION_RECENTLY_WATCHED: StatisticsBuilder.recently_watched(
                session,
                n,
                name_resolver=name_resolver,
            ),
            SECTION_RESOLUTIONS: StatisticsBuilder.resolutions(session, limit=8),
            SECTION_VIDEO_CODECS: StatisticsBuilder.video_codecs(session, limit=8),
            SECTION_AUDIO_CODECS: StatisticsBuilder.audio_codecs(session, limit=8),
            SECTION_MOST_POPULAR_GENRES: StatisticsBuilder.most_popular_genres(
                session, limit=5
            ),
            SECTION_TOP_LIBRARIES_BY_USER: (
                StatisticsBuilder.top_libraries_by_user(session, limit=5)
            ),
            SECTION_TOP_ITEMS_BY_USER: (
                StatisticsBuilder.top_items_by_user(session, limit=5)
            ),
            SECTION_LARGEST_ITEMS: StatisticsBuilder.top_largest_items(
                session, limit=10
            ),
        }

    @staticmethod
    def top_users_by_plays(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return highest-play users, excluding archived.

        :param session: Active SQL session
        :param limit: Max number of users to return
        :returns: List of users with Jellyfin ID, name, and play count
        """
        rows = (
            session.query(User)
            .filter(User.archived.is_(False))
            .order_by(User.total_plays.desc(), User.name.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "user_id": row.jellyfin_id,
                "name": row.name,
                "plays": int(row.total_plays or 0),
            }
            for row in rows
        ]

    @staticmethod
    def top_items_by_plays(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return highest-play items with their library names.

        :param session: Active SQL session
        :param limit: Max number of items to return
        :returns: List of items with type, library, and play count
        """
        rows = (
            session.query(Item, Library)
            .join(Library, Item.library_id == Library.id)
            .filter(Item.archived.is_(False), Library.archived.is_(False))
            .order_by(Item.total_plays.desc(), Item.name.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "item_id": item.jellyfin_id,
                "name": item.name,
                "type": item.type,
                "library_name": library.name,
                "plays": int(item.total_plays or 0),
            }
            for item, library in rows
        ]

    @staticmethod
    def top_libraries_by_plays(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return libraries ordered by total plays, excluding archived.

        :param session: Active SQL session
        :param limit: Max number of libraries to return
        :returns: List of libraries with Jellyfin ID, name, and play count
        """
        rows = (
            session.query(Library)
            .filter(Library.archived.is_(False))
            .order_by(Library.total_plays.desc(), Library.name.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "library_id": row.jellyfin_id,
                "name": row.name,
                "plays": int(row.total_plays or 0),
            }
            for row in rows
        ]

    @staticmethod
    def top_users_by_watch_time(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return users ordered by total watch time.

        :param session: Active SQL session
        :param limit: Max number of users to return
        :returns: List of users with Jellyfin ID, name, and watch seconds
        """
        rows = (
            session.query(User)
            .filter(User.archived.is_(False))
            .order_by(User.total_watch_time_seconds.desc(), User.name.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "user_id": row.jellyfin_id,
                "name": row.name,
                "watch_seconds": int(row.total_watch_time_seconds or 0),
            }
            for row in rows
        ]

    @staticmethod
    def most_active_weekdays(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return weekdays ranked by playback activity.

        :param session: Active SQL session
        :param limit: Max number of weekdays to return
        :returns: List of weekday rows with index, name, and play totals
        """
        weekday_expr = _sqlite_weekday_expr()

        rows = (
            session.query(
                weekday_expr.label("weekday_idx"),
                func.count(PlaybackActivity.id).label("plays"),
            )
            .group_by(weekday_expr)
            .order_by(func.count(PlaybackActivity.id).desc(), weekday_expr.asc())
            .limit(limit)
            .all()
        )

        out: List[Dict[str, Any]] = []
        for weekday_idx, plays in rows:
            idx = int(weekday_idx or 0)
            out.append(
                {
                    "weekday_index": idx,
                    "weekday": calendar.day_name[idx],
                    "plays": int(plays or 0),
                }
            )
        return out

    @staticmethod
    def recently_watched(
        session: Session,
        limit: int,
        name_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return recent items with last viewer and timestamp

        :param session: Active SQL session
        :param limit: Max number of unique items to return
        :param name_resolver: Optional callable to resolve item names by ID
        :returns: List of recently watched items with user context
        """
        raw = (
            session.query(PlaybackActivity, Item, User)
            .join(Item, PlaybackActivity.item_id == Item.jellyfin_id)
            .outerjoin(User, PlaybackActivity.user_id == User.jellyfin_id)
            .filter(Item.archived.is_(False))
            .order_by(
                PlaybackActivity.activity_at.desc(),
                PlaybackActivity.id.desc(),
            )
            .limit(limit * 5)
            .all()
        )

        out: List[Dict[str, Any]] = []
        seen_item_ids = set()

        for activity, item, user in raw:
            if item.jellyfin_id in seen_item_ids:
                continue
            seen_item_ids.add(item.jellyfin_id)

            out.append(
                {
                    "item_id": item.jellyfin_id,
                    "name": (
                        name_resolver(item.jellyfin_id) if name_resolver else item.name
                    )
                    or item.name,
                    "user_id": activity.user_id,
                    "user_name": (
                        user.name
                        if user and user.name
                        else (activity.username or "Unknown")
                    ),
                    "last_watched_at": int(activity.activity_at or 0),
                }
            )

            if len(out) >= limit:
                break

        return out

    @staticmethod
    def _codec_stats(session: Session, column: Any, limit: int) -> List[Dict[str, Any]]:
        """
        Compute statistics for a given codec or resolution column.

        :param session: Active SQLAlchemy session
        :param column: SQLAlchemy column to aggregate
        :param limit: Maximum number of rows to return
        :returns: List of dicts with the column value and its count
        :raises ValueError: If limit cannot be converted to an integer
        """
        max_rows = max(2, int(limit or 8))
        primary_limit = max_rows - 1

        rows = (
            session.query(column, func.count(Item.id).label("total"))
            .filter(
                Item.archived.is_(False),
                func.lower(Item.type).in_(["episode", "movie"]),
                column.isnot(None),
                func.trim(column) != "",
            )
            .group_by(column)
            .order_by(func.count(Item.id).desc(), column.asc())
            .all()
        )

        trimmed, others = rows[:primary_limit], rows[primary_limit:]
        others_total = sum(int(r.total or 0) for r in others)

        out = [{column.key: str(val), "count": int(cnt)} for val, cnt in trimmed if val]
        if others_total:
            out.append({column.key: "Others", "count": others_total})

        out.sort(key=lambda r: (-r["count"], r[column.key]))
        return out

    @staticmethod
    def audio_codecs(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return audio codec statistics

        :param session: Active SQLAlchemy session
        :param limit: Maximum number of rows to return
        :returns: List of dictionaries with audio-codec name and count
        """
        return StatisticsBuilder._codec_stats(session, Item.audio_codec, limit)

    @staticmethod
    def video_codecs(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return video codec statistics

        :param session: Active SQLAlchemy session
        :param limit: Maximum number of rows to return
        :returns: List of dictionaries with video-codec name and count
        """
        return StatisticsBuilder._codec_stats(session, Item.video_codec, limit)

    @staticmethod
    def resolutions(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return resolution statistics

        :param session: Active SQLAlchemy session
        :param limit: Maximum number of rows to return
        :returns: List of dictionaries with resolution value and count
        """
        rows = (
            session.query(Item.resolution, func.count(Item.id).label("total"))
            .filter(
                Item.archived.is_(False),
                func.lower(Item.type).in_(["episode", "movie"]),
                Item.resolution.isnot(None),
                func.trim(Item.resolution) != "",
            )
            .group_by(Item.resolution)
            .order_by(func.count(Item.id).desc())
            .all()
        )

        merged: Dict[str, int] = {}
        for val, cnt in rows:
            name = _normalize_resolution(val)
            merged[name] = merged.get(name, 0) + int(cnt or 0)

        sorted_items = sorted(merged.items(), key=lambda x: -x[1])[:limit]
        return [{"resolution": name, "count": count} for name, count in sorted_items]

    @staticmethod
    def most_popular_genres(session: Session, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Return top genres overall with per-user playback counts.

        :param session: Active SQL session
        :param limit: Max number of genres to return
        :returns: List of genre rows with total plays and non-archived user breakdown
        """
        rows = (
            session.query(PlaybackActivity.user_id, Item.genres)
            .join(Item, PlaybackActivity.item_id == Item.jellyfin_id)
            .join(User, PlaybackActivity.user_id == User.jellyfin_id)
            .filter(
                Item.archived.is_(False),
                User.archived.is_(False),
                Item.genres.isnot(None),
                func.trim(Item.genres) != "",
            )
            .all()
        )

        genre_counter = Counter()
        user_genre_counts = defaultdict(lambda: Counter())

        for user_id, genres_str in rows:
            try:
                genres = json.loads(genres_str) if isinstance(genres_str, str) else []
            except (json.JSONDecodeError, TypeError):
                continue
            for g in genres:
                name = str(g).strip()
                if not name:
                    continue
                genre_counter[name] += 1
                user_genre_counts[name][user_id] += 1

        out = []
        for genre, total in genre_counter.most_common(limit):
            breakdown = {
                uid: user_genre_counts[genre].get(uid, 0)
                for uid in [
                    u.jellyfin_id
                    for u in session.query(User.jellyfin_id)
                    .filter(User.archived.is_(False))
                    .order_by(User.name)
                    .all()
                ]
            }
            out.append(
                {"genre": genre, "total_plays": total, "user_breakdown": breakdown}
            )
        return out

    @staticmethod
    def top_libraries_by_user(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return top libraries for each user by play count.

        :param session: Active SQL session
        :param limit: Max number of libraries per user
        :returns: List of user dicts with their top libraries
        """
        users = (
            session.query(User)
            .filter(User.archived.is_(False))
            .order_by(User.name.asc())
            .all()
        )

        out: List[Dict[str, Any]] = []

        for user in users:
            libs = (
                session.query(
                    Library.jellyfin_id,
                    Library.name,
                    func.count(PlaybackActivity.id).label("total_plays"),
                )
                .join(Item, PlaybackActivity.item_id == Item.jellyfin_id)
                .join(Library, Item.library_id == Library.id)
                .filter(
                    PlaybackActivity.user_id == user.jellyfin_id,
                    PlaybackActivity.playback_type == "VideoPlaybackStopped",
                    Item.archived.is_(False),
                    Library.archived.is_(False),
                )
                .group_by(Library.jellyfin_id, Library.name)
                .order_by(func.count(PlaybackActivity.id).desc())
                .limit(limit)
                .all()
            )

            if not libs:
                continue

            out.append(
                {
                    "user_id": user.jellyfin_id,
                    "name": user.name,
                    "libraries": [
                        {
                            "library_id": lib_id,
                            "name": lib_name,
                            "plays": int(total_plays or 0),
                        }
                        for lib_id, lib_name, total_plays in libs
                    ],
                }
            )

        return out

    @staticmethod
    def top_items_by_user(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return top items for each user by play count.

        :param session: Active SQL session
        :param limit: Max number of items per user
        :returns: List of user dicts with their top items
        """
        users = (
            session.query(User)
            .filter(User.archived.is_(False))
            .order_by(User.name.asc())
            .all()
        )

        out: List[Dict[str, Any]] = []

        for user in users:
            items = (
                session.query(
                    Item.jellyfin_id,
                    Item.name,
                    Item.type,
                    Library.name.label("library_name"),
                    func.count(PlaybackActivity.id).label("total_plays"),
                )
                .join(PlaybackActivity, PlaybackActivity.item_id == Item.jellyfin_id)
                .join(Library, Item.library_id == Library.id)
                .filter(
                    PlaybackActivity.user_id == user.jellyfin_id,
                    PlaybackActivity.playback_type == "VideoPlaybackStopped",
                    Item.archived.is_(False),
                    Library.archived.is_(False),
                )
                .group_by(Item.jellyfin_id, Item.name, Item.type, Library.name)
                .order_by(func.count(PlaybackActivity.id).desc())
                .limit(limit)
                .all()
            )

            if not items:
                continue

            out.append(
                {
                    "user_id": user.jellyfin_id,
                    "name": user.name,
                    "items": [
                        {
                            "item_id": item_id,
                            "name": item_name,
                            "type": item_type,
                            "library_name": lib_name,
                            "plays": int(total_plays or 0),
                        }
                        for item_id, item_name, item_type, lib_name, total_plays in items
                    ],
                }
            )

        return out

    @staticmethod
    def top_largest_items(session: Session, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Return items ordered by size descending with library name and play count.

        :param session: Active SQL session
        :param limit: Max number of items to return
        :returns: List of items with name, library_name, total_plays, size_bytes, date_created
        """
        rows = (
            session.query(Item, Library)
            .join(Library, Item.library_id == Library.id)
            .filter(Item.archived.is_(False), Library.archived.is_(False))
            .filter(Item.size_bytes > 0)
            .order_by(Item.size_bytes.desc(), Item.name.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "item_id": item.jellyfin_id,
                "name": item.name,
                "library_name": library.name,
                "total_plays": int(item.total_plays or 0),
                "size_bytes": int(item.size_bytes or 0),
                "date_created": item.date_created,
            }
            for item, library in rows
        ]
