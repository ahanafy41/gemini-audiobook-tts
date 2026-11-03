#!/usr/bin/env python3
"""
Main Gemini Audiobook Engine.
Orchestrates book parsing, intelligent chunking, TTS synthesis, audio concatenation,
progress resumption, and playlist generation for complete spoken audiobooks.
"""

import argparse
import json
import logging
import math
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import audioop
except ImportError:
    audioop = None  # type: ignore
import array

from book_parser import BookParser, ParsedBook
from gemini_tts_client import GeminiTtsClient, PREBUILT_VOICES, STYLE_PRESETS
from markdown_stripper import CleanedChapter
from smart_chunker import SmartTextChunker, get_adaptive_chunk_limits

logger = logging.getLogger("AudiobookEngine")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class AudiobookEngine:
    """
    Core production pipeline for converting books into multi-chapter audiobooks.
    """

    def __init__(
        self,
        output_dir: Path,
        tts_client: GeminiTtsClient,
        chunk_size: int = 0,
        voice_name: str = "Kore",
        style: str = "narrator, clear pronunciation and natural pacing",
        multi_speaker: bool = False,
        speaker2_voice: str = "Charon",
        inter_chunk_silence_ms: int = 250,
        normalize_audio: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_client = tts_client
        self.chunker = SmartTextChunker(
            max_chunk_size=chunk_size if chunk_size > 0 else None,
            model_id=self.tts_client.model_id,
        )
        self.parser = BookParser()
        self.voice_name = voice_name
        self.style = style
        self.multi_speaker = multi_speaker
        self.speaker2_voice = speaker2_voice
        self.inter_chunk_silence_ms = max(0, int(inter_chunk_silence_ms))
        self.normalize_audio = normalize_audio

        self.progress_file = self.output_dir / "progress.json"
        self.manifest_file = self.output_dir / "book_manifest.json"
        self.playlist_file = self.output_dir / "playlist.m3u"

    @staticmethod
    def atomic_write_json(file_path: Path, data: Any) -> None:
        """Writes JSON to disk atomically."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = file_path.with_suffix(file_path.suffix + f".tmp_{os.getpid()}")
        content = json.dumps(data, ensure_ascii=False, indent=2)
        temp_file.write_text(content, encoding="utf-8")
        os.replace(str(temp_file), str(file_path))

    @staticmethod
    def normalize_pcm_rms(pcm_bytes: bytes, target_rms: float = 6500.0) -> bytes:
        """
        Normalizes 16-bit signed little-endian PCM audio to a balanced RMS loudness level,
        preventing clipping and keeping volume consistent across chunks.
        Optimized for high-speed processing with audioop and array fallback.
        """
        if not pcm_bytes or len(pcm_bytes) < 4:
            return pcm_bytes

        usable_len = (len(pcm_bytes) // 2) * 2
        pcm_body = pcm_bytes[:usable_len]

        if audioop is not None:
            try:
                current_rms = float(audioop.rms(pcm_body, 2))
                if current_rms < 50.0:
                    return pcm_bytes
                gain = max(0.4, min(2.8, target_rms / current_rms))
                if abs(gain - 1.0) < 0.05:
                    return pcm_bytes
                return audioop.mul(pcm_body, 2, gain)
            except Exception as e:
                logger.warning("audioop.mul failed: %s", e)

        try:
            arr = array.array("h")
            arr.frombytes(pcm_body)
            sum_sq = sum(float(s) * float(s) for s in arr)
            current_rms = math.sqrt(sum_sq / float(len(arr))) if arr else 0.0
            if current_rms < 50.0:
                return pcm_bytes
            gain = max(0.4, min(2.8, target_rms / current_rms))
            if abs(gain - 1.0) < 0.05:
                return pcm_bytes
            for i in range(len(arr)):
                arr[i] = max(-32767, min(32767, int(arr[i] * gain)))
            return arr.tobytes()
        except Exception as e:
            logger.warning("array normalization failed: %s", e)
            return pcm_bytes

    def load_progress(self) -> Dict[str, Any]:
        """Loads progress state to support seamless resumption."""
        if self.progress_file.exists():
            try:
                content = self.progress_file.read_text(encoding="utf-8")
                return json.loads(content)
            except Exception as e:
                logger.warning("Could not read progress file: %s. Starting fresh.", str(e))
        return {"completed_chapters": {}, "total_chapters": 0}

    def save_progress(self, progress_data: Dict[str, Any]) -> None:
        """Persists progress state atomically."""
        self.atomic_write_json(self.progress_file, progress_data)

    @classmethod
    def concatenate_wav_files(
        cls,
        input_paths: List[Path],
        output_path: Path,
        silence_ms: int = 250,
        normalize_rms: bool = True,
    ) -> int:
        """
        Concatenates multiple standard linear PCM WAV files into one contiguous WAV file,
        inserting natural silence between chunks and optionally normalizing RMS loudness.
        Returns the combined audio duration in milliseconds.
        """
        if not input_paths:
            return 0

        pcm_data_list: List[bytes] = []
        sample_rate = 24000
        channels = 1
        bits_per_sample = 16

        import wave
        for p in input_paths:
            if not p.is_file() or p.stat().st_size < 44:
                continue
            try:
                with wave.open(str(p), "rb") as w:
                    channels = w.getnchannels()
                    sample_rate = w.getframerate()
                    bits_per_sample = w.getsampwidth() * 8
                    raw_pcm = w.readframes(w.getnframes())
            except Exception:
                raw_bytes = p.read_bytes()
                if raw_bytes.startswith(b"RIFF"):
                    data_idx = raw_bytes.find(b"data")
                    if data_idx != -1 and len(raw_bytes) >= data_idx + 8:
                        channels = struct.unpack_from("<H", raw_bytes, 22)[0] or 1
                        sample_rate = struct.unpack_from("<I", raw_bytes, 24)[0] or 24000
                        bits_per_sample = struct.unpack_from("<H", raw_bytes, 34)[0] or 16
                        data_size = struct.unpack_from("<I", raw_bytes, data_idx + 4)[0]
                        raw_pcm = raw_bytes[data_idx + 8 : data_idx + 8 + data_size]
                    else:
                        channels = struct.unpack_from("<H", raw_bytes, 22)[0] or 1
                        sample_rate = struct.unpack_from("<I", raw_bytes, 24)[0] or 24000
                        bits_per_sample = struct.unpack_from("<H", raw_bytes, 34)[0] or 16
                        raw_pcm = raw_bytes[44:]
                else:
                    raw_pcm = raw_bytes

            if normalize_rms and bits_per_sample == 16:
                raw_pcm = cls.normalize_pcm_rms(raw_pcm)
            pcm_data_list.append(raw_pcm)

        if not pcm_data_list:
            return 0

        bytes_per_sample = channels * (bits_per_sample // 8)
        silence_samples = int((sample_rate * max(0, silence_ms)) / 1000.0)
        silence_bytes = b"\x00" * (silence_samples * bytes_per_sample)

        combined_pcm = silence_bytes.join(pcm_data_list)
        combined_wav = GeminiTtsClient.create_wav_header(
            combined_pcm,
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits_per_sample,
        )

        GeminiTtsClient.atomic_save_audio(output_path, combined_wav)

        bytes_per_second = sample_rate * bytes_per_sample
        duration_ms = int((len(combined_pcm) / bytes_per_second) * 1000) if bytes_per_second > 0 else 0
        return duration_ms

    def process_book(
        self,
        book_path: Path,
        export_wav_path: Optional[Path] = None,
        on_progress: Optional[Callable[[int, int, int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Processes an entire book into a structured audiobook with chapter audio files.
        Supports optional full-book WAV export and live progress callbacks.
        """
        logger.info("Ingesting book from: %s", book_path)
        parsed_book: ParsedBook = self.parser.parse_file(book_path)
        logger.info(
            "Book parsed successfully: '%s' (%d chapters, %d characters)",
            parsed_book.title,
            len(parsed_book.chapters),
            parsed_book.total_characters,
        )

        progress = self.load_progress()
        progress["total_chapters"] = len(parsed_book.chapters)
        progress["book_title"] = parsed_book.title

        chapters_dir = self.output_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        raw_chunks_dir = self.output_dir / "raw_chunks"
        raw_chunks_dir.mkdir(parents=True, exist_ok=True)

        chapter_manifest_records = []
        chapter_wav_files: List[Path] = []
        playlist_lines = ["#EXTM3U", f"#PLAYLIST:{parsed_book.title}"]

        for idx, chapter in enumerate(parsed_book.chapters, start=1):
            if should_cancel and should_cancel():
                logger.warning("Synthesis cancelled by caller at chapter %d.", idx)
                break

            chapter_key = f"chapter_{idx:03d}"
            chapter_filename = f"{chapter_key}.wav"
            chapter_audio_path = chapters_dir / chapter_filename

            # Check if this chapter is already synthesized and completed
            if (
                chapter_key in progress.get("completed_chapters", {})
                and chapter_audio_path.exists()
                and chapter_audio_path.stat().st_size > 44
            ):
                logger.info(
                    "Resuming: Chapter %d/%d ('%s') already completed.",
                    idx,
                    len(parsed_book.chapters),
                    chapter.chapter_title,
                )
                record = progress["completed_chapters"][chapter_key]
                chapter_manifest_records.append(record)
                chapter_wav_files.append(chapter_audio_path)
                playlist_lines.append(f"#EXTINF:{record.get('duration_seconds', 0)},{chapter.chapter_title}")
                playlist_lines.append(f"chapters/{chapter_filename}")
                if on_progress:
                    on_progress(idx, len(parsed_book.chapters), 1, 1, chapter.chapter_title)
                continue

            logger.info("Synthesizing Chapter %d/%d: '%s'...", idx, len(parsed_book.chapters), chapter.chapter_title)

            # Smart chunking for speech (adapts dynamically if model changed)
            chunks = self.chunker.chunk_text(chapter.text, model_id=self.tts_client.model_id if self.chunker.max_chunk_size == self.chunker.target_size else None)
            chunk_audio_paths: List[Path] = []

            for chunk_idx, chunk_text in enumerate(chunks, start=1):
                if should_cancel and should_cancel():
                    logger.warning("Synthesis cancelled by caller at chapter %d chunk %d.", idx, chunk_idx)
                    break

                if on_progress:
                    on_progress(idx, len(parsed_book.chapters), chunk_idx, len(chunks), chapter.chapter_title)

                chunk_filename = f"{chapter_key}_part_{chunk_idx:03d}.wav"
                chunk_path = raw_chunks_dir / chunk_filename

                if chunk_path.exists() and chunk_path.stat().st_size > 44:
                    logger.info("  Chunk %d/%d already exists. Skipping synthesis.", chunk_idx, len(chunks))
                else:
                    logger.info("  Synthesizing chunk %d/%d (%d chars)...", chunk_idx, len(chunks), len(chunk_text))
                    if self.multi_speaker:
                        audio_bytes = self.tts_client.synthesize_multi_speaker(
                            text=chunk_text,
                            speaker1_voice=self.voice_name,
                            speaker2_voice=self.speaker2_voice,
                            narrator_style=self.style,
                        )
                    else:
                        audio_bytes = self.tts_client.synthesize(
                            text=chunk_text,
                            voice_name=self.voice_name,
                            style=self.style,
                        )
                    GeminiTtsClient.atomic_save_audio(chunk_path, audio_bytes)

                chunk_audio_paths.append(chunk_path)

            if should_cancel and should_cancel():
                break

            # Concatenate chunks into final chapter audio
            duration_ms = self.concatenate_wav_files(
                chunk_audio_paths,
                chapter_audio_path,
                silence_ms=self.inter_chunk_silence_ms,
                normalize_rms=self.normalize_audio,
            )
            duration_sec = duration_ms // 1000
            chapter_wav_files.append(chapter_audio_path)

            chapter_record = {
                "index": idx,
                "id": chapter_key,
                "title": chapter.chapter_title,
                "level": chapter.level,
                "audio_file": f"chapters/{chapter_filename}",
                "duration_seconds": duration_sec,
                "duration_ms": duration_ms,
                "chunks_count": len(chunks),
            }

            chapter_manifest_records.append(chapter_record)
            progress["completed_chapters"][chapter_key] = chapter_record
            self.save_progress(progress)

            playlist_lines.append(f"#EXTINF:{duration_sec},{chapter.chapter_title}")
            playlist_lines.append(f"chapters/{chapter_filename}")

        # Write M3U playlist atomically
        playlist_content = "\n".join(playlist_lines) + "\n"
        temp_playlist = self.playlist_file.with_suffix(f".m3u.tmp_{os.getpid()}")
        temp_playlist.write_text(playlist_content, encoding="utf-8")
        os.replace(str(temp_playlist), str(self.playlist_file))

        # Optional single-file WAV export of the entire book
        exported_wav_str: Optional[str] = None
        if export_wav_path and chapter_wav_files:
            target_export = Path(export_wav_path)
            self.concatenate_wav_files(
                chapter_wav_files,
                target_export,
                silence_ms=600,
                normalize_rms=False,
            )
            exported_wav_str = str(target_export.resolve())
            logger.info("Exported full merged audiobook WAV to: %s", exported_wav_str)

        # Write book manifest atomically
        total_duration_sec = sum(c.get("duration_seconds", 0) for c in chapter_manifest_records)
        manifest_data: Dict[str, Any] = {
            "title": parsed_book.title,
            "source_file": str(book_path.resolve()),
            "total_chapters": len(chapter_manifest_records),
            "total_duration_seconds": total_duration_sec,
            "voice_name": self.voice_name,
            "multi_speaker": self.multi_speaker,
            "speaker2_voice": self.speaker2_voice if self.multi_speaker else None,
            "engine": self.tts_client.model_id,
            "generation_timestamp": int(time.time()),
            "playlist": "playlist.m3u",
            "exported_wav": exported_wav_str,
            "chapters": chapter_manifest_records,
        }
        self.atomic_write_json(self.manifest_file, manifest_data)

        logger.info(
            "Audiobook generation complete! Total duration: %d seconds across %d chapters.",
            total_duration_sec,
            len(chapter_manifest_records),
        )
        return manifest_data


def _load_keys_from_file(file_path: str) -> List[str]:
    """Reads API keys (one per line) from a text file, ignoring comments and blanks."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(
            f"[CLI] ملف مفاتيح API غير موجود في المسار: '{file_path}'. "
            f"الإجراء: تحقق من المسار أو مرر المفتاح عبر --api-key."
        )
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def main(argv: Optional[List[str]] = None) -> int:
    """CLI Entry point for Gemini Audiobook Engine (supports power users and AI agents)."""
    parser = argparse.ArgumentParser(description="Gemini Audiobook TTS Engine & Power CLI")
    parser.add_argument("--input", "-i", type=str, default=None, help="Path to input book (.md, .txt, or .docx)")
    parser.add_argument("--output-dir", "-o", type=str, default="./audiobook_output", help="Output directory")
    parser.add_argument("--export-wav", type=str, default=None, help="Optional path to export a single merged WAV file")
    parser.add_argument("--api-key", type=str, default=None, help="Google Gemini API key (or GEMINI_API_KEY env)")
    parser.add_argument("--api-keys-file", type=str, default=None, help="Path to text file with one API key per line")
    parser.add_argument("--model", type=str, default="gemini-3.8-flash-tts", help="TTS Model ID")
    parser.add_argument("--voice", type=str, default="Kore", help="Primary/Narrator prebuilt voice name")
    parser.add_argument("--style", type=str, default="طبيعي", help="Speech delivery style or Arabic preset name")
    parser.add_argument("--multi-speaker", action="store_true", help="Enable 2-speaker dramatic dialogue mode")
    parser.add_argument("--speaker2-voice", type=str, default="Charon", help="Second speaker voice for dialogue mode")
    parser.add_argument("--chunk-size", type=int, default=0, help="Override max chunk size (0 = model-adaptive)")
    parser.add_argument("--pacing-seconds", type=float, default=None, help="Seconds between consecutive API requests (default 60)")
    parser.add_argument("--mock", action="store_true", help="Generate synthetic audio offline for testing")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON summary to stdout for AI agents")
    parser.add_argument("--list-voices", action="store_true", help="List all 30 Gemini TTS voices and 5 style presets")
    parser.add_argument("--doctor", action="store_true", help="Run environment diagnostic checks and exit")

    args = parser.parse_args(argv)

    if args.doctor:
        from doctor import EnvironmentDoctor
        doc = EnvironmentDoctor()
        healthy = doc.run_all()
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "healthy": healthy,
                        "checks": {k: {"passed": v[0], "message": v[1]} for k, v in doc.report.items()},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        return 0 if healthy else 1

    if args.list_voices:
        catalog = {
            "voices": PREBUILT_VOICES,
            "style_presets": STYLE_PRESETS,
            "adaptive_limits": {
                "gemini-3.8-flash-tts": get_adaptive_chunk_limits("gemini-3.8-flash-tts"),
                "gemini-3.1-flash-tts-preview": get_adaptive_chunk_limits("gemini-3.1-flash-tts-preview"),
            },
        }
        if args.json:
            sys.stdout.write(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        else:
            lines = ["=== الأصوات الرسمية المتاحة في Gemini TTS (30 صوتاً) ==="]
            for v in PREBUILT_VOICES:
                lines.append(f"- {v['name']} ({v['gender']}): {v['style_ar']}")
            lines.append("\n=== الأنماط الإخراجية الجاهزة ===")
            for k, desc in STYLE_PRESETS.items():
                lines.append(f"- {k}: {desc}")
            sys.stdout.write("\n".join(lines) + "\n")
        return 0

    if not args.input:
        parser.error("المعامل --input مطلوب لتحويل الكتاب (أو استخدم --list-voices / --doctor).")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file does not exist: %s", args.input)
        return 1

    keys_list: List[str] = []
    if args.api_keys_file:
        keys_list.extend(_load_keys_from_file(args.api_keys_file))
    if args.api_key:
        keys_list.append(args.api_key)

    tts_client = GeminiTtsClient(
        api_key=args.api_key,
        api_keys=keys_list if keys_list else None,
        model_id=args.model,
        mock_mode=args.mock,
        pacing_seconds=args.pacing_seconds,
    )

    engine = AudiobookEngine(
        output_dir=Path(args.output_dir),
        tts_client=tts_client,
        chunk_size=args.chunk_size,
        voice_name=args.voice,
        style=args.style,
        multi_speaker=args.multi_speaker,
        speaker2_voice=args.speaker2_voice,
    )

    export_wav = Path(args.export_wav) if args.export_wav else None
    manifest = engine.process_book(input_path, export_wav_path=export_wav)
    logger.info("Manifest created: %s/book_manifest.json", args.output_dir)

    if args.json:
        sys.stdout.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())

