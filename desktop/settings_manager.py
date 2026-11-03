#!/usr/bin/env python3
"""
Atomic Settings and Bookmark Manager for Gemini Audiobook TTS Desktop.
Handles persistence of multiple API keys, selected TTS model, primary and secondary
voices, style presets, request pacing interval, output directory, custom voices,
and playback bookmarks using atomic file replacement (NamedTemporaryFile + os.replace).
"""

import json
import logging
import os
import platform
import base64
import ctypes
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("DesktopSettingsManager")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


from desktop.i18n import (
    MODEL_CHOICES,
    PREBUILT_VOICES_CATALOG,
    STYLE_PRESETS,
    normalize_lang,
)

SUPPORTED_MODELS: List[Dict[str, Any]] = MODEL_CHOICES

DEFAULT_SETTINGS: Dict[str, Any] = {
    "language": "en",
    "api_keys": [],
    "active_key_index": 0,
    "model_id": "gemini-3.8-flash-tts",
    "voice_name": "Charon",
    "style_index": 0,
    "style_label": STYLE_PRESETS[0]["label"],
    "style_prompt": "",
    "multi_speaker_enabled": False,
    "speaker2_voice": "Kore",
    "auto_emotion_inference": False,
    "pacing_seconds": 60.0,
    "output_dir": "",
    "merge_with_cue": True,
    "playback_speed": "1.0x",
    "last_opened_book": "",
    "custom_voices": [],
    "bookmarks": {},
}



def encrypt_key_for_storage(plain_key: str) -> str:
    """
    Encrypts an API key string for secure local storage on disk.
    On Windows: Uses Windows DPAPI (CryptProtectData) which encrypts data bound
    to the current user account credentials.
    On other platforms: Uses machine-bound obfuscation.
    Returns a string prefixed with 'enc:dpapi:' or 'enc:v1:'.
    """
    clean = plain_key.strip()
    if not clean or clean.startswith("enc:"):
        return clean

    if platform.system() == "Windows":
        try:
            import ctypes.wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [
                    ("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_byte)),
                ]

            data = clean.encode("utf-8")
            blob_in = DATA_BLOB(
                len(data),
                ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
            )
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(blob_in),
                "gemini_api_key",
                None,
                None,
                None,
                0,
                ctypes.byref(blob_out),
            ):
                encrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return "enc:dpapi:" + base64.b64encode(encrypted_bytes).decode("ascii")
        except Exception:
            pass

    import hashlib
    salt = hashlib.sha256(f"{platform.node()}-{os.name}".encode()).digest()
    data_b = clean.encode("utf-8")
    xor_b = bytes([b ^ salt[i % len(salt)] for i, b in enumerate(data_b)])
    return "enc:v1:" + base64.b64encode(xor_b).decode("ascii")


def decrypt_key_from_storage(stored_key: str) -> str:
    """
    Decrypts an API key string retrieved from local disk storage.
    Transparently handles unencrypted keys for backward compatibility.
    """
    clean = stored_key.strip()
    if not clean:
        return ""

    if clean.startswith("enc:dpapi:"):
        if platform.system() == "Windows":
            try:
                import ctypes.wintypes

                class DATA_BLOB(ctypes.Structure):
                    _fields_ = [
                        ("cbData", ctypes.wintypes.DWORD),
                        ("pbData", ctypes.POINTER(ctypes.c_byte)),
                    ]

                raw_b64 = clean[len("enc:dpapi:"):]
                encrypted_bytes = base64.b64decode(raw_b64)
                blob_in = DATA_BLOB(
                    len(encrypted_bytes),
                    ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_byte)),
                )
                blob_out = DATA_BLOB()
                if ctypes.windll.crypt32.CryptUnprotectData(
                    ctypes.byref(blob_in),
                    None,
                    None,
                    None,
                    None,
                    0,
                    ctypes.byref(blob_out),
                ):
                    decrypted_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                    return decrypted_bytes.decode("utf-8")
            except Exception:
                return ""
        return ""

    if clean.startswith("enc:v1:"):
        try:
            import hashlib
            salt = hashlib.sha256(f"{platform.node()}-{os.name}".encode()).digest()
            raw_b64 = clean[len("enc:v1:"):]
            xor_b = base64.b64decode(raw_b64)
            data_b = bytes([b ^ salt[i % len(salt)] for i, b in enumerate(xor_b)])
            return data_b.decode("utf-8")
        except Exception:
            return ""

    return clean


