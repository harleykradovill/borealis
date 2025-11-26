from aiohttp import web
import logging
import os
from .db import init_db, get_all_config, set_config_items, migrate_from_env

logger = logging.getLogger("finbot.web")

_runtime_config = {
    "DISCORD_TOKEN": "",
    "JELLYFIN_URL": "",
    "JELLYFIN_API_KEY": "",
}

def get_runtime_config():
    return _runtime_config

def load_from_db():
    config = get_all_config()
    for key in ("DISCORD_TOKEN", "JELLYFIN_URL", "JELLYFIN_API_KEY"):
        _runtime_config[key] = config.get(key, "")
    return _runtime_config

def create_web_app():
    app = web.Application()
    app.router.add_get("/", index_page)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", update_config)
    app.router.add_get("/api/status", get_status)
    app.router.add_post("/api/notify", send_test_notification)
    app["index_html_cache"] = None
    app["bot_connected"] = False

    init_db()
    load_from_db()

    return app

async def index_page(request: web.Request):
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")

    try:
        with open(tpl_path, "r", encoding="utf-8") as f:
            html = f.read()
    except Exception:
        html = "<!doctype html><html><head><title>FinBot Setup</title></head><body><h1>FinBot</h1></body></html>"
    return web.Response(text=html, content_type="text/html")

async def get_status(request: web.Request):
    return web.json_response({
        "bot_connected": bool(request.app.get("bot_connected", False))
    })

async def send_test_notification(request: web.Request):
    if not request.app.get("bot_connected"):
        return web.json_response({"ok": False, "error": "Bot not connect"}, status=400)

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    channel_id = str(payload.get("channel_id", "")).strip()
    message = str(payload.get("message", "Hello from FinBot!")).strip()

    return web.json_response({
        "ok": True,
        "stub": True,
        "channel_id": channel_id,
        "message": message
    })

async def get_config(request: web.Request):
    return web.json_response(_runtime_config)

async def update_config(request: web.Request):
    if request.content_type and request.content_type.startswith("application/json"):
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
    logger.info("Updated config keys: %s", ", ".join(changed) if changed else "none")
    return web.json_response({"updated": changed, "config": _runtime_config})