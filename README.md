# 🎵 Smart Audio Studio Bot

A professional Telegram audio editing bot with interactive color UI, built with Pyrofork and MongoDB.

[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/yourusername/smart-audio-studio-bot)

## ✨ Features

- ✂️ **Trim & Merge** - Cut and combine audio files
- 🔊 **Volume & Speed** - Adjust volume and playback speed
- 🎨 **Effects** - Normalize, bass boost, noise reduction
- 📦 **Format Conversion** - MP3, WAV, FLAC, OGG, M4A
- 🏷️ **ID3 Tags** - Edit metadata and add thumbnails
- 💾 **Session Management** - Resume editing anytime
- 🎯 **Preview System** - Listen before exporting

## 🚀 Quick Deploy

### One-Click Heroku Deploy

1. Click the Deploy button above
2. Fill in the required environment variables:
   - `API_ID` - Get from [my.telegram.org](https://my.telegram.org)
   - `API_HASH` - Get from [my.telegram.org](https://my.telegram.org)
   - `BOT_TOKEN` - Get from [@BotFather](https://t.me/BotFather)
   - `MONGO_URI` - MongoDB connection string (use [MongoDB Atlas](https://mongodb.com/atlas) free tier)
3. Click "Deploy App"

### Manual Deployment

```bash
# Clone repo
git clone https://github.com/yourusername/smart-audio-studio-bot
cd smart-audio-studio-bot

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export API_ID="your_api_id"
export API_HASH="your_api_hash"
export BOT_TOKEN="your_bot_token"
export MONGO_URI="your_mongodb_uri"

# Run bot
python bot.py
