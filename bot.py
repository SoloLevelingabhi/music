"""
bot.py – Entry point for the Music Editor Bot.

Start with:
    python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import discord
from discord.ext import commands

import config

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("MusicBot")

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

COGS_DIR = Path(__file__).parent / "cogs"
COGS = [
    f"cogs.{f.stem}"
    for f in COGS_DIR.glob("*.py")
    if not f.stem.startswith("_")
]

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True


class MusicBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.PREFIX),
            intents=intents,
            description="🎵 A powerful Discord music editor bot.",
            help_command=commands.DefaultHelpCommand(no_category="General"),
        )

    async def setup_hook(self) -> None:
        for cog in COGS:
            try:
                await self.load_extension(cog)
                log.info("Loaded cog: %s", cog)
            except Exception as exc:
                log.error("Failed to load cog %s: %s", cog, exc)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"{config.PREFIX}help | 🎵 Music Editor",
            )
        )

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing argument: `{error.param.name}`.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Bad argument: {error}")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(f"❌ {error}")
        else:
            log.error("Unhandled error in %s: %s", ctx.command, error, exc_info=error)
            await ctx.send(f"❌ An unexpected error occurred: {error}")


# ---------------------------------------------------------------------------
# General commands
# ---------------------------------------------------------------------------

bot = MusicBot()


@bot.command(name="ping")
async def ping(ctx: commands.Context) -> None:
    """Check the bot's latency."""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: **{latency} ms**")


@bot.command(name="invite")
async def invite(ctx: commands.Context) -> None:
    """Get the bot's invite link."""
    perms = discord.Permissions(
        connect=True,
        speak=True,
        send_messages=True,
        embed_links=True,
        read_message_history=True,
        add_reactions=True,
    )
    url = discord.utils.oauth_url(bot.user.id, permissions=perms)
    await ctx.send(f"🔗 Invite me: <{url}>")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not config.TOKEN:
        log.error(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill in your token."
        )
        sys.exit(1)

    asyncio.run(bot.start(config.TOKEN))
