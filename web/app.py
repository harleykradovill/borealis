from aiohttp import web
import asyncio
import aiohttp
from urllib.parse import urlparse
import logging
import os
from .db import init_db, get_all_config, set_config_items
import secrets

logger = logging.getLogger("finbot.web")

_runtime_config = {
    "DISCORD_TOKEN": "",
    "JELLYFIN_URL": "",
    "JELLYFIN_API_KEY": "",
}

AUTH_HEADER = "X-Auth-Token"
AUTH_COOKIE = "finbot_auth"
MAX_MESSAGE_LEN = 2000
MAX_CHANNEL_ID_LEN = 20

def get_runtime_config():
    return _runtime_config

def load_from_db():
    config = get_all_config()
    for key in ("DISCORD_TOKEN", "JELLYFIN_URL", "JELLYFIN_API_KEY"):
        _runtime_config[key] = config.get(key, "")
    return _runtime_config

def _redact_secret(value: str, visible: int = 4) -> str:
    v = value.strip()
    if not v:
        return ""
    if len(v) <= visible:
        return "*" * len(v)
    return f"{v[:visible]}…{'*' * (len(v) - visible)}"

def _check_auth(request: web.Request) -> bool:
    expected = request.app.get("auth_token")
    if not expected:
        return False

    cookie_val = request.cookies.get(AUTH_COOKIE)
    if cookie_val and cookie_val == expected:
        return True

    header_val = request.headers.get(AUTH_HEADER)
    if header_val and header_val == expected:
        return True

    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        bearer = authz[7:].strip()
        if bearer == expected:
            return True

    return False

@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy", "frame-ancestors 'none'"
    )
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response

@web.middleware
async def csrf_protect_middleware(request: web.Request, handler):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.cookies.get(AUTH_COOKIE):
            origin = request.headers.get("Origin")
            referer = request.headers.get("Referer")
            allowed = False
            req_origin = f"{request.scheme}://{request.host}"

            if origin:
                allowed = origin == req_origin
            elif referer:
                try:
                    from urllib.parse import urlparse
                    ref = urlparse(referer)
                    ref_origin = f"{ref.scheme}://{ref.netloc}"
                    allowed = ref_origin == req_origin
                except Exception:
                    allowed = False
            else:
                allowed = False

            if not allowed:
                return web.json_response(
                    {"error": "csrf check failed"},
                    status=403,
                )

    return await handler(request)

def create_web_app():
    app = web.Application()
    app.middlewares.append(security_headers_middleware)
    app.middlewares.append(csrf_protect_middleware)
    app.router.add_get("/", index_page)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", update_config)
    app.router.add_get("/api/status", get_status)
    app.router.add_post("/api/notify", send_test_notification)
    app.router.add_post("/api/jellyfin/test", jellyfin_test)
    app["index_html_cache"] = None
    app["bot_connected"] = False

    app["auth_token"] = secrets.token_hex(16)
    logger.info("Web API auth token generated.")

    init_db()
    load_from_db()

    return app

async def index_page(request: web.Request):
    tpl_path = os.path.join(
        os.path.dirname(__file__), "templates", "index.html"
    )
    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception:
        html = (
            "<!doctype html><html><head><title>FinBot Setup</title></head>"
            "<body><h1>FinBot</h1></body></html>"
        )

    resp = web.Response(text=html, content_type="text/html")
    token = request.app.get("auth_token", "")
    resp.set_cookie(
        AUTH_COOKIE,
        token,
        httponly=True,
        samesite="Strict",
        secure=False,
        path="/",
    )
    return resp

async def get_config(request: web.Request):
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    redacted = {
        "DISCORD_TOKEN": _redact_secret(
            _runtime_config.get("DISCORD_TOKEN", "")
        ),
        "JELLYFIN_URL": _runtime_config.get("JELLYFIN_URL", ""),
        "JELLYFIN_API_KEY": _redact_secret(
            _runtime_config.get("JELLYFIN_API_KEY", "")
        ),
    }
    return web.json_response(redacted)

async def get_status(request: web.Request):
    return web.json_response({
        "bot_connected": bool(request.app.get("bot_connected", False))
    })

