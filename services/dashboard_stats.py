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


def _weekday_name(monday_zero_index: int) -> str:
    """
    Convert a Monday-based weekday index to a weekday name.

    :para monday_zero_index: Weekday index where Monday = 0 and Sunday = 6
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


class DashboardStatsBuilder:
    """
    Build dashboard statistic sections from database models.
    """
    @staticmethod
    def build_all(
        session: Session,
        limit: int = 5,
        name_resolver: Optional[Callable[[str], Optional[str]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Build all dashboard statistic sections in one call.

        :param session: Active SQL session
        :param limit: Max records per section, clamped to at least 1
        :param name_resolver: Optional callable to resolve item names by ID
        :returns: Mapping of section keys to statistic row dicts
        :raises ValueError: Raised when limit cannot be converted to int
        :raises TypeError: Raised when limit type is not convertible to int
        """
        n = max(1, int(limit or 5))
        return {
            SECTION_TOP_USERS: DashboardStatsBuilder.top_users_by_plays(
                session, n
            ),
            SECTION_TOP_ITEMS: DashboardStatsBuilder.top_items_by_plays(
                session, n
            ),
            SECTION_TOP_LIBRARIES: (
                DashboardStatsBuilder.top_libraries_by_plays(session, n)
            ),
            SECTION_WATCH_TIME_BY_USER: (
                DashboardStatsBuilder.top_users_by_watch_time(session, n)
            ),
            SECTION_MOST_ACTIVE_DAY: DashboardStatsBuilder.most_active_weekdays(
                session, n
            ),
            SECTION_RECENTLY_WATCHED: DashboardStatsBuilder.recently_watched(
                session,
                n,
                name_resolver=name_resolver,
            ),
        }

    @staticmethod
    def top_users_by_plays(
        session: Session, limit: int
    ) -> List[Dict[str, Any]]:
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
    def top_items_by_plays(
        session: Session, limit: int
    ) -> List[Dict[str, Any]]:
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
    def top_libraries_by_plays(
        session: Session, limit: int
    ) -> List[Dict[str, Any]]:
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
    def top_users_by_watch_time(
        session: Session, limit: int
    ) -> List[Dict[str, Any]]:
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
    def most_active_weekdays(
        session: Session, limit: int
    ) -> List[Dict[str, Any]]:
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
                        name_resolver(item.jellyfin_id)
                        if name_resolver
                        else item.name
                    ) or item.name,
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