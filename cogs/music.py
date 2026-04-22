"""
music.py – Core music playback cog.

Commands
--------
play      – Search / queue a song or playlist from YouTube / Spotify URL
pause     – Pause the current track
resume    – Resume a paused track
stop      – Stop playback and clear the queue
skip      – Skip the current track
queue     – Display the upcoming queue
nowplaying– Show the currently-playing track with a progress bar
volume    – Set playback volume (1-200)
seek      – Seek to a position in the current track
loop      – Toggle loop mode (off / track / queue)
shuffle   – Shuffle the queue
clear     – Clear the queue
remove    – Remove a specific track from the queue
move      – Move a track to a different queue position
disconnect– Disconnect the bot from voice
"""

from __future__ import annotations

import asyncio
import datetime
import itertools
import math
import random
from typing import Optional

import discord
import yt_dlp
from discord.ext import commands

import config


# ---------------------------------------------------------------------------
# YTDLSource – wraps yt-dlp + discord.FFmpegPCMAudio
# ---------------------------------------------------------------------------

class YTDLSource(discord.PCMVolumeTransformer):
    """A PCM audio source produced by yt-dlp."""

    ytdl = yt_dlp.YoutubeDL(config.YTDL_FORMAT_OPTIONS)

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        data: dict,
        volume: float = 1.0,
    ) -> None:
        super().__init__(source, volume)
        self.data = data
        self.title: str = data.get("title", "Unknown")
        self.url: str = data.get("url", "")
        self.webpage_url: str = data.get("webpage_url", "")
        self.thumbnail: str = data.get("thumbnail", "")
        self.duration: int = data.get("duration") or 0
        self.uploader: str = data.get("uploader", "Unknown")
        self.requester: Optional[discord.Member] = None

    @classmethod
    async def create_source(
        cls,
        ctx: commands.Context,
        search: str,
        *,
        loop: asyncio.AbstractEventLoop,
        ffmpeg_options: Optional[dict] = None,
    ) -> "YTDLSource":
        loop = loop or asyncio.get_event_loop()
        ffmpeg_options = ffmpeg_options or config.FFMPEG_OPTIONS

        data = await loop.run_in_executor(
            None,
            lambda: cls.ytdl.extract_info(search, download=False),
        )

        if "entries" in data:
            data = data["entries"][0]

        source = cls(
            discord.FFmpegPCMAudio(data["url"], **ffmpeg_options),
            data=data,
        )
        source.requester = ctx.author
        return source

    @classmethod
    async def search_source(
        cls,
        ctx: commands.Context,
        search: str,
        *,
        loop: asyncio.AbstractEventLoop,
        ffmpeg_options: Optional[dict] = None,
    ) -> list["YTDLSource"]:
        """Return up to 10 search results without fetching audio URLs."""
        loop = loop or asyncio.get_event_loop()

        data = await loop.run_in_executor(
            None,
            lambda: cls.ytdl.extract_info(f"ytsearch10:{search}", download=False),
        )

        sources = []
        for entry in data.get("entries", []):
            s = cls.__new__(cls)
            s.data = entry
            s.title = entry.get("title", "Unknown")
            s.url = entry.get("url", "")
            s.webpage_url = entry.get("webpage_url", "")
            s.thumbnail = entry.get("thumbnail", "")
            s.duration = entry.get("duration") or 0
            s.uploader = entry.get("uploader", "Unknown")
            s.requester = ctx.author
            sources.append(s)
        return sources

    @staticmethod
    def fmt_duration(seconds: int) -> str:
        if not seconds:
            return "LIVE"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# GuildState – per-guild playback state
# ---------------------------------------------------------------------------

