import asyncio
import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Any

import config
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except Exception:  # pragma: no cover
    AsyncIOMotorClient = None


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("music_bot")


class ConversationState:
    IDLE = "idle"
    AWAITING_THUMBNAIL = "awaiting_thumbnail"
    AWAITING_WATERMARK = "awaiting_watermark"


DEFAULT_SETTINGS = {
    "send_as": "audio",
    "output_format": "mp3",
    "add_thumbnail": True,
    "thumbnail_file_id": "",
    "watermark_file_id": "",
    "watermark_position": "end",
}


def ensure_dirs() -> None:
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)


class SettingsStore:
    def __init__(self) -> None:
        self.mongo_collection = None
        self.file_path = Path(config.SETTINGS_FILE)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._json_cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        if config.MONGO_URI and AsyncIOMotorClient:
            try:
                client = AsyncIOMotorClient(config.MONGO_URI)
                self.mongo_collection = client["music_bot"]["user_settings"]
                await self.mongo_collection.create_index("user_id", unique=True)
                logger.info("Connected to MongoDB for user settings")
            except Exception as exc:
                logger.warning("Mongo init failed, using JSON fallback: %s", exc)
                self.mongo_collection = None
        await self._load_json()

    async def _load_json(self) -> None:
        if not self.file_path.exists():
            self._json_cache = {}
            return

        def _read() -> dict[str, dict[str, Any]]:
            with self.file_path.open("r", encoding="utf-8") as f:
                return json.load(f)

        try:
            self._json_cache = await asyncio.to_thread(_read)
        except Exception:
            self._json_cache = {}

    async def _save_json(self) -> None:
        data = self._json_cache.copy()

        def _write() -> None:
            with self.file_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        await asyncio.to_thread(_write)

    async def get(self, user_id: int) -> dict[str, Any]:
        user_key = str(user_id)
        if self.mongo_collection:
            doc = await self.mongo_collection.find_one({"user_id": user_id})
            if doc:
                merged = DEFAULT_SETTINGS.copy()
                merged.update(doc.get("settings", {}))
                return merged

        cached = self._json_cache.get(user_key, {})
        merged = DEFAULT_SETTINGS.copy()
        merged.update(cached)
        return merged

    async def update(self, user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            current = await self.get(user_id)
            current.update(updates)

            if self.mongo_collection:
                await self.mongo_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"settings": current}},
                    upsert=True,
                )

            self._json_cache[str(user_id)] = current
            await self._save_json()
            return current


app = Client(
    "music_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)

store = SettingsStore()
user_states: dict[int, str] = {}
merge_sessions: dict[int, list[str]] = {}


def settings_keyboard(settings: dict[str, Any]) -> InlineKeyboardMarkup:
    send_as = settings.get("send_as", "audio")
    output_format = settings.get("output_format", "mp3")
    watermark_position = settings.get("watermark_position", "end")
    add_thumb = "ON" if settings.get("add_thumbnail", True) else "OFF"

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Send As: {send_as.title()}", callback_data="settings:toggle_send"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Format: {output_format.upper()}", callback_data="settings:cycle_format"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Thumbnail: {add_thumb}", callback_data="settings:toggle_thumb"
                )
            ],
            [
                InlineKeyboardButton(
                    f"Watermark: {watermark_position.title()}",
                    callback_data="settings:cycle_watermark_position",
                )
            ],
            [InlineKeyboardButton("🖼️ Set Thumbnail", callback_data="settings:set_thumbnail")],
            [InlineKeyboardButton("🎙️ Watermark", callback_data="action:set_watermark")],
        ]
    )


def _sanitize_media_ext(message: Message) -> str:
    media = message.audio or message.document
    if media and media.file_name and "." in media.file_name:
        return media.file_name.rsplit(".", 1)[-1].lower()
    return "mp3"


async def run_ffmpeg(command: list[str]) -> tuple[bool, str]:
    loop = asyncio.get_running_loop()

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=False, capture_output=True, text=True)

    result = await loop.run_in_executor(None, _run)
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        logger.error("FFmpeg failed [%s]: %s", result.returncode, stderr)
        return False, stderr
    return True, stderr


