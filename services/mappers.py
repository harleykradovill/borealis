"""
Map Jellyfin API payloads to database row dictionaries. Includes helpers for parising
Jellyfin dates, extracting media metadata, and mapping users, libraries, items, and
playback events for ingestion.
"""

from __future__ import annotations

import re
import time

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# -------------------------
# Generic helpers
# -------------------------


def _clean_str(value: Any) -> str:
    """
    Convert a value to a trimmed string.

    :param value: Any value to convert to string
    :returns: A str with leading/trailing whitespace removed
    """
    return str(value).strip() if value else ""


def _parse_jf_date(value: Any) -> Optional[int]:
    """
    Parse various Jellyfin DateCreated formats into epoch seconds.

    :param value: The date value from Jellyfin
    :returns: Epoch seconds as an int, or None if cannot be parsed
    """
    if not value:
        return None

    if isinstance(value, (int, float)):
        v = int(value)
        return v // 1000 if v > 1_000_000_000_000 else v

    s = str(value).strip()

    m = re.search(r"/Date\((?P<ms>-?\d+)", s)
    if m:
        return int(int(m.group("ms")) // 1000)

    if s.isdigit():
        v = int(s)
        return v // 1000 if v > 1_000_000_000_000 else v

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return int(dt.timestamp())


def _map_many(
    items: List[Dict[str, Any]],
    fn,
) -> List[Dict[str, Any]]:
    """
    Map a list of Jellyfin objects to table row dicts.

    :param items: Iterable of dict-like Jellyfin objects
    :param fn: A function that accepts a single item
    :returns: A list of mapped dicts produced by fn for each item
    """
    return [m for item in items or [] if (m := fn(item))]


# -------------------------
# Users
# -------------------------


def map_user(jf_user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Tranform a Jellyfin user object into a User table row dict.

    :param jf_user: Jellyfin user object
    :returns: Mapped user row dict, or None when required fields are missing
    """
    jf_id = _clean_str(jf_user.get("Id"))
    name = _clean_str(jf_user.get("Name"))

    if not jf_id or not name:
        return None

    return {
        "jellyfin_id": jf_id,
        "name": name,
        "is_admin": bool(jf_user.get("Policy", {}).get("IsAdministrator")),
    }


def map_users(jf_users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin users into User table row dicts.

    :param jf_users: List of Jellyfin user dicts
    :returns: List of mapped user dicts
    """
    return _map_many(jf_users, map_user)


# -------------------------
# Libraries
# -------------------------


def map_library(jf_library: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin library/media folder into a Library table row dict.

    :param jf_library: Jellyfin library object
    :returns: A dict containing 'jellyfin_id', 'name', 'type', 'image_url'
    """
    jf_id = _clean_str(jf_library.get("Id"))
    name = _clean_str(jf_library.get("Name") or jf_library.get("Path"))

    if not jf_id or not name:
        return None

    image_tag = jf_library.get("ImageTags", {}).get("Primary")
    image_url = f"/Items/{jf_id}/Images/Primary?tag={image_tag}" if image_tag else None

    return {
        "jellyfin_id": jf_id,
        "name": name,
        "type": jf_library.get("CollectionType") or jf_library.get("Type"),
        "image_url": image_url,
    }


def map_libraries(jf_libraries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin libraries into Library table row dicts.

    :param jf_libraries: List of Jellyfin library dicts
    :returns: List of mapped library dicts
    """
    return _map_many(jf_libraries, map_library)


# -------------------------
# Items
# -------------------------


def map_item(
    jf_item: Dict[str, Any],
    library_internal_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin media item into an Item table row dict.

    :param jf_item: Jellyfin item object
    :param library_internal_id: Internal database ID for libary
    :returns: Mapped item row dict, or None when required fields are missing
    """
    jf_id = _clean_str(jf_item.get("Id"))
    name = _clean_str(jf_item.get("Name"))

    if not jf_id or not name:
        return None

    runtime_ticks = jf_item.get("RunTimeTicks") or jf_item.get("RunTimeTick") or 0
    runtime_seconds = (
        int(runtime_ticks) // 10_000_000 if str(runtime_ticks).isdigit() else 0
    )

    size_bytes = sum(
        int(src.get("Size") or src.get("size") or 0)
        for src in jf_item.get("MediaSources", [])
        if isinstance(src, dict)
    )

    video_codec = None
    audio_codec = None
    resolution = None
    media_sources = jf_item.get("MediaSources", [])
    if media_sources and isinstance(media_sources[0], dict):
        media_streams = media_sources[0].get("MediaStreams", [])
        for stream in media_streams:
            if isinstance(stream, dict):
                if stream.get("Type") == "Video" and not video_codec:
                    video_codec = _clean_str(stream.get("Codec"))
                    width = stream.get("Width")
                    height = stream.get("Height")
                    if width and height:
                        resolution = f"{width}x{height}"
                elif stream.get("Type") == "Audio" and not audio_codec:
                    codec = _clean_str(stream.get("Codec"))
                    channels = stream.get("Channels")
                    if codec and channels:
                        audio_codec = f"{codec}{channels}.0"
                    elif codec:
                        audio_codec = codec

    return {
        "jellyfin_id": jf_id,
        "library_id": library_internal_id,
        "parent_id": jf_item.get("ParentId"),
        "name": name,
        "type": jf_item.get("Type") or jf_item.get("MediaType"),
        "runtime_seconds": runtime_seconds,
        "size_bytes": size_bytes,
        "date_created": _parse_jf_date(jf_item.get("DateCreated")),
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "resolution": resolution,
    }


def map_items(
    jf_items: List[Dict[str, Any]],
    library_internal_id: int,
) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin items into Item table row dicts.

    :param jf_items: List of Jellyfin item dicts
    :param library_internal_id: Internal database ID for library
    :returns: List of mapped item dicts
    """
    return [m for item in jf_items or [] if (m := map_item(item, library_internal_id))]


# -------------------------
# Playback events
# -------------------------


def _encode_playback_event_name(jf_event: Dict[str, Any]) -> str:
    """
    Build an event_name that preserves Jellyfin event type and name.

    :param jf_event: Jellyfin playback event object
    :returns: Encoded event name string used to distinguish playback events
    """
    event_type = _clean_str(jf_event.get("Type"))
    event_name = _clean_str(jf_event.get("Name"))

    if event_type and event_name:
        return f"{event_type}||{event_name}"
    if event_type:
        return event_type
    return event_name


def map_playback_event(
    jf_event: Dict[str, Any],
    username: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin playback event into a PlaybackActivity table row dict.

    :param jf_event: Jellyfin playback event object
    :param username: Optional username to include with activity row
    :returns: A dict representing the playback activity row
    """
    user_id = _clean_str(jf_event.get("UserId"))
    item_id = _clean_str(jf_event.get("ItemId"))

    if not user_id or not item_id:
        return None

    activity_at = _parse_jf_date(
        jf_event.get("Date") or jf_event.get("ActivityDate")
    ) or int(time.time())

    return {
        "activity_log_id": jf_event.get("Id") or jf_event.get("ActivityId"),
        "user_id": user_id,
        "item_id": item_id,
        "event_name": _encode_playback_event_name(jf_event),
        "activity_at": activity_at,
        "username_denorm": username,
    }


def map_playback_events(
    jf_events: List[Dict[str, Any]],
    user_lookup: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin playback events into PlaybackActivity
    table row dicts.

    :param jf_events: List of Jellyfin playback event dicts
    :param user_lookup: Optional mapping of user_id -> username
    :returns: List of mapped playback activity dicts
    """
    results = []

    for event in jf_events or []:
        user_id = _clean_str(event.get("UserId"))
        username = user_lookup.get(user_id) if user_lookup and user_id else None

        if mapped := map_playback_event(event, username):
            results.append(mapped)

    return results
