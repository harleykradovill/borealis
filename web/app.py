from aiohttp import web
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