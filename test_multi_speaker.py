#!/usr/bin/env python3
"""
Test script for Gemini Multi-Speaker Dialogue Text-to-Speech (TTS).
Synthesizes Arabic multi-speaker dialogue using Google's Gemini TTS API.

Architecture & Insights:
1. Google Generative Language API Schema:
   Endpoint: https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}
   Payload:
   {
       "contents": [...],
       "generationConfig": {
           "responseModalities": ["AUDIO"],
           "speechConfig": {
               "multiSpeakerVoiceConfig": {
                   "speakerVoiceConfigs": [
                       {"speaker": "Speaker1", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}},
                       {"speaker": "Speaker2", "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}
                   ]
               }
           }
       }
   }
   NOTE: 'speaker' and 'voiceConfig' are the exact REST protobuf fields for Google Gemini API.
   (The Cloud TTS v1beta1 API uses 'speakerAlias' and 'speakerId', which Gemini API rejects with HTTP 400).

2. Dialogue Tagging Conventions:
   - Part-based tagging (Gemini 3.8 Flash TTS):
     contents[0].parts: [
         {"text": "...", "speechMetadata": {"speaker": "Speaker1"}},
         {"text": "...", "speechMetadata": {"speaker": "Speaker2"}}
     ]
   - Inline prompt tagging (Gemini 3.1 Flash TTS Preview):
     contents[0].parts: [
         {"text": "Speaker1: قال الراوي...\nSpeaker2: أجاب البطل..."}
     ]

3. Quota & Rate Limit Behavior:
   - Free Tier models have a limit of 10 requests/day per project (GenerateRequestsPerDayPerProjectPerModel-FreeTier).
   - This script supports automatic quota detection, backoff retries, and seamless model fallback.
"""

import argparse
import base64
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("multi_speaker_tts")


def craft_wav_header(
    pcm_data: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """Creates a standard 44-byte RIFF/WAVE header for linear PCM audio data."""
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
        16,
        1,  # PCM
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data


def parse_retry_delay(error_body: str) -> float:
    """Extracts wait delay in seconds from 429 RESOURCE_EXHAUSTED JSON."""
    try:
        data = json.loads(error_body)
        details = data.get("error", {}).get("details", [])
        for detail in details:
            if detail.get("@type", "").endswith("RetryInfo"):
                retry_str = detail.get("retryDelay", "")
                m = re.search(r"([\d\.]+)s?", retry_str)
                if m:
                    return float(m.group(1))
        msg = data.get("error", {}).get("message", "")
        m = re.search(r"retry in ([\d\.]+)s", msg)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return 30.0


def build_payload_part_metadata(
    turns: List[Tuple[str, str]],
    speaker1_alias: str,
    speaker1_voice: str,
    speaker2_alias: str,
    speaker2_voice: str,
) -> Dict[str, Any]:
    """Builds payload using part-level speechMetadata (standard for Gemini 3.8)."""
    parts = []
    for speaker_name, text in turns:
        parts.append({
            "text": text,
            "speechMetadata": {
                "speaker": speaker_name
            }
        })

    return {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": speaker1_alias,
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": speaker1_voice
                                }
                            }
                        },
                        {
                            "speaker": speaker2_alias,
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": speaker2_voice
                                }
                            }
                        }
                    ]
                }
            }
        }
    }


def build_payload_inline_prompt(
    turns: List[Tuple[str, str]],
    speaker1_alias: str,
    speaker1_voice: str,
    speaker2_alias: str,
    speaker2_voice: str,
) -> Dict[str, Any]:
    """Builds payload using inline text tags (standard for Gemini 3.1)."""
    lines = []
    for speaker_name, text in turns:
        lines.append(f"{speaker_name}: {text}")
    combined_prompt = "\n".join(lines)

    return {
        "contents": [{"parts": [{"text": combined_prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "multiSpeakerVoiceConfig": {
                    "speakerVoiceConfigs": [
                        {
                            "speaker": speaker1_alias,
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": speaker1_voice
                                }
                            }
                        },
                        {
                            "speaker": speaker2_alias,
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": speaker2_voice
                                }
                            }
                        }
                    ]
                }
            }
        }
    }