async def prepare_audio_file(input_path: Path, output_ext: str) -> tuple[Path | None, str]:
    if not input_path.exists() or input_path.stat().st_size == 0:
        return None, "Input audio file is missing or empty."

    last_error = ""
    for _ in range(3):
        output_path = config.CACHE_DIR / f"{uuid.uuid4().hex}.{output_ext}"
        if output_path.exists():
            output_path.unlink(missing_ok=True)

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path), str(output_path)]
        ok, err = await run_ffmpeg(cmd)
        if ok and output_path.exists() and output_path.stat().st_size > 0:
            return output_path, ""
        last_error = err or "Unknown ffmpeg failure"

    return None, last_error


async def apply_watermark(main_audio: Path, user_id: int) -> tuple[Path, str]:
    settings = await store.get(user_id)
    watermark_file_id = settings.get("watermark_file_id")
    if not watermark_file_id:
        return main_audio, ""

    wm_path = config.CACHE_DIR / f"wm_{user_id}_{uuid.uuid4().hex}.mp3"
    await app.download_media(watermark_file_id, file_name=str(wm_path))
    if not wm_path.exists() or wm_path.stat().st_size == 0:
        wm_path.unlink(missing_ok=True)
        return main_audio, ""

    output_ext = main_audio.suffix.lstrip(".") or "mp3"
    out_path = config.CACHE_DIR / f"watermarked_{uuid.uuid4().hex}.{output_ext}"
    out_path.unlink(missing_ok=True)

    position = settings.get("watermark_position", "end")
    if position == "start":
        filter_complex = "[1:a][0:a]concat=n=2:v=0:a=1[a]"
    elif position == "both":
        filter_complex = "[1:a][0:a][1:a]concat=n=3:v=0:a=1[a]"
    else:
        filter_complex = "[0:a][1:a]concat=n=2:v=0:a=1[a]"

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(main_audio),
        "-i",
        str(wm_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[a]",
        str(out_path),
    ]
    ok, err = await run_ffmpeg(cmd)

    wm_path.unlink(missing_ok=True)
    if not ok or not out_path.exists() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return main_audio, err

    return out_path, ""


async def send_processed_file(message: Message, audio_path: Path, user_id: int) -> None:
    settings = await store.get(user_id)
    caption = "✅ Processed audio ready"
    thumb_path = None

    if settings.get("add_thumbnail") and settings.get("thumbnail_file_id"):
        thumb_path = config.CACHE_DIR / f"thumb_{user_id}_{uuid.uuid4().hex}.jpg"
        try:
            await app.download_media(settings["thumbnail_file_id"], file_name=str(thumb_path))
            if not thumb_path.exists() or thumb_path.stat().st_size == 0:
                thumb_path = None
        except Exception:
            thumb_path = None

    if settings.get("send_as") == "document":
        await message.reply_document(document=str(audio_path), caption=caption)
    else:
        await message.reply_audio(
            audio=str(audio_path),
            caption=caption,
            thumb=str(thumb_path) if thumb_path else None,
        )

    if thumb_path:
        Path(thumb_path).unlink(missing_ok=True)


@app.on_message(filters.command("start"))
async def start_handler(_: Client, message: Message) -> None:
    text = (
        "🎵 Smart Audio Studio Bot\n\n"
        "Send an audio file to process with your settings.\n"
        "Commands:\n"
        "/settings - edit output settings\n"
        "/watermark - set watermark audio\n"
        "/merge - merge multiple audio files"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
            [InlineKeyboardButton("🎙️ Watermark", callback_data="action:set_watermark")],
            [InlineKeyboardButton("🔗 Merge", callback_data="action:merge")],
        ]
    )
    await message.reply_text(text, reply_markup=keyboard)


@app.on_message(filters.command("settings"))
async def settings_handler(_: Client, message: Message) -> None:
    settings = await store.get(message.from_user.id)
    await message.reply_text("⚙️ Your settings", reply_markup=settings_keyboard(settings))


@app.on_message(filters.command("watermark"))
async def watermark_command(_: Client, message: Message) -> None:
    user_states[message.from_user.id] = ConversationState.AWAITING_WATERMARK
    await message.reply_text("Send your watermark audio clip now.")


