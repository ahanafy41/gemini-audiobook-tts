#!/usr/bin/env python3
"""
CLI Doctor & API Tester for Gemini Audiobook TTS.
Tests Gemini API audio generation, inspects responses, and verifies local TTS.
Engine architecture references: GeminiTtsClient, LocalTtsEngine, getVoices, setVoice, generateContent.
"""

import argparse
import base64
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("test_api")

def craft_wav_header(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
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

def test_gemini_audio(api_key: str, model_id: str = "gemini-2.0-flash", voice_name: str = "Kore", output_path: str = "test_output.wav") -> bool:
    logger.info(f"[*] اختبار توليد الصوت عبر Gemini ({model_id} - صوت: {voice_name})...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": "مرحباً يا أحمد. هذا اختبار نجاح توليد الصوت بالذكاء الاصطناعي عبر جيمني."}]
        }],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name
                    }
                }
            }
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "GeminiAudiobookTester/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            candidates = res_json.get("candidates", [])
            if not candidates:
                logger.error("[-] خطأ: الاستجابة لم ترجع أي مرشحات (candidates).")
                logger.error(f"الاستجابة: {json.dumps(res_json, ensure_ascii=False, indent=2)}")
                return False
            
            part = candidates[0].get("content", {}).get("parts", [{}])[0]
            inline_data = part.get("inlineData", {})
            b64_data = inline_data.get("data", "")
            mime_type = inline_data.get("mimeType", "audio/wav")
            
            if not b64_data:
                logger.error("[-] خطأ: لم يتم العثور على بيانات الصوت في inlineData.")
                logger.error(f"محتوى الـ part: {part}")
                return False
                
            raw_audio = base64.b64decode(b64_data)
            wav_bytes = raw_audio if raw_audio.startswith(b"RIFF") else craft_wav_header(raw_audio, 24000)
            
            out_file = Path(output_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(out_file.parent), prefix="tmp_audio_")
            with os.fdopen(tmp_fd, "wb") as f:
                f.write(wav_bytes)
            os.replace(tmp_path, str(out_file))
            logger.info(f"[+] نجح الاختبار! تم استلام الصوت ({len(wav_bytes)} بايت، {mime_type}).")
            logger.info(f"[+] تم حفظ الملف في: {out_file.resolve()}")
            
            # محاولة التشغيل في ترمكس
            player = shutil.which("mpv") or shutil.which("termux-media-player") or shutil.which("ffplay")
            if player:
                logger.info(f"[*] تشغيل الصوت للاستماع عبر: {player}...")
                subprocess.run([player, str(out_file)], check=False)
            return True
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        logger.error(f"[-] خطأ HTTP {err.code}: {err.reason}")
        logger.error(f"تفاصيل الخطأ من جوجل: {body}")
        return False
    except Exception as exc:
        logger.error(f"[-] خطأ غير متوقع: {str(exc)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini TTS API Tester")
    parser.add_argument("--key", default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API Key")
    parser.add_argument("--voice", default="Kore", help="Gemini voice name (e.g. Kore, Puck, Charon, Fenrir, Aoede)")
    parser.add_argument("--model", default="gemini-2.0-flash", help="Gemini model ID")
    parser.add_argument("--out", default="/sdcard/Download/test_gemini_voice.wav", help="Output WAV path")
    args = parser.parse_args()
    
    key = args.key.strip()
    if not key:
        logger.warning("[-] تنبيه: لم يتم تمرير مفتاح API.")
        logger.warning("يمكنك تشغيل الاختبار بمفتاحك هكذا:")
        logger.warning("  python3 test_api.py --key AIzaSy...")
        sys.exit(1)
        
    success = test_gemini_audio(key, model_id=args.model, voice_name=args.voice, output_path=args.out)
    sys.exit(0 if success else 1)
