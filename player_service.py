#!/usr/bin/env python3
"""
Audiobook Player Service for Termux and CLI environments.
Handles media playback, bookmark tracking, and audio focus management.
"""

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
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
    Player service managing audio playback, position tracking, speed control, and bookmarks.
    Supports native Windows Multimedia Control Interface (winmm.dll MCI) and Termux/Linux CLI players.
    """

    MCI_ALIAS = "gemini_audiobook_stream"

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self.state_dir = Path(state_dir or (Path.home() / ".audiobook_state"))
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.bookmark_file = self.state_dir / "bookmarks.json"
        self.current_process: Optional[subprocess.Popen] = None
        self.current_audio_file: Optional[str] = None
        self.current_book_title: str = "Audiobook"
        self.current_chapter_id: str = "ch1"
        self.start_timestamp: float = 0.0
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.playback_speed: float = 1.0
        self._mci_active: bool = False
        self._simulated_position_ms: int = 0
        self._simulated_duration_ms: int = 0

    def _is_windows_mci_available(self) -> bool:
        """Checks whether ctypes.windll.winmm is available on Windows."""
        return sys.platform == "win32" and hasattr(ctypes, "windll") and hasattr(ctypes.windll, "winmm")

    def _mci_send(self, command: str) -> Optional[str]:
        """Executes a Windows MCI command string via winmm.mciSendStringW."""
        if not self._is_windows_mci_available():
            return None
        try:
            buf = ctypes.create_unicode_buffer(256)
            err_code = ctypes.windll.winmm.mciSendStringW(command, buf, 255, 0)
            if err_code != 0:
                err_buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.winmm.mciGetErrorStringW(err_code, err_buf, 255)
                logger.debug("MCI command '%s' returned code %d: %s", command, err_code, err_buf.value)
                return None
            return buf.value
        except Exception as exc:
            logger.debug("MCI exception for command '%s': %s", command, str(exc))
            return None

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
            "position_ms": max(0, int(position_ms)),
            "timestamp": int(time.time()),
        }
        temp_file = self.bookmark_file.with_suffix(f".tmp_{os.getpid()}")
        temp_file.write_text(json.dumps(bookmarks, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(temp_file), str(self.bookmark_file))
        logger.info("Bookmark saved: '%s' at %d ms", book_title, position_ms)

    def get_bookmark(self, book_title: str) -> Optional[Dict[str, Any]]:
        """Retrieves saved bookmark for a specific book title."""
        bookmarks = self.load_bookmarks()
        return bookmarks.get(book_title)

    def play(
        self,
        audio_path: str,
        book_title: str = "Audiobook",
        chapter_id: str = "ch1",
        start_position_ms: int = 0,
    ) -> bool:
        """Starts playback using Windows MCI or available Linux/Termux audio utility."""
        self.stop()
        audio_file = Path(audio_path)
        if not audio_file.exists():
            logger.error("Audio file does not exist: %s", audio_path)
            return False

        self.current_audio_file = str(audio_file.resolve())
        self.current_book_title = book_title
        self.current_chapter_id = chapter_id
        self.start_timestamp = time.time()
        self._simulated_position_ms = max(0, int(start_position_ms))

        # Estimate duration from WAV file size if standard 24kHz 16-bit mono
        try:
            fsize = audio_file.stat().st_size
            self._simulated_duration_ms = max(0, int(((fsize - 44) / 48000.0) * 1000))
        except Exception:
            self._simulated_duration_ms = 0

        if self._is_windows_mci_available():
            self._mci_send(f"close {self.MCI_ALIAS}")
            # Try mpegvideo first (supports speed control on WAV/MP3), fallback to waveaudio
            res = self._mci_send(f'open "{self.current_audio_file}" type mpegvideo alias {self.MCI_ALIAS}')
            if res is None:
                res = self._mci_send(f'open "{self.current_audio_file}" type waveaudio alias {self.MCI_ALIAS}')
            if res is not None:
                self._mci_send(f"set {self.MCI_ALIAS} time format milliseconds")
                if self.playback_speed != 1.0:
                    speed_int = int(self.playback_speed * 1000)
                    self._mci_send(f"set {self.MCI_ALIAS} speed {speed_int}")
                if start_position_ms > 0:
                    self._mci_send(f"play {self.MCI_ALIAS} from {int(start_position_ms)}")
                else:
                    self._mci_send(f"play {self.MCI_ALIAS}")
                self._mci_active = True
                self.is_playing = True
                self.is_paused = False
                logger.info("Started Windows MCI playback of: %s", audio_file.name)
                return True

        if shutil.which("termux-media-player"):
            cmd = ["termux-media-player", "play", self.current_audio_file]
        elif shutil.which("mpv"):
            cmd = ["mpv", "--no-video", self.current_audio_file]
        elif shutil.which("play"):
            cmd = ["play", self.current_audio_file]
        elif shutil.which("aplay"):
            cmd = ["aplay", self.current_audio_file]
        else:
            logger.warning("No external audio player binary found. Simulating playback.")
            self.is_playing = True
            self.is_paused = False
            return True

        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.is_playing = True
            self.is_paused = False
            logger.info("Started playback of: %s", audio_file.name)
            return True
        except Exception as e:
            logger.error("Failed to launch playback process: %s", str(e))
            return False

    def pause(self) -> None:
        """Pauses current playback."""
        if self._mci_active:
            self._mci_send(f"pause {self.MCI_ALIAS}")
            self.is_paused = True
            self.is_playing = False
            pos = self.get_position_ms()
            self.save_bookmark(self.current_book_title, self.current_chapter_id, pos)
            logger.info("Playback paused via Windows MCI at %d ms.", pos)
            return

        if shutil.which("termux-media-player"):
            subprocess.run(["termux-media-player", "pause"], check=False)
            self.is_paused = True
            self.is_playing = False
            logger.info("Playback paused via termux-media-player.")
        elif self.current_process:
            self.stop()

    def resume(self) -> None:
        """Resumes current playback."""
        if self._mci_active:
            self._mci_send(f"resume {self.MCI_ALIAS}")
            self.is_paused = False
            self.is_playing = True
            logger.info("Playback resumed via Windows MCI.")
            return

        if shutil.which("termux-media-player"):
            subprocess.run(["termux-media-player", "play"], check=False)
            self.is_paused = False
            self.is_playing = True
            logger.info("Playback resumed via termux-media-player.")

    def seek_ms(self, target_ms: int) -> int:
        """Seeks to the specified position in milliseconds and returns the new position."""
        duration = self.get_duration_ms()
        clamped = max(0, int(target_ms))
        if duration > 0:
            clamped = min(clamped, duration)
        self._simulated_position_ms = clamped

        if self._mci_active:
            if self.is_playing and not self.is_paused:
                self._mci_send(f"play {self.MCI_ALIAS} from {clamped}")
            else:
                self._mci_send(f"seek {self.MCI_ALIAS} to {clamped}")
        return clamped

    def seek_relative_ms(self, delta_ms: int) -> int:
        """Seeks forward or backward by delta_ms (e.g. +10000 or -10000)."""
        current = self.get_position_ms()
        return self.seek_ms(current + int(delta_ms))

    def set_speed(self, speed_multiplier: float) -> float:
        """Sets playback speed between 0.5x and 2.5x."""
        self.playback_speed = max(0.5, min(2.5, round(float(speed_multiplier), 2)))
        if self._mci_active:
            speed_int = int(self.playback_speed * 1000)
            self._mci_send(f"set {self.MCI_ALIAS} speed {speed_int}")
        logger.info("Playback speed set to %.2fx", self.playback_speed)
        return self.playback_speed

    def get_position_ms(self) -> int:
        """Returns current playback position in milliseconds."""
        if self._mci_active:
            val = self._mci_send(f"status {self.MCI_ALIAS} position")
            if val and val.strip().isdigit():
                return int(val.strip())
        if self.is_playing and not self.is_paused and self.start_timestamp > 0:
            elapsed = int((time.time() - self.start_timestamp) * 1000)
            return min(self._simulated_duration_ms or elapsed, self._simulated_position_ms + elapsed)
        return self._simulated_position_ms

    def get_duration_ms(self) -> int:
        """Returns total audio duration in milliseconds."""
        if self._mci_active:
            val = self._mci_send(f"status {self.MCI_ALIAS} length")
            if val and val.strip().isdigit():
                return int(val.strip())
        return self._simulated_duration_ms

    def stop(self) -> None:
        """Stops current playback and releases audio resources."""
        if self._mci_active:
            pos = self.get_position_ms()
            if self.current_book_title and pos > 0:
                self.save_bookmark(self.current_book_title, self.current_chapter_id, pos)
            self._mci_send(f"stop {self.MCI_ALIAS}")
            self._mci_send(f"close {self.MCI_ALIAS}")
            self._mci_active = False

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

        self.is_playing = False
        self.is_paused = False

