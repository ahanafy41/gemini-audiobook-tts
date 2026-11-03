#!/usr/bin/env python3
"""
Main Entry Point for Gemini Audiobook Desktop & Power CLI.
- When invoked with `--doctor`, runs environmental diagnostics.
- When invoked with `--list-voices`, outputs the 30 official Gemini TTS voices.
- When invoked with `--input <path>`, executes headless audiobook synthesis
  using SynthesisWorker (supporting multi-key rotation, 60s pacing, .docx/.md/.txt,
  optional `--export-wav` merged output, and `--json` structured reporting).
- When invoked with no CLI synthesis arguments, launches the 100% NVDA-accessible
  wxPython 4-tab desktop GUI (`MainFrame`).
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from doctor import EnvironmentDoctor
from desktop.i18n import (
    APP_NAME,
    MODEL_CHOICES,
    PREBUILT_VOICES_CATALOG,
    STYLE_PRESETS,
    format_voice_choice,
    normalize_lang,
)
from desktop.settings_manager import (
    SUPPORTED_MODELS,
    SettingsManager,
)
from desktop.worker import (
    SynthesisWorker,
    atomic_write_bytes,
    merge_and_normalize_wav_files,
)

logger = logging.getLogger("DesktopApp")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gemini Audiobook - NVDA Accessible Desktop App & Headless CLI"
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run self-diagnostic environment check and exit",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List all 30 official Gemini TTS voices and exit",
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to input book (.txt, .md, or .docx) for headless CLI synthesis",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output directory for generated audiobook chapters and manifest",
    )
    parser.add_argument(
        "--export-wav",
        type=str,
        default=None,
        help="Optional file path to export a single merged and normalized WAV audiobook",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Gemini TTS model ID (default: gemini-3.8-flash-tts)",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=None,
        help="Primary narrator voice name (default: Charon)",
    )
    parser.add_argument(
        "--style",
        type=str,
        default=None,
        help="Speech delivery style prompt or preset (default: empty for natural reading)",
    )
    parser.add_argument(
        "--multi-speaker",
        action="store_true",
        help="Enable 2-speaker dramatic dialogue mode (Narrator + Character)",
    )
    parser.add_argument(
        "--speaker2-voice",
        type=str,
        default=None,
        help="Second speaker voice name for dialogue mode (default: Kore)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Single Gemini API key (or comma-separated list of keys)",
    )
    parser.add_argument(
        "--api-keys-file",
        type=str,
        default=None,
        help="Path to a text file containing one Gemini API key per line",
    )
    parser.add_argument(
        "--pacing-seconds",
        type=float,
        default=None,
        help="Mandatory interval in seconds between consecutive API requests (default: 60.0)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in offline synthetic audio mock mode",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON output to stdout in CLI mode",
    )
    return parser


def run_cli_list_voices(as_json: bool = False, lang: str = "en") -> int:
    code = normalize_lang(lang)
    if as_json:
        payload = {
            "app_name": APP_NAME,
            "total_voices": len(PREBUILT_VOICES_CATALOG),
            "voices": PREBUILT_VOICES_CATALOG,
            "models": MODEL_CHOICES,
            "styles": STYLE_PRESETS,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        header = (
            f"=== {APP_NAME} Official Voices ({len(PREBUILT_VOICES_CATALOG)}) ===\n"
            if code == "en"
            else f"=== قائمة أصوات {APP_NAME} الرسمية ({len(PREBUILT_VOICES_CATALOG)}) ===\n"
        )
        sys.stdout.write(header)
        for idx, v in enumerate(PREBUILT_VOICES_CATALOG, start=1):
            sys.stdout.write(f"{idx:02d}. {format_voice_choice(v, code)}\n")
    return 0


def run_cli_headless(args: argparse.Namespace, settings_mgr: SettingsManager) -> int:
    from desktop.main_frame import read_book_file_with_docx_fallback

    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        err_msg = f"Input file not found: {input_path}"
        if args.json:
            sys.stdout.write(json.dumps({"success": False, "error": err_msg}, ensure_ascii=False) + "\n")
        else:
            logger.error(err_msg)
        return 1

    api_keys: List[str] = []
    if args.api_key:
        for part in args.api_key.replace("\n", ",").split(","):
            if part.strip():
                api_keys.append(part.strip())
    if args.api_keys_file:
        kf = Path(args.api_keys_file)
        if kf.is_file():
            for line in kf.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    api_keys.append(line.strip())
    if not api_keys:
        api_keys = settings_mgr.get_api_keys()

    model_id = args.model or str(settings_mgr.get("model_id", "gemini-3.8-flash-tts"))
    voice_name = args.voice or str(settings_mgr.get("voice_name", "Charon"))
    speaker2_voice = args.speaker2_voice or str(settings_mgr.get("speaker2_voice", "Kore"))

    style_idx = int(settings_mgr.get("style_index", 0) or 0)
    saved_style_prompt = "" if style_idx == 0 else str(settings_mgr.get("style_prompt", "") or "")
    style_prompt = args.style if args.style is not None else saved_style_prompt

    pacing_seconds = (
        float(args.pacing_seconds)
        if args.pacing_seconds is not None
        else float(settings_mgr.get("pacing_seconds", 60.0))
    )
    out_dir = Path(
        args.output_dir or str(settings_mgr.get("output_dir", settings_mgr.default_output_dir))
    ).resolve()

    book_text = read_book_file_with_docx_fallback(input_path)
    book_title = input_path.stem.replace("_", " ").strip() or "Audiobook"

    result_holder: Dict[str, Any] = {
        "success": False,
        "message": "",
        "manifest": None,
    }

    def on_finished(ok: bool, msg: str, manifest: Optional[Dict[str, Any]]) -> None:
        result_holder["success"] = ok
        result_holder["message"] = msg
        result_holder["manifest"] = manifest

    worker = SynthesisWorker(
        book_text=book_text,
        book_title=book_title,
        output_dir=out_dir,
        api_keys=api_keys,
        model_id=model_id,
        voice_name=voice_name,
        style_prompt=style_prompt,
        multi_speaker=bool(args.multi_speaker or settings_mgr.get("multi_speaker_enabled", False)),
        speaker2_voice=speaker2_voice,
        auto_emotion=bool(settings_mgr.get("auto_emotion_inference", False)),
        pacing_seconds=pacing_seconds,
        source_file_path=str(input_path),
        mock_mode=bool(args.mock or len(api_keys) == 0),
        on_finished=on_finished,
    )

    # Run synchronously on current thread for headless CLI execution
    worker.run()

    exported_wav_path: Optional[str] = None
    if result_holder["success"] and args.export_wav:
        dest_wav = Path(args.export_wav).resolve()
        chapters_dir = worker.output_dir / "chapters"
        if not chapters_dir.is_dir():
            chapters_dir = out_dir / "chapters"
        chapter_wavs = sorted(chapters_dir.glob("*.wav")) if chapters_dir.is_dir() else []
        if chapter_wavs:
            merge_and_normalize_wav_files(chapter_wavs, dest_wav, normalize=True)
            exported_wav_path = str(dest_wav)
        else:
            manifest_obj = result_holder.get("manifest") or {}
            merged_auto = manifest_obj.get("merged_audio_path") if isinstance(manifest_obj, dict) else None
            if merged_auto and Path(str(merged_auto)).is_file():
                atomic_write_bytes(dest_wav, Path(str(merged_auto)).read_bytes())
                exported_wav_path = str(dest_wav)

    if args.json:
        output_payload = {
            "success": result_holder["success"],
            "message": result_holder["message"],
            "output_dir": str(worker.output_dir),
            "exported_wav": exported_wav_path,
            "manifest": result_holder["manifest"],
        }
        sys.stdout.write(json.dumps(output_payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(f"{result_holder['message']}\n")
        if exported_wav_path:
            sys.stdout.write(f"Exported merged WAV: {exported_wav_path}\n")

    return 0 if result_holder["success"] else 1


def launch_gui(settings_mgr: SettingsManager) -> int:
    import wx
    from desktop.main_frame import MainFrame

    app = wx.App(False)
    app.SetAppName(APP_NAME)
    frame = MainFrame(settings_manager=settings_mgr)
    frame.Show(True)
    frame.Raise()
    app.MainLoop()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.doctor:
        doctor = EnvironmentDoctor()
        healthy = doctor.run_all()
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {"healthy": healthy, "checks": doctor.report},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        return 0 if healthy else 1

    settings_mgr = SettingsManager()

    if args.list_voices:
        return run_cli_list_voices(
            as_json=args.json,
            lang=str(settings_mgr.get("language", "en")),
        )

    if args.input:
        return run_cli_headless(args, settings_mgr)

    return launch_gui(settings_mgr)


if __name__ == "__main__":
    sys.exit(main())
