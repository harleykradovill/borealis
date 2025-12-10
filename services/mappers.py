from __future__ import annotations

from typing import Dict, Any, List, Optional


def map_user(jf_user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin user object into a User table row dict.
    """
    jf_id = (jf_user.get("Id") or "").strip()
    name = (jf_user.get("Name") or "").strip()
    
    if not jf_id or not name:
        return None
    
    return {
        "jellyfin_id": jf_id,
        "name": name,
        "is_admin": jf_user.get("Policy", {}).get("IsAdministrator", False),
    }


def map_users(jf_users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin users into User table row dicts.
    """
    results = []
    for user in jf_users:
        mapped = map_user(user)
        if mapped:
            results.append(mapped)
    return results


def map_library(jf_library: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin library/media folder into a Library table row
    dict.
    """
    jf_id = (jf_library.get("Id") or "").strip()
    name = (
        jf_library.get("Name")
        or jf_library.get("Path")
        or ""
    ).strip()
    
    if not jf_id or not name:
        return None
    
    lib_type = jf_library.get("CollectionType") or jf_library.get("Type")
    
    image_tags = jf_library.get("ImageTags", {})
    primary_tag = image_tags.get("Primary")
    image_url = None
    if primary_tag:
        image_url = (
            f"/Items/{jf_id}/Images/Primary?tag={primary_tag}"
        )
    
    return {
        "jellyfin_id": jf_id,
        "name": name,
        "type": lib_type,
        "image_url": image_url,
    }


def map_libraries(
    jf_libraries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin libraries into Library table row dicts.
    """
    results = []
    for lib in jf_libraries:
        mapped = map_library(lib)
        if mapped:
            results.append(mapped)
    return results


def map_item(
    jf_item: Dict[str, Any],
    library_internal_id: int
) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin media item into an Item table row dict.
             invalid
    """
    jf_id = (jf_item.get("Id") or "").strip()
    name = (jf_item.get("Name") or "").strip()
    
    if not jf_id or not name:
        return None
    
    item_type = jf_item.get("Type") or jf_item.get("MediaType")
    parent_id = jf_item.get("ParentId")
    
    return {
        "jellyfin_id": jf_id,
        "library_id": library_internal_id,
        "parent_id": parent_id,
        "name": name,
        "type": item_type,
    }


def map_items(
    jf_items: List[Dict[str, Any]],
    library_internal_id: int
) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin items into Item table row dicts.
    """
    results = []
    for item in jf_items:
        mapped = map_item(item, library_internal_id)
        if mapped:
            results.append(mapped)
    return results


def map_playback_event(
    jf_event: Dict[str, Any],
    username: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Transform a Jellyfin playback event into a PlaybackActivity table row dict.
    """
    user_id = (jf_event.get("UserId") or "").strip()
    item_id = (jf_event.get("ItemId") or "").strip()
    
    if not user_id or not item_id:
        return None
    
    session_info = jf_event.get("Session", {})
    device_name = session_info.get("DeviceName")
    client = session_info.get("Client")
    remote_endpoint = session_info.get("RemoteEndPoint")
    
    play_info = jf_event.get("PlaybackInfo", {})
    position_ticks = play_info.get("PositionTicks", 0)
    duration_s = int(position_ticks / 10_000_000) if position_ticks else 0
    
    activity_timestamp = jf_event.get("Timestamp")
    if activity_timestamp:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(
                activity_timestamp.replace("Z", "+00:00")
            )
            activity_at = int(dt.timestamp())
        except Exception:
            import time
            activity_at = int(time.time())
    else:
        import time
        activity_at = int(time.time())
    
    return {
        "user_id": user_id,
        "item_id": item_id,
        "device_name": device_name,
        "client": client,
        "remote_endpoint": remote_endpoint,
        "activity_at": activity_at,
        "duration_s": duration_s,
        "username_denorm": username,
    }


def map_playback_events(
    jf_events: List[Dict[str, Any]],
    user_lookup: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """
    Transform a list of Jellyfin playback events into PlaybackActivity
    table row dicts.
    """
    results = []
    for event in jf_events:
        user_id = event.get("UserId")
        username = None
        if user_lookup and user_id:
            username = user_lookup.get(user_id)
        
        mapped = map_playback_event(event, username)
        if mapped:
            results.append(mapped)
    return results