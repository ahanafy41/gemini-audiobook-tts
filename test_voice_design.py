#!/usr/bin/env python3
"""
Test script for Gemini API Voice Design & Custom Voices.
Demonstrates:
  1. Listing custom/prompted voices (/v1beta/voices?type=prompted).
  2. Designing a new custom voice via natural language prompt (POST /v1beta/voices).
  3. Auditioning the voice via the returned sample_audio WAV payload.
  4. Synthesizing arbitrary text using the custom voice_id (models/{model}:generateContent).
"""

import argparse
import base64
import json
import logging
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VoiceDesignTester")

DEFAULT_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def craft_wav_header(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wraps raw linear PCM audio data in a standard 44-byte RIFF/WAVE header."""
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    file_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", file_size, b"WAVE", b"fmt ",
        16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size
    )
    return header + pcm_data


def list_prompted_voices(api_key: str) -> Dict[str, Any]:
    """Retrieves all stored prompted custom voices for the project."""
    url = f"{BASE_URL}/voices?key={urllib.parse.quote(api_key)}&type=prompted"
    req = urllib.request.Request(url, headers={"User-Agent": "VoiceDesignTester/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_voice_details(api_key: str, voice_id: str) -> Dict[str, Any]:
    """Retrieves full metadata and sample audio for a specific voice ID."""
    url = f"{BASE_URL}/voices/{urllib.parse.quote(voice_id)}?key={urllib.parse.quote(api_key)}"
    req = urllib.request.Request(url, headers={"User-Agent": "VoiceDesignTester/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_designed_voice(
    api_key: str,
    display_name: str,
    prompt_description: str,
    model: str = "gemini-3.8-flash-tts",
) -> Dict[str, Any]:
    """
    Creates a new custom voice persona from a natural language prompt via Voice Design.
    Endpoint: POST /v1beta/voices
    Note: For type='prompted', store must be True.
    """
    url = f"{BASE_URL}/voices?key={urllib.parse.quote(api_key)}"
    payload = {
        "store": True,
        "voice": {
            "model": model,
            "type": "prompted",
            "display_name": display_name,
            "prompted": {
                "input": prompt_description
            }
        }
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json", "User-Agent": "VoiceDesignTester/1.0"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def synthesize_with_voice(
    api_key: str,
    text: str,
    voice_id: str,
    model: str = "gemini-3.8-flash-lite-tts",
    output_wav_path: Optional[str] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Synthesizes speech using a custom voice ID.
    Configures generationConfig.speechConfig.voiceConfig.voice = voice_id.
    """
    url = f"{BASE_URL}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key)}"
    payload = {
        "contents": [{
            "parts": [{"text": text}]
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "voice": voice_id
                }
            }
        }
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json", "User-Agent": "VoiceDesignTester/1.0"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    candidates = res.get("candidates", [])
    if not candidates:
        raise ValueError(f"No candidates in response: {res}")

    part = candidates[0].get("content", {}).get("parts", [{}])[0]
    inline_data = part.get("inlineData", {})
    b64_data = inline_data.get("data", "")
    mime_type = inline_data.get("mimeType", "audio/wav")

    if not b64_data:
        raise ValueError(f"No audio data returned in inlineData: {part}")

    raw_audio = base64.b64decode(b64_data)
    wav_bytes = raw_audio if raw_audio.startswith(b"RIFF") else craft_wav_header(raw_audio, 24000)

    if output_wav_path:
        out_path = Path(output_wav_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(wav_bytes)
        logger.info("Saved synthesized audio to: %s (%d bytes)", out_path.resolve(), len(wav_bytes))

    return wav_bytes, res


def main():
    parser = argparse.ArgumentParser(description="Test Gemini Voice Design API specifications")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Gemini API Key")
    parser.add_argument("--action", choices=["list", "create", "get", "synthesize", "full-test"], default="full-test")
    parser.add_argument("--voice-id", default=None, help="Existing voice ID to get or synthesize with")
    parser.add_argument("--name", default="Egyptian Historian & Storyteller", help="Voice display name")
    parser.add_argument(
        "--prompt",
        default="A wise, passionate Egyptian historian in his late 50s with an authentic, warm Cairene accent, speaking with deep knowledge, measured cadence, and captivating storytelling flair.",
        help="Natural language prompt for voice design"
    )
    parser.add_argument("--text", default="أهلاً بكم في رحلتنا التاريخية عبر شوارع القاهرة المعز.", help="Text to synthesize")
    parser.add_argument("--model", default="gemini-3.8-flash-lite-tts", help="TTS synthesis model (e.g. gemini-3.8-flash-lite-tts or gemini-3.8-flash-tts)")
    parser.add_argument("--output", default="output_sample/voice_design_test.wav", help="Output path for synthesized WAV")

    args = parser.parse_args()
    key = args.api_key

    if not key:
        logger.error("No API key provided.")
        sys.exit(1)

    print("==========================================================")
    print("  Gemini API Voice Design & Custom Voices Test Suite")
    print("==========================================================")

    # 1. Action: LIST
    if args.action in ("list", "full-test"):
        logger.info("[Step 1] Querying stored custom prompted voices (GET /v1beta/voices?type=prompted)...")
        try:
            voices_data = list_prompted_voices(key)
            stored_voices = voices_data.get("voices", [])
            logger.info("Found %d stored custom voice(s):", len(stored_voices))
            for v in stored_voices:
                logger.info(
                    "  - ID: %s | Name: %s | Model: %s | Expires: %s",
                    v.get("id"),
                    v.get("display_name"),
                    v.get("model"),
                    v.get("expire_time"),
                )
        except urllib.error.HTTPError as e:
            logger.error("Failed to list voices: HTTP %d - %s", e.code, e.read().decode("utf-8", errors="ignore"))
            if args.action == "list":
                sys.exit(1)

    # Determine target voice_id
    target_voice_id = args.voice_id

    # 2. Action: CREATE
    if args.action == "create" or (args.action == "full-test" and not target_voice_id):
        # In full-test, if an existing voice matching our prompt/name exists, we can reuse or create
        logger.info("[Step 2] Designing custom voice via natural language prompt (POST /v1beta/voices)...")
        logger.info("  Name: %s", args.name)
        logger.info("  Prompt: %s", args.prompt)
        try:
            created = create_designed_voice(
                api_key=key,
                display_name=args.name,
                prompt_description=args.prompt,
                model="gemini-3.8-flash-tts"
            )
            target_voice_id = created.get("id")
            logger.info("Voice created successfully!")
            logger.info("  Voice ID: %s", target_voice_id)
            logger.info("  Model: %s", created.get("model"))
            logger.info("  Expire Time: %s", created.get("expire_time"))

            # Save audition sample audio if provided
            sample_audio = created.get("sample_audio")
            if sample_audio and isinstance(sample_audio, dict) and "data" in sample_audio:
                audition_bytes = base64.b64decode(sample_audio["data"])
                audition_path = Path("output_sample/voice_designed_audition.wav")
                audition_path.parent.mkdir(parents=True, exist_ok=True)
                audition_path.write_bytes(audition_bytes)
                logger.info("  Audition sample audio saved to: %s (%d bytes)", audition_path.resolve(), len(audition_bytes))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.warning("Voice creation failed or rate-limited: HTTP %d - %s", e.code, err_body)
            # If full-test, fallback to existing voice if available
            if args.action == "full-test":
                logger.info("Attempting to reuse existing custom voice from project...")
                try:
                    voices_data = list_prompted_voices(key)
                    if voices_data.get("voices"):
                        target_voice_id = voices_data["voices"][0].get("id")
                        logger.info("Reusing existing voice ID: %s", target_voice_id)
                except Exception:
                    pass
            if not target_voice_id:
                sys.exit(1)

    # 3. Action: GET
    if args.action == "get" and target_voice_id:
        logger.info("Retrieving details for voice %s...", target_voice_id)
        details = get_voice_details(key, target_voice_id)
        # Remove massive base64 for display
        if "sample_audio" in details:
            details["sample_audio"] = {"mime_type": details["sample_audio"].get("mime_type"), "data_length": len(details["sample_audio"].get("data", ""))}
        print(json.dumps(details, indent=2, ensure_ascii=False))

    # 4. Action: SYNTHESIZE
    if args.action in ("synthesize", "full-test") and target_voice_id:
        logger.info("[Step 3] Synthesizing speech using custom voice (%s)...", target_voice_id)
        logger.info("  Target Model: %s", args.model)
        logger.info("  Input Text: %s", args.text)
        try:
            wav_bytes, res = synthesize_with_voice(
                api_key=key,
                text=args.text,
                voice_id=target_voice_id,
                model=args.model,
                output_wav_path=args.output
            )
            logger.info("Synthesis Succeeded! Audio payload size: %d bytes.", len(wav_bytes))
            print("----------------------------------------------------------")
            print(f"SUCCESS: Custom voice synthesis completed using {target_voice_id}.")
            print(f"Output File: {os.path.abspath(args.output)}")
            print("----------------------------------------------------------")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error("Synthesis failed: HTTP %d - %s", e.code, err_body)
            sys.exit(1)


if __name__ == "__main__":
    main()