@app.on_message(filters.command("merge"))
async def merge_command(_: Client, message: Message) -> None:
    merge_sessions[message.from_user.id] = []
    await message.reply_text(
        "Send me audio files one by one for merge. Send /done when finished, /cancelmerge to abort."
    )


@app.on_message(filters.command("cancelmerge"))
async def cancel_merge(_: Client, message: Message) -> None:
    merge_sessions.pop(message.from_user.id, None)
    await message.reply_text("❎ Merge session cancelled.")


@app.on_message(filters.command("done"))
async def done_merge(_: Client, message: Message) -> None:
    user_id = message.from_user.id
    session_files = merge_sessions.get(user_id, [])
    if not session_files:
        await message.reply_text("No merge session or no files queued.")
        return

    await message.reply_text("⏳ Merging your audio files...")

    merge_dir = config.CACHE_DIR / f"merge_{user_id}_{uuid.uuid4().hex}"
    merge_dir.mkdir(parents=True, exist_ok=True)
    local_paths: list[Path] = []

    try:
        for index, file_id in enumerate(session_files):
            src = merge_dir / f"in_{index}.mp3"
            await app.download_media(file_id, file_name=str(src))
            if not src.exists() or src.stat().st_size == 0:
                await message.reply_text("❌ Failed to load one of merge inputs.")
                return
            local_paths.append(src)

        list_file = merge_dir / "inputs.txt"
        with list_file.open("w", encoding="utf-8") as f:
            for p in local_paths:
                f.write(f"file '{p.as_posix()}'\n")

        settings = await store.get(user_id)
        output_ext = settings.get("output_format", "mp3")
        merged_file = merge_dir / f"merged_{uuid.uuid4().hex}.{output_ext}"
        merged_file.unlink(missing_ok=True)

        codec_map = {
            "mp3": "libmp3lame",
            "wav": "pcm_s16le",
            "flac": "flac",
            "ogg": "libvorbis",
            "m4a": "aac",
        }
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:a",
            codec_map.get(output_ext, "libmp3lame"),
            str(merged_file),
        ]
        ok, err = await run_ffmpeg(cmd)
        if not ok or not merged_file.exists() or merged_file.stat().st_size == 0:
            await message.reply_text(f"❌ Merge failed: {err or 'Unknown ffmpeg error'}")
            return

        watermarked, wm_error = await apply_watermark(merged_file, user_id)
        if wm_error:
            await message.reply_text(f"⚠️ Watermark skipped: {wm_error}")

        await send_processed_file(message, watermarked, user_id)
    finally:
        merge_sessions.pop(user_id, None)
        for path in merge_dir.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        merge_dir.rmdir()


@app.on_callback_query()
async def callback_handler(_: Client, query) -> None:
    user_id = query.from_user.id
    data = query.data or ""

    if data == "menu:settings":
        settings = await store.get(user_id)
        await query.message.edit_text("⚙️ Your settings", reply_markup=settings_keyboard(settings))
        await query.answer()
        return

    if data == "action:set_watermark":
        user_states[user_id] = ConversationState.AWAITING_WATERMARK
        await query.answer("Send an audio clip for watermark.", show_alert=True)
        return

    if data == "action:merge":
        merge_sessions[user_id] = []
        await query.answer("Send audio files then /done", show_alert=True)
        return

    if data.startswith("settings:"):
        settings = await store.get(user_id)
        action = data.split(":", 1)[1]

        if action == "toggle_send":
            new_value = "document" if settings.get("send_as") == "audio" else "audio"
            settings = await store.update(user_id, {"send_as": new_value})
        elif action == "cycle_format":
            formats = ["mp3", "wav", "flac", "ogg", "m4a"]
            current = settings.get("output_format", "mp3")
            idx = formats.index(current) if current in formats else 0
            settings = await store.update(user_id, {"output_format": formats[(idx + 1) % len(formats)]})
        elif action == "toggle_thumb":
            settings = await store.update(user_id, {"add_thumbnail": not settings.get("add_thumbnail", True)})
        elif action == "cycle_watermark_position":
            positions = ["start", "end", "both"]
            current = settings.get("watermark_position", "end")
            idx = positions.index(current) if current in positions else 1
            settings = await store.update(user_id, {"watermark_position": positions[(idx + 1) % len(positions)]})
        elif action == "set_thumbnail":
            user_states[user_id] = ConversationState.AWAITING_THUMBNAIL
            await query.answer("Send a photo for thumbnail.", show_alert=True)
            return

        await query.message.edit_text("⚙️ Your settings", reply_markup=settings_keyboard(settings))
        await query.answer("Updated")


