#!/usr/bin/env python3
"""
Telegram Audio Editing Bot - Complete Fixed Version
All features working: trim, speed, merge, insert at position
"""

import os
import logging
import traceback
import asyncio
import tempfile
import shutil
import subprocess
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import re

# Core libraries
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from pyrogram.enums import ParseMode

# MongoDB
from motor.motor_asyncio import AsyncIOMotorClient

# Metadata
import mutagen
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TCON, TDRC

# Utilities
import requests
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


# File handling
DOWNLOAD_DIR = "downloads"
CACHE_DIR = "cache"
TEMP_DIR = "temp"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

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

# ==================== FFMPEG HELPER FUNCTIONS ====================

def get_audio_info(file_path: str) -> dict:
    """Get detailed audio information using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # Find audio stream
        audio_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'audio':
                audio_stream = stream
                break
        
        duration = float(data.get('format', {}).get('duration', 0))
        bitrate = int(data.get('format', {}).get('bit_rate', 0)) // 1000 if data.get('format', {}).get('bit_rate') else 0
        
        return {
            'duration': duration,
            'bitrate': bitrate,
            'sample_rate': audio_stream.get('sample_rate', 'N/A') if audio_stream else 'N/A',
            'channels': audio_stream.get('channels', 'N/A') if audio_stream else 'N/A',
            'codec': audio_stream.get('codec_name', 'N/A') if audio_stream else 'N/A'
        }
    except Exception as e:
        logger.error(f"Audio info error: {e}")
        return {'duration': 0, 'bitrate': 0, 'sample_rate': 'N/A', 'channels': 'N/A', 'codec': 'N/A'}

def trim_audio(input_path: str, output_path: str, start_seconds: float, end_seconds: float):
    """Trim audio - fixed version"""
    duration = end_seconds - start_seconds
    cmd = [
        'ffmpeg', '-i', input_path,
        '-ss', str(start_seconds),
        '-t', str(duration),
        '-c', 'copy',
        '-y', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def change_volume(input_path: str, output_path: str, factor: float):
    """Change volume"""
    cmd = [
        'ffmpeg', '-i', input_path,
        '-filter:a', f'volume={factor}',
        '-y', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def change_speed_fixed(input_path: str, output_path: str, speed: float):
    """Change speed - handles any speed by chaining atempo filters"""
    try:
        # atempo filter only works between 0.5 and 2.0
        # For speeds outside this range, we chain multiple filters
        if 0.5 <= speed <= 2.0:
            cmd = [
                'ffmpeg', '-i', input_path,
                '-filter:a', f'atempo={speed}',
                '-y', output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            # Calculate required filters
            filters = []
            remaining = speed
            
            while remaining > 2.0:
                filters.append('atempo=2.0')
                remaining /= 2.0
            while remaining < 0.5:
                filters.append('atempo=0.5')
                remaining /= 0.5
            
            if remaining != 1.0:
                filters.append(f'atempo={remaining}')
            
            filter_chain = ','.join(filters)
            cmd = [
                'ffmpeg', '-i', input_path,
                '-filter:a', filter_chain,
                '-y', output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # Fallback to using aresample for speed change
        logger.warning(f"atempo failed, using aresample: {e}")
        cmd = [
            'ffmpeg', '-i', input_path,
            '-filter:a', f'aresample=sample_rate=44100,atempo={speed}',
            '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)

def normalize_audio(input_path: str, output_path: str):
    """Normalize audio volume"""
    cmd = [
        'ffmpeg', '-i', input_path,
        '-filter:a', 'loudnorm=I=-16:LRA=11:TP=-1.5',
        '-y', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def bass_boost(input_path: str, output_path: str):
    """Apply bass boost"""
    cmd = [
        'ffmpeg', '-i', input_path,
        '-filter:a', 'bass=g=10',
        '-y', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def convert_format(input_path: str, output_path: str, format_type: str):
    """Convert audio format"""
    cmd = ['ffmpeg', '-i', input_path, '-y', output_path]
    subprocess.run(cmd, check=True, capture_output=True)

def compress_audio(input_path: str, output_path: str, bitrate: str):
    """Compress audio"""
    cmd = [
        'ffmpeg', '-i', input_path,
        '-b:a', bitrate,
        '-y', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def generate_preview_ffmpeg(input_path: str, output_path: str, duration: int = 15):
    """Generate preview"""
    cmd = [
        'ffmpeg', '-i', input_path,
        '-t', str(duration),
        '-c', 'copy',
        '-y', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)

def merge_audios_fixed(input_paths: List[str], output_path: str):
    """Merge multiple audio files - fixed version"""
    try:
        # Create concat file with absolute paths
        concat_file = tempfile.mktemp(suffix=".txt")
        with open(concat_file, 'w') as f:
            for path in input_paths:
                # Ensure path is absolute and properly escaped
                abs_path = os.path.abspath(path)
                f.write(f"file '{abs_path}'\n")
        
        # First, ensure all files have same format by converting if needed
        normalized_paths = []
        for i, path in enumerate(input_paths):
            normalized = tempfile.mktemp(suffix=".mp3")
            cmd_convert = ['ffmpeg', '-i', path, '-acodec', 'libmp3lame', '-y', normalized]
            subprocess.run(cmd_convert, check=True, capture_output=True)
            normalized_paths.append(normalized)
        
        # Update concat file with normalized paths
        with open(concat_file, 'w') as f:
            for path in normalized_paths:
                f.write(f"file '{path}'\n")
        
        # Merge using concat demuxer
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', concat_file, '-c', 'copy', '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Cleanup normalized files
        for path in normalized_paths:
            if os.path.exists(path):
                os.remove(path)
        
        os.remove(concat_file)
    except Exception as e:
        logger.error(f"Merge error: {e}")
        # Fallback: use filter_complex
        raise

def insert_audio_at_position(main_audio: str, insert_audio: str, output_path: str, position_seconds: float):
    """Insert audio clip at specific position in main audio"""
    try:
        # Get duration of insert audio
        insert_info = get_audio_info(insert_audio)
        insert_duration = insert_info['duration']
        
        # Create temp files for parts
        part1 = tempfile.mktemp(suffix=".mp3")
        part2 = tempfile.mktemp(suffix=".mp3")
        
        # Split main audio at insertion point
        # Part 1: from start to insertion point
        if position_seconds > 0:
            cmd1 = [
                'ffmpeg', '-i', main_audio,
                '-t', str(position_seconds),
                '-c', 'copy',
                '-y', part1
            ]
            subprocess.run(cmd1, check=True, capture_output=True)
        else:
            # If inserting at beginning, part1 is empty
            part1 = None
        
        # Part 2: from insertion point to end
        cmd2 = [
            'ffmpeg', '-i', main_audio,
            '-ss', str(position_seconds),
            '-c', 'copy',
            '-y', part2
        ]
        subprocess.run(cmd2, check=True, capture_output=True)
        
        # Create concat file
        concat_file = tempfile.mktemp(suffix=".txt")
        with open(concat_file, 'w') as f:
            if part1 and os.path.exists(part1) and os.path.getsize(part1) > 0:
                f.write(f"file '{os.path.abspath(part1)}'\n")
            f.write(f"file '{os.path.abspath(insert_audio)}'\n")
            if os.path.exists(part2) and os.path.getsize(part2) > 0:
                f.write(f"file '{os.path.abspath(part2)}'\n")
        
        # Merge all parts
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', concat_file, '-c', 'copy', '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Cleanup
        if part1 and os.path.exists(part1):
            os.remove(part1)
        if os.path.exists(part2):
            os.remove(part2)
        os.remove(concat_file)
        
    except Exception as e:
        logger.error(f"Insert error: {e}")
        raise

# ==================== DATABASE FUNCTIONS ====================

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
            "thumbnail_path": None,
            "merge_queue": [],
            "insert_audio_file": None,
            "insert_position": None,
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
        cache_key = hashlib.md5(f"{file_id}".encode()).hexdigest()
        cache_path = os.path.join(CACHE_DIR, f"{cache_key}.mp3")
        
        if os.path.exists(cache_path):
            logger.info(f"Using cached file for {file_id}")
            return cache_path
        
        temp_path = os.path.join(DOWNLOAD_DIR, f"{user_id}_{file_id}.mp3")
        await app.download_media(file_id, file_name=temp_path)
        
        # Convert to standard format using ffmpeg
        convert_format(temp_path, cache_path, "mp3")
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return cache_path
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise

async def apply_all_edits(audio_path: str, edits: List[dict]) -> str:
    """Apply all edits in sequence"""
    try:
        current_path = audio_path
        temp_files = []
        
        for i, edit in enumerate(edits):
            edit_type = edit.get("type")
            output_path = tempfile.mktemp(suffix=f"_edit_{i}.mp3")
            temp_files.append(output_path)
            
            try:
                if edit_type == "trim":
                    trim_audio(current_path, output_path, 
                              edit.get("start", 0), 
                              edit.get("end", 60))
                
                elif edit_type == "volume":
                    change_volume(current_path, output_path, edit.get("factor", 1.0))
                
                elif edit_type == "speed":
                    change_speed_fixed(current_path, output_path, edit.get("speed", 1.0))
                
                elif edit_type == "normalize":
                    normalize_audio(current_path, output_path)
                
                elif edit_type == "bass_boost":
                    bass_boost(current_path, output_path)
                
                elif edit_type == "compress":
                    compress_audio(current_path, output_path, edit.get("bitrate", "128k"))
                
                elif edit_type == "convert":
                    convert_format(current_path, output_path, edit.get("format", "mp3"))
                
                # Clean up previous file if not original
                if current_path != audio_path and os.path.exists(current_path):
                    os.remove(current_path)
                
                current_path = output_path
                
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg error for edit {edit_type}: {e.stderr.decode() if e.stderr else str(e)}")
                raise
        
        # Final output path
        final_output = tempfile.mktemp(suffix=".mp3")
        shutil.copy(current_path, final_output)
        
        # Cleanup temp files
        for temp_file in temp_files:
            if os.path.exists(temp_file) and temp_file != current_path:
                os.remove(temp_file)
        
        return final_output
    except Exception as e:
        logger.error(f"Edit application error: {traceback.format_exc()}")
        raise

async def add_metadata_to_audio(audio_path: str, metadata: dict, thumbnail_path: str = None) -> str:
    """Add metadata and thumbnail"""
    try:
        # Load audio with mutagen
        audio = mutagen.File(audio_path, easy=True)
        
        if metadata.get("title"):
            audio['title'] = metadata["title"]
        if metadata.get("artist"):
            audio['artist'] = metadata["artist"]
        if metadata.get("album"):
            audio['album'] = metadata["album"]
        if metadata.get("genre"):
            audio['genre'] = metadata["genre"]
        if metadata.get("year"):
            audio['date'] = metadata["year"]
        
        audio.save()
        
        # Add thumbnail if provided
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                id3 = ID3(audio_path)
                with open(thumbnail_path, 'rb') as f:
                    id3.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=f.read()
                    ))
                id3.save()
            except:
                id3 = ID3()
                with open(thumbnail_path, 'rb') as f:
                    id3.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=f.read()
                    ))
                id3.save(audio_path)
        
        return audio_path
    except Exception as e:
        logger.error(f"Metadata error: {e}")
        return audio_path

async def fetch_metadata_from_api(query: str) -> dict:
    """Fetch metadata from MusicBrainz"""
    try:
        url = "https://musicbrainz.org/ws/2/recording/"
        params = {"query": query, "fmt": "json", "limit": 1}
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("recordings"):
                recording = data["recordings"][0]
                metadata = {"title": recording.get("title", "")}
                
                if recording.get("artist-credit"):
                    metadata["artist"] = recording["artist-credit"][0].get("name", "")
                
                if recording.get("releases"):
                    release = recording["releases"][0]
                    metadata["album"] = release.get("title", "")
                    if release.get("date"):
                        metadata["year"] = release.get("date", "")[:4]
                
                return metadata
        return {}
    except Exception as e:
        logger.error(f"Metadata fetch error: {e}")
        return {}

# ==================== KEYBOARD MENUS ====================

def get_main_menu() -> InlineKeyboardMarkup:
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
            InlineKeyboardButton("🔀 Merge", callback_data="menu_merge"),
            InlineKeyboardButton("➕ Insert", callback_data="menu_insert"),
            InlineKeyboardButton("🎬 Preview", callback_data="action_preview")
        ],
        [
            InlineKeyboardButton("✅ Export", callback_data="action_export"),
            InlineKeyboardButton("🗑 Reset", callback_data="action_reset"),
            InlineKeyboardButton("ℹ️ Info", callback_data="action_info")
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_trim_menu() -> InlineKeyboardMarkup:
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
    buttons = [
        [
            InlineKeyboardButton("🔇 50%", callback_data="vol_0.5"),
            InlineKeyboardButton("🔉 75%", callback_data="vol_0.75"),
            InlineKeyboardButton("🔊 100%", callback_data="vol_1.0")
        ],
        [
            InlineKeyboardButton("📢 125%", callback_data="vol_1.25"),
            InlineKeyboardButton("🔊 150%", callback_data="vol_1.5"),
            InlineKeyboardButton("💥 200%", callback_data="vol_2.0")
        ],
        [
            InlineKeyboardButton("✨ Normalize", callback_data="vol_normalize"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_speed_menu() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🐢 0.5x", callback_data="speed_0.5"),
            InlineKeyboardButton("🚶 0.75x", callback_data="speed_0.75"),
            InlineKeyboardButton("🏃 1.25x", callback_data="speed_1.25")
        ],
        [
            InlineKeyboardButton("⚡ 1.5x", callback_data="speed_1.5"),
            InlineKeyboardButton("💨 2.0x", callback_data="speed_2.0"),
            InlineKeyboardButton("🔥 3.0x", callback_data="speed_3.0")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_convert_menu() -> InlineKeyboardMarkup:
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
    buttons = [
        [
            InlineKeyboardButton("✨ Normalize Volume", callback_data="enhance_normalize"),
            InlineKeyboardButton("🎸 Bass Boost", callback_data="enhance_bass")
        ],
        [
            InlineKeyboardButton("📦 Compress", callback_data="menu_compress"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_compress_menu() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("📦 Low (64kbps)", callback_data="compress_low"),
            InlineKeyboardButton("📦 Medium (128kbps)", callback_data="compress_medium")
        ],
        [
            InlineKeyboardButton("📦 High (192kbps)", callback_data="compress_high"),
            InlineKeyboardButton("💎 Max (320kbps)", callback_data="compress_max")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_metadata_menu() -> InlineKeyboardMarkup:
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
            InlineKeyboardButton("📅 Year", callback_data="meta_year"),
            InlineKeyboardButton("🖼 Thumbnail", callback_data="meta_thumbnail")
        ],
        [
            InlineKeyboardButton("🌐 Auto Fetch", callback_data="meta_autofetch"),
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_merge_menu() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("➕ Add Audio", callback_data="merge_add"),
            InlineKeyboardButton("📋 View Queue", callback_data="merge_view")
        ],
        [
            InlineKeyboardButton("🔀 Merge Now", callback_data="merge_now"),
            InlineKeyboardButton("🗑 Clear Queue", callback_data="merge_clear")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_insert_menu() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("📤 Upload Audio to Insert", callback_data="insert_upload"),
            InlineKeyboardButton("📍 Set Position", callback_data="insert_set_position")
        ],
        [
            InlineKeyboardButton("▶️ Insert Now", callback_data="insert_now"),
            InlineKeyboardButton("🗑 Clear Insert", callback_data="insert_clear")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_main")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_position_menu() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🏁 At Beginning", callback_data="insert_pos_0"),
            InlineKeyboardButton("🏁 At End", callback_data="insert_pos_end")
        ],
        [
            InlineKeyboardButton("🎯 Custom Position", callback_data="insert_pos_custom"),
            InlineKeyboardButton("🔙 Back", callback_data="back_insert")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_settings_menu(settings: dict) -> InlineKeyboardMarkup:
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

# ==================== COMMAND HANDLERS ====================

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    welcome_text = """
🎵 **Welcome to Audio Studio Bot!** 🎵