async def send_test_notification(request: web.Request):
    if not _check_auth(request):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    if not request.app.get("bot_connected"):
        return web.json_response(
            {"ok": False, "error": "Bot not connected"}, status=400
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    channel_id = str(payload.get("channel_id", "")).strip()
    message = str(
        payload.get("message", "Hello from FinBot!")
    ).strip()
    sender = request.app.get("send_message_func")
    if not sender:
        return web.json_response(
            {"ok": False, "error": "Send function not available"},
            status=503,
        )
    if not channel_id or not channel_id.isdigit():
        return web.json_response(
            {"ok": False, "error": "channel_id must be numeric"},
            status=400,
        )
    if len(channel_id) > MAX_CHANNEL_ID_LEN:
        return web.json_response(
            {"ok": False,
             "error": f"channel_id too long (max {MAX_CHANNEL_ID_LEN})"},
            status=400,
        )
    if len(message) > MAX_MESSAGE_LEN:
        return web.json_response(
            {"ok": False,
             "error": f"message too long (max {MAX_MESSAGE_LEN} chars)"},
            status=400,
        )
    try:
        await sender(channel_id, message)
        return web.json_response({"ok": True})
    except ValueError as ve:
        return web.json_response(
            {"ok": False, "error": str(ve)}, status=400
        )
    except Exception:
        logger.exception("Unexpected error sending test notification")
        return web.json_response(
            {"ok": False, "error": "Failed to send message"}, status=500
        )

async def update_config(request: web.Request):
    if not _check_auth(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    if request.content_type and request.content_type.startswith(
            "application/json"
    ):
        payload = await request.json()
    else:
        form = await request.post()
        payload = dict(form)

    changed = []
    items_to_save = {}
    for key in ("DISCORD_TOKEN", "JELLYFIN_URL", "JELLYFIN_API_KEY"):
        if key in payload:
            _runtime_config[key] = payload[key]
            items_to_save[key] = payload[key]
            changed.append(key)

    if items_to_save:
        set_config_items(items_to_save)

    request.app["index_html_cache"] = None
    logger.info(
        "Updated config keys: %s",
        ", ".join(changed) if changed else "none",
    )
    return web.json_response({"updated": changed})

async def jellyfin_test(request: web.Request):
    if not _check_auth(request):
        return web.json_response(
            {"ok": False, "error": "unauthorized"}, status=401
        )

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    base_url = str(
        (payload.get("url") or _runtime_config.get("JELLYFIN_URL") or "")
    ).strip()
    api_key = str(
        (payload.get("api_key") or _runtime_config.get("JELLYFIN_API_KEY") or "")
    ).strip()

    def _valid_url(u: str) -> bool:
        try:
            p = urlparse(u)
            return p.scheme in {"http", "https"} and bool(p.netloc)
        except Exception:
            return False

    if not base_url or not _valid_url(base_url):
        return web.json_response(
            {"ok": False, "error": "invalid or missing Jellyfin URL"},
            status=400,
        )
    if not api_key:
        return web.json_response(
            {"ok": False, "error": "missing Jellyfin API key"},
            status=400,
        )

    system_public = f"{base_url.rstrip('/')}/System/Info/Public"
    system_auth = f"{base_url.rstrip('/')}/System/Info"

    device_id = (request.app.get("auth_token", "") or "finbot")[:16]
    client = "FinBot"
    version = "1.0.0"
    auth_str = (
        f'MediaBrowser Token="{api_key}", Client="{client}", '
        f'Device="FinBot UI", DeviceId="{device_id}", Version="{version}"'
    )

    base_headers = {
        "Accept": "application/json",
        "User-Agent": f"{client}/{version}",
    }
    # Keep only X-Emby-Authorization + token header (dup Authorization removed)
    auth_headers = {
        **base_headers,
        "X-Emby-Authorization": auth_str,
        "X-Emby-Token": api_key,
    }

    timeout = aiohttp.ClientTimeout(total=5)
    server_version = None

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Probe reachability/version (public)
            try:
                async with session.get(system_public, headers=base_headers) as sp:
                    if sp.status == 200:
                        info_pub = await sp.json(content_type=None)
                        server_version = info_pub.get("Version")
            except Exception:
                pass  # Non-fatal

            # Attempt header auth
            async with session.get(system_auth, headers=auth_headers) as resp:
                header_status = resp.status
                if header_status == 200:
                    data = await resp.json(content_type=None)
                    server_version = data.get("Version") or server_version
                    users_me = f"{base_url.rstrip('/')}/Users/Me"
                    user_obj = None
                    user_token = False
                    try:
                        async with session.get(users_me,
                                               headers=auth_headers) as ures:
                            if ures.status == 200:
                                udata = await ures.json(content_type=None)
                                user_obj = {
                                    "id": udata.get("Id"),
                                    "name": udata.get("Name"),
                                }
                                user_token = True
                    except Exception:
                        pass
                    return web.json_response({
                        "ok": True,
                        "server": base_url,
                        "server_version": server_version,
                        "auth_mode": "header",
                        "user": user_obj,
                        "user_token": user_token,
                    })
            # Fallback: query ?api_key=
            async with session.get(f"{system_auth}?api_key={api_key}",
                                   headers=base_headers) as q1:
                api_key_status = q1.status
                if api_key_status == 200:
                    data = await q1.json(content_type=None)
                    server_version = data.get("Version") or server_version
                    users_me = (
                        f"{base_url.rstrip('/')}/Users/Me?api_key={api_key}"
                    )
                    user_obj = None
                    user_token = False
                    try:
                        async with session.get(users_me,
                                               headers=base_headers) as ures:
                            if ures.status == 200:
                                udata = await ures.json(content_type=None)
                                user_obj = {
                                    "id": udata.get("Id"),
                                    "name": udata.get("Name"),
                                }
                                user_token = True
                    except Exception:
                        pass
                    return web.json_response({
                        "ok": True,
                        "server": base_url,
                        "server_version": server_version,
                        "auth_mode": "query_api_key",
                        "user": user_obj,
                        "user_token": user_token,
                    })
            # Legacy fallback: ?X-Emby-Token=
            async with session.get(f"{system_auth}?X-Emby-Token={api_key}",
                                   headers=base_headers) as q2:
                legacy_status = q2.status
                if legacy_status == 200:
                    data = await q2.json(content_type=None)
                    server_version = data.get("Version") or server_version
                    users_me = (
                        f"{base_url.rstrip('/')}/Users/Me"
                        f"?X-Emby-Token={api_key}"
                    )
                    user_obj = None
                    user_token = False
                    try:
                        async with session.get(users_me,
                                               headers=base_headers) as ures:
                            if ures.status == 200:
                                udata = await ures.json(content_type=None)
                                user_obj = {
                                    "id": udata.get("Id"),
                                    "name": udata.get("Name"),
                                }
                                user_token = True
                    except Exception:
                        pass
                    return web.json_response({
                        "ok": True,
                        "server": base_url,
                        "server_version": server_version,
                        "auth_mode": "query_legacy",
                        "user": user_obj,
                        "user_token": user_token,
                    })

            # Classification
            if {header_status, api_key_status, legacy_status} & {401, 403}:
                return web.json_response({
                    "ok": False,
                    "error": "authentication failed (verify API key)",
                    "server_version": server_version,
                    "statuses": {
                        "header": header_status,
                        "api_key": api_key_status,
                        "legacy": legacy_status,
                    },
                }, status=401)

            return web.json_response({
                "ok": False,
                "error": ("unexpected http statuses: "
                          f"header={header_status}, api_key={api_key_status}, "
                          f"legacy={legacy_status}"),
                "server_version": server_version,
            }, status=400)

    except asyncio.TimeoutError:
        return web.json_response(
            {"ok": False, "error": "request timed out",
             "server_version": server_version},
            status=504,
        )
    except aiohttp.ClientError as e:
        return web.json_response(
            {"ok": False, "error": f"network error: {e}",
             "server_version": server_version},
            status=502,
        )
    except Exception:
        logger.exception("Unexpected error during Jellyfin test")
        return web.json_response(
            {"ok": False, "error": "unexpected error",
             "server_version": server_version},
            status=500,
        )