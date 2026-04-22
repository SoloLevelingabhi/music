"""
filters.py – Audio effects / equalizer cog.

Commands
--------
filter      – Apply a named audio filter preset (or list all)
bassboost   – Boost bass (0-20 dB)
nightcore   – Nightcore effect (speed+pitch up)
vaporwave   – Vaporwave effect (speed+pitch down)
8d          – 8D surround sound effect
echo        – Add echo / reverb
treble      – Boost treble (0-20 dB)
speed       – Change playback speed (0.5–2.0x)
pitch       – Change pitch in semitones (-12 to +12)
equalizer   – 10-band equalizer shortcut
resetfx     – Remove all audio effects
"""

from __future__ import annotations

import discord
from discord.ext import commands

import config

# ---------------------------------------------------------------------------
# Preset filters
# ---------------------------------------------------------------------------

PRESETS: dict[str, tuple[str, str]] = {
    # name: (ffmpeg_af_string, description)
    "bassboost":  (
        "equalizer=f=40:width_type=o:width=2:g=8,"
        "equalizer=f=60:width_type=o:width=2:g=5,"
        "equalizer=f=80:width_type=o:width=2:g=3",
        "Heavy bass boost",
    ),
    "nightcore":  (
        "asetrate=48000*1.25,aresample=48000,atempo=1.0",
        "Speed+pitch up (Nightcore)",
    ),
    "vaporwave":  (
        "asetrate=48000*0.8,aresample=48000,atempo=1.0",
        "Speed+pitch down (Vaporwave)",
    ),
    "8d":         (
        "apulsator=hz=0.08",
        "8D surround panning effect",
    ),
    "echo":       (
        "aecho=0.8:0.9:1000:0.3",
        "Echo / reverb effect",
    ),
    "karaoke":    (
        "pan=stereo|c0=c0-c1|c1=c1-c0",
        "Reduce centre (vocal removal attempt)",
    ),
    "loud":       (
        "dynaudnorm=g=101",
        "Dynamic loudness normalisation",
    ),
    "clear":      (
        "",
        "Remove all audio effects",
    ),
}


def _apply_filter(ctx: commands.Context, af: str) -> None:
    """Update the guild state with a new FFmpeg audio-filter string."""
    music_cog = ctx.bot.get_cog("Music")
    if not music_cog:
        return
    state = music_cog.states.get(ctx.guild.id)
    if state:
        state.audio_filter = af