def is_audio_message(message: Message) -> bool:
    if message.audio:
        return True
    if message.document and message.document.mime_type:
        return message.document.mime_type.startswith("audio/")
    return False


@app.on_message(filters.photo)
async def photo_handler(_: Client, message: Message) -> None:
    user_id = message.from_user.id
    if user_states.get(user_id) != ConversationState.AWAITING_THUMBNAIL:
        return

    try:
        file_id = message.photo.file_id
        await store.update(user_id, {"thumbnail_file_id": file_id, "add_thumbnail": True})
        user_states[user_id] = ConversationState.IDLE
        await message.reply_text("✅ Thumbnail saved successfully.")
    except Exception as exc:
        logger.exception("Thumbnail save failed: %s", exc)
        await message.reply_text(f"❌ Failed to save thumbnail: {exc}")


@app.on_message(filters.audio | filters.document)
async def audio_handler(_: Client, message: Message) -> None:
    if not is_audio_message(message):
        return

    user_id = message.from_user.id

    if user_states.get(user_id) == ConversationState.AWAITING_WATERMARK:
        media = message.audio or message.document
        await store.update(user_id, {"watermark_file_id": media.file_id})
        user_states[user_id] = ConversationState.IDLE
        await message.reply_text("✅ Watermark audio saved. It will be applied to all your exports.")
        return

    if user_id in merge_sessions:
        media = message.audio or message.document
        merge_sessions[user_id].append(media.file_id)
        await message.reply_text(f"✅ Added to merge queue ({len(merge_sessions[user_id])}).")
        return

    await message.reply_text("⏳ Processing audio...")

    media = message.audio or message.document
    source_ext = _sanitize_media_ext(message)
    source_file = config.DOWNLOAD_DIR / f"{user_id}_{uuid.uuid4().hex}.{source_ext}"
    converted_file: Path | None = None
    final_audio: Path | None = None

    try:
        await app.download_media(media.file_id, file_name=str(source_file))
        if not source_file.exists() or source_file.stat().st_size == 0:
            await message.reply_text("❌ Failed to load audio input.")
            return

        settings = await store.get(user_id)
        out_ext = settings.get("output_format", "mp3")
        converted_file, error_text = await prepare_audio_file(source_file, out_ext)
        if not converted_file:
            await message.reply_text(f"❌ Failed to load audio: {error_text}")
            return

        final_audio, wm_error = await apply_watermark(converted_file, user_id)
        if wm_error:
            await message.reply_text(f"⚠️ Watermark skipped: {wm_error}")

        await send_processed_file(message, final_audio, user_id)
    except Exception as exc:
        logger.exception("Audio processing failed: %s", exc)
        await message.reply_text(f"❌ Failed to load audio: {exc}")
    finally:
        source_file.unlink(missing_ok=True)
        if converted_file:
            converted_file.unlink(missing_ok=True)
        if final_audio and final_audio != converted_file:
            final_audio.unlink(missing_ok=True)


@app.on_message(filters.command("help"))
async def help_handler(_: Client, message: Message) -> None:
    await message.reply_text(
        "Commands:\n"
        "/start - Start bot\n"
        "/settings - Edit settings\n"
        "/watermark - Save watermark audio\n"
        "/merge - Start merge mode\n"
        "/done - Finish merge\n"
        "/cancelmerge - Cancel merge"
    )


# ============================= START BOT =============================
if __name__ == "__main__":
    ensure_dirs()
    logger.info("🚀 Starting Music Bot...")
    asyncio.run(store.init())
    app.run()