I'm your professional audio editing assistant inside Telegram.

**Features:**
✂️ Trim & Cut
🔊 Volume Control (50% to 200%)
⚡ Speed Change (0.5x to 3.0x)
🔄 Format Conversion (MP3, WAV, FLAC, OGG, M4A)
🎨 Audio Enhancements (Normalize, Bass Boost, Compress)
🔀 Merge Multiple Audios
➕ Insert Audio at Any Position
📝 Metadata & Thumbnails
🎬 Preview Before Export

**How to use:**
1️⃣ Send me any audio file
2️⃣ Use the interactive buttons to edit
3️⃣ Preview your changes
4️⃣ Export the final result

Send an audio file to get started! 🚀
    """
    
    await message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu())

@app.on_message(filters.command("settings"))
async def settings_command(client: Client, message: Message):
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
    
    await message.reply_text(settings_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_settings_menu(settings))

@app.on_message(filters.command("reset"))
async def reset_command(client: Client, message: Message):
    user_id = message.from_user.id
    await delete_user_session(user_id)
    await message.reply_text("✅ Session reset successfully! Send a new audio file to start editing.")

@app.on_message(filters.audio | filters.voice)
async def handle_audio(client: Client, message: Message):
    user_id = message.from_user.id
    
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
    
    processing_msg = await message.reply_text("📥 **Downloading audio...**", parse_mode=ParseMode.MARKDOWN)
    
    try:
        audio_path = await download_audio(file_id, user_id)
        audio_info = get_audio_info(audio_path)
        
        session = await get_user_session(user_id)
        session["current_file"] = audio_path
        session["original_file_id"] = file_id
        session["original_file_path"] = audio_path
        session["edits"] = []
        await update_user_session(user_id, session)
        
        info_text = f"""