class Filters(commands.Cog):
    """🎚️ Audio effects and equalizer."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Generic filter command
    # ------------------------------------------------------------------

    @commands.command(name="filter", aliases=["fx"])
    async def filter_cmd(self, ctx: commands.Context, preset: str = "") -> None:
        """Apply a named filter preset, or list all presets when used with no argument."""
        if not preset:
            lines = []
            for name, (_, desc) in PRESETS.items():
                lines.append(f"`{name}` – {desc}")
            embed = discord.Embed(
                title="🎚️ Available Filter Presets",
                description="\n".join(lines),
                color=discord.Color.orange(),
            )
            embed.set_footer(text=f"Usage: {ctx.prefix}filter <preset>  |  {ctx.prefix}resetfx to clear")
            await ctx.send(embed=embed)
            return

        preset = preset.lower()
        if preset not in PRESETS:
            await ctx.send(
                f"❌ Unknown preset `{preset}`. Use `{ctx.prefix}filter` to list all."
            )
            return

        af, desc = PRESETS[preset]
        _apply_filter(ctx, af)

        vc: discord.VoiceClient = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            await ctx.send(
                f"✅ Filter **{preset}** applied ({desc}).\n"
                "⚠️ Skip the current track to hear the effect: "
                f"`{ctx.prefix}skip`"
            )
        else:
            await ctx.send(f"✅ Filter **{preset}** set ({desc}). It will apply to the next track.")

    # ------------------------------------------------------------------
    # Individual effect commands
    # ------------------------------------------------------------------

    @commands.command(name="bassboost", aliases=["bb"])
    async def bassboost(self, ctx: commands.Context, gain: int = 8) -> None:
        """Bass boost by `gain` dB (1-20). Default: 8."""
        gain = max(1, min(gain, 20))
        af = (
            f"equalizer=f=40:width_type=o:width=2:g={gain},"
            f"equalizer=f=60:width_type=o:width=2:g={max(gain-3,0)},"
            f"equalizer=f=80:width_type=o:width=2:g={max(gain-5,0)}"
        )
        _apply_filter(ctx, af)
        await ctx.send(
            f"🔊 Bass boost set to **+{gain} dB**. "
            f"Use `{ctx.prefix}skip` to apply to the current track."
        )

    @commands.command(name="nightcore", aliases=["nc"])
    async def nightcore(self, ctx: commands.Context) -> None:
        """Apply the Nightcore effect (speed + pitch up)."""
        af = "asetrate=48000*1.25,aresample=48000,atempo=1.0"
        _apply_filter(ctx, af)
        await ctx.send(f"🌙 Nightcore effect applied. Use `{ctx.prefix}skip` to hear it.")

    @commands.command(name="vaporwave", aliases=["vw"])
    async def vaporwave(self, ctx: commands.Context) -> None:
        """Apply the Vaporwave effect (speed + pitch down)."""
        af = "asetrate=48000*0.8,aresample=48000,atempo=1.0"
        _apply_filter(ctx, af)
        await ctx.send(f"🌊 Vaporwave effect applied. Use `{ctx.prefix}skip` to hear it.")

    @commands.command(name="8d")
    async def eight_d(self, ctx: commands.Context) -> None:
        """Apply the 8D audio panning effect."""
        af = "apulsator=hz=0.08"
        _apply_filter(ctx, af)
        await ctx.send(f"🎧 8D effect applied. Use `{ctx.prefix}skip` to hear it.")

    @commands.command(name="echo")
    async def echo(self, ctx: commands.Context, delay: int = 1000, decay: float = 0.3) -> None:
        """Add echo effect. `delay` = ms (100-5000), `decay` = 0.1-0.9."""
        delay = max(100, min(delay, 5000))
        decay = max(0.1, min(decay, 0.9))
        af = f"aecho=0.8:0.9:{delay}:{decay:.1f}"
        _apply_filter(ctx, af)
        await ctx.send(
            f"🔁 Echo: delay **{delay}ms**, decay **{decay:.1f}**. "
            f"Use `{ctx.prefix}skip` to hear it."
        )

    @commands.command(name="treble")
    async def treble(self, ctx: commands.Context, gain: int = 5) -> None:
        """Boost or cut treble by `gain` dB (-20 to 20). Default: 5."""
        gain = max(-20, min(gain, 20))
        af = f"equalizer=f=8000:width_type=o:width=2:g={gain}"
        _apply_filter(ctx, af)
        sign = "+" if gain >= 0 else ""
        await ctx.send(
            f"🎵 Treble set to **{sign}{gain} dB**. "
            f"Use `{ctx.prefix}skip` to apply to the current track."
        )

    @commands.command(name="speed")
    async def speed(self, ctx: commands.Context, rate: float = 1.0) -> None:
        """Change playback speed (0.5 – 2.0). Default: 1.0."""
        rate = max(0.5, min(rate, 2.0))
        af = f"atempo={rate:.2f}"
        _apply_filter(ctx, af)
        await ctx.send(
            f"⏩ Speed set to **{rate:.2f}x**. "
            f"Use `{ctx.prefix}skip` to apply to the current track."
        )

    @commands.command(name="pitch")
    async def pitch(self, ctx: commands.Context, semitones: int = 0) -> None:
        """Shift pitch by semitones (-12 to +12). Default: 0."""
        semitones = max(-12, min(semitones, 12))
        rate = 2 ** (semitones / 12)
        # asetrate changes pitch without tempo; compensate with atempo
        af = f"asetrate=48000*{rate:.4f},aresample=48000,atempo={1/rate:.4f}"
        _apply_filter(ctx, af)
        sign = "+" if semitones >= 0 else ""
        await ctx.send(
            f"🎼 Pitch shifted **{sign}{semitones} semitones**. "
            f"Use `{ctx.prefix}skip` to apply."
        )

    @commands.command(name="equalizer", aliases=["eq"])
    async def equalizer(
        self,
        ctx: commands.Context,
        b32: int = 0,
        b64: int = 0,
        b125: int = 0,
        b250: int = 0,
        b500: int = 0,
        b1k: int = 0,
        b2k: int = 0,
        b4k: int = 0,
        b8k: int = 0,
        b16k: int = 0,
    ) -> None:
        """10-band equalizer. Provide gain values in dB for each band.

        Bands (Hz): 32 64 125 250 500 1k 2k 4k 8k 16k
        Example: `!eq 4 3 2 0 0 0 0 1 2 3`
        """
        bands = [
            (32,    b32),
            (64,    b64),
            (125,   b125),
            (250,   b250),
            (500,   b500),
            (1000,  b1k),
            (2000,  b2k),
            (4000,  b4k),
            (8000,  b8k),
            (16000, b16k),
        ]
        parts = [
            f"equalizer=f={freq}:width_type=o:width=1:g={gain}"
            for freq, gain in bands
            if gain != 0
        ]
        af = ",".join(parts) if parts else ""
        _apply_filter(ctx, af)

        rows = " | ".join(f"`{f//1000 if f>=1000 else f}{'k' if f>=1000 else ''}Hz: {'+' if g>=0 else ''}{g}`" for f, g in bands)
        await ctx.send(
            f"🎚️ EQ applied:\n{rows}\n"
            f"Use `{ctx.prefix}skip` to hear it."
        )

    @commands.command(name="resetfx", aliases=["clearfx", "nofx"])
    async def resetfx(self, ctx: commands.Context) -> None:
        """Remove all audio effects / filters."""
        _apply_filter(ctx, "")
        await ctx.send(
            f"✨ All audio effects removed. "
            f"Use `{ctx.prefix}skip` to apply to the current track."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Filters(bot))
