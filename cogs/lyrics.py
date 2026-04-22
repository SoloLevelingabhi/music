"""
lyrics.py – Lyrics fetching cog (requires Genius API token).

Commands
--------
lyrics  – Fetch and display lyrics for the current song or a given title
"""

from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord.ext import commands

import config


class Lyrics(commands.Cog):
    """📜 Song lyrics fetcher."""

    CHUNK_SIZE = 1900   # Discord message limit is 2000 chars

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._genius = None

        if config.GENIUS_TOKEN:
            try:
                import lyricsgenius
                self._genius = lyricsgenius.Genius(
                    config.GENIUS_TOKEN,
                    skip_non_songs=True,
                    excluded_terms=["(Remix)", "(Live)"],
                    verbose=False,
                )
            except ImportError:
                pass  # lyricsgenius not installed; lyrics disabled

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @commands.command(name="lyrics", aliases=["ly"])
    async def lyrics(self, ctx: commands.Context, *, title: Optional[str] = None) -> None:
        """Fetch lyrics for the current song or a provided title."""
        if self._genius is None:
            await ctx.send(
                "❌ Lyrics are disabled. Set `GENIUS_TOKEN` in `.env` and restart the bot."
            )
            return

        # Determine what to search
        if not title:
            music_cog = self.bot.get_cog("Music")
            state = music_cog.states.get(ctx.guild.id) if music_cog else None
            if state and state.current:
                title = state.current.title
            else:
                await ctx.send("❌ Nothing is playing. Provide a song title: `!lyrics <title>`")
                return

        async with ctx.typing():
            song = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._genius.search_song(title)
            )

        if not song:
            await ctx.send(f"❌ Lyrics not found for **{title}**.")
            return

        lyrics_text = song.lyrics.strip()
        # Discord has a 2000 char limit – send in chunks
        chunks = [
            lyrics_text[i:i + self.CHUNK_SIZE]
            for i in range(0, len(lyrics_text), self.CHUNK_SIZE)
        ]

        embed = discord.Embed(
            title=f"📜 {song.title} — {song.artist}",
            description=chunks[0],
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)

        for chunk in chunks[1:]:
            await ctx.send(f"```{chunk}```")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Lyrics(bot))
