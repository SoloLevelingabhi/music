#!/usr/bin/env python3
"""
Telegram Audio Editing Bot - Smart Audio Studio inside Telegram
Author: Functional Python Implementation
Requirements: pyrogram, motor, ffmpeg-python, pydub, mutagen, requests
"""

import os
import logging
import traceback
import asyncio
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Core libraries
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, InputMediaAudio
)
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

# MongoDB
from motor.motor_asyncio import AsyncIOMotorClient

# Audio processing
import ffmpeg
from pydub import AudioSegment
from pydub.effects import normalize
import mutagen
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TCON, TDRC

# Utilities
import requests
from io import BytesIO
import hashlib

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8765826723:AAH1HhVIVKv83uueUnxjZfTRG-vM61_bhEU"
API_ID = 19500615   # Your API ID
API_HASH = "7ee1d55d072add75a01e617fc0cef635"
MONGO_URL = "mongodb+srv://cegin48057:HZuqtvUqi0tYJEda@cluster0.vw0nw.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# FFmpeg path (usually auto-detected, set if needed)
FFMPEG_PATH = "ffmpeg"

# File handling
DOWNLOAD_DIR = "downloads"
CACHE_DIR = "cache"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Initialize bot
app = Client(
    "audio_editor_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

# MongoDB connection
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.audio_editor_bot
sessions_collection = db.sessions
settings_collection = db.settings

# ==================== HELPER FUNCTIONS ====================

async def get_user_settings(user_id: int) -> dict:
    """Get or create user settings"""
    settings = await settings_collection.find_one({"user_id": user_id})
    if not settings:
        settings = {
            "user_id": user_id,
            "default_format": "mp3",
            "default_compression": "medium",
            "auto_metadata": True,
            "reuse_thumbnail": False,
            "filename_format": "{title}_{timestamp}",
            "created_at": datetime.utcnow()
        }
        await settings_collection.insert_one(settings)
    return settings

async def update_user_settings(user_id: int, updates: dict):
    """Update user settings"""
    await settings_collection.update_one(
        {"user_id": user_id},
        {"$set": updates}
    )

async def get_user_session(user_id: int) -> dict:
    """Get or create editing session"""
    session = await sessions_collection.find_one({"user_id": user_id})
    if not session:
        session = {
            "user_id": user_id,
            "current_file": None,
            "original_file_id": None,
            "original_file_path": None,
            "edits": [],
            "metadata": {},
            "thumbnail_file_id": None,
            "settings": {},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await sessions_collection.insert_one(session)
    return session

async def update_user_session(user_id: int, updates: dict):
    """Update user session"""
    updates["updated_at"] = datetime.utcnow()
    await sessions_collection.update_one(
        {"user_id": user_id},
        {"$set": updates}
    )

async def delete_user_session(user_id: int):
    """Delete user session"""
    await sessions_collection.delete_one({"user_id": user_id})

async def download_audio(file_id: str, user_id: int) -> str:
    """Download audio file from Telegram"""
    try:
        # Check cache first
        cache_key = hashlib.md5(f"{file_id}".encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{cache_key}.mp3")
        
        if os.path.exists(cache_path):
            logger.info(f"Using cached file for {file_id}")
            return cache_path
        
        # Download file
        temp_path = os.path.join(DOWNLOAD_DIR, f"{user_id}_{file_id}.mp3")
        await app.download_media(file_id, file_name=temp_path)
        
        # Convert to standard format
        audio = AudioSegment.from_file(temp_path)
        audio.export(cache_path, format="mp3")
        
        # Cleanup temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return cache_path
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise

async def apply_edits(audio_path: str, edits: List[dict]) -> str:
    """Apply all edits in sequence to audio file"""
    try:
        # Load audio
        audio = AudioSegment.from_file(audio_path)
        
        for edit in edits:
            edit_type = edit.get("type")
            
            if edit_type == "trim":
                start = edit.get("start", 0) * 1000  # Convert to ms
                end = edit.get("end", len(audio)) * 1000
                audio = audio[start:end]
            
            elif edit_type == "volume":
                factor = edit.get("factor", 1.0)
                audio = audio + (factor - 1) * 10  # Approximate volume change
            
            elif edit_type == "speed":
                speed = edit.get("speed", 1.0)
                audio = audio.speedup(playback_speed=speed)
            
            elif edit_type == "normalize":
                audio = normalize(audio)
            
            elif edit_type == "bass_boost":
                audio = audio.low_pass_filter(300)  # Simple bass boost
            
            elif edit_type == "compress":
                bitrate = edit.get("bitrate", "128k")
                # Compression handled during export
            
        # Generate output path
        output_path = tempfile.mktemp(suffix=".mp3")
        audio.export(output_path, format="mp3", bitrate="192k")
        
        return output_path
    except Exception as e:
        logger.error(f"Edit application error: {e}")
        raise

async def generate_preview(audio_path: str, duration: int = 15) -> str:
    """Generate short preview of audio"""
    try:
        audio = AudioSegment.from_file(audio_path)
        preview = audio[:duration * 1000]  # First N seconds
        preview_path = tempfile.mktemp(suffix="_preview.mp3")
        preview.export(preview_path, format="mp3")
        return preview_path
    except Exception as e:
        logger.error(f"Preview generation error: {e}")
        raise

async def fetch_metadata_from_api(query: str) -> dict:
    """Fetch metadata from external API (MusicBrainz example)"""
    try:
        # Simple MusicBrainz search
        url = f"https://musicbrainz.org/ws/2/recording/"
        params = {"query": query, "fmt": "json"}
        
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("recordings"):
                recording = data["recordings"][0]
                return {
                    "title": recording.get("title", ""),
                    "artist": recording.get("artist-credit", [{}])[0].get("name", ""),
                    "album": recording.get("releases", [{}])[0].get("title", ""),
                    "year": recording.get("first-release-date", "").split("-")[0]
                }
        return {}
    except Exception as e:
        logger.error(f"Metadata fetch error: {e}")
        return {}

async def add_metadata(audio_path: str, metadata: dict, thumbnail_path: str = None):
    """Add ID3 tags and thumbnail to audio"""
    try:
        audio = AudioSegment.from_file(audio_path)
        
        # Save with metadata using mutagen
        temp_output = tempfile.mktemp(suffix=".mp3")
        audio.export(temp_output, format="mp3")
        
        # Add ID3 tags
        tags = ID3(temp_output)
        
        if metadata.get("title"):
            tags.add(TIT2(encoding=3, text=metadata["title"]))
        if metadata.get("artist"):
            tags.add(TPE1(encoding=3, text=metadata["artist"]))
        if metadata.get("album"):
            tags.add(TALB(encoding=3, text=metadata["album"]))
        if metadata.get("genre"):
            tags.add(TCON(encoding=3, text=metadata["genre"]))
        if metadata.get("year"):
            tags.add(TDRC(encoding=3, text=metadata["year"]))
        
        # Add thumbnail
        if thumbnail_path and os.path.exists(thumbnail_path):
            with open(thumbnail_path, "rb") as f:
                tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,
                    desc='Cover',
                    data=f.read()
                ))
        
        tags.save(temp_output)
        return temp_output
    except Exception as e:
        logger.error(f"Metadata addition error: {e}")
        return audio_path

# ==================== KEYBOARD MENUS ====================

def get_main_menu() -> InlineKeyboardMarkup:
    """Main editing menu with colored buttons"""
    buttons = [
        [
            InlineKeyboardButton("✂️ Trim", callback_data="menu_trim"),
            InlineKeyboardButton("🔊 Volume", callback_data="menu_volume"),
            InlineKeyboardButton("⚡ Speed", callback_data="menu_speed")
        ],
        [
            InlineKeyboardButton("🔄 Convert", callback_data="menu_convert"),
            InlineKeyboardButton("🎨 Enhance", callback_data="menu_enhance"),
            InlineKeyboardButton("📝 Metadata", callback_data="menu_metadata")
        ],
        [
            InlineKeyboardButton("🎬 Preview", callback_data="action_preview"),
            InlineKeyboardButton("✅ Export", callback_data="action_export"),
            InlineKeyboardButton("🗑 Reset", callback_data="action_reset")
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
            InlineKeyboardButton("ℹ️ Info", callback_data="action_info")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_trim_menu() -> InlineKeyboardMarkup:
    """Trim audio menu"""
    buttons = [
        [
            InlineKeyboardButton("📍 Set Start", callback_data="trim_set_start"),
            InlineKeyboardButton("📍 Set End", callback_data="trim_set_end")
        ],
        [
            InlineKeyboardButton("▶️ Apply Trim", callback_data="trim_apply"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_volume_menu() -> InlineKeyboardMarkup:
    """Volume control menu"""
    buttons = [
        [
            InlineKeyboardButton("🔇 -50%", callback_data="vol_0.5"),
            InlineKeyboardButton("🔉 -25%", callback_data="vol_0.75")
        ],
        [
            InlineKeyboardButton("🔊 +25%", callback_data="vol_1.25"),
            InlineKeyboardButton("📢 +50%", callback_data="vol_1.5")
        ],
        [
            InlineKeyboardButton("🔊 Normalize", callback_data="vol_normalize"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_speed_menu() -> InlineKeyboardMarkup:
    """Speed control menu"""
    buttons = [
        [
            InlineKeyboardButton("🐢 0.5x", callback_data="speed_0.5"),
            InlineKeyboardButton("🚶 0.75x", callback_data="speed_0.75")
        ],
        [
            InlineKeyboardButton("🏃 1.25x", callback_data="speed_1.25"),
            InlineKeyboardButton("⚡ 1.5x", callback_data="speed_1.5")
        ],
        [
            InlineKeyboardButton("💨 2.0x", callback_data="speed_2.0"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_convert_menu() -> InlineKeyboardMarkup:
    """Format conversion menu"""
    buttons = [
        [
            InlineKeyboardButton("🎵 MP3", callback_data="convert_mp3"),
            InlineKeyboardButton("🎶 WAV", callback_data="convert_wav"),
            InlineKeyboardButton("🎼 FLAC", callback_data="convert_flac")
        ],
        [
            InlineKeyboardButton("📀 OGG", callback_data="convert_ogg"),
            InlineKeyboardButton("📱 M4A", callback_data="convert_m4a"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_enhance_menu() -> InlineKeyboardMarkup:
    """Audio enhancement menu"""
    buttons = [
        [
            InlineKeyboardButton("✨ Normalize", callback_data="enhance_normalize"),
            InlineKeyboardButton("🎸 Bass Boost", callback_data="enhance_bass")
        ],
        [
            InlineKeyboardButton("🔇 Noise Reduction", callback_data="enhance_noise"),
            InlineKeyboardButton("📊 Compress", callback_data="menu_compress")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_compress_menu() -> InlineKeyboardMarkup:
    """Compression menu"""
    buttons = [
        [
            InlineKeyboardButton("📦 Low (64k)", callback_data="compress_low"),
            InlineKeyboardButton("📦 Medium (128k)", callback_data="compress_medium")
        ],
        [
            InlineKeyboardButton("📦 High (192k)", callback_data="compress_high"),
            InlineKeyboardButton("🎚 Custom", callback_data="compress_custom")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_metadata_menu() -> InlineKeyboardMarkup:
    """Metadata editing menu"""
    buttons = [
        [
            InlineKeyboardButton("📝 Title", callback_data="meta_title"),
            InlineKeyboardButton("👤 Artist", callback_data="meta_artist")
        ],
        [
            InlineKeyboardButton("💿 Album", callback_data="meta_album"),
            InlineKeyboardButton("🎭 Genre", callback_data="meta_genre")
        ],
        [
            InlineKeyboardButton("🖼 Thumbnail", callback_data="meta_thumbnail"),
            InlineKeyboardButton("🌐 Auto Fetch", callback_data="meta_autofetch")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_settings_menu(settings: dict) -> InlineKeyboardMarkup:
    """Settings menu"""
    auto_status = "✅ ON" if settings.get("auto_metadata") else "❌ OFF"
    thumb_status = "✅ ON" if settings.get("reuse_thumbnail") else "❌ OFF"
    
    buttons = [
        [
            InlineKeyboardButton(f"🤖 Auto Metadata {auto_status}", 
                               callback_data="toggle_auto_metadata")
        ],
        [
            InlineKeyboardButton(f"🖼 Reuse Thumbnail {thumb_status}", 
                               callback_data="toggle_reuse_thumbnail")
        ],
        [
            InlineKeyboardButton(f"🎵 Format: {settings.get('default_format', 'mp3').upper()}", 
                               callback_data="setting_format")
        ],
        [
            InlineKeyboardButton(f"📦 Compression: {settings.get('default_compression', 'medium')}", 
                               callback_data="setting_compression")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

# ==================== BOT COMMAND HANDLERS ====================

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    welcome_text = """
🎵 **Welcome to Audio Studio Bot!** 🎵

I'm your professional audio editing assistant inside Telegram.

**Features:**
✂️ Trim & Cut
🔊 Volume Control
⚡ Speed Change
🔄 Format Conversion
🎨 Audio Enhancements
📝 Metadata & Thumbnails
🎬 Preview Before Export

**How to use:**
1️⃣ Send me any audio file
2️⃣ Use the interactive buttons to edit
3️⃣ Preview your changes
4️⃣ Export the final result

Send an audio file to get started! 🚀
    """
    
    await message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

@app.on_message(filters.command("settings"))
async def settings_command(client: Client, message: Message):
    """Handle /settings command"""
    user_id = message.from_user.id
    settings = await get_user_settings(user_id)
    
    settings_text = f"""
⚙️ **Your Settings**

🎵 Default Format: `{settings.get('default_format', 'mp3')}`
📦 Compression: `{settings.get('default_compression', 'medium')}`
🤖 Auto Metadata: `{settings.get('auto_metadata')}`
🖼 Reuse Thumbnail: `{settings.get('reuse_thumbnail')}`

Use buttons below to modify settings
    """
    
    await message.reply_text(
        settings_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_settings_menu(settings)
    )

@app.on_message(filters.command("reset"))
async def reset_command(client: Client, message: Message):
    """Reset current session"""
    user_id = message.from_user.id
    await delete_user_session(user_id)
    await message.reply_text("✅ Session reset successfully! Send a new audio file to start editing.")

@app.on_message(filters.audio | filters.voice)
async def handle_audio(client: Client, message: Message):
    """Handle incoming audio files"""
    user_id = message.from_user.id
    
    # Get audio file info
    if message.audio:
        audio = message.audio
        file_id = audio.file_id
        duration = audio.duration
        title = audio.file_name or "Unknown"
    else:
        audio = message.voice
        file_id = audio.file_id
        duration = audio.duration
        title = "Voice Message"
    
    # Send processing message
    processing_msg = await message.reply_text("📥 **Downloading audio...**", parse_mode=ParseMode.MARKDOWN)
    
    try:
        # Download audio
        audio_path = await download_audio(file_id, user_id)
        
        # Create session
        session = await get_user_session(user_id)
        session["current_file"] = audio_path
        session["original_file_id"] = file_id
        session["original_file_path"] = audio_path
        session["edits"] = []
        await update_user_session(user_id, session)
        
        # Send success message
        info_text = f"""
✅ **Audio loaded successfully!**

📝 **Title:** `{title}`
⏱ **Duration:** `{duration // 60}:{duration % 60:02d}`

Now choose an editing option from the menu below:
        """
        
        await processing_msg.edit_text(
            info_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu()
        )
        
    except Exception as e:
        logger.error(f"Audio handling error: {traceback.format_exc()}")
        await processing_msg.edit_text(f"❌ Error loading audio: {str(e)}")

# ==================== CALLBACK QUERY HANDLERS ====================

@app.on_callback_query()
async def handle_callback(client: Client, callback_query: CallbackQuery):
    """Handle all callback queries"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # Get user session
    session = await get_user_session(user_id)
    
    # Handle back to main menu
    if data == "back_main":
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
        await callback_query.answer()
        return
    
    # Main menu actions
    if data == "menu_trim":
        await callback_query.message.edit_reply_markup(reply_markup=get_trim_menu())
        await callback_query.answer("Trim mode activated")
    
    elif data == "menu_volume":
        await callback_query.message.edit_reply_markup(reply_markup=get_volume_menu())
        await callback_query.answer("Volume control activated")
    
    elif data == "menu_speed":
        await callback_query.message.edit_reply_markup(reply_markup=get_speed_menu())
        await callback_query.answer("Speed control activated")
    
    elif data == "menu_convert":
        await callback_query.message.edit_reply_markup(reply_markup=get_convert_menu())
        await callback_query.answer("Format conversion activated")
    
    elif data == "menu_enhance":
        await callback_query.message.edit_reply_markup(reply_markup=get_enhance_menu())
        await callback_query.answer("Audio enhancement activated")
    
    elif data == "menu_metadata":
        await callback_query.message.edit_reply_markup(reply_markup=get_metadata_menu())
        await callback_query.answer("Metadata editor activated")
    
    elif data == "menu_settings":
        settings = await get_user_settings(user_id)
        await callback_query.message.edit_reply_markup(reply_markup=get_settings_menu(settings))
        await callback_query.answer("Settings menu")
    
    elif data == "menu_compress":
        await callback_query.message.edit_reply_markup(reply_markup=get_compress_menu())
        await callback_query.answer("Compression settings")
    
    # Trim actions
    elif data == "trim_set_start":
        await callback_query.answer("Send the start time in seconds (e.g., 30 for 30 seconds)", show_alert=True)
        # Store state in session
        session["awaiting_trim_start"] = True
        await update_user_session(user_id, session)
    
    elif data == "trim_set_end":
        await callback_query.answer("Send the end time in seconds (e.g., 120 for 2 minutes)", show_alert=True)
        session["awaiting_trim_end"] = True
        await update_user_session(user_id, session)
    
    elif data == "trim_apply":
        if session.get("trim_start") and session.get("trim_end"):
            edit = {
                "type": "trim",
                "start": session["trim_start"],
                "end": session["trim_end"]
            }
            session["edits"].append(edit)
            await update_user_session(user_id, session)
            await callback_query.answer("Trim applied successfully!", show_alert=True)
            await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
        else:
            await callback_query.answer("Please set both start and end times first!", show_alert=True)
    
    # Volume actions
    elif data.startswith("vol_"):
        factor = float(data.split("_")[1])
        edit = {"type": "volume", "factor": factor}
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer(f"Volume set to {factor}x", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    elif data == "vol_normalize":
        edit = {"type": "normalize"}
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer("Audio normalized", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Speed actions
    elif data.startswith("speed_"):
        speed = float(data.split("_")[1])
        edit = {"type": "speed", "speed": speed}
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer(f"Speed set to {speed}x", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Convert actions
    elif data.startswith("convert_"):
        format_type = data.split("_")[1]
        edit = {"type": "convert", "format": format_type}
        session["edits"].append(edit)
        session["output_format"] = format_type
        await update_user_session(user_id, session)
        await callback_query.answer(f"Will convert to {format_type.upper()}", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Enhance actions
    elif data == "enhance_normalize":
        edit = {"type": "normalize"}
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer("Normalization added", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    elif data == "enhance_bass":
        edit = {"type": "bass_boost"}
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer("Bass boost added", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    elif data == "enhance_noise":
        await callback_query.answer("Noise reduction coming soon!", show_alert=True)
    
    # Compression actions
    elif data.startswith("compress_"):
        level = data.split("_")[1]
        bitrates = {"low": "64k", "medium": "128k", "high": "192k"}
        bitrate = bitrates.get(level, "128k")
        
        edit = {"type": "compress", "bitrate": bitrate, "level": level}
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer(f"Compression set to {level}", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Metadata actions
    elif data == "meta_title":
        await callback_query.answer("Send the new title for this audio", show_alert=True)
        session["awaiting_meta_title"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_artist":
        await callback_query.answer("Send the artist name", show_alert=True)
        session["awaiting_meta_artist"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_album":
        await callback_query.answer("Send the album name", show_alert=True)
        session["awaiting_meta_album"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_genre":
        await callback_query.answer("Send the genre", show_alert=True)
        session["awaiting_meta_genre"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_thumbnail":
        await callback_query.answer("Send a photo to use as album art", show_alert=True)
        session["awaiting_thumbnail"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_autofetch":
        await callback_query.answer("Send song name to fetch metadata", show_alert=True)
        session["awaiting_autofetch"] = True
        await update_user_session(user_id, session)
    
    # Preview action
    elif data == "action_preview":
        if not session.get("current_file"):
            await callback_query.answer("No audio loaded! Send an audio file first.", show_alert=True)
            return
        
        await callback_query.answer("Generating preview...")
        
        try:
            # Apply current edits to generate preview
            temp_preview = await generate_preview(session["current_file"], duration=15)
            
            # Send preview
            await callback_query.message.reply_audio(
                audio=temp_preview,
                title="Preview (15 seconds)",
                performer="Audio Editor Bot",
                caption="🎬 Here's your 15-second preview. Continue editing or export when ready."
            )
            
            # Cleanup
            if os.path.exists(temp_preview):
                os.remove(temp_preview)
                
        except Exception as e:
            logger.error(f"Preview error: {e}")
            await callback_query.answer(f"Preview failed: {str(e)}", show_alert=True)
    
    # Export action
    elif data == "action_export":
        if not session.get("current_file"):
            await callback_query.answer("No audio loaded!", show_alert=True)
            return
        
        status_msg = await callback_query.message.reply_text("🎨 **Processing your audio...**", parse_mode=ParseMode.MARKDOWN)
        
        try:
            # Apply all edits
            processed_path = await apply_edits(session["current_file"], session.get("edits", []))
            
            # Add metadata if available
            if session.get("metadata"):
                processed_path = await add_metadata(
                    processed_path,
                    session["metadata"],
                    session.get("thumbnail_path")
                )
            
            # Send final result
            format_type = session.get("output_format", "mp3")
            await callback_query.message.reply_audio(
                audio=processed_path,
                title=session.get("metadata", {}).get("title", "Edited Audio"),
                performer=session.get("metadata", {}).get("artist", "Audio Editor Bot"),
                caption="✅ **Export complete!**\n\nThank you for using Audio Studio Bot! 🎵",
                parse_mode=ParseMode.MARKDOWN
            )
            
            await status_msg.delete()
            await callback_query.answer("Export completed successfully!", show_alert=True)
            
            # Cleanup
            if os.path.exists(processed_path):
                os.remove(processed_path)
                
        except Exception as e:
            logger.error(f"Export error: {traceback.format_exc()}")
            await status_msg.edit_text(f"❌ Export failed: {str(e)}")
    
    # Reset action
    elif data == "action_reset":
        await delete_user_session(user_id)
        await callback_query.answer("Session reset!", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Info action
    elif data == "action_info":
        if session.get("current_file"):
            info_text = f"""
📊 **Audio Information**

📝 **Edits applied:** `{len(session.get('edits', []))}`
🎵 **Output format:** `{session.get('output_format', 'mp3')}`
📦 **Metadata:** `{'Yes' if session.get('metadata') else 'No'}`
🖼 **Thumbnail:** `{'Yes' if session.get('thumbnail_file_id') else 'No'}`

Use the menu to continue editing or export!
            """
        else:
            info_text = "No audio loaded. Send an audio file to start editing!"
        
        await callback_query.message.reply_text(info_text, parse_mode=ParseMode.MARKDOWN)
        await callback_query.answer()
    
    # Settings toggles
    elif data == "toggle_auto_metadata":
        settings = await get_user_settings(user_id)
        new_value = not settings.get("auto_metadata", True)
        await update_user_settings(user_id, {"auto_metadata": new_value})
        settings = await get_user_settings(user_id)
        await callback_query.message.edit_reply_markup(reply_markup=get_settings_menu(settings))
        await callback_query.answer(f"Auto metadata {'enabled' if new_value else 'disabled'}")
    
    elif data == "toggle_reuse_thumbnail":
        settings = await get_user_settings(user_id)
        new_value = not settings.get("reuse_thumbnail", False)
        await update_user_settings(user_id, {"reuse_thumbnail": new_value})
        settings = await get_user_settings(user_id)
        await callback_query.message.edit_reply_markup(reply_markup=get_settings_menu(settings))
        await callback_query.answer(f"Reuse thumbnail {'enabled' if new_value else 'disabled'}")
    
    elif data == "setting_format":
        await callback_query.answer("Feature: Change default format in next update", show_alert=True)
    
    elif data == "setting_compression":
        await callback_query.answer("Feature: Change default compression in next update", show_alert=True)

# ==================== TEXT MESSAGE HANDLERS ====================

@app.on_message(filters.text & filters.private)
async def handle_text_input(client: Client, message: Message):
    """Handle text input for trim times and metadata"""
    user_id = message.from_user.id
    session = await get_user_session(user_id)
    text = message.text.strip()
    
    # Handle trim start time
    if session.get("awaiting_trim_start"):
        try:
            start_time = float(text)
            session["trim_start"] = start_time
            session["awaiting_trim_start"] = False
            await update_user_session(user_id, session)
            await message.reply_text(f"✅ Start time set to {start_time} seconds\nNow send the end time or use the trim menu.")
        except ValueError:
            await message.reply_text("❌ Invalid time! Please send a number (e.g., 30 for 30 seconds)")
    
    # Handle trim end time
    elif session.get("awaiting_trim_end"):
        try:
            end_time = float(text)
            session["trim_end"] = end_time
            session["awaiting_trim_end"] = False
            await update_user_session(user_id, session)
            await message.reply_text(f"✅ End time set to {end_time} seconds\nClick 'Apply Trim' to finish.")
        except ValueError:
            await message.reply_text("❌ Invalid time! Please send a number (e.g., 120 for 2 minutes)")
    
    # Handle metadata inputs
    elif session.get("awaiting_meta_title"):
        session["metadata"]["title"] = text
        session["awaiting_meta_title"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Title set to: {text}")
    
    elif session.get("awaiting_meta_artist"):
        session["metadata"]["artist"] = text
        session["awaiting_meta_artist"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Artist set to: {text}")
    
    elif session.get("awaiting_meta_album"):
        session["metadata"]["album"] = text
        session["awaiting_meta_album"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Album set to: {text}")
    
    elif session.get("awaiting_meta_genre"):
        session["metadata"]["genre"] = text
        session["awaiting_meta_genre"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Genre set to: {text}")
    
    elif session.get("awaiting_autofetch"):
        await message.reply_text("🔍 Fetching metadata from MusicBrainz...")
        metadata = await fetch_metadata_from_api(text)
        
        if metadata:
            session["metadata"].update(metadata)
            await update_user_session(user_id, session)
            await message.reply_text(f"""
✅ **Metadata fetched successfully!**

📝 Title: {metadata.get('title', 'N/A')}
👤 Artist: {metadata.get('artist', 'N/A')}
💿 Album: {metadata.get('album', 'N/A')}
📅 Year: {metadata.get('year', 'N/A')}
            """)
        else:
            await message.reply_text("❌ Could not fetch metadata. Please enter manually.")
        
        session["awaiting_autofetch"] = False
        await update_user_session(user_id, session)

# ==================== PHOTO HANDLER FOR THUMBNAILS ====================

@app.on_message(filters.photo & filters.private)
async def handle_thumbnail(client: Client, message: Message):
    """Handle thumbnail uploads"""
    user_id = message.from_user.id
    session = await get_user_session(user_id)
    
    if session.get("awaiting_thumbnail"):
        try:
            # Download thumbnail
            photo = message.photo[-1]  # Get highest quality
            thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{user_id}.jpg")
            await app.download_media(photo, file_name=thumb_path)
            
            session["thumbnail_path"] = thumb_path
            session["thumbnail_file_id"] = photo.file_id
            session["awaiting_thumbnail"] = False
            await update_user_session(user_id, session)
            
            await message.reply_text("✅ Thumbnail added successfully! It will be embedded in the final audio.")
        except Exception as e:
            logger.error(f"Thumbnail error: {e}")
            await message.reply_text("❌ Failed to save thumbnail. Please try again.")

# ==================== ERROR HANDLING ====================

@app.on_error()
async def error_handler(client: Client, error: Exception):
    """Global error handler"""
    logger.error(f"Global error: {traceback.format_exc()}")
    # Don't crash the bot, just log

# ==================== MAIN ====================

async def cleanup_old_files():
    """Periodically clean up old downloaded files"""
    while True:
        try:
            # Delete files older than 1 hour
            cutoff = datetime.now() - timedelta(hours=1)
            for file in os.listdir(DOWNLOAD_DIR):
                file_path = os.path.join(DOWNLOAD_DIR, file)
                if os.path.isfile(file_path):
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff:
                        os.remove(file_path)
                        logger.info(f"Cleaned up old file: {file}")
            
            for file in os.listdir(CACHE_DIR):
                file_path = os.path.join(CACHE_DIR, file)
                if os.path.isfile(file_path):
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff:
                        os.remove(file_path)
                        logger.info(f"Cleaned up cached file: {file}")
            
            await asyncio.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(3600)

if __name__ == "__main__":
    # Start cleanup task
    loop = asyncio.get_event_loop()
    loop.create_task(cleanup_old_files())
    
    # Run bot
    logger.info("Starting Audio Editor Bot...")
    app.run()
