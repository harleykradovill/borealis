import asyncio
import logging
import contextlib
from aiohttp import web
import discord
from discord.ext import commands
from web.app import create_web_app, get_runtime_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("finbot")

WEB_HOST = "127.0.0.1"
WEB_PORT = 2929

current_bot: commands.Bot | None = None
bot_task: asyncio.Task | None = None
current_token: str = ""


def build_bot(app: web.Application) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info("Discord bot logged in as %s", bot.user)
        app["bot_connected"] = True

    @bot.event
    async def on_disconnect():
        app["bot_connected"] = False

    @bot.command(name="status")
    async def status_cmd(ctx: commands.Context):
        await ctx.send("FinBot is running.")

    async def send_message_async(channel_id: str, message: str):
        try:
            ch_id = int(channel_id)
        except ValueError:
            raise ValueError("channel_id must be an integer")
        chan = bot.get_channel(ch_id)
        if chan is None:
            chan = await bot.fetch_channel(ch_id)
        await chan.send(message)

    app["send_message_func"] = send_message_async
    return bot


async def run_bot(b: commands.Bot, token: str, app: web.Application):
    try:
        await b.start(token)
    except Exception as e:
        logger.error("Discord bot stopped with error: %s", e)
        app["bot_connected"] = False
    finally:
        app["bot_connected"] = False


async def bot_manager(app: web.Application):
    global current_bot, bot_task, current_token
    while True:
        desired = (get_runtime_config().get("DISCORD_TOKEN") or "").strip()
        want_running = bool(desired)
        token_changed = desired != current_token

        if want_running and (token_changed or current_bot is None):
            if current_bot:
                await current_bot.close()
            if bot_task:
                with contextlib.suppress(Exception):
                    await bot_task
            current_bot = build_bot(app)
            bot_task = asyncio.create_task(run_bot(current_bot, desired, app))
            current_token = desired
            logger.info("Starting Discord bot with provided token.")
        elif not want_running and current_bot:
            await current_bot.close()
            if bot_task:
                with contextlib.suppress(Exception):
                    await bot_task
            current_bot = None
            bot_task = None
            current_token = ""
            logger.info("Discord bot stopped because no token is configured.")
        await asyncio.sleep(2)


async def start_web_runner(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
    await site.start()
    logger.info("Web UI available at http://%s:%s", WEB_HOST, WEB_PORT)
    return runner


async def main():
    app = create_web_app()
    runner = await start_web_runner(app)

    manager_task = asyncio.create_task(bot_manager(app))
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Shutdown requested.")
    finally:
        manager_task.cancel()
        with contextlib.suppress(Exception):
            await manager_task
        if current_bot:
            await current_bot.close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")