class GuildState:
    """Holds queue and settings for a single guild."""

    def __init__(self, bot: commands.Bot, ctx: commands.Context) -> None:
        self.bot = bot
        self.ctx = ctx
        self._queue: asyncio.Queue[YTDLSource] = asyncio.Queue()
        self.queue_list: list[YTDLSource] = []   # mirror for display / shuffle
        self.current: Optional[YTDLSource] = None
        self.next: asyncio.Event = asyncio.Event()
        self.loop_mode: str = "off"              # "off" | "track" | "queue"
        self.volume: float = config.DEFAULT_VOLUME / 100
        self.ffmpeg_options: dict = dict(config.FFMPEG_OPTIONS)
        self.audio_filter: str = ""              # FFmpeg -af string
        self._play_task: asyncio.Task = bot.loop.create_task(self._player_task())
        self._inactivity_task: Optional[asyncio.Task] = None
        self._start_time: Optional[datetime.datetime] = None  # timezone-aware UTC

    # ------------------------------------------------------------------
    # Internal player loop
    # ------------------------------------------------------------------

    async def _player_task(self) -> None:
        while True:
            self.next.clear()
            try:
                async with asyncio.timeout(config.INACTIVITY_TIMEOUT):
                    source = await self._queue.get()
            except asyncio.TimeoutError:
                await self._auto_disconnect()
                return

            # Re-fetch a fresh audio URL (stream URLs expire)
            try:
                ffmpeg_opts = self._build_ffmpeg_options()
                fresh = await YTDLSource.create_source(
                    self.ctx, source.webpage_url, loop=self.bot.loop,
                    ffmpeg_options=ffmpeg_opts,
                )
                fresh.requester = source.requester
                fresh.volume = self.volume
            except Exception as exc:
                await self.ctx.send(f"⚠️ Error loading **{source.title}**: {exc}")
                continue

            self.current = fresh
            self._start_time = datetime.datetime.now(datetime.UTC)

            vc = self.ctx.voice_client
            if vc and vc.is_connected():
                vc.play(fresh, after=self._after_play)

            await self.next.wait()

            # Loop-track: re-queue the same source at the front so it plays again.
            # We use `source` (the original metadata object) rather than `self.current`
            # (the now-finished fresh stream) so that a new audio URL is fetched on the
            # next iteration and any updated filters are picked up.
            if self.loop_mode == "track":
                await self._queue.put(source)
                self.queue_list.insert(0, source)
            elif self.loop_mode == "queue":
                # Loop-queue: move played track to the back
                self.queue_list.append(source)
                await self._queue.put(source)

            # Remove the just-played entry from the mirror list
            # (it was already appended to the back for queue-loop above, so only
            # remove the *first* occurrence which was the original position)
            if source in self.queue_list and (
                self.loop_mode == "off" or self.loop_mode == "queue"
            ):
                self.queue_list.remove(source)

            self.current = None

    def _after_play(self, error: Optional[Exception]) -> None:
        if error:
            print(f"[Player] Error: {error}")
        self.next.set()

    def _build_ffmpeg_options(self) -> dict:
        opts = dict(config.FFMPEG_OPTIONS)
        if self.audio_filter:
            opts["options"] = f"-vn -af {self.audio_filter}"
        return opts

    async def _auto_disconnect(self) -> None:
        vc = self.ctx.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
        await self.ctx.send("👋 Disconnected due to inactivity.")
        self.bot.get_cog("Music").states.pop(self.ctx.guild.id, None)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def enqueue(self, source: YTDLSource) -> None:
        await self._queue.put(source)
        self.queue_list.append(source)

    def shuffle(self) -> None:
        random.shuffle(self.queue_list)
        # Rebuild internal queue from shuffled list
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for item in self.queue_list:
            self._queue.put_nowait(item)

    def clear(self) -> None:
        self.queue_list.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def stop(self) -> None:
        self.loop_mode = "off"
        self.clear()
        vc = self.ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

    def elapsed(self) -> int:
        if self._start_time is None:
            return 0
        return int((datetime.datetime.now(datetime.UTC) - self._start_time).total_seconds())

    def destroy(self) -> None:
        self._play_task.cancel()
        self.bot.get_cog("Music").states.pop(self.ctx.guild.id, None)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def is_in_voice():
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            raise commands.CheckFailure("You must be in a voice channel.")
        return True
    return commands.check(predicate)


# ---------------------------------------------------------------------------
# Music Cog
# ---------------------------------------------------------------------------