✅ **Audio loaded successfully!**

📝 **Title:** `{title}`
⏱ **Duration:** `{int(audio_info['duration'] // 60)}:{int(audio_info['duration'] % 60):02d}`
🎵 **Bitrate:** `{audio_info['bitrate']} kbps`
🔊 **Sample Rate:** `{audio_info['sample_rate']} Hz`

Now choose an editing option from the menu below:
        """
        
        await processing_msg.edit_text(info_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu())
        
    except Exception as e:
        logger.error(f"Audio handling error: {traceback.format_exc()}")
        await processing_msg.edit_text(f"❌ Error loading audio: {str(e)}")

# ==================== CALLBACK HANDLERS ====================

@app.on_callback_query()
async def handle_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    session = await get_user_session(user_id)
    
    if data == "back_main":
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
        await callback_query.answer()
        return
    
    if data == "back_insert":
        await callback_query.message.edit_reply_markup(reply_markup=get_insert_menu())
        await callback_query.answer()
        return
    
    # Menu navigation
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
    
    elif data == "menu_merge":
        await callback_query.message.edit_reply_markup(reply_markup=get_merge_menu())
        await callback_query.answer("Merge mode - Add audio files to queue")
    
    elif data == "menu_insert":
        await callback_query.message.edit_reply_markup(reply_markup=get_insert_menu())
        await callback_query.answer("Insert mode - Add audio to insert")
    
    # Trim actions
    elif data == "trim_set_start":
        await callback_query.answer("Send the start time in seconds (e.g., 30)", show_alert=True)
        session["awaiting_trim_start"] = True
        await update_user_session(user_id, session)
    
    elif data == "trim_set_end":
        await callback_query.answer("Send the end time in seconds (e.g., 120)", show_alert=True)
        session["awaiting_trim_end"] = True
        await update_user_session(user_id, session)
    
    elif data == "trim_apply":
        if session.get("trim_start") is not None and session.get("trim_end") is not None:
            edit = {"type": "trim", "start": session["trim_start"], "end": session["trim_end"]}
            if "edits" not in session:
                session["edits"] = []
            session["edits"].append(edit)
            await update_user_session(user_id, session)
            await callback_query.answer("Trim applied successfully!", show_alert=True)
            await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
        else:
            await callback_query.answer("Please set both start and end times first!", show_alert=True)
    
    # Volume actions
    elif data.startswith("vol_"):
        if data == "vol_normalize":
            edit = {"type": "normalize"}
            await callback_query.answer("Normalization added", show_alert=True)
        else:
            factor = float(data.split("_")[1])
            edit = {"type": "volume", "factor": factor}
            await callback_query.answer(f"Volume set to {factor}x", show_alert=True)
        
        if "edits" not in session:
            session["edits"] = []
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Speed actions
    elif data.startswith("speed_"):
        speed = float(data.split("_")[1])
        edit = {"type": "speed", "speed": speed}
        
        if "edits" not in session:
            session["edits"] = []
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer(f"Speed set to {speed}x", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Convert actions
    elif data.startswith("convert_"):
        format_type = data.split("_")[1]
        edit = {"type": "convert", "format": format_type}
        
        if "edits" not in session:
            session["edits"] = []
        session["edits"].append(edit)
        session["output_format"] = format_type
        await update_user_session(user_id, session)
        await callback_query.answer(f"Will convert to {format_type.upper()}", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Enhance actions
    elif data == "enhance_normalize":
        edit = {"type": "normalize"}
        if "edits" not in session:
            session["edits"] = []
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer("Normalization added", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    elif data == "enhance_bass":
        edit = {"type": "bass_boost"}
        if "edits" not in session:
            session["edits"] = []
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer("Bass boost added", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Compression actions
    elif data.startswith("compress_"):
        level = data.split("_")[1]
        bitrates = {"low": "64k", "medium": "128k", "high": "192k", "max": "320k"}
        bitrate = bitrates.get(level, "128k")
        
        edit = {"type": "compress", "bitrate": bitrate, "level": level}
        if "edits" not in session:
            session["edits"] = []
        session["edits"].append(edit)
        await update_user_session(user_id, session)
        await callback_query.answer(f"Compression set to {level}", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
    
    # Metadata actions
    elif data == "meta_title":
        await callback_query.answer("Send the new title", show_alert=True)
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
    
    elif data == "meta_year":
        await callback_query.answer("Send the year", show_alert=True)
        session["awaiting_meta_year"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_thumbnail":
        await callback_query.answer("Send a photo for album art", show_alert=True)
        session["awaiting_thumbnail"] = True
        await update_user_session(user_id, session)
    
    elif data == "meta_autofetch":
        await callback_query.answer("Send song/artist name", show_alert=True)
        session["awaiting_autofetch"] = True
        await update_user_session(user_id, session)
    
    # Merge actions
    elif data == "merge_add":
        await callback_query.answer("Send the audio file to add to merge queue", show_alert=True)
        session["awaiting_merge_add"] = True
        await update_user_session(user_id, session)
    
    elif data == "merge_view":
        merge_queue = session.get("merge_queue", [])
        if merge_queue:
            queue_text = "📋 **Merge Queue:**\n\n"
            total_duration = 0
            for i, file in enumerate(merge_queue, 1):
                info = get_audio_info(file['path'])
                duration = info['duration']
                total_duration += duration
                queue_text += f"{i}. {file.get('name', 'Unknown')} - {int(duration // 60)}:{int(duration % 60):02d}\n"
            queue_text += f"\n📊 Total duration: {int(total_duration // 60)}:{int(total_duration % 60):02d}\n📁 Files: {len(merge_queue)}"
            await callback_query.message.reply_text(queue_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await callback_query.answer("Merge queue is empty!", show_alert=True)
    
    elif data == "merge_now":
        merge_queue = session.get("merge_queue", [])
        if len(merge_queue) < 2:
            await callback_query.answer("Need at least 2 audio files to merge!", show_alert=True)
        else:
            await callback_query.answer("Merging audio files...", show_alert=True)
            status_msg = await callback_query.message.reply_text("🔄 **Merging audio files...**\n\nThis may take a moment.", parse_mode=ParseMode.MARKDOWN)
            
            try:
                # Prepare merge paths
                merge_paths = [file['path'] for file in merge_queue]
                output_path = tempfile.mktemp(suffix="_merged.mp3")
                
                # Merge audios
                merge_audios_fixed(merge_paths, output_path)
                
                # Send merged file
                await callback_query.message.reply_audio(
                    audio=output_path,
                    title="Merged Audio",
                    performer="Audio Editor Bot",
                    caption="✅ **Merge completed!**\n\nYou can now apply more edits or export."
                )
                
                # Update session with merged file
                session["current_file"] = output_path
                session["merge_queue"] = []
                await update_user_session(user_id, session)
                
                await status_msg.delete()
                await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
                
            except Exception as e:
                logger.error(f"Merge error: {traceback.format_exc()}")
                await status_msg.edit_text(f"❌ Merge failed: {str(e)}")
    
    elif data == "merge_clear":
        session["merge_queue"] = []
        await update_user_session(user_id, session)
        await callback_query.answer("Merge queue cleared!", show_alert=True)
    
    # Insert actions
    elif data == "insert_upload":
        await callback_query.answer("Send the audio file to insert", show_alert=True)
        session["awaiting_insert_audio"] = True
        await update_user_session(user_id, session)
    
    elif data == "insert_set_position":
        await callback_query.message.edit_reply_markup(reply_markup=get_position_menu())
        await callback_query.answer("Choose where to insert")
    
    elif data == "insert_pos_0":
        session["insert_position"] = 0
        await update_user_session(user_id, session)
        await callback_query.answer("Will insert at beginning", show_alert=True)
        await callback_query.message.edit_reply_markup(reply_markup=get_insert_menu())
    
    elif data == "insert_pos_end":
        if session.get("current_file"):
            audio_info = get_audio_info(session["current_file"])
            session["insert_position"] = audio_info['duration']
            await update_user_session(user_id, session)
            await callback_query.answer("Will insert at end", show_alert=True)
            await callback_query.message.edit_reply_markup(reply_markup=get_insert_menu())
        else:
            await callback_query.answer("No audio loaded!", show_alert=True)
    
    elif data == "insert_pos_custom":
        await callback_query.answer("Send the position in seconds (e.g., 30)", show_alert=True)
        session["awaiting_insert_position"] = True
        await update_user_session(user_id, session)
    
    elif data == "insert_now":
        if not session.get("insert_audio_file"):
            await callback_query.answer("Please upload an audio to insert first!", show_alert=True)
        elif session.get("insert_position") is None:
            await callback_query.answer("Please set the insertion position first!", show_alert=True)
        elif not session.get("current_file"):
            await callback_query.answer("No main audio loaded!", show_alert=True)
        else:
            await callback_query.answer("Inserting audio...", show_alert=True)
            status_msg = await callback_query.message.reply_text("🔄 **Inserting audio...**\n\nThis may take a moment.", parse_mode=ParseMode.MARKDOWN)
            
            try:
                output_path = tempfile.mktemp(suffix="_inserted.mp3")
                insert_audio_at_position(
                    session["current_file"],
                    session["insert_audio_file"],
                    output_path,
                    session["insert_position"]
                )
                
                # Send result
                await callback_query.message.reply_audio(
                    audio=output_path,
                    title="Audio with Insert",
                    performer="Audio Editor Bot",
                    caption="✅ **Insert completed!**\n\nThe audio clip has been inserted at the specified position."
                )
                
                # Update session
                session["current_file"] = output_path
                session["insert_audio_file"] = None
                session["insert_position"] = None
                await update_user_session(user_id, session)
                
                await status_msg.delete()
                await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
                
            except Exception as e:
                logger.error(f"Insert error: {traceback.format_exc()}")
                await status_msg.edit_text(f"❌ Insert failed: {str(e)}")
    
    elif data == "insert_clear":
        session["insert_audio_file"] = None
        session["insert_position"] = None
        await update_user_session(user_id, session)
        await callback_query.answer("Insert data cleared!", show_alert=True)
    
    # Preview action
    elif data == "action_preview":
        if not session.get("current_file"):
            await callback_query.answer("No audio loaded!", show_alert=True)
            return
        
        await callback_query.answer("Generating preview...")
        
        try:
            temp_preview = tempfile.mktemp(suffix="_preview.mp3")
            
            if session.get("edits"):
                processed_path = await apply_all_edits(session["current_file"], session["edits"])
                generate_preview_ffmpeg(processed_path, temp_preview, duration=15)
                if os.path.exists(processed_path):
                    os.remove(processed_path)
            else:
                generate_preview_ffmpeg(session["current_file"], temp_preview, duration=15)
            
            await callback_query.message.reply_audio(
                audio=temp_preview,
                title="Preview (15 seconds)",
                performer="Audio Editor Bot",
                caption="🎬 Here's your 15-second preview."
            )
            
            if os.path.exists(temp_preview):
                os.remove(temp_preview)
                
        except Exception as e:
            logger.error(f"Preview error: {traceback.format_exc()}")
            await callback_query.answer(f"Preview failed: {str(e)}", show_alert=True)
    
    # Export action
    elif data == "action_export":
        if not session.get("current_file"):
            await callback_query.answer("No audio loaded!", show_alert=True)
            return
        
        status_msg = await callback_query.message.reply_text("🎨 **Processing your audio...**\n\nThis may take a moment.", parse_mode=ParseMode.MARKDOWN)
        
        try:
            processed_path = await apply_all_edits(session["current_file"], session.get("edits", []))
            
            if session.get("metadata"):
                processed_path = await add_metadata_to_audio(
                    processed_path,
                    session["metadata"],
                    session.get("thumbnail_path")
                )
            
            format_type = session.get("output_format", "mp3")
            title = session.get("metadata", {}).get("title", "Edited Audio")
            artist = session.get("metadata", {}).get("artist", "Audio Editor Bot")
            
            await callback_query.message.reply_audio(
                audio=processed_path,
                title=title,
                performer=artist,
                caption="✅ **Export complete!**\n\nThank you for using Audio Studio Bot! 🎵",
                parse_mode=ParseMode.MARKDOWN
            )
            
            await status_msg.delete()
            await callback_query.answer("Export completed!", show_alert=True)
            
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
            audio_info = get_audio_info(session["current_file"])
            info_text = f"""