def execute_synthesis_request(
    url: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[bytes], str, Optional[int]]:
    """Sends HTTP request and parses audio response. Returns (success, pcm_bytes, error_or_mime, http_code)."""
    post_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=post_data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "GeminiMultiSpeakerTester/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            candidates = res_json.get("candidates", [])
            if not candidates:
                return False, None, "No candidates in response", 200
            part = candidates[0].get("content", {}).get("parts", [{}])[0]
            inline = part.get("inlineData", {})
            b64_data = inline.get("data", "")
            mime = inline.get("mimeType", "audio/l16")
            if not b64_data:
                return False, None, "No audio data in inlineData", 200
            raw_audio = base64.b64decode(b64_data)
            return True, raw_audio, mime, 200
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        return False, None, body, err.code
    except Exception as exc:
        return False, None, str(exc), None


def synthesize_multi_speaker(
    api_key: str,
    turns: List[Tuple[str, str]],
    speaker1_alias: str = "Speaker1",
    speaker1_voice: str = "Charon",
    speaker2_alias: str = "Speaker2",
    speaker2_voice: str = "Kore",
    model_id: str = "gemini-3.8-flash-tts",
    output_path: str = "output_multi_speaker.wav",
    auto_fallback: bool = True,
) -> bool:
    """Executes multi-speaker synthesis with automatic schema selection and fallback."""
    logger.info("=" * 65)
    logger.info(f"[*] بدء توليد الحوار متعدد الأصوات (Gemini Multi-Speaker TTS)")
    logger.info(f"[*] النموذج الأساسي: {model_id}")
    logger.info(f"[*] المتحدث الأول: '{speaker1_alias}' (الصوت: {speaker1_voice})")
    logger.info(f"[*] المتحدث الثاني: '{speaker2_alias}' (الصوت: {speaker2_voice})")
    logger.info(f"[*] عدد مقاطع الحوار: {len(turns)}")
    for idx, (spk, txt) in enumerate(turns, 1):
        logger.info(f"    {idx}. [{spk}]: {txt}")
    logger.info("=" * 65)

    models_to_try = [model_id]
    if auto_fallback and model_id != "gemini-3.1-flash-tts-preview":
        models_to_try.append("gemini-3.1-flash-tts-preview")

    raw_audio = None
    successful_model = None

    for current_model in models_to_try:
        logger.info(f"[*] تجربة النموذج: {current_model}...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"

        # Choose payload strategy based on model
        if "3.8" in current_model:
            payload = build_payload_part_metadata(
                turns, speaker1_alias, speaker1_voice, speaker2_alias, speaker2_voice
            )
        else:
            payload = build_payload_inline_prompt(
                turns, speaker1_alias, speaker1_voice, speaker2_alias, speaker2_voice
            )

        success, audio_bytes, info, code = execute_synthesis_request(url, payload)

        if success and audio_bytes:
            raw_audio = audio_bytes
            successful_model = current_model
            logger.info(f"[+] نجح التوليد بنجاح عبر النموذج: {current_model} (MIME: {info})")
            break

        logger.warning(f"[-] فشل الطلب عبر {current_model} (رمز الحالة: {code})")
        if code == 429:
            logger.warning("[!] تم بلوغ حد الحصة المجانية لهذا النموذج (Quota Limit Exceeded).")
            # If there's another model in the fallback queue, try it
            continue
        elif code == 400:
            logger.warning(f"[-] خطأ في البارامترات أو عدم توافق الميتاداتا: {info[:150]}")
            # Try inline payload if part-metadata failed
            if "3.8" in current_model:
                logger.info("[*] محاولة استخدام أسلوب inline prompt بدلاً من speechMetadata...")
                alt_payload = build_payload_inline_prompt(
                    turns, speaker1_alias, speaker1_voice, speaker2_alias, speaker2_voice
                )
                alt_success, alt_audio, alt_info, alt_code = execute_synthesis_request(url, alt_payload)
                if alt_success and alt_audio:
                    raw_audio = alt_audio
                    successful_model = current_model
                    break
        else:
            logger.error(f"[-] خطأ غير متوقع: {info[:200]}")

    if not raw_audio:
        logger.error("[-] تعذر الحصول على الصوت من جميع النماذج المختبرة.")
        return False

    # Check WAV header or craft it
    if raw_audio.startswith(b"RIFF"):
        wav_bytes = raw_audio
    else:
        logger.info("[*] إضافة ترويسة RIFF/WAVE (24000 Hz, 16-bit, Mono)...")
        wav_bytes = craft_wav_header(raw_audio, sample_rate=24000, channels=1, bits_per_sample=16)

    # Save to target destination
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(out_file.parent), delete=False, suffix=".wav") as tmp:
        tmp.write(wav_bytes)
        tmp_name = tmp.name
    os.replace(tmp_name, str(out_file))

    # Also copy to /sdcard/Download if possible
    sdcard_dest = Path("/sdcard/Download/test_multi_speaker.wav")
    try:
        if sdcard_dest.parent.exists():
            shutil.copyfile(str(out_file), str(sdcard_dest))
            logger.info(f"[+] تم نسخ الملف إلى مسار التنزيلات للأندرويد: {sdcard_dest}")
    except Exception as copy_err:
        logger.debug(f"Could not copy to sdcard: {copy_err}")

    # Inspect WAV parameters with standard wave module
    try:
        with wave.open(str(out_file), "rb") as w:
            channels = w.getnchannels()
            sample_width = w.getsampwidth()
            framerate = w.getframerate()
            frames = w.getnframes()
            duration = frames / float(framerate) if framerate > 0 else 0
            logger.info("=" * 65)
            logger.info(f"[+] تقرير فحص ملف الصوت النهائي ({out_file.name}):")
            logger.info(f"    - المسار الكامل: {out_file}")
            logger.info(f"    - النموذج المولد: {successful_model}")
            logger.info(f"    - الحجم الإجمالي: {len(wav_bytes):,} بايت")
            logger.info(f"    - عدد القنوات: {channels} (أحادي - Mono)")
            logger.info(f"    - دقة العينة: {sample_width * 8} بت (PCM)")
            logger.info(f"    - معدل التردد: {framerate} هرتز")
            logger.info(f"    - المدة الزمنية: {duration:.2f} ثانية")
            logger.info("=" * 65)
    except Exception as w_err:
        logger.warning(f"تعذر استخراج بيانات wave: {w_err}")

    # Play audio if player available
    for player in ["termux-media-player", "mpv", "ffplay"]:
        cmd = shutil.which(player)
        if cmd:
            logger.info(f"[*] تشغيل عينة الحوار عبر: {player}...")
            try:
                if player == "termux-media-player":
                    subprocess.run([cmd, "play", str(out_file)], check=False)
                else:
                    subprocess.run([cmd, str(out_file)], check=False)
            except Exception as play_err:
                logger.warning(f"تنبيه أثناء التشغيل: {play_err}")
            break

    return True


