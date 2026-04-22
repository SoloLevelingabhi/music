import os
import config
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo


app = Client(
    "music_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)


# ============================= START BOT =============================
if __name__ == "__main__":
    logger.info("🚀 Starting Music Bot...")
    app.run()
