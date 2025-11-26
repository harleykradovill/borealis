import os
import asyncio
import logging
from aiohttp import web
import discord
from discord.ext import commands
from dotenv import load_dotenv
from web.app import create_web_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("finbot")
load_dotenv("token.env")

WEB_HOST = "127.0.0.1"
WEB_PORT = 2929
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logger.info("Discord bot logged in as %s", bot.user)

@bot.command(name="status")
async def status_cmd(ctx):
    await ctx.send("FinBot is running.")

async def start_web_runner(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
    await site.start()
    logger.info("Web UI running at http://%s:%d", WEB_HOST, WEB_PORT)
    return runner

async def main():
    app = create_web_app()
    runner = await start_web_runner(app)

    bot_task = None
    try:
        if DISCORD_TOKEN:
            bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))
            await bot_task
        else:
            # No token provided
            logger.warning("DISCORD_TOKEN not set, running web UI only.")
            while True:
                await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Shutdown requested.")
    finally:
        if bot_task and not bot_task.done():
            await bot.close()
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")