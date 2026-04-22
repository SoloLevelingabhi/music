"""
╔══════════════════════════════════════════════════════════════════════════╗
║                      MUSIC BOT —                                         ║
║                                                                          ║
║  Telegram Audio Editing Bot - Complete Rewritten Version                 ║
║  All features working: trim, speed, merge, insert at position            ║
║                                                                          ║
║  Sponsored by  : MUSIC                                                   ║
║  Developed by  : DEVA                                                    ║
║  Version       : 1.5                                                     ║
║  License       : MIT                                                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import os
import logging
import traceback
import asyncio
import tempfile
import shutil
import subprocess
import json
import hashlib
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from enum import Enum as PyroEnum

# Core libraries
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ForceReply
)
from pyrogram.enums import ParseMode

# MongoDB
from motor.motor_asyncio import AsyncIOMotorClient

# Metadata
import mutagen
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TCON, TDRC

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
BOT_TOKEN = "8765826723:AAH1HhVIVKv83uueUnxjZfTRG-vM61_bhEU"
API_ID = 19500615
API_HASH = "7ee1d55d072add75a01e617fc0cef635"
MONGO_URL = "mongodb+srv://cegin48057:HZuqtvUqi0tYJEda@cluster0.vw0nw.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
OWNER_ID = 8765826723  # Replace with your owner ID

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

# ==================== FFMPEG HELPER FUNCTIONS (FIXED) ====================
def get_audio_info(file_path: str) -> dict:
    """Get detailed audio information using ffprobe"""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-show_format', file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
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
    """Change speed - fixed version with better error handling"""
    try:
        # First, re-encode to ensure consistent format
        normalized_path = tempfile.mktemp(suffix=".mp3")
        norm_cmd = ['ffmpeg', '-i', input_path, '-acodec', 'libmp3lame', '-ar', '44100', '-y', normalized_path]
        subprocess.run(norm_cmd, check=True, capture_output=True)
        
        # Handle speed change
        if 0.5 <= speed <= 2.0:
            cmd = [
                'ffmpeg', '-i', normalized_path,
                '-filter:a', f'atempo={speed}',
                '-acodec', 'libmp3lame',
                '-y', output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        else:
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
                'ffmpeg', '-i', normalized_path,
                '-filter:a', filter_chain,
                '-acodec', 'libmp3lame',
                '-y', output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        
        # Cleanup
        if os.path.exists(normalized_path):
            os.remove(normalized_path)
            
    except subprocess.CalledProcessError as e:
        logger.error(f"Speed change error: {e}")
        # Fallback using aresample
        cmd = [
            'ffmpeg', '-i', input_path,
            '-filter:a', f'aresample=44100,atempo={speed}',
            '-acodec', 'libmp3lame',
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
        '-acodec', 'libmp3lame',
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
        # Normalize all files to same format
        normalized_paths = []
        for i, path in enumerate(input_paths):
            normalized = tempfile.mktemp(suffix=".mp3")
            cmd_convert = ['ffmpeg', '-i', path, '-acodec', 'libmp3lame', '-ar', '44100', '-y', normalized]
            subprocess.run(cmd_convert, check=True, capture_output=True)
            normalized_paths.append(normalized)
        
        # Create concat file
        concat_file = tempfile.mktemp(suffix=".txt")
        with open(concat_file, 'w') as f:
            for path in normalized_paths:
                abs_path = os.path.abspath(path)
                f.write(f"file '{abs_path}'\n")
        
        # Merge
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', concat_file, '-c', 'copy', '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Cleanup
        for path in normalized_paths:
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(concat_file):
            os.remove(concat_file)
            
    except Exception as e:
        logger.error(f"Merge error: {e}")
        raise

def insert_audio_at_position(main_audio: str, insert_audio: str, output_path: str, position_seconds: float):
    """Insert audio clip at specific position in main audio"""
    try:
        # Normalize both files
        norm_main = tempfile.mktemp(suffix=".mp3")
        norm_insert = tempfile.mktemp(suffix=".mp3")
        
        cmd_main = ['ffmpeg', '-i', main_audio, '-acodec', 'libmp3lame', '-ar', '44100', '-y', norm_main]
        cmd_insert = ['ffmpeg', '-i', insert_audio, '-acodec', 'libmp3lame', '-ar', '44100', '-y', norm_insert]
        
        subprocess.run(cmd_main, check=True, capture_output=True)
        subprocess.run(cmd_insert, check=True, capture_output=True)
        
        # Split main audio
        part1 = tempfile.mktemp(suffix=".mp3")
        part2 = tempfile.mktemp(suffix=".mp3")
        
        if position_seconds > 0:
            cmd1 = ['ffmpeg', '-i', norm_main, '-t', str(position_seconds), '-c', 'copy', '-y', part1]
            subprocess.run(cmd1, check=True, capture_output=True)
        
        cmd2 = ['ffmpeg', '-i', norm_main, '-ss', str(position_seconds), '-c', 'copy', '-y', part2]
        subprocess.run(cmd2, check=True, capture_output=True)
        
        # Create concat file
        concat_file = tempfile.mktemp(suffix=".txt")
        with open(concat_file, 'w') as f:
            if position_seconds > 0 and os.path.exists(part1) and os.path.getsize(part1) > 0:
                f.write(f"file '{os.path.abspath(part1)}'\n")
            f.write(f"file '{os.path.abspath(norm_insert)}'\n")
            if os.path.exists(part2) and os.path.getsize(part2) > 0:
                f.write(f"file '{os.path.abspath(part2)}'\n")
        
        # Merge
        cmd = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_file, '-c', 'copy', '-y', output_path]
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Cleanup
        for f in [norm_main, norm_insert, part1, part2, concat_file]:
            if os.path.exists(f):
                os.remove(f)
                
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
            "thumbnail_path": None,
            "merge_queue": [],
            "insert_audio_file": None,
            "insert_position": None,
            "state": None,  # Current state machine state
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
    # Clean up files
    session = await get_user_session(user_id)
    if session.get("current_file") and os.path.exists(session["current_file"]):
        try:
            os.remove(session["current_file"])
        except:
            pass
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
        
        # Convert to standard format
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
                
                if current_path != audio_path and os.path.exists(current_path):
                    os.remove(current_path)
                
                current_path = output_path
                
            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg error for edit {edit_type}: {e}")
                raise
        
        final_output = tempfile.mktemp(suffix=".mp3")
        shutil.copy(current_path, final_output)
        
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
                # Try to add as ID3 tag
                audio_file = mutagen.File(audio_path)
                if audio_file and hasattr(audio_file, 'add'):
                    with open(thumbnail_path, 'rb') as f:
                        audio_file.tags.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc='Cover',
                            data=f.read()
                        ))
                    audio_file.save()
            except Exception as e:
                logger.warning(f"Could not add thumbnail: {e}")
        
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
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
            InlineKeyboardButton("❌ Close", callback_data="menu_close")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_start_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
            InlineKeyboardButton("📋 Plans", callback_data="menu_plans")
        ],
        [InlineKeyboardButton("❌ Close", callback_data="menu_close")]
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
            InlineKeyboardButton("👁 View Metadata", callback_data="meta_view"),
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
def notify_owner():
    """Notify owner that bot is live"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": OWNER_ID,
            "text": "🤖 Audio Editor Bot is Live Now!\n\n✅ All features working\n🎵 Ready for audio editing"
        }
        requests.post(url, json=data)
    except Exception as e:
        logger.error(f"Owner notification failed: {e}")

