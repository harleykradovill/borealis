"""
Statistics aggregation service for computing analytics from
playback activity events.
"""

from __future__ import annotations

from typing import Dict, Any, List
from sqlalchemy.orm import Session

from services.data_models import (
    User,
    Item,
    Library,
    PlaybackActivity,
)


class StatsAggregator:
    def refresh_user_play_counts(session: Session) -> int:
        """
        Refresh total_plays count for all users based on
        PlaybackActivity records.
        """
        users = session.query(User).all()
        updated = 0

        for user in users:
            play_count = (
                session.query(PlaybackActivity)
                .filter(PlaybackActivity.user_id == user.jellyfin_id)
                .count()
            )
            user.total_plays = play_count
            updated += 1

        return updated

    def refresh_item_play_counts(session: Session) -> int:
        """
        Refresh play_count for all items based on
        PlaybackActivity records.
        """
        items = session.query(Item).all()
        updated = 0

        for item in items:
            play_count = (
                session.query(PlaybackActivity)
                .filter(PlaybackActivity.item_id == item.jellyfin_id)
                .count()
            )
            item.play_count = play_count
            updated += 1

        return updated

    def refresh_library_play_counts(session: Session) -> int:
        """
        Refresh total_plays count for all libraries based on
        PlaybackActivity records for their items.
        """
        libraries = session.query(Library).all()
        updated = 0

        for lib in libraries:
            play_count = (
                session.query(PlaybackActivity)
                .join(
                    Item,
                    PlaybackActivity.item_id == Item.jellyfin_id
                )
                .filter(Item.library_id == lib.id)
                .count()
            )
            lib.total_plays = play_count
            updated += 1

        return updated

    def refresh_all_stats(session: Session) -> Dict[str, int]:
        """
        Refresh all denormalized statistics in a single operation.
        """
        return {
            "users_updated": (
                StatsAggregator.refresh_user_play_counts(session)
            ),
            "items_updated": (
                StatsAggregator.refresh_item_play_counts(session)
            ),
            "libraries_updated": (
                StatsAggregator.refresh_library_play_counts(session)
            ),
        }

    def get_top_items_by_plays(
        session: Session,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most played items across all libraries.
        """
        items = (
            session.query(Item)
            .filter(Item.archived == False)
            .order_by(Item.play_count.desc())
            .limit(limit)
            .all()
        )
        return [item.to_dict() for item in items]

    def get_top_users_by_plays(
        session: Session,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most active users by play count.
        """
        users = (
            session.query(User)
            .filter(User.archived == False)
            .order_by(User.total_plays.desc())
            .limit(limit)
            .all()
        )
        return [user.to_dict() for user in users]

    def get_library_stats(
        session: Session,
        include_archived: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve all libraries with their play counts.
        """
        query = session.query(Library)
        if not include_archived:
            query = query.filter(Library.archived == False)

        libraries = query.order_by(
            Library.total_plays.desc()
        ).all()
        return [lib.to_dict() for lib in libraries]