class SettingsManager:
    """
    Manages persistent desktop configuration and bookmarks in settings.json
    with strict atomic file writes.
    """

    DEFAULT_LANGUAGE = "en"
    DEFAULT_MODEL = "gemini-3.8-flash-tts"
    DEFAULT_PRIMARY_VOICE = "Charon"
    DEFAULT_SECONDARY_VOICE = "Kore"
    DEFAULT_PACING_SECONDS = 60.0

    def __init__(self, settings_path: Optional[Union[str, Path]] = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        if settings_path is not None:
            self.settings_path = Path(settings_path).resolve()
        else:
            self.settings_path = base_dir / "settings.json"

        self.default_output_dir = str((base_dir / "audiobook_output").resolve())
        self.settings: Dict[str, Any] = self._build_default_settings()
        self.load()

    def _build_default_settings(self) -> Dict[str, Any]:
        env_key = os.getenv("GEMINI_API_KEY", "").strip()
        initial_keys = [env_key] if env_key else []
        defaults = dict(DEFAULT_SETTINGS)
        defaults.update(
            {
                "language": self.DEFAULT_LANGUAGE,
                "api_keys": initial_keys,
                "active_key_index": 0,
                "model_id": self.DEFAULT_MODEL,
                "voice_name": self.DEFAULT_PRIMARY_VOICE,
                "style_index": 0,
                "style_label": STYLE_PRESETS[0]["label"],
                "style_prompt": "",
                "multi_speaker_enabled": False,
                "speaker2_voice": self.DEFAULT_SECONDARY_VOICE,
                "auto_emotion_inference": False,
                "pacing_seconds": self.DEFAULT_PACING_SECONDS,
                "output_dir": self.default_output_dir,
                "playback_speed": "1.0x",
                "last_opened_book": "",
                "custom_voices": [],
                "bookmarks": {},
            }
        )
        return defaults

    @staticmethod
    def atomic_write_json(target_path: Union[str, Path], payload: Dict[str, Any]) -> None:
        """
        Writes a JSON dictionary atomically using tempfile.NamedTemporaryFile and os.replace.
        """
        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(target.parent),
                prefix=f".{target.stem}_",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write(serialized)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, str(target))
        except Exception as exc:
            logger.error("Atomic write failed for %s: %s", target, str(exc))
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def load(self) -> Dict[str, Any]:
        """
        Loads settings from disk and merges with defaults.
        Automatically populates GEMINI_API_KEY from environment if api_keys is empty.
        """
        defaults = self._build_default_settings()
        if self.settings_path.is_file():
            try:
                raw_text = self.settings_path.read_text(encoding="utf-8")
                loaded = json.loads(raw_text)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
            except Exception as exc:
                logger.warning("Failed to load settings from %s: %s", self.settings_path, str(exc))

        # Sanitize api_keys list
        raw_keys = defaults.get("api_keys", [])
        clean_keys: List[str] = []
        if isinstance(raw_keys, list):
            for k in raw_keys:
                if isinstance(k, str):
                    stripped = k.strip()
                    if stripped and stripped not in clean_keys:
                        clean_keys.append(stripped)

        if not clean_keys:
            env_key = os.getenv("GEMINI_API_KEY", "").strip()
            if env_key:
                clean_keys.append(env_key)

        defaults["api_keys"] = clean_keys

        # Validate model_id
        valid_models = {m["id"] for m in SUPPORTED_MODELS}
        if defaults.get("model_id") not in valid_models:
            defaults["model_id"] = self.DEFAULT_MODEL

        # Validate pacing_seconds
        try:
            pacing = float(defaults.get("pacing_seconds", self.DEFAULT_PACING_SECONDS))
            defaults["pacing_seconds"] = max(1.0, pacing)
        except (TypeError, ValueError):
            defaults["pacing_seconds"] = self.DEFAULT_PACING_SECONDS

        # Validate language
        defaults["language"] = normalize_lang(str(defaults.get("language", self.DEFAULT_LANGUAGE)))

        # Ensure style_index 0 uses clean empty style_prompt
        try:
            style_idx = int(defaults.get("style_index", 0))
        except (TypeError, ValueError):
            style_idx = 0
        style_idx = max(0, min(len(STYLE_PRESETS) - 1, style_idx))
        defaults["style_index"] = style_idx
        if style_idx == 0:
            defaults["style_prompt"] = ""
            defaults["style_label"] = STYLE_PRESETS[0]["label"]

        # Validate primary & secondary voice defaults
        if not str(defaults.get("voice_name", "")).strip():
            defaults["voice_name"] = self.DEFAULT_PRIMARY_VOICE
        if not str(defaults.get("speaker2_voice", "")).strip():
            defaults["speaker2_voice"] = self.DEFAULT_SECONDARY_VOICE

        if not isinstance(defaults.get("bookmarks"), dict):
            defaults["bookmarks"] = {}
        if not isinstance(defaults.get("custom_voices"), list):
            defaults["custom_voices"] = []

        self.settings = defaults

        # Auto-encrypt legacy plain keys on disk
        raw_keys = self.settings.get("api_keys", [])
        needs_encryption = False
        encrypted_keys = []
        for k in raw_keys:
            if isinstance(k, str) and k.strip():
                if not k.strip().startswith("enc:"):
                    needs_encryption = True
                    encrypted_keys.append(encrypt_key_for_storage(k.strip()))
                else:
                    encrypted_keys.append(k.strip())
        if needs_encryption:
            self.settings["api_keys"] = encrypted_keys
            self.save()

        return self.settings

    def save(self) -> None:
        """
        Persists the current settings dictionary atomically to settings.json.
        """
        self.atomic_write_json(self.settings_path, self.settings)

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        self.settings[key] = value
        if auto_save:
            self.save()

    def get_api_keys(self) -> List[str]:
        keys = self.settings.get("api_keys", [])
        decrypted = [decrypt_key_from_storage(k) for k in keys if isinstance(k, str) and k.strip()]
        decrypted = [k for k in decrypted if k]
        if not decrypted:
            env_key = os.getenv("GEMINI_API_KEY", "").strip()
            if env_key:
                return [env_key]
        return decrypted

    def set_api_keys(self, keys: List[str], auto_save: bool = True) -> List[str]:
        cleaned_plain: List[str] = []
        encrypted: List[str] = []
        for k in keys:
            stripped = str(k).strip()
            if stripped:
                plain = decrypt_key_from_storage(stripped) if stripped.startswith("enc:") else stripped
                if plain and plain not in cleaned_plain:
                    cleaned_plain.append(plain)
                    encrypted.append(encrypt_key_for_storage(plain))
        self.settings["api_keys"] = encrypted
        self.settings["active_key_index"] = 0
        if auto_save:
            self.save()
        return cleaned_plain

    def save_bookmark(
        self,
        book_id: str,
        chapter_file: str,
        chapter_index: int,
        position_ms: int,
        speed: str = "1.0x",
    ) -> None:
        bookmarks = self.settings.setdefault("bookmarks", {})
        bookmarks[book_id] = {
            "chapter_file": chapter_file,
            "chapter_index": int(chapter_index),
            "position_ms": max(0, int(position_ms)),
            "speed": speed,
            "timestamp": int(time.time()),
        }
        self.save()

    def get_bookmark(self, book_id: str) -> Optional[Dict[str, Any]]:
        bookmarks = self.settings.get("bookmarks", {})
        if isinstance(bookmarks, dict):
            return bookmarks.get(book_id)
        return None

    @staticmethod
    def get_model_metadata(model_id: str) -> Dict[str, Any]:
        for item in SUPPORTED_MODELS:
            if item["id"] == model_id:
                return dict(item)
        is_38 = "3.8" in (model_id or "")
        return {
            "id": model_id or SettingsManager.DEFAULT_MODEL,
            "label": model_id or SettingsManager.DEFAULT_MODEL,
            "daily_cap": 100 if is_38 else 10,
            "chunk_target": 8000 if is_38 else 2000,
            "is_legacy": not is_38,
        }
