#!/usr/bin/env python3
"""
Environment Diagnostic & Self-Check Tool for Gemini Audiobook TTS.
Verifies Python version, runtime modules, Termux/Android integration, storage
permissions, audio playback utilities, network reachability, and audio synthesis.
"""

import ctypes
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
    Diagnostic suite for validating execution environment readiness across Windows Desktop and Termux.
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
        modules = [
            "urllib.request",
            "json",
            "wave",
            "struct",
            "base64",
            "math",
            "time",
            "logging",
            "pathlib",
            "zipfile",
            "xml.etree.ElementTree",
        ]
        missing = []
        for mod in modules:
            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)

        passed = len(missing) == 0
        msg = "All standard library modules (including .docx XML parser) available." if passed else f"Missing modules: {', '.join(missing)}"
        self.report["standard_modules"] = (passed, msg)
        return passed

    def check_desktop_gui_dependencies(self) -> bool:
        """Checks whether wxPython and optional python-docx are installed for the Desktop GUI."""
        has_wx = False
        wx_ver = "not installed"
        try:
            import wx  # type: ignore
            has_wx = True
            wx_ver = getattr(wx, "__version__", "installed")
        except Exception:
            has_wx = False

        has_docx = False
        try:
            import docx  # type: ignore # noqa: F401
            has_docx = True
        except Exception:
            has_docx = False

        msg = f"wxPython: {wx_ver} | python-docx: {'installed' if has_docx else 'using stdlib XML fallback'}"
        self.report["desktop_gui"] = (True, msg)
        return has_wx

    def check_storage_permissions(self) -> bool:
        """Verifies write and atomic rename capabilities on current filesystem."""
        try:
            test_dir = Path("./.doctor_scratch")
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / f"test_{os.getpid()}.tmp"
            test_file.write_text("ok", encoding="utf-8")
            dest_file = test_dir / f"test_{os.getpid()}.dat"
            os.replace(str(test_file), str(dest_file))
            dest_file.unlink()
            test_dir.rmdir()
            passed = True
            msg = "Local directory write and atomic os.replace verified."
        except Exception as e:
            passed = False
            msg = f"Storage write test failed: {str(e)}"

        self.report["storage_write"] = (passed, msg)
        return passed

    def check_termux_environment(self) -> bool:
        """Inspects Termux, Android, and Windows platform flags."""
        is_termux = "com.termux" in os.getenv("PREFIX", "") or "com.termux" in str(Path.home())
        termux_storage = Path.home() / "storage"
        has_storage_link = termux_storage.exists() and termux_storage.is_dir()

        msg = (
            f"Platform: {sys.platform} | Termux runtime: {is_termux} | "
            f"Termux shared storage accessible: {has_storage_link}"
        )
        self.report["platform_env"] = (True, msg)
        return True

    def check_audio_playback_utilities(self) -> bool:
        """Detects Windows native winmm MCI or available CLI audio playback tools."""
        found = []
        if sys.platform == "win32" and hasattr(ctypes, "windll") and hasattr(ctypes.windll, "winmm"):
            found.append("windows-winmm-mci")

        candidates = ["termux-media-player", "ffplay", "mpv", "play", "aplay"]
        found.extend(cmd for cmd in candidates if shutil.which(cmd) is not None)

        passed = len(found) > 0
        msg = f"Available audio backends: {', '.join(found)}" if passed else "No audio player backend found."
        self.report["audio_players"] = (passed, msg)
        return passed

    def check_gemini_api_connectivity(self) -> bool:
        """Tests network reachability to Google Generative Language API endpoint."""
        url = "https://generativelanguage.googleapis.com"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "GeminiAudiobookDoctor/2.0"})
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
        """Checks if GEMINI_API_KEY environment variable or desktop settings is configured."""
        key = os.getenv("GEMINI_API_KEY", "").strip()
        settings_path = Path.home() / ".gemini_audiobook_desktop" / "settings.json"
        has_saved_keys = False
        if settings_path.is_file():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                has_saved_keys = bool(data.get("api_keys") or data.get("api_key"))
            except Exception:
                has_saved_keys = False

        passed = bool(key or has_saved_keys)
        msg = (
            "API key configured (via environment or saved settings)."
            if passed
            else "GEMINI_API_KEY is not set (mock mode or GUI settings key will be used)."
        )
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
                self.report["audio_synthesis"] = (False, f"Invalid WAVE format marker: {wave_marker!r}")
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
        self.check_desktop_gui_dependencies()
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