def reset_and_set_commands():
    """Reset and set bot commands"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        # Reset commands
        requests.post(url, json={"commands": []})
        # Set new commands
        commands = [
            {"command": "start", "description": "✅ Start the bot"},
            {"command": "settings", "description": "⚙️ Change bot settings"},
            {"command": "reset", "description": "♻️ Reset current session"},
            {"command": "help", "description": "❓ Get help"},
        ]
        requests.post(url, json={"commands": commands})
    except Exception as e:
        logger.error(f"Set commands failed: {e}")

@app.on_message(filters.command(["start", "help"]))
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
    await message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_start_menu())

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

# ==================== AUDIO HANDLER (Main Entry Point) ====================
@app.on_message(filters.audio | filters.voice)
async def handle_audio(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Determine audio type
    if message.audio:
        audio = message.audio
        file_id = audio.file_id
        title = audio.file_name or "Unknown"
    else:
        audio = message.voice
        file_id = audio.file_id
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

📝 **Title:** {title}
⏱ **Duration:** {int(audio_info['duration'] // 60)}:{int(audio_info['duration'] % 60):02d}
🎵 **Bitrate:** {audio_info['bitrate']} kbps
🔊 **Sample Rate:** {audio_info['sample_rate']} Hz

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
    
    # Close menu
    if data == "menu_close":
        await callback_query.message.delete()
        await callback_query.answer("Menu closed")
        return
    
    # Help menu
    if data == "menu_help":
        help_text = """
