# 🎵 Smart Audio Studio Bot

A professional Telegram audio editing bot with interactive color UI, built with Pyrofork and MongoDB.

## 🚀 One-Click Deploy

| Platform | Deploy Button |
|----------|---------------|
| **Heroku** | [![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/yourusername/smart-audio-studio-bot) |
| **Render** | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/yourusername/smart-audio-studio-bot) |
| **Koyeb** | [![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy?type=git&repository=github.com/yourusername/smart-audio-studio-bot&branch=main&name=audio-editor-bot) |
| **Railway** | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/your-template-id) |
| **Zeabur** | [![Deploy on Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/templates/your-template-id) |
| **Fly.io** | `fly launch --image ghcr.io/yourusername/smart-audio-studio-bot` |
| **DigitalOcean** | [![Deploy to DO](https://www.deploytodo.com/do-btn.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/yourusername/smart-audio-studio-bot/tree/main) |

## ✨ Features

- ✂️ **Trim & Merge** - Cut and combine audio files
- 🔊 **Volume & Speed** - Adjust volume (0.5x-2x)
- 🎨 **Effects** - Normalize, bass boost, noise reduction
- 📦 **Format Conversion** - MP3, WAV, FLAC, OGG, M4A
- 🏷️ **ID3 Tags** - Edit metadata and thumbnails
- 💾 **Session Management** - Resume editing anytime
- 🎯 **Preview System** - 15s preview before export
- 🔄 **Undo/Redo** - Revert unwanted changes

## 📋 Quick Setup

### 1. Get Required Tokens

| Token | Source | How to Get |
|-------|--------|------------|
| `API_ID` | [my.telegram.org](https://my.telegram.org) | Login → Create Application |
| `API_HASH` | [my.telegram.org](https://my.telegram.org) | Login → Create Application |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) | `/newbot` → Copy token |
| `MONGO_URI` | [MongoDB Atlas](https://mongodb.com/atlas) | Free tier → Create cluster → Connect |

### 2. Deploy to Platform

Choose any platform above and fill the required environment variables.

### 3. FFmpeg Setup by Platform

| Platform | FFmpeg Installation |
|----------|---------------------|
| **Heroku** | Add buildpack: `heroku buildpacks:add https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git` |
| **Render** | Uses Dockerfile (FFmpeg pre-installed) |
| **Koyeb** | Uses Dockerfile (FFmpeg pre-installed) |
| **Railway** | Uses nixpacks (auto-detects FFmpeg) |
| **Zeabur** | Auto-installs via apt |

## 🛠️ Local Development

```bash
# Clone repository
git clone https://github.com/yourusername/smart-audio-studio-bot
cd smart-audio-studio-bot

# Install FFmpeg
# Ubuntu/Debian: sudo apt install ffmpeg
# macOS: brew install ffmpeg
# Windows: Download from ffmpeg.org

# Install Python dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
MONGO_URI=mongodb://localhost:27017
EOF

# Run bot
python bot.py

## 📁 File Structure
smart-audio-studio-bot/
├── .github/
│   └── workflows/
│       └── deploy.yml
├── bot.py                    # Main bot file
├── config.py                 # Configuration handler
├── alive.py                  # Keep-alive web server
├── requirements.txt          # Python dependencies
├── Dockerfile               # Docker configuration
├── Procfile                 # Heroku process file
├── runtime.txt              # Python version for Heroku
├── app.json                 # Heroku deploy config
├── heroku.yml               # Heroku Docker config
├── render.yaml              # Render deploy config
├── koyeb.yaml               # Koyeb deploy config
├── railway.json             # Railway deploy config
├── fly.toml                 # Fly.io deploy config
├── zeabur.yaml              # Zeabur deploy config
└── README.md                # Documentation
