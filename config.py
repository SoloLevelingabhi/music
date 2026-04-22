# config.py - fill these values before running
import os

API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "your_api_hash")
BOT_TOKEN = os.getenv("BOT_TOKEN", "123456:ABC-DEF")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1001234567890"))  # channel to forward uploads to
