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


def _weekday_name(monday_zero_index: int) -> str:
    """
    Convert a Monday-based weekday index to a weekday name.

    :param monday_zero_index: Weekday index where Monday = 0 and Sunday = 6
    :returns: Weekday name when index is valid, otherwise "Unknown"
    """
    names = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    if 0 <= monday_zero_index < len(names):
        return names[monday_zero_index]
    return "Unknown"


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
            .order_by(Item.play_count.desc(), Item.name.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "item_id": item.jellyfin_id,
                "name": item.name,
                "type": item.type,
                "library_name": library.name,
                "plays": int(item.play_count or 0),
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
                    "weekday": _weekday_name(idx),
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
                        else (activity.username_denorm or "Unknown")
                    ),
                    "last_watched_at": int(activity.activity_at or 0),
                }
            )

            if len(out) >= limit:
                break

        return out

    @staticmethod
    def resolutions(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return resolution counts for Episode/Movie items with an "Others" bucket.

        :param session: Active SQL session
        :param limit: Max number of rows to return including Others
        :returns: List of resolution rows with name and count
        """
        max_rows = max(2, int(limit or 8))  # Reserve a row for Others
        primary_limit = max_rows - 1  # Keep top N-1 before Others

        rows = (
            session.query(
                Item.resolution,
                func.count(Item.id).label("total"),
            )
            .filter(
                Item.archived.is_(False),
                func.lower(Item.type).in_(["episode", "movie"]),
                Item.resolution.isnot(None),
                func.trim(Item.resolution) != "",
            )
            .group_by(Item.resolution)
            .order_by(func.count(Item.id).desc(), Item.resolution.asc())
            .all()
        )

        trimmed = rows[:primary_limit]
        others_rows = rows[primary_limit:]
        others_total = sum(int(r.total or 0) for r in others_rows)  # Aggregate rest

        out = [
            {"resolution": str(resolution), "count": int(total or 0)}
            for resolution, total in trimmed
            if resolution
        ]

        if others_total > 0:
            out.append({"resolution": "Others", "count": others_total})

        out.sort(
            key=lambda row: (-int(row.get("count") or 0), row.get("resolution") or "")
        )

        return out

    @staticmethod
    def audio_codecs(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return top audio codec counts for Episode/Movie items with an "Others" bucket.

        :param session: Active SQL session
        :param limit: Max number of rows to return including Others
        :returns: List of audio codec rows with name and count
        """
        max_rows = max(2, int(limit or 8))  # Reserve a row for Others
        primary_limit = max_rows - 1  # Keep top N-1 before Others

        rows = (
            session.query(
                Item.audio_codec,
                func.count(Item.id).label("total"),
            )
            .filter(
                Item.archived.is_(False),
                func.lower(Item.type).in_(["episode", "movie"]),
                Item.audio_codec.isnot(None),
                func.trim(Item.audio_codec) != "",
            )
            .group_by(Item.audio_codec)
            .order_by(func.count(Item.id).desc(), Item.audio_codec.asc())
            .all()
        )

        trimmed = rows[:primary_limit]
        others_rows = rows[primary_limit:]
        others_total = sum(int(r.total or 0) for r in others_rows)  # Aggregate rest

        out = [
            {"audio_codec": str(codec), "count": int(total or 0)}
            for codec, total in trimmed
            if codec
        ]

        if others_total > 0:
            out.append({"audio_codec": "Others", "count": others_total})

        out.sort(
            key=lambda row: (-int(row.get("count") or 0), row.get("audio_codec") or "")
        )

        return out

    @staticmethod
    def video_codecs(session: Session, limit: int) -> List[Dict[str, Any]]:
        """
        Return top video codec counts for Episode/Movie items with an "Others" bucket.

        :param session: Active SQL session
        :param limit: Max number of rows to return including Others
        :returns: List of video codec rows with name and count
        """
        max_rows = max(2, int(limit or 8))  # Reserve a row for Others
        primary_limit = max_rows - 1  # Keep top N-1 before Others

        rows = (
            session.query(
                Item.video_codec,
                func.count(Item.id).label("total"),
            )
            .filter(
                Item.archived.is_(False),
                func.lower(Item.type).in_(["episode", "movie"]),
                Item.video_codec.isnot(None),
                func.trim(Item.video_codec) != "",
            )
            .group_by(Item.video_codec)
            .order_by(func.count(Item.id).desc(), Item.video_codec.asc())
            .all()
        )

        trimmed = rows[:primary_limit]
        others_rows = rows[primary_limit:]
        others_total = sum(int(r.total or 0) for r in others_rows)  # Aggregate rest

        out = [
            {"video_codec": str(codec), "count": int(total or 0)}
            for codec, total in trimmed
            if codec
        ]

        if others_total > 0:
            out.append({"video_codec": "Others", "count": others_total})

        out.sort(
            key=lambda row: (-int(row.get("count") or 0), row.get("video_codec") or "")
        )

        return out

    @staticmethod
    def most_popular_genres(
        session: Session,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Return top genres overall with per-user playback counts.

        :param session: Active SQL session
        :param limit: Max number of genres to return
        :returns: List of genre rows with total plays and non-archived user breakdown
        """
        max_rows = max(1, int(limit or 5))

        user_ids = [
            row.jellyfin_id
            for row in session.query(User.jellyfin_id)
            .filter(User.archived.is_(False))
            .order_by(User.name.asc())
            .all()
            if row and row.jellyfin_id
        ]

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

        genre_plays: Dict[str, int] = {}
        genre_user_breakdown: Dict[str, Dict[str, int]] = {}

        import json

        for user_id, genres_str in rows:
            if not user_id:
                continue

            try:
                genres_list = (
                    json.loads(genres_str) if isinstance(genres_str, str) else []
                )
            except (json.JSONDecodeError, TypeError):
                continue

            for genre in genres_list:
                genre_name = str(genre).strip()
                if not genre_name:
                    continue

                genre_plays[genre_name] = genre_plays.get(genre_name, 0) + 1

                if genre_name not in genre_user_breakdown:
                    genre_user_breakdown[genre_name] = dict.fromkeys(user_ids, 0)

                genre_user_breakdown[genre_name][user_id] = (
                    genre_user_breakdown[genre_name].get(user_id, 0) + 1
                )

        out = []
        for genre, total in sorted(
            genre_plays.items(), key=lambda item: (-item[1], item[0])
        )[:max_rows]:
            out.append(
                {
                    "genre": genre,
                    "total_plays": int(total),
                    "user_breakdown": genre_user_breakdown.get(
                        genre, dict.fromkeys(user_ids, 0)
                    ),
                }
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
                    func.count(PlaybackActivity.id).label("play_count"),
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
                            "plays": int(play_count or 0),
                        }
                        for lib_id, lib_name, play_count in libs
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
                    func.count(PlaybackActivity.id).label("play_count"),
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
                            "plays": int(play_count or 0),
                        }
                        for item_id, item_name, item_type, lib_name, play_count in items
                    ],
                }
            )

        return out
