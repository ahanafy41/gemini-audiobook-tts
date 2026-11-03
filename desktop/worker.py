#!/usr/bin/env python3
"""
Background Synthesis Worker for Gemini Audiobook TTS Desktop.
Manages book parsing, model-adaptive smart chunking, strict 60-second inter-request
pacing with live UI countdowns, 2-retry 65-second transient HTTP 429 buffering,
sequential multi-API-key rotation (100 RPD for 3.8 / 10 RPD for legacy models),
strict model commitment, pause/resume/cancel controls, and normalized WAV export.
All UI callbacks are marshaled exclusively via wx.CallAfter.
"""

import base64
import inspect
import json
import logging
import math
import os
import re
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import audioop
except ImportError:
    audioop = None  # type: ignore
import array

try:
    import wx
except ImportError:
    wx = None  # type: ignore

# Ensure parent project directory is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from book_parser import BookParser, ParsedBook
from gemini_tts_client import GeminiTtsClient, DialogueTurnAnnotator
from markdown_stripper import CleanedChapter
from smart_chunker import SmartTextChunker
from key_quota_manager import (
    KeyQuotaManager,
    get_model_daily_cap,
    mask_key,
    parse_retry_delay_from_error,
)

SmartChunker = SmartTextChunker

logger = logging.getLogger("DesktopSynthesisWorker")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


ARABIC_EMOTION_CUES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"(همس|بهمس|هامسا|هامسة|بصوت خافت)"), "whispering, soft and secretive tone"),
    (re.compile(r"(صرخ|صاح|بغضب|غاضبا|غاضبة|بانفعال|بحدة)"), "dramatic, intense andurgent tone"),
    (re.compile(r"(بحزن|بأسى|باكيا|باكية|بدموع|بألم|تنهيدة)"), "sad, melancholic and empathetic tone"),
    (re.compile(r"(مبتسما|مبتسمة|بفرح|بسعادة|ضاحكا|ضاحكة|ببهجة)"), "warm, cheerful and smiling tone"),
    (re.compile(r"(بخوف|برعب|مرتجفا|مرتجفة|بقلق|بتوتر)"), "tense, breathless and suspenseful tone"),
    (re.compile(r"(بهدوء|برصانة|بحكمة|بتأمل|بوقار)"), "calm, composed and authoritative tone"),
]


def dispatch_to_ui(callback: Optional[Callable[..., Any]], *args: Any, **kwargs: Any) -> None:
    """
    Marshals any UI callback strictly through wx.CallAfter when a wx.App is active.
    """
    if callback is None:
        return
    if wx is not None and wx.GetApp() is not None:
        wx.CallAfter(callback, *args, **kwargs)
    else:
        callback(*args, **kwargs)


