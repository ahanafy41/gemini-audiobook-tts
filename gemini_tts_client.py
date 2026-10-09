#!/usr/bin/env python3
"""
Gemini TTS Client for Gemini Audiobook TTS.
Handles communication with the Gemini 3.8 Flash TTS REST API via standard library
(urllib.request & json), parses speech metadata, handles audio decoding,
and crafts valid WAV headers for raw PCM output.
"""

import base64
import json
import logging
import math
import os
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("GeminiTtsClient")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class GeminiTtsClient:
    """
    Client for synthesizing speech via Google's Gemini TTS models (gemini-3.8-flash-tts).
    Requires no third-party dependencies, leveraging pure Python standard libraries.
    """

    DEFAULT_MODEL_ID = "gemini-3.8-flash-tts"
    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = DEFAULT_MODEL_ID,
        custom_endpoint: Optional[str] = None,
        max_retries: int = 3,
        mock_mode: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.model_id = model_id or self.DEFAULT_MODEL_ID
        self.custom_endpoint = custom_endpoint
        self.max_retries = max_retries
        self.mock_mode = mock_mode or (not self.api_key)

        if self.mock_mode:
            logger.info("GeminiTtsClient initialized in MOCK mode (synthetic audio generation).")
        else:
            logger.info("GeminiTtsClient initialized for model %s.", self.model_id)

    @staticmethod
    def create_wav_header(
        pcm_data: bytes,
        sample_rate: int = 24000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> bytes:
        """
        Creates a standard 44-byte RIFF/WAVE header for linear PCM audio data.
        """
        byte_rate = sample_rate * channels * (bits_per_sample // 8)
        block_align = channels * (bits_per_sample // 8)
        data_size = len(pcm_data)
        file_size = 36 + data_size

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            file_size,
            b"WAVE",
            b"fmt ",
            16,               # Subchunk1Size for PCM
            1,                # AudioFormat 1 = Linear PCM
            channels,         # NumChannels
            sample_rate,      # SampleRate
            byte_rate,        # ByteRate
            block_align,      # BlockAlign
            bits_per_sample,  # BitsPerSample
            b"data",
            data_size,
        )
        return header + pcm_data

    @staticmethod
    def generate_synthetic_wav(
        duration_seconds: float = 1.0,
        frequency_hz: float = 440.0,
        sample_rate: int = 24000,
    ) -> bytes:
        """
        Generates a valid, playable synthetic sine-wave WAV file.
        Used for offline testing, dry-runs, and diagnostic self-checks.
        """
        total_samples = int(duration_seconds * sample_rate)
        amplitude = 12000
        pcm_chunks = []

        for i in range(total_samples):
            envelope = math.sin(math.pi * i / total_samples)
            sample_val = int(
                amplitude * envelope * math.sin(2.0 * math.pi * frequency_hz * (i / sample_rate))
            )
            pcm_chunks.append(struct.pack("<h", max(-32768, min(32767, sample_val))))

        raw_pcm = b"".join(pcm_chunks)
        return GeminiTtsClient.create_wav_header(raw_pcm, sample_rate=sample_rate)

    def _build_payload(
        self,
        text: str,
        voice_name: str,
        style: str,
    ) -> Dict[str, Any]:
        """
        Constructs the structured JSON request payload for gemini-3.8-flash-tts.
        """
        is_custom_voice = voice_name.startswith("voice_") or voice_name.startswith("voices/")
        clean_voice_id = voice_name.replace("voices/", "")
        if is_custom_voice:
            voice_config = {"voice": clean_voice_id}
        else:
            voice_config = {
                "prebuilt_voice_config": {
                    "voice_name": voice_name
                }
            }

        return {
            "model": self.model_id,
            "input": text,
            "generation_config": {
                "speech_config": {
                    "voice_config": voice_config
                }
            },
            "speech_metadata": {
                "style": style
            },
        }

    def _extract_audio_bytes(self, response_data: Dict[str, Any]) -> bytes:
        """
        Extracts and Base64-decodes audio bytes from diverse Google API response schemas.
        """
        # Format 1: Direct audioContent field (Google Cloud / TTS standard)
        if "audioContent" in response_data and response_data["audioContent"]:
            return base64.b64decode(response_data["audioContent"])

        # Format 2: Direct audio field
        if "audio" in response_data and response_data["audio"]:
            return base64.b64decode(response_data["audio"])

        # Format 3: Gemini contents / candidates payload
        candidates = response_data.get("candidates", [])
        if candidates and isinstance(candidates, list):
            first_candidate = candidates[0]
            content = first_candidate.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                if "inlineData" in part and "data" in part["inlineData"]:
                    return base64.b64decode(part["inlineData"]["data"])
                if "audioData" in part and "data" in part["audioData"]:
                    return base64.b64decode(part["audioData"]["data"])

        # Format 4: Fallback output field
        if "output" in response_data and isinstance(response_data["output"], str):
            try:
                return base64.b64decode(response_data["output"])
            except Exception:
                pass

        raise ValueError(f"Unable to locate Base64 audio in response payload: {list(response_data.keys())}")

    def synthesize(
        self,
        text: str,
        voice_name: str = "Kore",
        style: str = "narrator, clear pronunciation and natural pacing",
    ) -> bytes:
        """
        Synthesizes the given text to playable WAV audio bytes.
        """
        clean_text = text.strip()
        if not clean_text:
            return self.generate_synthetic_wav(duration_seconds=0.1)

        if self.mock_mode:
            logger.info("Synthesizing mock audio for text segment (%d chars)...", len(clean_text))
            # Calculate mock duration relative to text length (~15 chars per second)
            simulated_duration = max(0.5, min(10.0, len(clean_text) / 15.0))
            return self.generate_synthetic_wav(duration_seconds=simulated_duration)

        endpoint = self.custom_endpoint
        if not endpoint:
            endpoint = f"{self.BASE_API_URL}/{self.model_id}:generateAudio?key={self.api_key}"

        payload = self._build_payload(clean_text, voice_name=voice_name, style=style)
        post_data = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "GeminiAudiobookEngine/1.0",
        }

        req = urllib.request.Request(endpoint, data=post_data, headers=headers, method="POST")

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Sending TTS request (attempt %d/%d, length %d chars)...",
                    attempt,
                    self.max_retries,
                    len(clean_text),
                )
                with urllib.request.urlopen(req, timeout=60) as response:
                    raw_response = response.read().decode("utf-8")
                    json_resp = json.loads(raw_response)
                    decoded_bytes = self._extract_audio_bytes(json_resp)

                    # Ensure standard WAV container
                    if decoded_bytes.startswith(b"RIFF"):
                        return decoded_bytes
                    return self.create_wav_header(decoded_bytes, sample_rate=24000)

            except urllib.error.HTTPError as err:
                error_body = ""
                try:
                    error_body = err.read().decode("utf-8", errors="ignore")
                except Exception:
                    pass

                logger.warning(
                    "HTTP Error %d on attempt %d: %s. Body: %s",
                    err.code,
                    attempt,
                    err.reason,
                    error_body[:300],
                )
                last_error = err

                if err.code in (429, 500, 502, 503, 504):
                    backoff = attempt * 2.5
                    time.sleep(backoff)
                    continue
                else:
                    break

            except Exception as exc:
                logger.warning("Network exception on attempt %d: %s", attempt, str(exc))
                last_error = exc
                time.sleep(attempt * 2.0)

        logger.error("Synthesis failed after %d attempts. Falling back to synthetic audio.", self.max_retries)
        if last_error:
            logger.error("Last error was: %s", str(last_error))

        return self.generate_synthetic_wav(duration_seconds=1.0)

    @staticmethod
    def atomic_save_audio(file_path: Union[str, Path], audio_bytes: bytes) -> None:
        """
        Saves audio bytes atomically to disk to prevent partial/corrupted files.
        """
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_file = target.with_suffix(target.suffix + f".tmp_{os.getpid()}_{int(time.time()*1000)}")
        temp_file.write_bytes(audio_bytes)
        temp_file.replace(target)
        logger.info("Saved audio file atomically to: %s (%d bytes)", target, len(audio_bytes))