❓ **Help Guide**

**Basic Workflow:**
1. Send an audio file to load it
2. Use buttons to apply edits
3. Use Preview to check results
4. Export when satisfied

**Available Edits:**
- **Trim:** Cut audio to specific time range
- **Volume:** Adjust loudness (50% to 200%)
- **Speed:** Change playback speed
- **Convert:** Change audio format
- **Enhance:** Normalize or add bass boost
- **Metadata:** Add title, artist, album, etc.
- **Merge:** Combine multiple audio files
- **Insert:** Place audio at specific position

**Tips:**
- You can apply multiple edits in sequence
- Always preview before export
- Use Reset to start over
        """
        await callback_query.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        await callback_query.answer()
        return
    
    # Plans menu
    if data == "menu_plans":
        plans_text = """
📋 **Bot Plans**

**Free Plan:**
✅ All editing features
✅ Up to 10MB files
✅ Basic metadata
✅ 5 merges per day

**Premium (Coming Soon):**
⭐ Unlimited file size
⭐ Batch processing
⭐ Advanced effects
⭐ Priority support
        """
        await callback_query.message.reply_text(plans_text, parse_mode=ParseMode.MARKDOWN)
        await callback_query.answer()
        return
    
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
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "📍 **Send the start time in seconds**\n\nExample: `30` for 30 seconds, `1.5` for 1.5 seconds\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        try:
            start_time = float(response.text)
            if start_time < 0:
                raise ValueError
            session["trim_start"] = start_time
            await update_user_session(user_id, session)
            await response.reply_text(f"✅ Start time set to {start_time} seconds\n\nNow set the end time using the menu.")
        except ValueError:
            await response.reply_text("❌ Invalid time! Please send a positive number (e.g., 30)")
    
    elif data == "trim_set_end":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "📍 **Send the end time in seconds**\n\nExample: `120` for 120 seconds\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        try:
            end_time = float(response.text)
            if end_time < 0:
                raise ValueError
            session["trim_end"] = end_time
            await update_user_session(user_id, session)
            await response.reply_text(f"✅ End time set to {end_time} seconds\n\nClick 'Apply Trim' to finish.")
        except ValueError:
            await response.reply_text("❌ Invalid time! Please send a positive number")
    
    elif data == "trim_apply":
        if session.get("trim_start") is not None and session.get("trim_end") is not None:
            if session["trim_start"] >= session["trim_end"]:
                await callback_query.answer("Start time must be less than end time!", show_alert=True)
                return
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
            await callback_query.answer(f"Volume set to {int(factor*100)}%", show_alert=True)
        
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
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "📝 **Send the new title**\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["title"] = response.text
        await update_user_session(user_id, session)
        await response.reply_text(f"✅ Title set to: {response.text}")
    
    elif data == "meta_artist":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "👤 **Send the artist name**\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["artist"] = response.text
        await update_user_session(user_id, session)
        await response.reply_text(f"✅ Artist set to: {response.text}")
    
    elif data == "meta_album":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "💿 **Send the album name**\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["album"] = response.text
        await update_user_session(user_id, session)
        await response.reply_text(f"✅ Album set to: {response.text}")
    
    elif data == "meta_genre":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "🎭 **Send the genre**\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["genre"] = response.text
        await update_user_session(user_id, session)
        await response.reply_text(f"✅ Genre set to: {response.text}")
    
    elif data == "meta_year":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "📅 **Send the year**\n\nExample: 2024\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if "metadata" not in session:
            session["metadata"] = {}
        session["metadata"]["year"] = response.text
        await update_user_session(user_id, session)
        await response.reply_text(f"✅ Year set to: {response.text}")
    
    elif data == "meta_thumbnail":
        await callback_query.answer("Send a photo for album art", show_alert=True)
        
        response = await client.ask(
            callback_query.message.chat.id,
            "🖼 **Send a photo to use as album art**\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if response.photo:
            try:
                photo = response.photo[-1]
                thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{user_id}.jpg")
                await app.download_media(photo, file_name=thumb_path)
                
                session["thumbnail_path"] = thumb_path
                await update_user_session(user_id, session)
                await response.reply_text("✅ Thumbnail added! It will be embedded in the final audio.")
            except Exception as e:
                await response.reply_text(f"❌ Failed to save thumbnail: {str(e)}")
        else:
            await response.reply_text("❌ Please send a valid photo.")
    
    elif data == "meta_autofetch":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "🔍 **Send song/artist name to fetch metadata**\n\nExample: `Bohemian Rhapsody Queen`\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        status_msg = await response.reply_text("🔍 Fetching metadata...")
        metadata = await fetch_metadata_from_api(response.text)
        
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
            await status_msg.edit_text(info_text)
        else:
            await status_msg.edit_text("❌ Could not fetch metadata. Please enter manually.")
    
    elif data == "meta_view":
        metadata = session.get("metadata", {})
        if metadata:
            info_text = f"""