📊 **Audio Information**

⏱ **Duration:** `{int(audio_info['duration'] // 60)}:{int(audio_info['duration'] % 60):02d}`
🎵 **Bitrate:** `{audio_info['bitrate']} kbps`
🔊 **Sample Rate:** `{audio_info['sample_rate']} Hz`
📝 **Edits applied:** `{len(session.get('edits', []))}`
🎵 **Output format:** `{session.get('output_format', 'mp3')}`
📦 **Metadata:** `{'Yes' if session.get('metadata') else 'No'}`
🖼 **Thumbnail:** `{'Yes' if session.get('thumbnail_file_id') else 'No'}`
🔀 **Merge queue:** `{len(session.get('merge_queue', []))} files`
➕ **Insert ready:** `{'Yes' if session.get('insert_audio_file') else 'No'}`
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
        await callback_query.answer("Feature coming soon!", show_alert=True)
    
    elif data == "setting_compression":
        await callback_query.answer("Feature coming soon!", show_alert=True)

# ==================== TEXT HANDLERS ====================

@app.on_message(filters.text & filters.private)
async def handle_text_input(client: Client, message: Message):
    user_id = message.from_user.id
    session = await get_user_session(user_id)
    text = message.text.strip()
    
    # Trim start time
    if session.get("awaiting_trim_start"):
        try:
            start_time = float(text)
            if start_time < 0:
                raise ValueError
            session["trim_start"] = start_time
            session["awaiting_trim_start"] = False
            await update_user_session(user_id, session)
            await message.reply_text(f"✅ Start time set to {start_time} seconds\nNow send the end time.")
        except ValueError:
            await message.reply_text("❌ Invalid time! Please send a positive number (e.g., 30)")
    
    # Trim end time
    elif session.get("awaiting_trim_end"):
        try:
            end_time = float(text)
            if end_time < 0:
                raise ValueError
            session["trim_end"] = end_time
            session["awaiting_trim_end"] = False
            await update_user_session(user_id, session)
            await message.reply_text(f"✅ End time set to {end_time} seconds\nClick 'Apply Trim' to finish.")
        except ValueError:
            await message.reply_text("❌ Invalid time! Please send a positive number")
    
    # Insert position
    elif session.get("awaiting_insert_position"):
        try:
            position = float(text)
            if position < 0:
                raise ValueError
            session["insert_position"] = position
            session["awaiting_insert_position"] = False
            await update_user_session(user_id, session)
            await message.reply_text(f"✅ Insert position set to {position} seconds\nClick 'Insert Now' to proceed.")
        except ValueError:
            await message.reply_text("❌ Invalid position! Please send a positive number")
    
    # Metadata inputs
    elif session.get("awaiting_meta_title"):
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["title"] = text
        session["awaiting_meta_title"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Title set to: {text}")
    
    elif session.get("awaiting_meta_artist"):
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["artist"] = text
        session["awaiting_meta_artist"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Artist set to: {text}")
    
    elif session.get("awaiting_meta_album"):
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["album"] = text
        session["awaiting_meta_album"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Album set to: {text}")
    
    elif session.get("awaiting_meta_genre"):
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["genre"] = text
        session["awaiting_meta_genre"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Genre set to: {text}")
    
    elif session.get("awaiting_meta_year"):
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["year"] = text
        session["awaiting_meta_year"] = False
        await update_user_session(user_id, session)
        await message.reply_text(f"✅ Year set to: {text}")
    
    elif session.get("awaiting_autofetch"):
        await message.reply_text("🔍 Fetching metadata...")
        metadata = await fetch_metadata_from_api(text)
        
        if metadata:
            if "metadata" not in session:
                session["metadata"] = {}
            session["metadata"].update(metadata)
            await update_user_session(user_id, session)
            
            info_text = f"""
✅ **Metadata fetched!**

📝 Title: {metadata.get('title', 'N/A')}
👤 Artist: {metadata.get('artist', 'N/A')}
💿 Album: {metadata.get('album', 'N/A')}
📅 Year: {metadata.get('year', 'N/A')}
            """
            await message.reply_text(info_text)
        else:
            await message.reply_text("❌ Could not fetch metadata. Please enter manually.")
        
        session["awaiting_autofetch"] = False
        await update_user_session(user_id, session)

# ==================== AUDIO HANDLERS ====================

@app.on_message(filters.audio & filters.private)
async def handle_audio_for_merge_insert(client: Client, message: Message):
    """Handle audio for merge queue or insert"""
    user_id = message.from_user.id
    session = await get_user_session(user_id)
    
    # Handle merge queue addition
    if session.get("awaiting_merge_add"):
        try:
            audio = message.audio
            file_id = audio.file_id
            file_name = audio.file_name or f"audio_{len(session.get('merge_queue', [])) + 1}"
            
            audio_path = await download_audio(file_id, user_id)
            
            if "merge_queue" not in session:
                session["merge_queue"] = []
            
            session["merge_queue"].append({
                "file_id": file_id,
                "name": file_name,
                "path": audio_path
            })
            session["awaiting_merge_add"] = False
            await update_user_session(user_id, session)
            
            await message.reply_text(f"✅ Added to merge queue: {file_name}\n\nQueue size: {len(session['merge_queue'])}/10\nUse merge menu to add more or merge now.")
        except Exception as e:
            logger.error(f"Merge add error: {e}")
            await message.reply_text(f"❌ Failed to add audio: {str(e)}")
    
    # Handle insert audio upload
    elif session.get("awaiting_insert_audio"):
        try:
            audio = message.audio
            file_id = audio.file_id
            file_name = audio.file_name or "insert_audio"
            
            audio_path = await download_audio(file_id, user_id)
            
            session["insert_audio_file"] = audio_path
            session["awaiting_insert_audio"] = False
            await update_user_session(user_id, session)
            
            audio_info = get_audio_info(audio_path)
            await message.reply_text(
                f"✅ Audio ready to insert!\n\n"
                f"📝 Name: {file_name}\n"
                f"⏱ Duration: {int(audio_info['duration'] // 60)}:{int(audio_info['duration'] % 60):02d}\n\n"
                f"Now set the insertion position using the menu."
            )
            await message.reply_text("Choose where to insert:", reply_markup=get_position_menu())
        except Exception as e:
            logger.error(f"Insert audio error: {e}")
            await message.reply_text(f"❌ Failed to load audio: {str(e)}")

# ==================== PHOTO HANDLER ====================

@app.on_message(filters.photo & filters.private)
async def handle_thumbnail(client: Client, message: Message):
    """Handle thumbnail uploads"""
    user_id = message.from_user.id
    session = await get_user_session(user_id)
    
    if session.get("awaiting_thumbnail"):
        try:
            photo = message.photo[-1]
            thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{user_id}.jpg")
            await app.download_media(photo, file_name=thumb_path)
            
            session["thumbnail_path"] = thumb_path
            session["thumbnail_file_id"] = photo.file_id
            session["awaiting_thumbnail"] = False
            await update_user_session(user_id, session)
            
            await message.reply_text("✅ Thumbnail added! It will be embedded in the final audio.")
        except Exception as e:
            logger.error(f"Thumbnail error: {e}")
            await message.reply_text("❌ Failed to save thumbnail.")

# ==================== CLEANUP ====================

async def cleanup_old_files():
    """Periodically clean up old files"""
    while True:
        try:
            cutoff = datetime.now() - timedelta(hours=1)
            for directory in [DOWNLOAD_DIR, CACHE_DIR, TEMP_DIR]:
                if os.path.exists(directory):
                    for file in os.listdir(directory):
                        file_path = os.path.join(directory, file)
                        if os.path.isfile(file_path):
                            file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                            if file_time < cutoff:
                                os.remove(file_path)
                                logger.info(f"Cleaned up: {file}")
            
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            await asyncio.sleep(3600)

# ==================== MAIN ====================

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(cleanup_old_files())
    
    logger.info("Starting Audio Editor Bot v2.0...")
    app.run()
