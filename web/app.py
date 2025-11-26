from aiohttp import web
import logging

logger = logging.getLogger("finbot.web")

_runtime_config = {
    "DISCORD_TOKEN": "",
    "JELLYFIN_URL": "",
    "JELLYFIN_API_KEY": "",
}

def create_web_app():
    app = web.Application()
    app.router.add_get("/", index_page)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", update_config)
    app["index_html_cache"] = None
    return app

async def index_page(request: web.Request):
    cfg = _runtime_config
    html = (
        "<!doctype html><html><head><title>FinBot Setup</title></head><body>"
        "<h1>FinBot Configuration</h1>"
        "<form method='post' action='/api/config'>"
        "<label>Discord Token:<br><input name='DISCORD_TOKEN' value='{dt}' /></label><br><br>"
        "<label>Jellyfin URL:<br><input name='JELLYFIN_URL' value='{ju}' /></label><br><br>"
        "<label>Jellyfin API Key:<br><input name='JELLYFIN_API_KEY' value='{jk}' /></label><br><br>"
        "<button type='submit'>Save</button>"
        "</form>"
        "<p><a href='/api/config'>View raw config (JSON)</a></p>"
        "</body></html>"
    ).format(dt=cfg.get("DISCORD_TOKEN", ""), ju=cfg.get("JELLYFIN_URL", ""), jk=cfg.get("JELLYFIN_API_KEY", ""))
    return web.Response(text=html, content_type="text/html")

async def get_config(request: web.Request):
    return web.json_response(_runtime_config)

async def update_config(request: web.Request):
    if request.content_type and request.content_type.startswith("application/json"):
        payload = await request.json()
    else:
        form = await request.post()
        payload = dict(form)
    changed = []
    for key in ("DISCORD_TOKEN", "JELLYFIN_URL", "JELLYFIN_API_KEY"):
        if key in payload:
            _runtime_config[key] = payload[key]
            changed.append(key)
    request.app["index_html_cache"] = None
    logger.info("Updated config keys: %s", ", ".join(changed) if changed else "none")
    return web.json_response({"updated": changed, "config": _runtime_config})