📝 **Current Metadata**

Title: {metadata.get('title', 'Not set')}
Artist: {metadata.get('artist', 'Not set')}
Album: {metadata.get('album', 'Not set')}
Genre: {metadata.get('genre', 'Not set')}
Year: {metadata.get('year', 'Not set')}
Thumbnail: {'✅ Set' if session.get('thumbnail_path') else '❌ Not set'}
            """
        else:
            info_text = "📝 No metadata set yet. Use the buttons to add metadata."
        
        await callback_query.message.reply_text(info_text, parse_mode=ParseMode.MARKDOWN)
        await callback_query.answer()
    
    # Merge actions (using ask for auto queue)
    elif data == "merge_add":
        await callback_query.answer()
        
        await callback_query.message.reply_text(
            "📤 **Send audio files to add to merge queue**\n\n"
            "Send one or more audio files. I'll automatically add them to the queue.\n"
            "Send **/done** when finished adding files.\n"
            "Send **/cancel** to cancel."
        )
        
        session["awaiting_merge"] = True
        if "merge_queue" not in session:
            session["merge_queue"] = []
        await update_user_session(user_id, session)
        
        # Listen for multiple audio files
        while True:
            try:
                response = await client.ask(
                    callback_query.message.chat.id,
                    "Waiting for audio files...",
                    timeout=120
                )
                
                if response.text == "/done":
                    break
                elif response.text == "/cancel":
                    session["awaiting_merge"] = False
                    await update_user_session(user_id, session)
                    await response.reply_text("❌ Merge cancelled.")
                    return
                
                if response.audio or response.voice:
                    audio = response.audio if response.audio else response.voice
                    file_id = audio.file_id
                    file_name = audio.file_name if response.audio else "Voice Message"
                    
                    audio_path = await download_audio(file_id, user_id)
                    
                    session["merge_queue"].append({
                        "file_id": file_id,
                        "name": file_name,
                        "path": audio_path
                    })
                    await update_user_session(user_id, session)
                    
                    await response.reply_text(
                        f"✅ Added to merge queue: {file_name}\n"
                        f"Queue size: {len(session['merge_queue'])}/10\n\n"
                        f"Send more files or type **/done** to finish."
                    )
                else:
                    await response.reply_text("❌ Please send an audio file.")
                    
            except asyncio.TimeoutError:
                await callback_query.message.reply_text("⏰ Timeout! Merge cancelled.")
                session["awaiting_merge"] = False
                await update_user_session(user_id, session)
                break
    
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
                merge_paths = [file['path'] for file in merge_queue]
                output_path = tempfile.mktemp(suffix="_merged.mp3")
                
                merge_audios_fixed(merge_paths, output_path)
                
                await callback_query.message.reply_audio(
                    audio=output_path,
                    title="Merged Audio",
                    performer="Audio Editor Bot",
                    caption="✅ **Merge completed!**\n\nYou can now apply more edits or export."
                )
                
                session["current_file"] = output_path
                session["merge_queue"] = []
                await update_user_session(user_id, session)
                
                await status_msg.delete()
                await callback_query.message.edit_reply_markup(reply_markup=get_main_menu())
                
            except Exception as e:
                logger.error(f"Merge error: {traceback.format_exc()}")
                await status_msg.edit_text(f"❌ Merge failed: {str(e)}")
    
    elif data == "merge_clear":
        # Clean up files
        for file in session.get("merge_queue", []):
            if os.path.exists(file['path']):
                try:
                    os.remove(file['path'])
                except:
                    pass
        session["merge_queue"] = []
        await update_user_session(user_id, session)
        await callback_query.answer("Merge queue cleared!", show_alert=True)
    
    # Insert actions
    elif data == "insert_upload":
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "📤 **Send the audio file to insert**\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        if response.audio or response.voice:
            try:
                audio = response.audio if response.audio else response.voice
                file_id = audio.file_id
                file_name = audio.file_name if response.audio else "Voice Message"
                
                audio_path = await download_audio(file_id, user_id)
                
                session["insert_audio_file"] = audio_path
                await update_user_session(user_id, session)
                
                audio_info = get_audio_info(audio_path)
                await response.reply_text(
                    f"✅ Audio ready to insert!\n\n"
                    f"📝 Name: {file_name}\n"
                    f"⏱ Duration: {int(audio_info['duration'] // 60)}:{int(audio_info['duration'] % 60):02d}\n\n"
                    f"Now set the insertion position using the menu."
                )
                await response.reply_text("Choose where to insert:", reply_markup=get_position_menu())
            except Exception as e:
                await response.reply_text(f"❌ Failed to load audio: {str(e)}")
        else:
            await response.reply_text("❌ Please send an audio file.")
    
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
        await callback_query.answer()
        response = await client.ask(
            callback_query.message.chat.id,
            "📍 **Send the position in seconds**\n\nExample: `30` for 30 seconds\n\nSend /cancel to cancel.",
            timeout=60,
            parse_mode=ParseMode.MARKDOWN
        )
        
        if response.text == "/cancel":
            await response.reply_text("❌ Operation cancelled.")
            return
        
        try:
            position = float(response.text)
            if position < 0:
                raise ValueError
            session["insert_position"] = position
            await update_user_session(user_id, session)
            await response.reply_text(f"✅ Insert position set to {position} seconds\n\nClick 'Insert Now' to proceed.")
        except ValueError:
            await response.reply_text("❌ Invalid position! Please send a positive number")
    
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
                
                await callback_query.message.reply_audio(
                    audio=output_path,
                    title="Audio with Insert",
                    performer="Audio Editor Bot",
                    caption="✅ **Insert completed!**\n\nThe audio clip has been inserted at the specified position."
                )
                
                # Clean up old file
                if session["current_file"] != session.get("original_file_path"):
                    if os.path.exists(session["current_file"]):
                        try:
                            os.remove(session["current_file"])
                        except:
                            pass
                
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
        if session.get("insert_audio_file") and os.path.exists(session["insert_audio_file"]):
            try:
                os.remove(session["insert_audio_file"])
            except:
                pass
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

⏱ **Duration:** {int(audio_info['duration'] // 60)}:{int(audio_info['duration'] % 60):02d}
🎵 **Bitrate:** {audio_info['bitrate']} kbps
🔊 **Sample Rate:** {audio_info['sample_rate']} Hz

📝 **Edits applied:** {len(session.get('edits', []))}
🎵 **Output format:** {session.get('output_format', 'mp3')}

📦 **Metadata:** {'Yes' if session.get('metadata') else 'No'}
🖼 **Thumbnail:** {'Yes' if session.get('thumbnail_path') else 'No'}

🔀 **Merge queue:** {len(session.get('merge_queue', []))} files
➕ **Insert ready:** {'Yes' if session.get('insert_audio_file') else 'No'}
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
    # Setup commands and notify owner
    reset_and_set_commands()
    notify_owner()
    
    # Start cleanup task
    loop = asyncio.get_event_loop()
    loop.create_task(cleanup_old_files())
    
    logger.info("Starting Audio Editor Bot v3.0...")
    app.run()
