#!/usr/bin/env python3
"""
Main Gemini Audiobook Engine.
Orchestrates book parsing, intelligent chunking, TTS synthesis, audio concatenation,
progress resumption, and playlist generation for complete spoken audiobooks.
"""

import argparse
import json
import logging
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from book_parser import BookParser, ParsedBook
from gemini_tts_client import GeminiTtsClient
from markdown_stripper import CleanedChapter
from smart_chunker import SmartTextChunker

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
        chunk_size: int = 7500,
        voice_name: str = "Kore",
        style: str = "narrator, clear pronunciation and natural pacing",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_client = tts_client
        self.chunker = SmartTextChunker(max_chunk_size=chunk_size)
        self.parser = BookParser()
        self.voice_name = voice_name
        self.style = style

        self.progress_file = self.output_dir / "progress.json"
        self.manifest_file = self.output_dir / "book_manifest.json"
        self.playlist_file = self.output_dir / "playlist.m3u"

    @staticmethod
    def atomic_write_json(file_path: Path, data: Any) -> None:
        """Writes JSON to disk atomically."""
        temp_file = file_path.with_suffix(file_path.suffix + f".tmp_{os.getpid()}")
        content = json.dumps(data, ensure_ascii=False, indent=2)
        temp_file.write_text(content, encoding="utf-8")
        temp_file.replace(file_path)

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

    @staticmethod
    def concatenate_wav_files(input_paths: List[Path], output_path: Path) -> int:
        """
        Concatenates multiple standard linear PCM WAV files into one contiguous WAV file.
        Returns the combined audio duration in milliseconds.
        """
        if not input_paths:
            return 0

        pcm_data_list = []
        sample_rate = 24000
        channels = 1
        bits_per_sample = 16

        for p in input_paths:
            if not p.is_file() or p.stat().st_size < 44:
                continue
            raw_bytes = p.read_bytes()
            if raw_bytes.startswith(b"RIFF"):
                # Extract header parameters from first file
                fmt_channels = struct.unpack_from("<H", raw_bytes, 22)[0]
                fmt_rate = struct.unpack_from("<I", raw_bytes, 24)[0]
                fmt_bits = struct.unpack_from("<H", raw_bytes, 34)[0]
                sample_rate = fmt_rate
                channels = fmt_channels
                bits_per_sample = fmt_bits
                # Raw PCM is after 44 bytes standard header
                pcm_data_list.append(raw_bytes[44:])
            else:
                pcm_data_list.append(raw_bytes)

        combined_pcm = b"".join(pcm_data_list)
        combined_wav = GeminiTtsClient.create_wav_header(
            combined_pcm,
            sample_rate=sample_rate,
            channels=channels,
            bits_per_sample=bits_per_sample,
        )

        GeminiTtsClient.atomic_save_audio(output_path, combined_wav)

        bytes_per_second = sample_rate * channels * (bits_per_sample // 8)
        duration_ms = int((len(combined_pcm) / bytes_per_second) * 1000) if bytes_per_second > 0 else 0
        return duration_ms

    def process_book(self, book_path: Path) -> Dict[str, Any]:
        """
        Processes an entire book into a structured audio book with chapter audio files.
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
        playlist_lines = ["#EXTM3U", f"#PLAYLIST:{parsed_book.title}"]

        for idx, chapter in enumerate(parsed_book.chapters, start=1):
            chapter_key = f"chapter_{idx:03d}"
            chapter_filename = f"{chapter_key}.wav"
            chapter_audio_path = chapters_dir / chapter_filename

            # Check if this chapter is already synthesized and completed
            if (
                chapter_key in progress.get("completed_chapters", {})
                and chapter_audio_path.exists()
                and chapter_audio_path.stat().st_size > 44
            ):
                logger.info("Resuming: Chapter %d/%d ('%s') already completed.", idx, len(parsed_book.chapters), chapter.chapter_title)
                record = progress["completed_chapters"][chapter_key]
                chapter_manifest_records.append(record)
                playlist_lines.append(f"#EXTINF:{record.get('duration_seconds', 0)},{chapter.chapter_title}")
                playlist_lines.append(f"chapters/{chapter_filename}")
                continue

            logger.info("Synthesizing Chapter %d/%d: '%s'...", idx, len(parsed_book.chapters), chapter.chapter_title)

            # Smart chunking for speech
            chunks = self.chunker.chunk_text(chapter.text)
            chunk_audio_paths: List[Path] = []

            for chunk_idx, chunk_text in enumerate(chunks, start=1):
                chunk_filename = f"{chapter_key}_part_{chunk_idx:03d}.wav"
                chunk_path = raw_chunks_dir / chunk_filename

                if chunk_path.exists() and chunk_path.stat().st_size > 44:
                    logger.info("  Chunk %d/%d already exists. Skipping synthesis.", chunk_idx, len(chunks))
                else:
                    logger.info("  Synthesizing chunk %d/%d (%d chars)...", chunk_idx, len(chunks), len(chunk_text))
                    audio_bytes = self.tts_client.synthesize(
                        text=chunk_text,
                        voice_name=self.voice_name,
                        style=self.style,
                    )
                    GeminiTtsClient.atomic_save_audio(chunk_path, audio_bytes)

                chunk_audio_paths.append(chunk_path)

            # Concatenate chunks into final chapter audio
            duration_ms = self.concatenate_wav_files(chunk_audio_paths, chapter_audio_path)
            duration_sec = duration_ms // 1000

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
        temp_playlist = self.playlist_file.with_suffix(".m3u.tmp")
        temp_playlist.write_text(playlist_content, encoding="utf-8")
        temp_playlist.replace(self.playlist_file)

        # Write book manifest atomically
        total_duration_sec = sum(c.get("duration_seconds", 0) for c in chapter_manifest_records)
        manifest_data = {
            "title": parsed_book.title,
            "source_file": str(book_path.resolve()),
            "total_chapters": len(chapter_manifest_records),
            "total_duration_seconds": total_duration_sec,
            "voice_name": self.voice_name,
            "engine": "gemini-3.8-flash-tts",
            "generation_timestamp": int(time.time()),
            "playlist": "playlist.m3u",
            "chapters": chapter_manifest_records,
        }
        self.atomic_write_json(self.manifest_file, manifest_data)

        logger.info(
            "Audiobook generation complete! Total duration: %d seconds across %d chapters.",
            total_duration_sec,
            len(chapter_manifest_records),
        )
        return manifest_data


def main() -> None:
    """CLI Entry point for Gemini Audiobook Engine."""
    parser = argparse.ArgumentParser(description="Gemini Audiobook TTS Engine")
    parser.add_argument("--input", "-i", type=str, required=True, help="Path to input book (.md or .txt)")
    parser.add_argument("--output-dir", "-o", type=str, default="./audiobook_output", help="Output directory")
    parser.add_argument("--api-key", type=str, default=None, help="Google Gemini API key (or GEMINI_API_KEY env)")
    parser.add_argument("--model", type=str, default="gemini-3.8-flash-tts", help="TTS Model ID")
    parser.add_argument("--voice", type=str, default="Kore", help="Prebuilt voice name")
    parser.add_argument("--style", type=str, default="narrator, natural pacing", help="Speech delivery style")
    parser.add_argument("--chunk-size", type=int, default=7500, help="Max chunk size (<= 8000)")
    parser.add_argument("--mock", action="store_true", help="Generate synthetic audio offline for testing")

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file does not exist: %s", args.input)
        sys.exit(1)

    tts_client = GeminiTtsClient(
        api_key=args.api_key,
        model_id=args.model,
        mock_mode=args.mock,
    )

    engine = AudiobookEngine(
        output_dir=Path(args.output_dir),
        tts_client=tts_client,
        chunk_size=args.chunk_size,
        voice_name=args.voice,
        style=args.style,
    )

    manifest = engine.process_book(input_path)
    logger.info("Manifest created: %s/book_manifest.json", args.output_dir)


if __name__ == "__main__":
    main()