class Music(commands.Cog):
    """🎵 Powerful music playback and queue management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.states: dict[int, GuildState] = {}

    def get_state(self, ctx: commands.Context) -> GuildState:
        state = self.states.get(ctx.guild.id)
        if state is None:
            state = GuildState(self.bot, ctx)
            self.states[ctx.guild.id] = state
        return state

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    async def ensure_voice(self, ctx: commands.Context) -> Optional[discord.VoiceClient]:
        """Connect/move bot to author's voice channel. Returns VoiceClient."""
        if not ctx.author.voice:
            await ctx.send("❌ You need to be in a voice channel.")
            return None

        channel = ctx.author.voice.channel
        vc: Optional[discord.VoiceClient] = ctx.voice_client

        if vc is None:
            try:
                vc = await channel.connect()
            except discord.ClientException as exc:
                await ctx.send(f"❌ Could not connect: {exc}")
                return None
        elif vc.channel != channel:
            await vc.move_to(channel)

        return vc

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @commands.command(name="play", aliases=["p"])
    @is_in_voice()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Play a song or add it to the queue. Accepts a YouTube URL or search terms."""
        async with ctx.typing():
            vc = await self.ensure_voice(ctx)
            if vc is None:
                return

            state = self.get_state(ctx)

            try:
                source = await YTDLSource.create_source(
                    ctx, query, loop=self.bot.loop,
                )
            except yt_dlp.utils.DownloadError as exc:
                await ctx.send(f"❌ Could not find: `{query}`\n{exc}")
                return

            source.volume = state.volume
            await state.enqueue(source)

            if vc.is_playing() or vc.is_paused():
                embed = discord.Embed(
                    title="➕ Added to Queue",
                    description=f"[{source.title}]({source.webpage_url})",
                    color=discord.Color.green(),
                )
                embed.set_thumbnail(url=source.thumbnail)
                embed.add_field(name="Duration", value=YTDLSource.fmt_duration(source.duration))
                embed.add_field(name="Requested by", value=source.requester.mention)
                embed.add_field(name="Position", value=str(len(state.queue_list)))
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"▶️ Now playing: **{source.title}**")

    @commands.command(name="search", aliases=["find"])
    @is_in_voice()
    async def search(self, ctx: commands.Context, *, query: str) -> None:
        """Search YouTube and choose a result to play."""
        async with ctx.typing():
            results = await YTDLSource.search_source(ctx, query, loop=self.bot.loop)

        if not results:
            await ctx.send("❌ No results found.")
            return

        lines = []
        for i, r in enumerate(results[:10], 1):
            lines.append(
                f"`{i}.` [{r.title}]({r.webpage_url}) "
                f"— `{YTDLSource.fmt_duration(r.duration)}`"
            )

        embed = discord.Embed(
            title=f"🔍 Search results for: {query}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Reply with a number (1-10) to pick a result, or 'cancel'.")
        msg = await ctx.send(embed=embed)

        def check(m: discord.Message) -> bool:
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and (m.content.isdigit() or m.content.lower() == "cancel")
            )

        try:
            reply = await self.bot.wait_for("message", timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await msg.delete()
            return

        if reply.content.lower() == "cancel":
            await msg.delete()
            return

        idx = int(reply.content) - 1
        if not (0 <= idx < len(results)):
            await ctx.send("❌ Invalid choice.")
            return

        chosen = results[idx]
        await ctx.invoke(self.play, query=chosen.webpage_url)

    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context) -> None:
        """Pause the current track."""
        vc: discord.VoiceClient = ctx.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸️ Paused.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.command(name="resume", aliases=["unpause"])
    async def resume(self, ctx: commands.Context) -> None:
        """Resume a paused track."""
        vc: discord.VoiceClient = ctx.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶️ Resumed.")
        else:
            await ctx.send("Nothing is paused.")

    @commands.command(name="skip", aliases=["s", "next"])
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current track."""
        vc: discord.VoiceClient = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await ctx.send("⏭️ Skipped.")
        else:
            await ctx.send("Nothing is playing.")

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context) -> None:
        """Stop playback and clear the queue."""
        state = self.get_state(ctx)
        state.stop()
        await ctx.send("⏹️ Stopped and cleared the queue.")

    @commands.command(name="volume", aliases=["vol", "v"])
    async def volume(self, ctx: commands.Context, vol: int) -> None:
        """Set the playback volume (1-200)."""
        if not (1 <= vol <= config.MAX_VOLUME):
            await ctx.send(f"❌ Volume must be between 1 and {config.MAX_VOLUME}.")
            return

        state = self.get_state(ctx)
        state.volume = vol / 100

        vc: discord.VoiceClient = ctx.voice_client
        if vc and vc.source:
            vc.source.volume = state.volume

        await ctx.send(f"🔊 Volume set to **{vol}%**.")

    @commands.command(name="nowplaying", aliases=["np", "current"])
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Show what's currently playing with a progress bar."""
        state = self.get_state(ctx)
        track = state.current

        if not track:
            await ctx.send("Nothing is playing right now.")
            return

        elapsed = state.elapsed()
        duration = track.duration

        # Build progress bar
        if duration:
            ratio = min(elapsed / duration, 1.0)
            bar_len = 20
            filled = int(bar_len * ratio)
            bar = "▓" * filled + "░" * (bar_len - filled)
            progress = f"`{YTDLSource.fmt_duration(elapsed)}` [{bar}] `{YTDLSource.fmt_duration(duration)}`"
        else:
            progress = "🔴 LIVE"

        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"[{track.title}]({track.webpage_url})",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=track.thumbnail)
        embed.add_field(name="Progress", value=progress, inline=False)
        embed.add_field(name="Uploader", value=track.uploader)
        embed.add_field(name="Requested by", value=track.requester.mention if track.requester else "Unknown")
        embed.add_field(name="Volume", value=f"{int(state.volume * 100)}%")
        embed.add_field(name="Loop", value=state.loop_mode.capitalize())

        await ctx.send(embed=embed)

    @commands.command(name="queue", aliases=["q", "playlist"])
    async def queue(self, ctx: commands.Context, page: int = 1) -> None:
        """Display the current queue."""
        state = self.get_state(ctx)
        items = state.queue_list

        if not items and not state.current:
            await ctx.send("The queue is empty.")
            return

        per_page = 10
        pages = math.ceil(len(items) / per_page) if items else 1
        page = max(1, min(page, pages))
        start = (page - 1) * per_page
        chunk = items[start:start + per_page]

        lines = []
        for i, src in enumerate(chunk, start + 1):
            lines.append(
                f"`{i}.` [{src.title}]({src.webpage_url}) "
                f"— `{YTDLSource.fmt_duration(src.duration)}` "
                f"— {src.requester.mention if src.requester else 'Unknown'}"
            )

        now = state.current
        now_line = (
            f"**Now:** [{now.title}]({now.webpage_url})\n\n"
            if now else ""
        )

        embed = discord.Embed(
            title=f"📋 Queue — {len(items)} track(s)",
            description=now_line + ("\n".join(lines) if lines else "No upcoming tracks."),
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Page {page}/{pages} • Loop: {state.loop_mode}")
        await ctx.send(embed=embed)

    @commands.command(name="shuffle")
    async def shuffle(self, ctx: commands.Context) -> None:
        """Shuffle the queue."""
        state = self.get_state(ctx)
        if not state.queue_list:
            await ctx.send("The queue is empty.")
            return
        state.shuffle()
        await ctx.send("🔀 Queue shuffled.")

    @commands.command(name="loop", aliases=["repeat"])
    async def loop(self, ctx: commands.Context, mode: str = "track") -> None:
        """Set loop mode: `off`, `track`, or `queue`."""
        mode = mode.lower()
        if mode not in ("off", "track", "queue"):
            await ctx.send("❌ Mode must be `off`, `track`, or `queue`.")
            return
        state = self.get_state(ctx)
        state.loop_mode = mode
        emoji = {"off": "➡️", "track": "🔂", "queue": "🔁"}[mode]
        await ctx.send(f"{emoji} Loop mode set to **{mode}**.")

    @commands.command(name="clear")
    async def clear(self, ctx: commands.Context) -> None:
        """Clear all tracks from the queue."""
        state = self.get_state(ctx)
        state.clear()
        await ctx.send("🗑️ Queue cleared.")

    @commands.command(name="remove", aliases=["rm"])
    async def remove(self, ctx: commands.Context, index: int) -> None:
        """Remove a track from the queue by its position number."""
        state = self.get_state(ctx)
        items = state.queue_list

        if not items:
            await ctx.send("The queue is empty.")
            return
        if not (1 <= index <= len(items)):
            await ctx.send(f"❌ Index must be between 1 and {len(items)}.")
            return

        removed = items.pop(index - 1)
        # Rebuild internal queue
        while not state._queue.empty():
            try:
                state._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for item in items:
            state._queue.put_nowait(item)

        await ctx.send(f"🗑️ Removed **{removed.title}** from the queue.")

    @commands.command(name="move", aliases=["mv"])
    async def move(self, ctx: commands.Context, from_pos: int, to_pos: int) -> None:
        """Move a track from one queue position to another."""
        state = self.get_state(ctx)
        items = state.queue_list
        n = len(items)

        if not items:
            await ctx.send("The queue is empty.")
            return
        if not (1 <= from_pos <= n and 1 <= to_pos <= n):
            await ctx.send(f"❌ Positions must be between 1 and {n}.")
            return

        track = items.pop(from_pos - 1)
        items.insert(to_pos - 1, track)

        # Rebuild internal queue
        while not state._queue.empty():
            try:
                state._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        for item in items:
            state._queue.put_nowait(item)

        await ctx.send(f"↕️ Moved **{track.title}** to position **{to_pos}**.")

    @commands.command(name="disconnect", aliases=["dc", "leave"])
    async def disconnect(self, ctx: commands.Context) -> None:
        """Disconnect the bot from the voice channel."""
        vc: discord.VoiceClient = ctx.voice_client
        if vc:
            state = self.states.pop(ctx.guild.id, None)
            if state:
                state.destroy()
            await vc.disconnect()
            await ctx.send("👋 Disconnected.")
        else:
            await ctx.send("I'm not in a voice channel.")

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @play.error
    @search.error
    async def play_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ Please provide a song name or URL.")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(f"❌ {error}")
        else:
            await ctx.send(f"❌ An error occurred: {error}")

    @volume.error
    async def volume_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.BadArgument):
            await ctx.send("❌ Volume must be an integer (e.g. `!volume 80`).")

    @remove.error
    @move.error
    async def index_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.BadArgument):
            await ctx.send("❌ Please provide valid number(s).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
