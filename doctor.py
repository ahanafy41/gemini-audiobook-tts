#!/usr/bin/env python3
"""
Environment Diagnostic & Self-Check Tool for Gemini Audiobook TTS.
Verifies Python version, runtime modules, Termux/Android integration, storage
permissions, audio playback utilities, network reachability, and audio synthesis.
"""

import json
import logging
import os
import shutil
import struct
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Tuple

from gemini_tts_client import GeminiTtsClient

logger = logging.getLogger("AudiobookDoctor")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class EnvironmentDoctor:
    """
    Diagnostic suite for validating execution environment readiness.
    """

    def __init__(self) -> None:
        self.report: Dict[str, Tuple[bool, str]] = {}

    def check_python_version(self) -> bool:
        """Verifies Python version is at least 3.9."""
        major, minor = sys.version_info.major, sys.version_info.minor
        passed = (major == 3 and minor >= 9) or (major > 3)
        msg = f"Python {major}.{minor}.{sys.version_info.micro} detected."
        self.report["python_version"] = (passed, msg)
        return passed

    def check_standard_modules(self) -> bool:
        """Verifies all required standard modules can be imported."""
        modules = ["urllib.request", "json", "wave", "struct", "base64", "math", "time", "logging", "pathlib"]
        missing = []
        for mod in modules:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)

        passed = len(missing) == 0
        msg = "All standard library modules available." if passed else f"Missing modules: {', '.join(missing)}"
        self.report["standard_modules"] = (passed, msg)
        return passed

    def check_storage_permissions(self) -> bool:
        """Verifies write and atomic rename capabilities on current filesystem."""
        try:
            test_dir = Path("./.doctor_scratch")
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / f"test_{os.getpid()}.tmp"
            test_file.write_text("ok", encoding="utf-8")
            dest_file = test_dir / f"test_{os.getpid()}.dat"
            test_file.replace(dest_file)
            dest_file.unlink()
            test_dir.rmdir()
            passed = True
            msg = "Local directory write and atomic replace verified."
        except Exception as e:
            passed = False
            msg = f"Storage write test failed: {str(e)}"

        self.report["storage_write"] = (passed, msg)
        return passed

    def check_termux_environment(self) -> bool:
        """Inspects Termux and Android environment flags."""
        is_termux = "com.termux" in os.getenv("PREFIX", "") or "com.termux" in str(Path.home())
        termux_storage = Path.home() / "storage"
        has_storage_link = termux_storage.exists() and termux_storage.is_dir()

        msg = f"Termux runtime: {is_termux} | Termux shared storage accessible: {has_storage_link}"
        self.report["termux_env"] = (True, msg)
        return True

    def check_audio_playback_utilities(self) -> bool:
        """Detects available audio playback CLI tools."""
        candidates = ["termux-media-player", "ffplay", "mpv", "play", "aplay"]
        found = [cmd for cmd in candidates if shutil.which(cmd) is not None]

        passed = len(found) > 0
        msg = f"Available audio players: {', '.join(found)}" if passed else "No audio player binary found (install termux-api or mpv)."
        self.report["audio_players"] = (passed, msg)
        return passed

    def check_gemini_api_connectivity(self) -> bool:
        """Tests network reachability to Google Generative Language API endpoint."""
        url = "https://generativelanguage.googleapis.com"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GeminiAudiobookDoctor/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                status = response.status
                passed = status in (200, 301, 302, 404)
                msg = f"Google Generative Language API reachable (HTTP {status})."
        except urllib.error.HTTPError as e:
            passed = True
            msg = f"Google API endpoint reachable (HTTP response: {e.code})."
        except Exception as exc:
            passed = False
            msg = f"Network connection to Google API failed: {str(exc)}"

        self.report["network_reachability"] = (passed, msg)
        return passed

    def check_api_key_configured(self) -> bool:
        """Checks if GEMINI_API_KEY environment variable is configured."""
        key = os.getenv("GEMINI_API_KEY", "").strip()
        passed = bool(key)
        msg = "GEMINI_API_KEY environment variable is set." if passed else "GEMINI_API_KEY is not set (mock mode will be used)."
        self.report["api_key_configured"] = (passed, msg)
        return passed

    def check_audio_synthesis_pipeline(self) -> bool:
        """Generates synthetic audio and verifies WAV RIFF header structure."""
        try:
            synthetic_wav = GeminiTtsClient.generate_synthetic_wav(duration_seconds=0.2, sample_rate=24000)
            if not synthetic_wav.startswith(b"RIFF"):
                self.report["audio_synthesis"] = (False, "WAV header missing RIFF marker.")
                return False

            wave_marker = synthetic_wav[8:12]
            if wave_marker != b"WAVE":
                self.report["audio_synthesis"] = (False, f"Invalid WAVE format marker: {wave_marker}")
                return False

            # Verify fmt chunk sample rate
            sample_rate = struct.unpack_from("<I", synthetic_wav, 24)[0]
            if sample_rate != 24000:
                self.report["audio_synthesis"] = (False, f"Expected 24000Hz, received {sample_rate}Hz.")
                return False

            self.report["audio_synthesis"] = (True, "Synthetic audio generation & WAV integrity check passed.")
            return True
        except Exception as e:
            self.report["audio_synthesis"] = (False, f"Audio synthesis check failed: {str(e)}")
            return False

    def run_all(self) -> bool:
        """Executes all environmental diagnostics."""
        logger.info("Starting Gemini Audiobook TTS Environment Doctor...")
        self.check_python_version()
        self.check_standard_modules()
        self.check_storage_permissions()
        self.check_termux_environment()
        self.check_audio_playback_utilities()
        self.check_gemini_api_connectivity()
        self.check_api_key_configured()
        self.check_audio_synthesis_pipeline()

        critical_keys = ["python_version", "standard_modules", "storage_write", "audio_synthesis"]
        all_critical_passed = all(self.report[k][0] for k in critical_keys if k in self.report)

        logger.info("=== Environmental Diagnostic Results ===")
        for key, (passed, msg) in self.report.items():
            status_tag = "[PASS]" if passed else "[WARN/FAIL]"
            logger.info("  %s %-25s: %s", status_tag, key, msg)

        if all_critical_passed:
            logger.info("Doctor summary: Environment is READY for Gemini Audiobook synthesis.")
            return True
        else:
            logger.error("Doctor summary: Critical environment checks failed.")
            return False


def main() -> None:
    doctor = EnvironmentDoctor()
    healthy = doctor.run_all()
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
