import os
from pathlib import Path

API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "your_api_hash")
BOT_TOKEN = os.getenv("BOT_TOKEN", "123456:ABC-DEF")
MONGO_URI = os.getenv("MONGO_URI", "")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1001234567890"))

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", BASE_DIR / "downloads"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", BASE_DIR / "cache"))
SETTINGS_FILE = Path(os.getenv("SETTINGS_FILE", CACHE_DIR / "user_settings.json"))
