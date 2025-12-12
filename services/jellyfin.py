"""
Lightweight Jellyfin client that reads persisted settings and performs
authenticated requests to the Jellyfin REST API.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from services.settings_store import SettingsService


class JellyfinClient:
    def __init__(self, settings: SettingsService) -> None:
        self._settings = settings

    def _read_settings(self) -> Tuple[str, str, str, str]:
        """
        Read settings and normalize scheme/host.
        """
        s = self._settings.get()
        host = (s.get("jf_host") or "").strip()
        port = (s.get("jf_port") or "").strip()
        token = (s.get("jf_api_key") or "").strip()
        scheme = "http"

        if host.startswith(("http://", "https://")):
            if host.startswith("https://"):
                scheme = "https"
                host = host.removeprefix("https://")
            else:
                host = host.removeprefix("http://")

        return scheme, host, port, token

    def _build_url(self, path: str) -> Optional[str]:
        """
        Construct a full URL for a given Jellyfin path.
        """
        scheme, host, port, token = self._read_settings()
        if not host or not port or not port.isdigit() or not token:
            return None
        base = f"{scheme}://{host}:{port}"
        return f"{base}{path}"

    def _is_transient_error(self, exc: Exception) -> bool:
        """
        Determine if an error is transient and should be retried.
        """
        if isinstance(exc, HTTPError):
            return exc.code in (408, 429, 500, 502, 503, 504)
        if isinstance(exc, URLError):
            return True
        return False

    def _get(
        self,
        path: str,
        max_retries: int = 3,
        backoff_base: float = 1.0
    ) -> Dict[str, Any]:
        """
        Perform a GET request to Jellyfin.
        """
        url = self._build_url(path)
        if not url:
            return {
                "ok": False,
                "status": 400,
                "message": (
                    "Missing or invalid host/port/token in settings."
                ),
            }

        _, _, _, token = self._read_settings()

        req = Request(url, method="GET")
        req.add_header("X-Emby-Token", token)
        req.add_header("Accept", "application/json")

        last_exception = None
        for attempt in range(max_retries):
            try:
                with urlopen(req, timeout=5.0) as resp:
                    status = getattr(resp, "status", 200)
                    data = resp.read()
                    import json
                    try:
                        parsed = json.loads(data.decode("utf-8"))
                    except Exception:
                        parsed = {}

                    return {
                        "ok": 200 <= status < 300,
                        "status": status,
                        "data": parsed,
                    }
            except HTTPError as he:
                last_exception = he
                if not self._is_transient_error(he):
                    return {
                        "ok": False,
                        "status": he.code,
                        "message": (
                            f"HTTP error from Jellyfin ({he.code}): "
                            f"{he.reason or 'Unknown'}"
                        ),
                    }
            except URLError as ue:
                last_exception = ue
                if not self._is_transient_error(ue):
                    reason = getattr(ue, "reason", "Unknown")
                    return {
                        "ok": False,
                        "status": 0,
                        "message": f"Network error: {reason}",
                    }
            except Exception as exc:
                return {
                    "ok": False,
                    "status": 0,
                    "message": f"Unexpected error: {str(exc)}",
                }

            if attempt < max_retries - 1:
                delay = backoff_base * (2 ** attempt)
                time.sleep(delay)

        if last_exception:
            if isinstance(last_exception, HTTPError):
                return {
                    "ok": False,
                    "status": last_exception.code,
                    "message": (
                        f"HTTP error after {max_retries} retries "
                        f"({last_exception.code}): "
                        f"{last_exception.reason or 'Unknown'}"
                    ),
                }
            elif isinstance(last_exception, URLError):
                reason = getattr(last_exception, "reason", "Unknown")
                return {
                    "ok": False,
                    "status": 0,
                    "message": (
                        f"Network error after {max_retries} retries: "
                        f"{reason}"
                    ),
                }

        return {
            "ok": False,
            "status": 0,
            "message": f"Failed after {max_retries} retries",
        }

    def validate_connection(self) -> Dict[str, Any]:
        """
        Calls /System/Info to validate connectivity and credentials.
        """
        return self._get("/System/Info")

    def system_info(self) -> Dict[str, Any]:
        """
        Returns Jellyfin system info.
        """
        return self._get("/System/Info")

    def users(self) -> Dict[str, Any]:
        """
        Returns list of users.
        """
        return self._get("/Users")

    def libraries(self) -> Dict[str, Any]:
        """
        Returns media folders.
        """
        return self._get("/Library/MediaFolders")

    def library_items(self, library_id: str) -> Dict[str, Any]:
        """
        Returns all items in a library.
        """
        path = (
            f"/Items?ParentId={library_id}&Recursive=true&Limit=0"
        )
        return self._get(path)

    def library_stats(self, library_id: str) -> Dict[str, Any]:
        """
        Returns item count for a library.
        """
        result = self.library_items(library_id)
        if result.get("ok") and isinstance(result.get("data"), dict):
            return {
                "ok": True,
                "item_count": result["data"].get(
                    "TotalRecordCount", 0
                )
            }
        return {"ok": False, "item_count": 0}

    def get_playback_activity(
        self,
        start_timestamp: Optional[int] = None,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Returns playback activity from Jellyfin activity log.
        """
        path = f"/System/ActivityLog/Entries?Limit={limit}"
        if start_timestamp:
            path += f"&MinDate={start_timestamp}"
        return self._get(path)
    
    def get_activity_log(
        self,
        start_index: int = 0,
        limit: int = 100,
        min_date: Optional[str] = None,
        has_user_id: bool = True
    ) -> Dict[str, Any]:
        """
        Retrieve activity log entries from Jellyfin with pagination.

        Supports filtering by date range and user context. Returns
        paginated results suitable for bulk historical pulls.
        """
        # Build query parameters carefully to avoid exceeding
        # line length
        path = (
            f"/System/ActivityLog/Entries?"
            f"startIndex={start_index}&"
            f"limit={limit}&"
            f"hasUserId={str(has_user_id).lower()}"
        )

        if min_date:
            from urllib.parse import quote
            encoded_date = quote(min_date, safe='')
            path += f"&minDate={encoded_date}"

        return self._get(path)


def create_client(settings_service: SettingsService) -> JellyfinClient:
    """
    Factory to create a JellyfinClient from a settings_store.
    """
    return JellyfinClient(settings_service)