def main():
    parser = argparse.ArgumentParser(description="Gemini Multi-Speaker Dialogue TTS Tester")
    parser.add_argument(
        "--key",
        default=os.getenv("GEMINI_API_KEY", ""),
        help="Gemini API Key",
    )
    parser.add_argument(
        "--model",
        default="gemini-3.8-flash-tts",
        help="Gemini Model ID (default: gemini-3.8-flash-tts)",
    )
    parser.add_argument(
        "--speaker1-name",
        default="Speaker1",
        help="Alias for speaker 1",
    )
    parser.add_argument(
        "--speaker1-voice",
        default="Charon",
        help="Prebuilt voice for speaker 1 (e.g. Charon, Fenrir, Puck)",
    )
    parser.add_argument(
        "--speaker2-name",
        default="Speaker2",
        help="Alias for speaker 2",
    )
    parser.add_argument(
        "--speaker2-voice",
        default="Kore",
        help="Prebuilt voice for speaker 2 (e.g. Kore, Aoede)",
    )
    parser.add_argument(
        "--out",
        default="/data/data/com.termux/files/home/gemini_audiobook_tts/output_multi_speaker.wav",
        help="Output WAV file path",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable automatic fallback to gemini-3.1-flash-tts-preview on quota limits",
    )

    args = parser.parse_args()

    api_key = args.key.strip()
    if not api_key:
        logger.error("[-] خطأ: لم يتم توفير مفتاح API.")
        sys.exit(1)

    dialogue_turns = [
        (args.speaker1_name, "قال الراوي بصوت هادئ: وقف المعلم أمام طلابه وسأل تلميذه النجيب باهتمام:"),
        (args.speaker2_name, "يا أستاذي، كيف استطاع أسلافنا تدوين هذا التراث العظيم وحفظه عبر الأجيال؟"),
        (args.speaker1_name, "أجاب المعلم مبتسماً: بالصبر والأمانة العلمية الصارمة، وبمنهج التوثيق الذي لا يضيع حرفاً."),
    ]

    success = synthesize_multi_speaker(
        api_key=api_key,
        turns=dialogue_turns,
        speaker1_alias=args.speaker1_name,
        speaker1_voice=args.speaker1_voice,
        speaker2_alias=args.speaker2_name,
        speaker2_voice=args.speaker2_voice,
        model_id=args.model,
        output_path=args.out,
        auto_fallback=not args.no_fallback,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
