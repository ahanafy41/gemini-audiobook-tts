#!/usr/bin/env python3
"""
Audiobook Player Service for Termux and CLI environments.
Handles media playback, bookmark tracking, and audio focus management.
"""

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("AudiobookPlayerService")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class AudiobookPlayerService:
    """
    Player service managing audio playback, position tracking, and bookmarks.
    """

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self.state_dir = Path(state_dir or (Path.home() / ".audiobook_state"))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.bookmark_file = self.state_dir / "bookmarks.json"
        self.current_process: Optional[subprocess.Popen] = None
        self.current_audio_file: Optional[str] = None
        self.start_timestamp: float = 0.0

    def load_bookmarks(self) -> Dict[str, Any]:
        """Loads saved bookmarks from disk."""
        if self.bookmark_file.exists():
            try:
                content = self.bookmark_file.read_text(encoding="utf-8")
                return json.loads(content)
            except Exception as e:
                logger.warning("Could not read bookmarks: %s", str(e))
        return {}

    def save_bookmark(self, book_title: str, chapter_id: str, position_ms: int) -> None:
        """Saves current playback bookmark atomically."""
        bookmarks = self.load_bookmarks()
        bookmarks[book_title] = {
            "chapter_id": chapter_id,
            "position_ms": position_ms,
            "timestamp": int(time.time()),
        }
        temp_file = self.bookmark_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(bookmarks, indent=2), encoding="utf-8")
        temp_file.replace(self.bookmark_file)
        logger.info("Bookmark saved: '%s' at %d ms", book_title, position_ms)

    def play(self, audio_path: str, book_title: str = "Audiobook", chapter_id: str = "ch1") -> bool:
        """Starts playback using available audio utility."""
        self.stop()
        audio_file = Path(audio_path)
        if not audio_file.exists():
            logger.error("Audio file does not exist: %s", audio_path)
            return False

        self.current_audio_file = str(audio_file.resolve())
        self.start_timestamp = time.time()

        if shutil.which("termux-media-player"):
            cmd = ["termux-media-player", "play", self.current_audio_file]
        elif shutil.which("mpv"):
            cmd = ["mpv", "--no-video", self.current_audio_file]
        elif shutil.which("play"):
            cmd = ["play", self.current_audio_file]
        elif shutil.which("aplay"):
            cmd = ["aplay", self.current_audio_file]
        else:
            logger.warning("No audio player binary found. Simulating playback.")
            return True

        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Started playback of: %s", audio_file.name)
            return True
        except Exception as e:
            logger.error("Failed to launch playback process: %s", str(e))
            return False

    def pause(self) -> None:
        """Pauses current playback."""
        if shutil.which("termux-media-player"):
            subprocess.run(["termux-media-player", "pause"], check=False)
            logger.info("Playback paused via termux-media-player.")
        elif self.current_process:
            self.stop()

    def resume(self) -> None:
        """Resumes current playback."""
        if shutil.which("termux-media-player"):
            subprocess.run(["termux-media-player", "play"], check=False)
            logger.info("Playback resumed via termux-media-player.")

    def stop(self) -> None:
        """Stops current playback."""
        if shutil.which("termux-media-player"):
            subprocess.run(["termux-media-player", "stop"], check=False)

        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=1.0)
            except Exception:
                self.current_process.kill()
            self.current_process = None
            logger.info("Playback process terminated.")
