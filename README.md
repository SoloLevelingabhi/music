# 🎵 Music Editor Bot

A **powerful Discord music editor bot** built with [discord.py](https://discordpy.readthedocs.io/) and [yt-dlp](https://github.com/yt-dlp/yt-dlp).  
Stream music from YouTube, manage a rich queue, and apply real-time audio effects — all from Discord.

---

## ✨ Features

| Category | Commands |
|---|---|
| **Playback** | `play`, `search`, `pause`, `resume`, `stop`, `skip` |
| **Queue** | `queue`, `nowplaying`, `shuffle`, `loop`, `clear`, `remove`, `move` |
| **Volume** | `volume` (1–200 %) |
| **Audio Effects** | `bassboost`, `nightcore`, `vaporwave`, `8d`, `echo`, `treble`, `speed`, `pitch`, `equalizer`, `filter`, `resetfx` |
| **Lyrics** | `lyrics` (requires Genius token) |
| **Utility** | `ping`, `invite`, `help` |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and on your `PATH`
- A [Discord Bot token](https://discord.com/developers/applications)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/SoloLevelingabhi/music.git
cd music

# 2. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure the bot
cp .env.example .env
# Edit .env and set your DISCORD_TOKEN (and optional API keys)

# 5. Run the bot
python bot.py
```

---

## ⚙️ Configuration (`.env`)

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | ✅ | Your Discord bot token |
| `PREFIX` | ❌ | Command prefix (default: `!`) |
| `GENIUS_TOKEN` | ❌ | [Genius API](https://genius.com/api-clients) token for lyrics |
| `SPOTIFY_CLIENT_ID` | ❌ | Spotify app client ID (future use) |
| `SPOTIFY_CLIENT_SECRET` | ❌ | Spotify app client secret (future use) |

---

## 🎵 Command Reference

### Playback

| Command | Aliases | Description |
|---|---|---|
| `!play <query|URL>` | `!p` | Play a song or add it to the queue |
| `!search <query>` | `!find` | Search YouTube and pick from 10 results |
| `!pause` | — | Pause the current track |
| `!resume` | `!unpause` | Resume a paused track |
| `!skip` | `!s`, `!next` | Skip to the next track |
| `!stop` | — | Stop playback and clear the queue |
| `!nowplaying` | `!np`, `!current` | Show the current track with progress bar |
| `!disconnect` | `!dc`, `!leave` | Disconnect from the voice channel |

### Queue Management

| Command | Aliases | Description |
|---|---|---|
| `!queue [page]` | `!q`, `!playlist` | Show the queue (paginated) |
| `!shuffle` | — | Shuffle the queue |
| `!loop <off|track|queue>` | `!repeat` | Set loop mode |
| `!clear` | — | Clear all queued tracks |
| `!remove <index>` | `!rm` | Remove a track by queue position |
| `!move <from> <to>` | `!mv` | Move a track to a different position |

### Volume

| Command | Aliases | Description |
|---|---|---|
| `!volume <1-200>` | `!vol`, `!v` | Set playback volume |

### 🎚️ Audio Effects

All effects apply to the **next** track you play (or after `!skip`).

| Command | Description |
|---|---|
| `!filter [preset]` | List or apply a named effect preset |
| `!bassboost [gain]` | Bass boost by `gain` dB (1–20, default 8) |
| `!nightcore` | Speed + pitch up (Nightcore style) |
| `!vaporwave` | Speed + pitch down (Vaporwave style) |
| `!8d` | 8D panning surround effect |
| `!echo [delay] [decay]` | Echo/reverb effect |
| `!treble [gain]` | Treble boost/cut in dB |
| `!speed <0.5-2.0>` | Change playback speed |
| `!pitch <-12 to +12>` | Shift pitch in semitones |
| `!equalizer <b32> <b64> ... <b16k>` | 10-band EQ (gains in dB) |
| `!resetfx` | Remove all audio effects |

**Filter presets** (use `!filter`):  
`bassboost` · `nightcore` · `vaporwave` · `8d` · `echo` · `karaoke` · `loud` · `clear`

### 📜 Lyrics

| Command | Aliases | Description |
|---|---|---|
| `!lyrics [title]` | `!ly` | Fetch lyrics for the current song or a given title |

---

## 🏗️ Project Structure

```
music/
├── bot.py              # Entry point, bot class, utility commands
├── config.py           # Configuration loaded from .env
├── requirements.txt    # Python dependencies
├── .env.example        # Template for environment variables
└── cogs/
    ├── music.py        # Core playback & queue commands
    ├── filters.py      # Audio effects & equalizer commands
    └── lyrics.py       # Song lyrics (Genius API)
```

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run with auto-reload (requires watchdog)
# pip install watchdog
# python -m watchdog.watchmedo auto-restart --pattern="*.py" -- python bot.py
```

---

## 📄 License

MIT License – see [LICENSE](LICENSE) for details.