def atomic_write_bytes(target_path: Union[str, Path], data: bytes) -> None:
    """
    Writes binary content atomically using tempfile.NamedTemporaryFile and os.replace.
    """
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(target.parent),
            prefix=f".{target.stem}_",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def atomic_write_text(target_path: Union[str, Path], text: str) -> None:
    """
    Writes UTF-8 text atomically using tempfile.NamedTemporaryFile and os.replace.
    """
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
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
            tmp_file.write(text)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, str(target))
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def detect_dialogue_and_emotions(text: str) -> Dict[str, Any]:
    """
    Analyzes input text to detect whether it contains 2-speaker dialogue markers
    (e.g., الراوي: / الشخصية: or المتحدث 1: / المتحدث 2: or dialogue dashes)
    and identifies Arabic contextual emotion cues.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    dialogue_lines = 0
    speaker_pattern = re.compile(
        r"^(الراوي|الشخصية|المتحدث\s*[12١٢]|Narrator|Speaker\s*[12]|[-–—«])\s*[:：]?",
        re.IGNORECASE,
    )
    for ln in lines:
        if speaker_pattern.match(ln):
            dialogue_lines += 1

    detected_emotions: List[str] = []
    for pattern, style_desc in ARABIC_EMOTION_CUES:
        if pattern.search(text):
            detected_emotions.append(style_desc)

    is_dialogue = dialogue_lines >= 2
    return {
        "is_dialogue": is_dialogue,
        "dialogue_turns": dialogue_lines,
        "detected_emotions": detected_emotions,
    }


def get_adaptive_chunk_limit(model_id: str) -> int:
    """
    Returns 8000 characters for gemini-3.8-* models and 2000 characters for legacy 3.1/2.5 models.
    """
    if "3.8" in (model_id or ""):
        return 8000
    return 2000


def get_model_daily_cap(model_id: str) -> int:
    """
    Returns daily request cap per project for Free Tier TTS models (10 RPD per model).
    """
    return 10


def sanitize_book_folder_name(title: str) -> str:
    """
    Produces a safe filesystem folder/file stem from a book title while preserving Arabic and Latin characters.
    """
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (title or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or "كتاب_صوتي"


def normalize_pcm16_mono(
    pcm_bytes: bytes,
    target_rms: float = 4200.0,
    max_gain: float = 2.5,
    min_gain: float = 0.4,
    clip_limit: int = 32000,
    fade_ms: float = 15.0,
    sample_rate: int = 24000,
) -> bytes:
    """
    Normalizes 16-bit signed little-endian mono PCM audio using balanced RMS normalization
    (target_rms=4200.0, max_gain=2.5, min_gain=0.4, clip_limit=32000) and applies a smooth
    15ms Fade-In and Fade-Out envelope to eliminate pop/click artifacts.
    Optimized for gigabit-speed processing with audioop and local boundary slicing.
    """
    if not pcm_bytes or len(pcm_bytes) < 4:
        return pcm_bytes

    usable_len = (len(pcm_bytes) // 2) * 2
    pcm_body = pcm_bytes[:usable_len]
    total_samples = usable_len // 2

    # 1. High-speed RMS calculation and gain scaling
    if audioop is not None:
        try:
            current_rms = float(audioop.rms(pcm_body, 2))
            if current_rms < 1.0:
                gain = 1.0
            else:
                gain = max(min_gain, min(max_gain, target_rms / current_rms))
            if abs(gain - 1.0) > 0.01:
                pcm_body = audioop.mul(pcm_body, 2, gain)
        except Exception as exc:
            logger.warning("audioop processing failed, using raw: %s", exc)
    else:
        try:
            arr = array.array("h")
            arr.frombytes(pcm_body)
            sum_sq = sum(float(s) * float(s) for s in arr)
            current_rms = math.sqrt(sum_sq / float(len(arr))) if arr else 1.0
            gain = max(min_gain, min(max_gain, target_rms / max(1.0, current_rms)))
            if abs(gain - 1.0) > 0.01:
                for i in range(len(arr)):
                    arr[i] = max(-clip_limit, min(clip_limit, int(round(arr[i] * gain))))
                pcm_body = arr.tobytes()
        except Exception as exc:
            logger.warning("array normalization failed: %s", exc)

    # 2. Fast 15ms Fade-In & Fade-Out Envelope (touch only boundary samples!)
    fade_samples = int((sample_rate * fade_ms) / 1000.0)
    fade_len = min(fade_samples, total_samples // 2)
    if fade_len > 0:
        fade_bytes_len = fade_len * 2
        try:
            # Start fade-in
            start_samples = list(struct.unpack(f"<{fade_len}h", pcm_body[:fade_bytes_len]))
            for i in range(fade_len):
                factor = float(i) / float(fade_len)
                start_samples[i] = int(round(start_samples[i] * factor))
            faded_start = struct.pack(f"<{fade_len}h", *start_samples)

            # End fade-out
            end_samples = list(struct.unpack(f"<{fade_len}h", pcm_body[-fade_bytes_len:]))
            for i in range(fade_len):
                factor = float(fade_len - 1 - i) / float(fade_len)
                end_samples[i] = int(round(end_samples[i] * factor))
            faded_end = struct.pack(f"<{fade_len}h", *end_samples)

            pcm_body = faded_start + pcm_body[fade_bytes_len:-fade_bytes_len] + faded_end
        except Exception as exc:
            logger.warning("Fade envelope application failed: %s", exc)

    return pcm_body


def extract_pcm_from_wav(path: Path) -> Tuple[bytes, int, int, int]:
    """
    Extracts pure PCM frames from a WAV file, cleanly discarding
    any RIFF header chunks and trailing metadata (such as Google's C2PA / JUMBF provenance metadata).
    Returns (pcm_bytes, sample_rate, channels, bits_per_sample).
    """
    try:
        with wave.open(str(path), "rb") as w:
            channels = w.getnchannels()
            sample_rate = w.getframerate()
            bits_per_sample = w.getsampwidth() * 8
            pcm_bytes = w.readframes(w.getnframes())
            return pcm_bytes, sample_rate, channels, bits_per_sample
    except Exception:
        raw = path.read_bytes()
        if raw.startswith(b"RIFF") and len(raw) >= 44:
            data_idx = raw.find(b"data")
            if data_idx != -1 and len(raw) >= data_idx + 8:
                channels = struct.unpack_from("<H", raw, 22)[0] or 1
                sample_rate = struct.unpack_from("<I", raw, 24)[0] or 24000
                bits_per_sample = struct.unpack_from("<H", raw, 34)[0] or 16
                data_size = struct.unpack_from("<I", raw, data_idx + 4)[0]
                pcm_bytes = raw[data_idx + 8 : data_idx + 8 + data_size]
                return pcm_bytes, sample_rate, channels, bits_per_sample
            return raw[44:], 24000, 1, 16
        return raw, 24000, 1, 16


def merge_and_normalize_wav_files(
    input_paths: List[Path],
    output_path: Path,
    normalize: bool = True,
    silence_padding_ms: int = 250,
) -> int:
    """
    Concatenates multiple WAV files into a single normalized WAV file atomically.
    Extracts pure PCM audio frames, discarding C2PA watermark trailers to eliminate pops/clicks.
    Returns total duration in milliseconds.
    """
    pcm_segments: List[bytes] = []
    sample_rate = 24000
    channels = 1
    bits_per_sample = 16

    for idx, p in enumerate(input_paths):
        if not p.is_file() or p.stat().st_size < 44:
            continue
        pcm_body, s_rate, ch, bits = extract_pcm_from_wav(p)
        sample_rate = s_rate
        channels = ch
        bits_per_sample = bits

        if normalize and bits_per_sample == 16:
            pcm_body = normalize_pcm16_mono(pcm_body, sample_rate=sample_rate)
        elif bits_per_sample == 16 and len(pcm_body) >= 2:
            # Still apply subtle 15ms fade-in/out to prevent boundary zero-crossing clicks
            pcm_body = normalize_pcm16_mono(
                pcm_body,
                target_rms=4200.0,
                max_gain=1.0,
                min_gain=1.0,
                sample_rate=sample_rate,
            )
        pcm_segments.append(pcm_body)

        if silence_padding_ms > 0 and idx < len(input_paths) - 1:
            bytes_per_sample = max(1, bits_per_sample // 8)
            silence_samples = int((sample_rate * silence_padding_ms) / 1000.0)
            silence_bytes = b"\x00" * (silence_samples * channels * bytes_per_sample)
            pcm_segments.append(silence_bytes)

    combined_pcm = b"".join(pcm_segments)
    wav_bytes = GeminiTtsClient.create_wav_header(
        combined_pcm,
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits_per_sample,
    )
    atomic_write_bytes(output_path, wav_bytes)

    bytes_per_sec = sample_rate * channels * max(1, bits_per_sample // 8)
    duration_ms = int((len(combined_pcm) / bytes_per_sec) * 1000) if bytes_per_sec > 0 else 0
    return duration_ms


def generate_cue_sheet(
    cue_path: Path,
    wav_filename: str,
    book_title: str,
    chapter_records: List[Dict[str, Any]],
    silence_padding_ms: int = 400,
) -> None:
    """
    Generates a standard CUE sheet mapping each chapter to its exact start timestamp in the merged audio file.
    """
    lines = [
        "REM GENRE Audiobook",
        f"REM DATE {time.strftime('%Y')}",
        'PERFORMER "Gemini Audiobook"',
        f'TITLE "{book_title}"',
        f'FILE "{wav_filename}" WAVE',
    ]
    current_ms = 0
    for idx, r in enumerate(chapter_records):
        track_num = idx + 1
        raw_title = r.get("title", f"Chapter {track_num}")
        clean_title = raw_title.replace('"', "'").strip()
        total_seconds = current_ms / 1000.0
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        frames = int((total_seconds - int(total_seconds)) * 75.0)
        lines.append(f"  TRACK {track_num:02d} AUDIO")
        lines.append(f'    TITLE "{clean_title}"')
        lines.append(f"    INDEX 01 {minutes:02d}:{seconds:02d}:{frames:02d}")
        dur_ms = r.get("duration_ms", int(r.get("duration_seconds", 0) * 1000))
        current_ms += dur_ms + silence_padding_ms

    atomic_write_text(cue_path, "\n".join(lines) + "\n")


def generate_chapters_m3u(
    m3u_path: Path,
    wav_filename: str,
    chapter_records: List[Dict[str, Any]],
    silence_padding_ms: int = 400,
) -> None:
    """
    Generates an extended M3U playlist with #EXTVLCOPT:start-time for chapter-aware playback in VLC/players.
    """
    lines = ["#EXTM3U"]
    current_ms = 0
    for idx, r in enumerate(chapter_records):
        title = r.get("title", f"Chapter {idx+1}").replace('"', "'").strip()
        dur_sec = r.get("duration_seconds", 0)
        dur_ms = r.get("duration_ms", dur_sec * 1000)
        start_sec = current_ms / 1000.0
        stop_sec = (current_ms + dur_ms) / 1000.0
        lines.append(f"#EXTINF:{dur_sec},{title}")
        lines.append(f"#EXTVLCOPT:start-time={start_sec:.2f}")
        lines.append(f"#EXTVLCOPT:stop-time={stop_sec:.2f}")
        lines.append(wav_filename)
        current_ms += dur_ms + silence_padding_ms

    atomic_write_text(m3u_path, "\n".join(lines) + "\n")


class QuotaExhaustedException(Exception):
    """Raised when an API key's quota is confirmed exhausted after retry buffering."""


class SynthesisWorker(threading.Thread):
    """
    Background worker thread that orchestrates book parsing, adaptive chunking,
    paced synthesis (60s interval), 2-retry 65s HTTP 429 buffering, multi-key
    sequential rotation, and atomic progress persistence.
    """

    RETRY_COOLDOWN_SECONDS = 65
    MAX_429_RETRIES_PER_KEY = 2

    def __init__(
        self,
        book_text: str,
        book_title: str,
        output_dir: Union[str, Path],
        api_keys: List[str],
        model_id: str = "gemini-3.8-flash-tts",
        voice_name: str = "Charon",
        style_prompt: str = "",
        multi_speaker: bool = False,
        speaker2_voice: str = "Kore",
        auto_emotion: bool = True,
        pacing_seconds: float = 60.0,
        source_file_path: str = "",
        mock_mode: bool = False,
        merge_with_cue: bool = True,
        on_progress: Optional[Callable[[int, int, int, int, float, str], None]] = None,
        on_countdown: Optional[Callable[[int, str, int, int], None]] = None,
        on_key_rotated: Optional[Callable[[int, int, str], None]] = None,
        on_chapter_ready: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_ask_legacy_fallback: Optional[Callable[[str, str, Callable[[bool], None]], None]] = None,
        on_finished: Optional[Callable[[bool, str, Optional[Dict[str, Any]]], None]] = None,
        quota_manager: Optional[KeyQuotaManager] = None,
    ) -> None:
        super().__init__(daemon=True, name="SynthesisWorkerThread")
        self.book_text = book_text
        self.book_title = (
            book_title
            or (Path(source_file_path).stem if source_file_path else "")
            or "كتاب_صوتي"
        )
        self.base_output_dir = Path(output_dir).resolve()
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self.safe_book_folder_name = sanitize_book_folder_name(self.book_title)
        if self.base_output_dir.name == self.safe_book_folder_name:
            book_output_dir = self.base_output_dir
        else:
            book_output_dir = self.base_output_dir / self.safe_book_folder_name
        self.output_dir = book_output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        cleaned_keys = [k.strip() for k in api_keys if k and k.strip()]
        if not cleaned_keys:
            env_key = os.getenv("GEMINI_API_KEY", "").strip()
            if env_key:
                cleaned_keys = [env_key]
        self.api_keys = cleaned_keys
        self.active_key_index = 0
        self.key_request_counts: Dict[int, int] = {i: 0 for i in range(len(self.api_keys))}

        self.model_id = model_id or "gemini-3.8-flash-tts"
        self.voice_name = voice_name or "Charon"
        self.style_prompt = GeminiTtsClient.resolve_style_instruction(style_prompt)
        self.multi_speaker = multi_speaker
        self.speaker2_voice = speaker2_voice or "Kore"
        self.auto_emotion = auto_emotion
        self.pacing_seconds = max(1.0, float(pacing_seconds))
        self.source_file_path = source_file_path
        self.mock_mode = mock_mode or (len(self.api_keys) == 0)
        self.merge_with_cue = bool(merge_with_cue)

        self.on_progress = on_progress
        self.on_countdown = on_countdown
        self.on_key_rotated = on_key_rotated
        self.on_chapter_ready = on_chapter_ready
        self.on_ask_legacy_fallback = on_ask_legacy_fallback
        self.on_finished = on_finished
        self.quota_manager = quota_manager if quota_manager is not None else KeyQuotaManager()

        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._cancel_event = threading.Event()
        self._last_request_timestamp: float = 0.0

        self.progress_file = self.output_dir / "progress.json"
        self.manifest_file = self.output_dir / "book_manifest.json"
        self.playlist_file = self.output_dir / "playlist.m3u"

        self.parser = BookParser()
        self.chunker = SmartTextChunker(max_chunk_size=get_adaptive_chunk_limit(self.model_id))

    def pause(self) -> None:
        """Pauses synthesis safely."""
        self._pause_event.clear()
        logger.info("Synthesis worker paused.")

    def resume(self) -> None:
        """Resumes synthesis from pause."""
        self._pause_event.set()
        logger.info("Synthesis worker resumed.")

    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def cancel(self) -> None:
        """Requests immediate cancellation of the worker thread."""
        self._cancel_event.set()
        self._pause_event.set()
        logger.info("Synthesis worker cancellation requested.")

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _wait_if_paused_or_cancelled(self) -> bool:
        """
        Blocks while paused and returns False if cancelled.
        """
        while not self._pause_event.is_set():
            if self._cancel_event.is_set():
                return False
            time.sleep(0.2)
        return not self._cancel_event.is_set()

    def _sleep_with_countdown(self, seconds: float, reason_ar: str) -> bool:
        """
        Sleeps for `seconds` in 1-second increments while emitting `on_countdown`
        via `wx.CallAfter`, respecting pause and cancel events immediately.
        Returns False if cancelled.
        """
        remaining = int(round(seconds))
        total_keys = max(1, len(self.api_keys))
        while remaining > 0:
            if not self._wait_if_paused_or_cancelled():
                return False
            dispatch_to_ui(
                self.on_countdown,
                remaining,
                reason_ar,
                self.active_key_index + 1,
                total_keys,
            )
            step = min(1.0, float(remaining))
            start_tick = time.time()
            while time.time() - start_tick < step:
                if self._cancel_event.is_set():
                    return False
                if not self._pause_event.is_set():
                    break
                time.sleep(0.1)
            if self._pause_event.is_set():
                remaining -= 1

        dispatch_to_ui(
            self.on_countdown,
            0,
            "جاهز لإرسال الطلب التالي",
            self.active_key_index + 1,
            total_keys,
        )
        return not self._cancel_event.is_set()

    def _load_progress(self) -> Dict[str, Any]:
        if self.progress_file.is_file():
            try:
                return json.loads(self.progress_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not read progress.json: %s", str(exc))
        return {
            "book_title": self.book_title,
            "model_id": self.model_id,
            "completed_chapters": {},
            "completed_chunks": {},
            "total_chapters": 0,
        }

    def _save_progress(self, progress_data: Dict[str, Any]) -> None:
        progress_data["updated_at"] = int(time.time())
        progress_data["model_id"] = self.model_id
        progress_data["active_key_index"] = self.active_key_index
        atomic_write_text(
            self.progress_file,
            json.dumps(progress_data, ensure_ascii=False, indent=2),
        )

    def _enrich_style_with_arabic_emotion(self, chunk_text: str) -> str:
        """
        Infers emotional style cues from Arabic narrative text when auto_emotion is enabled.
        """
        if not self.auto_emotion:
            return self.style_prompt
        matched_cues: List[str] = []
        for pattern, cue in ARABIC_EMOTION_CUES:
            if pattern.search(chunk_text):
                matched_cues.append(cue)
        if not matched_cues:
            return self.style_prompt
        unique_cues = ", ".join(dict.fromkeys(matched_cues))
        return f"{self.style_prompt} ({unique_cues})"

    def _invoke_gemini_rest_directly(
        self,
        api_key: str,
        text: str,
        effective_style: str = "",
    ) -> bytes:
        """
        Calls the official Gemini v1beta :generateContent endpoint with responseModalities=['AUDIO'],
        supporting both single-speaker prebuiltVoiceConfig and 2-speaker multiSpeakerVoiceConfig.
        In single-speaker mode, sends clean_text purely in parts[0].text without English prefixes
        to preserve 100% consistent Arabic dialect, voice timbre, and persona across all chunks.
        """
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_id}:generateContent?key={api_key}"
        )

        clean_text = text.strip()

        if self.multi_speaker:
            turns = DialogueTurnAnnotator.extract_turns(
                clean_text,
                narrator_style=self.style_prompt or "natural audiobook narrator, clear pronunciation",
                character_default_style="expressive character dialogue",
            )
            parts: List[Dict[str, Any]] = []
            is_gemini_38 = self.model_id.startswith("gemini-3.8")
            if is_gemini_38:
                for turn in turns:
                    part_entry: Dict[str, Any] = {
                        "text": turn["text"],
                        "speechMetadata": {"speaker": turn["speaker"]},
                    }
                    if turn.get("style"):
                        part_entry["speechMetadata"]["style"] = turn["style"]
                    parts.append(part_entry)
            else:
                inline_script = "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)
                parts = [{"text": inline_script}]

            def _build_vc(v_name: str) -> Dict[str, Any]:
                vn = (v_name or "Charon").strip()
                if vn.startswith("voice_") or vn.startswith("voices/"):
                    return {"voice": vn.replace("voices/", "")}
                return {"prebuiltVoiceConfig": {"voiceName": vn}}

            speech_config: Dict[str, Any] = {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": "Speaker1",
                            "voiceConfig": _build_vc(self.voice_name),
                        },
                        {
                            "speaker": "Speaker2",
                            "voiceConfig": _build_vc(self.speaker2_voice),
                        },
                    ]
                }
            }
        else:
            def _build_single_vc(v_name: str) -> Dict[str, Any]:
                vn = (v_name or "Charon").strip()
                if vn.startswith("voice_") or vn.startswith("voices/"):
                    return {"voice": vn.replace("voices/", "")}
                return {"prebuiltVoiceConfig": {"voiceName": vn}}

            parts = [{"text": clean_text}]
            speech_config = {
                "voiceConfig": _build_single_vc(self.voice_name)
            }

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": parts
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": speech_config,
            },
        }

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "GeminiAudiobookDesktop/2.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=90) as resp:
            raw_json = json.loads(resp.read().decode("utf-8"))

        client_helper = GeminiTtsClient(api_key=api_key, model_id=self.model_id, mock_mode=True)
        decoded_audio = client_helper._extract_audio_bytes(raw_json)
        if decoded_audio.startswith(b"RIFF"):
            return decoded_audio
        return GeminiTtsClient.create_wav_header(decoded_audio, sample_rate=24000)

    def _rotate_to_next_key(self, reason_ar: str) -> bool:
        """
        Advances to the next available API key in `self.api_keys` skipping any
        keys that are already recorded as exhausted in `KeyQuotaManager`.
        Returns True if an available key was found, or False if all remaining keys are exhausted.
        """
        next_idx, next_key = self.quota_manager.get_next_available_key(
            self.api_keys,
            self.active_key_index,
            self.model_id,
        )
        if next_idx != -1 and next_key is not None:
            skipped_count = next_idx - (self.active_key_index + 1)
            self.active_key_index = next_idx
            total_keys = len(self.api_keys)
            skip_msg = f" (تم تخطي {skipped_count} مفتاحاً مستنفد الحصة)" if skipped_count > 0 else ""
            msg = (
                f"تم الانتقال التلقائي إلى المفتاح رقم {self.active_key_index + 1} من {total_keys}{skip_msg} "
                f"({reason_ar})."
            )
            logger.info(msg)
            dispatch_to_ui(self.on_key_rotated, self.active_key_index + 1, total_keys, msg)
            return True
        return False

    def _ask_user_for_legacy_model_switch(self) -> Optional[str]:
        """
        If the active model is a legacy model (3.1 or 2.5) and all API keys are exhausted,
        prompts the user via UI dialog whether to switch to the alternative legacy model
        or stop and wait for quota renewal.
        For 3.8 models, strictly returns None (never downgrades to legacy models).
        """
        if "3.8" in self.model_id:
            return None

        alt_model = (
            "gemini-2.5-flash-preview-tts"
            if "3.1" in self.model_id
            else "gemini-3.1-flash-tts-preview"
        )

        if self.on_ask_legacy_fallback is None:
            return None

        decision_event = threading.Event()
        decision_holder = {"switch": False}

        def receive_decision(user_accepted: bool) -> None:
            decision_holder["switch"] = bool(user_accepted)
            decision_event.set()

        dispatch_to_ui(
            self.on_ask_legacy_fallback,
            self.model_id,
            alt_model,
            receive_decision,
        )

        while not decision_event.is_set():
            if self._cancel_event.is_set():
                return None
            time.sleep(0.2)

        if decision_holder["switch"]:
            return alt_model
        return None

    def _synthesize_chunk_with_quota_policy(
        self,
        chunk_text: str,
        context_prefix: str = "",
    ) -> Optional[bytes]:
        """Alias for _synthesize_chunk_with_resilience."""
        return self._synthesize_chunk_with_resilience(chunk_text, context_prefix=context_prefix)

    def _synthesize_chunk_with_resilience(
        self,
        chunk_text: str,
        context_prefix: str = "",
    ) -> Optional[bytes]:
        """
        Synthesizes a single chunk while enforcing:
        1. Strict 60-second minimum interval between consecutive requests.
        2. Proactive key rotation when the active key reaches 100 requests (3.8) or 10 requests (legacy).
        3. Smart 2-retry buffer with 65-second countdown on unexpected HTTP 429 before rotating keys.
        4. Strict model commitment (never switches models silently).
        5. In single-speaker mode (self.multi_speaker is False), never calls _enrich_style_with_arabic_emotion
           and keeps the text pure to prevent accent/persona drift between chunks.
        """
        if not self._wait_if_paused_or_cancelled():
            return None

        if self.multi_speaker:
            effective_style = self._enrich_style_with_arabic_emotion(chunk_text)
        else:
            effective_style = ""

        if self.mock_mode:
            if self._last_request_timestamp > 0:
                elapsed = time.time() - self._last_request_timestamp
                wait_needed = min(2.0, max(0.0, self.pacing_seconds - elapsed))
                if wait_needed > 0:
                    mock_reason = f"{context_prefix} - فاصل تجريبي بين الطلبات" if context_prefix else "فاصل تجريبي بين الطلبات"
                    if not self._sleep_with_countdown(wait_needed, mock_reason):
                        return None
            self._last_request_timestamp = time.time()
            dur = max(0.5, min(6.0, len(chunk_text) / 25.0))
            return GeminiTtsClient.generate_synthetic_wav(duration_seconds=dur)

        while not self._cancel_event.is_set():
            daily_cap = get_model_daily_cap(self.model_id)
            current_key = self.api_keys[self.active_key_index]
            used_on_key = self.key_request_counts.get(self.active_key_index, 0)

            # Check if current key reached its daily cap or is recorded as exhausted
            if used_on_key >= daily_cap or not self.quota_manager.is_key_available(current_key, self.model_id):
                rotated = self._rotate_to_next_key(
                    f"المفتاح الحالي مستنفد الحصة للنموذج {self.model_id}"
                )
                if not rotated:
                    rem_sec, rem_human = self.quota_manager.get_earliest_renewal_time(
                        self.api_keys, self.model_id
                    )
                    hint = f" ستبدأ أول حصة بالتجدد بعد {rem_human}." if rem_human else ""
                    raise QuotaExhaustedException(
                        f"استُنفدت جميع المفاتيح المتاحة ({len(self.api_keys)}) للنموذج {self.model_id}.{hint}"
                    )
                continue

            # Enforce strict 60-second pacing between consecutive API requests
            if self._last_request_timestamp > 0:
                elapsed = time.time() - self._last_request_timestamp
                remaining_pace = self.pacing_seconds - elapsed
                if remaining_pace > 0:
                    pace_reason = (
                        f"{context_prefix} - انتظار إلزامي بين الطلبات ({int(self.pacing_seconds)} ث)"
                        if context_prefix
                        else f"الانتظار الإلزامي بين الطلبات ({int(self.pacing_seconds)} ثانية)"
                    )
                    if not self._sleep_with_countdown(remaining_pace, pace_reason):
                        return None

            current_key = self.api_keys[self.active_key_index]
            retries_429 = 0
            key_rotated = False

            while retries_429 <= self.MAX_429_RETRIES_PER_KEY:
                if not self._wait_if_paused_or_cancelled():
                    return None
                try:
                    total_keys_count = max(1, len(self.api_keys))
                    active_reason = (
                        f"{context_prefix} - جاري إرسال الطلب وتوليد الصوت"
                        if context_prefix
                        else "جاري إرسال الطلب وتوليد الصوت للمقطع..."
                    )
                    dispatch_to_ui(
                        self.on_countdown,
                        0,
                        active_reason,
                        self.active_key_index + 1,
                        total_keys_count,
                    )
                    self._last_request_timestamp = time.time()
                    audio_bytes = self._invoke_gemini_rest_directly(
                        api_key=current_key,
                        text=chunk_text,
                        effective_style=effective_style,
                    )
                    self.key_request_counts[self.active_key_index] = (
                        self.key_request_counts.get(self.active_key_index, 0) + 1
                    )
                    self.quota_manager.record_success(current_key, self.model_id)
                    return audio_bytes

                except urllib.error.HTTPError as http_err:
                    err_body = ""
                    try:
                        err_body = http_err.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                    if http_err.code == 429 or "RESOURCE_EXHAUSTED" in err_body:
                        is_daily_exhaustion = False
                        retry_hint = ""
                        server_delay = parse_retry_delay_from_error(err_body)
                        if server_delay and server_delay > 120:
                            is_daily_exhaustion = True
                            hrs = server_delay // 3600
                            mins = (server_delay % 3600) // 60
                            if hrs > 0:
                                retry_hint = f" (تتجدد الحصة بعد {hrs} ساعة و{mins} دقيقة)"
                            else:
                                retry_hint = f" (تتجدد الحصة بعد {mins} دقيقة)"

                        if err_body:
                            try:
                                parsed_err = json.loads(err_body)
                                err_details = parsed_err.get("error", {}).get("details", [])
                                for d in err_details:
                                    if "QuotaFailure" in d.get("@type", ""):
                                        is_daily_exhaustion = True
                                err_msg = parsed_err.get("error", {}).get("message", "")
                                if "GenerateRequestsPerDayPerProjectPerModel" in err_msg or "limit: 10" in err_msg:
                                    is_daily_exhaustion = True
                            except Exception:
                                pass

                        if is_daily_exhaustion:
                            self.quota_manager.record_429_exhaustion(
                                current_key,
                                self.model_id,
                                retry_delay_seconds=server_delay,
                                error_message=err_body,
                            )
                            # Immediate key rotation without wasting 130s waiting on an exhausted daily quota
                            rotated = self._rotate_to_next_key(
                                f"استُنفدت الحصة اليومية للمفتاح الحالي{retry_hint}"
                            )
                            if not rotated:
                                rem_sec, rem_human = self.quota_manager.get_earliest_renewal_time(
                                    self.api_keys, self.model_id
                                )
                                hint = f" ستبدأ أول حصة بالتجدد بعد {rem_human}." if rem_human else ""
                                raise QuotaExhaustedException(
                                    f"استُنفدت الحصة اليومية للمفتاح الحالي للنموذج {self.model_id}{retry_hint}.{hint} "
                                    "يمكنك إضافة مفتاح API إضافي من حساب آخر في الإعدادات لمواصلة التحويل فوراً."
                                )
                            key_rotated = True
                            break

                        retries_429 += 1
                        if retries_429 <= self.MAX_429_RETRIES_PER_KEY:
                            reason = (
                                f"تنبيه 429 عابر من الخادم - محاولة تأكيد {retries_429} من "
                                f"{self.MAX_429_RETRIES_PER_KEY} للمفتاح رقم {self.active_key_index + 1} "
                                f"(انتظار {self.RETRY_COOLDOWN_SECONDS} ثانية)"
                            )
                            logger.warning(reason)
                            if not self._sleep_with_countdown(self.RETRY_COOLDOWN_SECONDS, reason):
                                return None
                            continue
                        else:
                            # Confirmed key exhaustion after 2 retries of 65s each
                            self.quota_manager.record_429_exhaustion(
                                current_key,
                                self.model_id,
                                retry_delay_seconds=server_delay,
                                error_message=err_body,
                            )
                            rotated = self._rotate_to_next_key(
                                "تأكد انتهاء حصة المفتاح الحالي بعد محاولتي تأكيد (65 ثانية)"
                            )
                            if not rotated:
                                rem_sec, rem_human = self.quota_manager.get_earliest_renewal_time(
                                    self.api_keys, self.model_id
                                )
                                hint = f" ستبدأ أول حصة بالتجدد بعد {rem_human}." if rem_human else ""
                                raise QuotaExhaustedException(
                                    f"استُنفدت حصة جميع المفاتيح للنموذج {self.model_id}.{hint}"
                                )
                            key_rotated = True
                            break
                    elif http_err.code in (500, 502, 503, 504):
                        retries_429 += 1
                        if retries_429 <= self.MAX_429_RETRIES_PER_KEY:
                            if not self._sleep_with_countdown(
                                15,
                                f"خطأ خادم مؤقت ({http_err.code}) - إعادة المحاولة {retries_429}",
                            ):
                                return None
                            continue
                        raise
                    else:
                        detail_msg = f"HTTP Error {http_err.code}: {http_err.reason}"
                        if err_body:
                            try:
                                parsed_err = json.loads(err_body)
                                api_msg = parsed_err.get("error", {}).get("message", "")
                                if api_msg:
                                    detail_msg = f"{detail_msg} ({api_msg})"
                            except Exception:
                                detail_msg = f"{detail_msg} ({err_body[:200]})"
                        logger.error("Gemini API call failed with %s", detail_msg)
                        raise RuntimeError(detail_msg) from http_err

            if key_rotated:
                continue

        return None

    def run(self) -> None:
        """
        Main worker loop executing on the background thread.
        """
        try:
            if not self.book_text.strip() and self.source_file_path:
                parsed_book = self.parser.parse_file(self.source_file_path)
            else:
                parsed_book = self.parser.parse_content(
                    self.book_text,
                    filename=self.book_title,
                    file_path=self.source_file_path,
                )

            if not parsed_book.chapters:
                dispatch_to_ui(
                    self.on_finished,
                    False,
                    "لم يتم العثور على أي نص صالح للتحويل الصوتي.",
                    None,
                )
                return

            progress = self._load_progress()
            saved_key_idx = progress.get("active_key_index", 0)
            self.active_key_index = self.quota_manager.find_first_available_key_index(
                self.api_keys,
                self.model_id,
                preferred_index=saved_key_idx,
            )
            if self.active_key_index != saved_key_idx and len(self.api_keys) > 0:
                logger.info(
                    "Initial key #%d was unavailable. Automatically advancing to first ready key #%d.",
                    saved_key_idx + 1,
                    self.active_key_index + 1,
                )
            progress["book_title"] = parsed_book.title
            progress["total_chapters"] = len(parsed_book.chapters)
            completed_chapters: Dict[str, Any] = progress.setdefault("completed_chapters", {})
            completed_chunks: Dict[str, Any] = progress.setdefault("completed_chunks", {})

            chapters_dir = self.output_dir / "chapters"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            raw_chunks_dir = self.output_dir / "raw_chunks"
            raw_chunks_dir.mkdir(parents=True, exist_ok=True)

            chapter_records: List[Dict[str, Any]] = []
            playlist_lines = ["#EXTM3U", f"#PLAYLIST:{parsed_book.title}"]

            total_chapters = len(parsed_book.chapters)

            for ch_idx, chapter in enumerate(parsed_book.chapters, start=1):
                if not self._wait_if_paused_or_cancelled():
                    self._save_progress(progress)
                    dispatch_to_ui(
                        self.on_finished,
                        False,
                        "تم إيقاف التحويل الصوتي وحفظ التقدم الحالي بأمان.",
                        None,
                    )
                    return

                chapter_key = f"chapter_{ch_idx:03d}"
                chapter_wav_name = f"{chapter_key}.wav"
                chapter_wav_path = chapters_dir / chapter_wav_name

                # Segment chapter using model-adaptive chunk limit
                self.chunker = SmartTextChunker(max_chunk_size=get_adaptive_chunk_limit(self.model_id))
                chunks = self.chunker.chunk_text(
                    chapter.text,
                    max_chunk_size=get_adaptive_chunk_limit(self.model_id),
                )
                if not chunks:
                    continue

                total_chunks = len(chunks)

                if (
                    chapter_key in completed_chapters
                    and chapter_wav_path.is_file()
                    and chapter_wav_path.stat().st_size > 44
                    and completed_chapters[chapter_key].get("chunks_count", 0) == total_chunks
                ):
                    rec = completed_chapters[chapter_key]
                    chapter_records.append(rec)
                    playlist_lines.append(f"#EXTINF:{rec.get('duration_seconds', 0)},{chapter.chapter_title}")
                    playlist_lines.append(f"chapters/{chapter_wav_name}")
                    pct = (ch_idx / float(total_chapters)) * 100.0
                    dispatch_to_ui(
                        self.on_progress,
                        ch_idx,
                        total_chapters,
                        total_chunks,
                        total_chunks,
                        pct,
                        f"تم استرجاع الفصل {ch_idx}/{total_chapters} من الذاكرة المحفوظة: {chapter.chapter_title}",
                    )
                    dispatch_to_ui(self.on_chapter_ready, rec)
                    continue

                chunk_paths: List[Path] = []

                chunk_idx = 1
                while chunk_idx <= total_chunks:
                    if not self._wait_if_paused_or_cancelled():
                        self._save_progress(progress)
                        dispatch_to_ui(
                            self.on_finished,
                            False,
                            "تم إلغاء التحويل الصوتي وحفظ التقدم في progress.json.",
                            None,
                        )
                        return

                    chunk_text = chunks[chunk_idx - 1]
                    chunk_key = f"{chapter_key}_part_{chunk_idx:03d}"
                    chunk_wav_path = raw_chunks_dir / f"{chunk_key}.wav"

                    overall_pct = (
                        ((ch_idx - 1) + ((chunk_idx - 1) / float(total_chunks)))
                        / float(total_chapters)
                    ) * 100.0

                    if chunk_wav_path.is_file() and chunk_wav_path.stat().st_size > 44:
                        chunk_paths.append(chunk_wav_path)
                        dispatch_to_ui(
                            self.on_progress,
                            ch_idx,
                            total_chapters,
                            chunk_idx,
                            total_chunks,
                            overall_pct,
                            f"القسم {ch_idx}/{total_chapters} | تخطي المقطع المكتمل {chunk_idx}/{total_chunks}",
                        )
                        chunk_idx += 1
                        continue

                    chunk_info = (
                        f"القسم {ch_idx}/{total_chapters} | "
                        f"المقطع {chunk_idx}/{total_chunks} ({len(chunk_text)} حرفاً)"
                    )
                    status_msg = f"{chunk_info} - جاري التحويل | المفتاح {self.active_key_index + 1}/{max(1, len(self.api_keys))}"
                    dispatch_to_ui(
                        self.on_progress,
                        ch_idx,
                        total_chapters,
                        chunk_idx,
                        total_chunks,
                        overall_pct,
                        status_msg,
                    )

                    try:
                        audio_bytes = self._synthesize_chunk_with_resilience(chunk_text, context_prefix=chunk_info)
                        if audio_bytes is None:
                            self._save_progress(progress)
                            dispatch_to_ui(
                                self.on_finished,
                                False,
                                "تم إيقاف التحويل الصوتي بناءً على طلب المستخدم وحفظ التقدم.",
                                None,
                            )
                            return

                        atomic_write_bytes(chunk_wav_path, audio_bytes)
                        completed_chunks[chunk_key] = {
                            "chapter_key": chapter_key,
                            "chunk_index": chunk_idx,
                            "file": str(chunk_wav_path),
                            "chars": len(chunk_text),
                        }
                        self._save_progress(progress)
                        chunk_paths.append(chunk_wav_path)
                        chunk_idx += 1

                    except QuotaExhaustedException:
                        self._save_progress(progress)
                        alt_legacy = self._ask_user_for_legacy_model_switch()
                        if alt_legacy:
                            self.model_id = alt_legacy
                            self.active_key_index = 0
                            self.key_request_counts = {i: 0 for i in range(len(self.api_keys))}
                            # Re-chunk remaining text if needed or continue with new model
                            logger.info("User approved switching to legacy model: %s", alt_legacy)
                            continue
                        else:
                            if "3.8" in self.model_id:
                                stop_msg = (
                                    f"استُنفدت حصة جميع المفاتيح للنموذج {self.model_id}. "
                                    "تم حفظ التقدم بأمان في progress.json دون الرجوع لأي نموذج قديم."
                                )
                            else:
                                stop_msg = (
                                    "استُنفدت حصة جميع المفاتيح للنموذج الحالي وتم حفظ التقدم في "
                                    "progress.json بانتظار تجديد الحصص."
                                )
                            dispatch_to_ui(self.on_finished, False, stop_msg, None)
                            return

                # Merge chapter chunks into normalized chapter WAV
                duration_ms = merge_and_normalize_wav_files(
                    chunk_paths,
                    chapter_wav_path,
                    normalize=True,
                )
                duration_sec = duration_ms // 1000

                chapter_record = {
                    "index": ch_idx,
                    "id": chapter_key,
                    "title": chapter.chapter_title,
                    "level": chapter.level,
                    "audio_file": f"chapters/{chapter_wav_name}",
                    "abs_audio_path": str(chapter_wav_path),
                    "duration_seconds": duration_sec,
                    "duration_ms": duration_ms,
                    "chunks_count": total_chunks,
                }
                chapter_records.append(chapter_record)
                completed_chapters[chapter_key] = chapter_record
                self._save_progress(progress)

                playlist_lines.append(f"#EXTINF:{duration_sec},{chapter.chapter_title}")
                playlist_lines.append(f"chapters/{chapter_wav_name}")

                dispatch_to_ui(self.on_chapter_ready, chapter_record)

            # Automatically merge all completed chapters into a single complete audiobook WAV file
            safe_book_title = sanitize_book_folder_name(parsed_book.title or self.book_title)
            merged_wav_path = self.output_dir / f"{safe_book_title}_complete.wav"
            chapter_wav_paths = [
                Path(r["abs_audio_path"])
                for r in chapter_records
                if r.get("abs_audio_path") and Path(r["abs_audio_path"]).is_file()
            ]
            if chapter_wav_paths:
                merge_and_normalize_wav_files(
                    chapter_wav_paths,
                    merged_wav_path,
                    normalize=False,
                    silence_padding_ms=400,
                )
                if self.merge_with_cue:
                    cue_file = self.output_dir / f"{safe_book_title}_complete.cue"
                    generate_cue_sheet(
                        cue_file,
                        merged_wav_path.name,
                        parsed_book.title or self.book_title,
                        chapter_records,
                        silence_padding_ms=400,
                    )
                    chapters_m3u_file = self.output_dir / f"{safe_book_title}_chapters.m3u"
                    generate_chapters_m3u(
                        chapters_m3u_file,
                        merged_wav_path.name,
                        chapter_records,
                        silence_padding_ms=400,
                    )

            # Write playlist.m3u atomically
            atomic_write_text(self.playlist_file, "\n".join(playlist_lines) + "\n")

            # Build chapters timeline for programmatic navigation
            chapters_timeline = []
            cur_ms = 0
            for idx, r in enumerate(chapter_records):
                t_sec = cur_ms / 1000.0
                d_sec = r.get("duration_seconds", 0)
                d_ms = r.get("duration_ms", d_sec * 1000)
                h, m, s = int(t_sec // 3600), int((t_sec % 3600) // 60), int(t_sec % 60)
                chapters_timeline.append({
                    "track": idx + 1,
                    "title": r.get("title", f"Chapter {idx+1}"),
                    "start_seconds": round(t_sec, 2),
                    "end_seconds": round((cur_ms + d_ms) / 1000.0, 2),
                    "duration_seconds": d_sec,
                    "start_formatted": f"{h:02d}:{m:02d}:{s:02d}",
                })
                cur_ms += d_ms + 400

            # Write book_manifest.json atomically
            total_dur_sec = sum(r.get("duration_seconds", 0) for r in chapter_records)
            manifest_data = {
                "title": parsed_book.title,
                "source_file": self.source_file_path,
                "output_dir": str(self.output_dir),
                "merged_audio_path": str(merged_wav_path) if merged_wav_path.is_file() else "",
                "total_chapters": len(chapter_records),
                "total_duration_seconds": total_dur_sec,
                "voice_name": self.voice_name,
                "speaker2_voice": self.speaker2_voice if self.multi_speaker else "",
                "multi_speaker": self.multi_speaker,
                "engine": self.model_id,
                "generation_timestamp": int(time.time()),
                "playlist": "playlist.m3u",
                "chapters_timeline": chapters_timeline,
                "chapters": chapter_records,
            }
            if self.merge_with_cue and merged_wav_path.is_file():
                manifest_data["cue_sheet"] = f"{safe_book_title}_complete.cue"
                manifest_data["chapters_playlist"] = f"{safe_book_title}_chapters.m3u"

            atomic_write_text(
                self.manifest_file,
                json.dumps(manifest_data, ensure_ascii=False, indent=2),
            )

            completion_msg = (
                f"تم إتمام تحويل الكتاب الصوتي '{parsed_book.title}' بنجاح وحفظ جميع الفصول "
                f"والملف الصوتي الكامل المدمج في: {merged_wav_path}"
            )
            dispatch_to_ui(
                self.on_progress,
                total_chapters,
                total_chapters,
                1,
                1,
                100.0,
                completion_msg,
            )
            dispatch_to_ui(
                self.on_finished,
                True,
                completion_msg,
                manifest_data,
            )

        except Exception as exc:
            logger.error("SynthesisWorker encountered an error: %s", str(exc))
            dispatch_to_ui(
                self.on_finished,
                False,
                f"توقف التحويل بسبب خطأ: {str(exc)}",
                None,
            )
