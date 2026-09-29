#!/usr/bin/env python3
"""
Test Voice Styles & Prebuilt Voices Catalog for Gemini 3.8 Flash TTS.

Demonstrates and evaluates:
1. 3 Distinct Audiobook Styles (Documentary, Dramatic Novel, Calm Sleep) in Arabic.
2. Official Gemini TTS Prebuilt Voices Roster (30 Astronomical/Mythological Voices).
3. Acoustic Steering via Structured Director Prompts and Inline Tags ([short pause], [gasp], <short pause>).
4. Automated Model Fallback (gemini-3.8-flash-tts -> gemini-3.8-flash-lite-tts) & Quota/Rate Limit Handling.
"""

import argparse
import base64
import json
import logging
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VoiceStyleTester")

# ---------------------------------------------------------------------------
# Complete Catalog of 30 Prebuilt Gemini Voices
# ---------------------------------------------------------------------------
PREBUILT_VOICES_CATALOG: Dict[str, Dict[str, str]] = {
    "Puck": {
        "character": "Upbeat, lively, energetic",
        "gender": "Male",
        "pitch_tone": "Mid-high pitch, vibrant, expressive resonance",
        "best_genre": "Children's literature, young adult fiction, fast-paced dialogue",
    },
    "Charon": {
        "character": "Informative, authoritative, solemn, grave",
        "gender": "Male",
        "pitch_tone": "Deep baritone/bass, steady cadence, rich resonance",
        "best_genre": "Historical chronicles, documentary, serious non-fiction, biographies",
    },
    "Kore": {
        "character": "Firm, clear, confident, poised",
        "gender": "Female",
        "pitch_tone": "Balanced alto, articulated, crisp diction",
        "best_genre": "Literary novels, investigative journalism, mainstream audiobooks",
    },
    "Fenrir": {
        "character": "Excitable, intense, dramatic, dynamic",
        "gender": "Male",
        "pitch_tone": "Dynamic tenor, variable pitch, urgent emotional energy",
        "best_genre": "Action thrillers, battle scenes, dramatic climaxes, fantasy",
    },
    "Aoede": {
        "character": "Breezy, natural, melodious, warm",
        "gender": "Female",
        "pitch_tone": "Warm soprano, fluid pacing, engaging and approachable",
        "best_genre": "Memoirs, travelogues, romance, conversational non-fiction",
    },
    "Zephyr": {
        "character": "Bright, light, calming, serene",
        "gender": "Female",
        "pitch_tone": "Soft soprano, soothing airflow, relaxed pacing",
        "best_genre": "Bedtime stories, guided meditations, mindfulness, poetry",
    },
    "Leda": {
        "character": "Youthful, cheerful, bright",
        "gender": "Female",
        "pitch_tone": "High-mid pitch, enthusiastic, sparkling cadence",
        "best_genre": "Children's books, cheerful narratives, lighthearted comedy",
    },
    "Orus": {
        "character": "Firm, calm, grounded, deliberate",
        "gender": "Male",
        "pitch_tone": "Mid-low baritone, stable pacing, reassuring presence",
        "best_genre": "Educational philosophy, scientific essays, stoic biographies",
    },
    "Achernar": {
        "character": "Soft, gentle, whisper-like",
        "gender": "Female",
        "pitch_tone": "Low-volume soprano, delicate breath support, quiet delivery",
        "best_genre": "Sleep stories, lullabies, introspective personal diaries",
    },
    "Achird": {
        "character": "Friendly, approachable, casual",
        "gender": "Male",
        "pitch_tone": "Natural conversational baritone, friendly smile in voice",
        "best_genre": "Podcasts, self-help, how-to audio guides",
    },
    "Algenib": {
        "character": "Gravelly, gritty, weathered",
        "gender": "Male",
        "pitch_tone": "Deep raspy bass, textured timbre",
        "best_genre": "Noir detective fiction, veteran soldier memoirs, dark fantasy",
    },
    "Algieba": {
        "character": "Smooth, lyrical, rhythmic",
        "gender": "Female",
        "pitch_tone": "Silky alto, fluid phrasing, poetic cadence",
        "best_genre": "Arabic poetry (شعر عربي), classical prose, epic drama",
    },
    "Alnilam": {
        "character": "Firm, direct, decisive",
        "gender": "Male",
        "pitch_tone": "Authoritative mid-baritone, strong consonants",
        "best_genre": "Military history, investigative journalism, politics",
    },
    "Autonoe": {
        "character": "Bright, vivacious, energetic",
        "gender": "Female",
        "pitch_tone": "Lively soprano, upward inflections",
        "best_genre": "Youth adventures, fantasy, upbeat storytelling",
    },
    "Callirrhoe": {
        "character": "Easy-going, relaxed, unhurried",
        "gender": "Female",
        "pitch_tone": "Warm mezzo, laid-back cadence",
        "best_genre": "Casual storytelling, lifestyle essays, road trip narratives",
    },
    "Despina": {
        "character": "Smooth, polished, refined",
        "gender": "Female",
        "pitch_tone": "Elegant alto, velvety finish",
        "best_genre": "High literature, art history, classical mythology",
    },
    "Enceladus": {
        "character": "Breathy, intimate, nocturnal",
        "gender": "Male",
        "pitch_tone": "Subdued baritone with airiness, close-mic effect",
        "best_genre": "Deep relaxation, sleep hypnosis, late-night radio style",
    },
    "Erinome": {
        "character": "Clear, precise, articulate",
        "gender": "Female",
        "pitch_tone": "Neutral alto, crystalline diction",
        "best_genre": "Academic lectures, science textbooks, encyclopedias",
    },
    "Gacrux": {
        "character": "Mature, elder, dignified",
        "gender": "Male",
        "pitch_tone": "Aged deep baritone, slow dignified gravity",
        "best_genre": "Wise mentor dialogue, ancient historical sagas, folklore",
    },
    "Iapetus": {
        "character": "Clear, objective, crisp",
        "gender": "Male",
        "pitch_tone": "Neutral mid-baritone, clean projection",
        "best_genre": "Science fiction, technical documentaries, analytical books",
    },
    "Laomedeia": {
        "character": "Upbeat, musical, vibrant",
        "gender": "Female",
        "pitch_tone": "Melodic soprano, expressive dynamic range",
        "best_genre": "Musical memoirs, whimsical adventures, children's fables",
    },
    "Pulcherrima": {
        "character": "Forward, assertive, modern",
        "gender": "Female",
        "pitch_tone": "Confident mid-pitch, crisp contemporary presence",
        "best_genre": "Modern thrillers, corporate bios, tech innovators",
    },
    "Rasalgethi": {
        "character": "Informative, methodical, steady",
        "gender": "Male",
        "pitch_tone": "Measured baritone, instructional cadence",
        "best_genre": "Documentary narration, historical chronicles",
    },
    "Sadachbia": {
        "character": "Lively, curious, animated",
        "gender": "Female",
        "pitch_tone": "Engaging mezzo-soprano, enthusiastic rhythm",
        "best_genre": "Young adult adventures, popular science, explorations",
    },
    "Sadaltager": {
        "character": "Knowledgeable, professorial, scholarly",
        "gender": "Male",
        "pitch_tone": "Warm academic baritone, thoughtful pacing",
        "best_genre": "History of science, scholarly treatises, philosophical texts",
    },
    "Schedar": {
        "character": "Even, balanced, neutral",
        "gender": "Male",
        "pitch_tone": "Neutral baritone, transparent delivery without bias",
        "best_genre": "News reporting, unbiased historical archives",
    },
    "Sulafat": {
        "character": "Warm, empathetic, deeply comforting",
        "gender": "Female",
        "pitch_tone": "Gentle mezzo, emotional resonance and depth",
        "best_genre": "Psychological drama, emotional biographies, spiritual essays",
    },
    "Umbriel": {
        "character": "Easy-going, comfortable, companionable",
        "gender": "Male",
        "pitch_tone": "Warm conversational tenor, casual rhythm",
        "best_genre": "Travel memoirs, casual storytelling, humor",
    },
    "Vindemiatrix": {
        "character": "Gentle, nurturing, serene",
        "gender": "Female",
        "pitch_tone": "Soft soothing alto, gentle round tone",
        "best_genre": "Parenting, bedtime stories, meditation, cozy mysteries",
    },
    "Zubenelgenubi": {
        "character": "Casual, modern, relaxed",
        "gender": "Male",
        "pitch_tone": "Everyday casual baritone, relatable cadence",
        "best_genre": "Contemporary fiction, conversational humor, modern essays",
    }
}

# ---------------------------------------------------------------------------
# 3 Distinct Delivery Styles Specification for Arabic Audiobooks
# ---------------------------------------------------------------------------
STYLE_SPECIFICATIONS: Dict[str, Dict[str, Any]] = {
    "documentary": {
        "name_ar": "الوثائقي التاريخي الرصين (Solemn Historical Documentary)",
        "recommended_voice": "Charon",
        "alternative_voices": ["Orus", "Alnilam", "Rasalgethi"],
        "director_prompt": "[Style: Authoritative, solemn historical documentary narration, grave baritone, deliberate and measured cadence]",
        "arabic_text": (
            "[Style: Authoritative, solemn historical documentary narration, grave baritone, deliberate and measured cadence]\n"
            "في قلبِ القاهرةِ الفاطمية، [short pause] يقفُ الجامعُ الأزهرُ شامخاً منذ أكثرَ من ألفِ عام، "
            "شاهداً على تحولاتِ الفكرِ وعراقةِ الحضارةِ الإسلامية."
        ),
        "description": "نبرة وقورة وجادة تناسب كتب التاريخ والسير والتراث والوثائقيات، مع وقفات محسوبة لإبراز ثقل الكلمات."
    },
    "dramatic": {
        "name_ar": "الرواية الدرامية والتشويق (Dramatic Novel & Suspense)",
        "recommended_voice": "Fenrir",
        "alternative_voices": ["Kore", "Puck", "Pulcherrima"],
        "director_prompt": "[Style: Dramatic, cinematic, intense suspense, breathless anticipation and emotional charge]",
        "arabic_text": (
            "[Style: Dramatic, cinematic, intense suspense, breathless anticipation and emotional charge]\n"
            "دقّت ساعةُ منتصفِ الليل! [gasp] التفتَ حاملاً السراج، فرأى ظلاً طويلاً يتحركُ بخفةٍ نحو البابِ المغلق، "
            "<short pause> وحبس أنفاسَه مترقباً المجهول."
        ),
        "description": "نبرة سينمائية مشدودة ومليئة بالحيوية والترقب، تدمج بين الوقفات ولحظات المفاجأة [gasp] لنقل المشاعر المتصاعدة."
    },
    "calm_sleep": {
        "name_ar": "الهدوء والسكينة والنوم (Calm Sleep & Meditation)",
        "recommended_voice": "Zephyr",
        "alternative_voices": ["Achernar", "Aoede", "Vindemiatrix", "Enceladus"],
        "director_prompt": "[Style: Whispering, gentle bedtime story, deeply relaxing, slow peaceful pacing]",
        "arabic_text": (
            "[Style: Whispering, gentle bedtime story, deeply relaxing, slow peaceful pacing]\n"
            "أغمض عينيكَ بهدوءٍ وسكينة... [short pause] اترك همومَ اليومِ تتلاشى بعيداً خلفَ الأفق، "
            "واستسلم لدفءِ الليلِ وهدوءِ الراحةِ التامة."
        ),
        "description": "نبرة هامسة هادئة وإيقاع متمهل ومريح، يزيل التوتر ويساعد على النوم والاسترخاء والتأمل العميق."
    }
}

# ---------------------------------------------------------------------------
# Audio Processing Utilities
# ---------------------------------------------------------------------------
def craft_wav_header(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Creates a standard 44-byte RIFF/WAVE header for linear PCM audio."""
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

def inspect_wav_bytes(audio_bytes: bytes) -> Dict[str, Any]:
    """Inspects header, sample rate, channels, and calculates duration."""
    if not audio_bytes.startswith(b"RIFF") or len(audio_bytes) < 44:
        # Raw PCM fallback
        duration = len(audio_bytes) / 48000.0  # 24kHz * 16bit mono = 48000 B/s
        return {"sample_rate": 24000, "channels": 1, "duration_sec": round(duration, 2), "is_riff": False}

    try:
        audio_format, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack("<HHIIHH", audio_bytes[20:36])
        data_idx = audio_bytes.find(b"data")
        if data_idx != -1 and len(audio_bytes) >= data_idx + 8:
            data_size = struct.unpack("<I", audio_bytes[data_idx+4:data_idx+8])[0]
        else:
            data_size = len(audio_bytes) - 44
        duration = (data_size / byte_rate) if byte_rate > 0 else (data_size / 48000.0)
        return {
            "sample_rate": sample_rate,
            "channels": channels,
            "bits_per_sample": bits_per_sample,
            "duration_sec": round(duration, 2),
            "is_riff": True,
            "bytes_total": len(audio_bytes)
        }
    except Exception:
        duration = len(audio_bytes) / 48000.0
        return {"sample_rate": 24000, "channels": 1, "duration_sec": round(duration, 2), "is_riff": True}

# ---------------------------------------------------------------------------
# TTS API Client with Intelligent Cascading & Rate Limiting
# ---------------------------------------------------------------------------
class GeminiVoiceTester:
    DEFAULT_MODELS_CASCADE = [
        "gemini-3.8-flash-tts",
        "gemini-3.8-flash-lite-tts"
    ]

    def __init__(self, api_key: str, primary_model: str = "gemini-3.8-flash-tts", delay_seconds: float = 21.0):
        self.api_key = api_key
        self.models = [primary_model] + [m for m in self.DEFAULT_MODELS_CASCADE if m != primary_model]
        self.delay_seconds = delay_seconds
        self.last_request_time = 0.0

    def _wait_for_rate_limit(self, extra_wait: float = 0.0) -> None:
        """Ensures compliance with Gemini Free Tier 3 RPM limit (~20s between calls)."""
        elapsed = time.time() - self.last_request_time
        target_wait = max(self.delay_seconds, extra_wait)
        if elapsed < target_wait:
            sleep_needed = target_wait - elapsed
            logger.info("Pacing request: sleeping %.1f seconds to respect API rate limits...", sleep_needed)
            time.sleep(sleep_needed)

    def synthesize(self, text: str, voice_name: str, force_model: Optional[str] = None) -> Tuple[bytes, str, Dict[str, Any]]:
        """
        Synthesizes text using available models in cascade.
        Returns: (wav_bytes, model_used, audio_meta)
        """
        models_to_try = [force_model] if force_model else list(self.models)
        last_error = None

        for model in models_to_try:
            self._wait_for_rate_limit()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": text}]}],
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
                headers={"Content-Type": "application/json", "User-Agent": "GeminiVoiceStyleTester/1.0"},
                method="POST"
            )

            try:
                logger.info("Calling Gemini TTS [model=%s, voice=%s]...", model, voice_name)
                with urllib.request.urlopen(req, timeout=45) as resp:
                    self.last_request_time = time.time()
                    res_json = json.loads(resp.read().decode("utf-8"))
                    candidates = res_json.get("candidates", [])
                    if not candidates:
                        raise ValueError("No candidates returned in API response")
                    
                    part = candidates[0].get("content", {}).get("parts", [{}])[0]
                    inline_data = part.get("inlineData", {})
                    b64_data = inline_data.get("data", "")
                    if not b64_data:
                        raise ValueError(f"No audio inlineData found in candidate part: {part}")
                    
                    raw_audio = base64.b64decode(b64_data)
                    wav_bytes = raw_audio if raw_audio.startswith(b"RIFF") else craft_wav_header(raw_audio, 24000)
                    meta = inspect_wav_bytes(wav_bytes)
                    logger.info("Successfully synthesized audio: %d bytes (~%.2fs duration)", len(wav_bytes), meta["duration_sec"])
                    return wav_bytes, model, meta

            except urllib.error.HTTPError as err:
                self.last_request_time = time.time()
                body = err.read().decode("utf-8", errors="ignore")
                last_error = f"HTTP {err.code}: {body[:250]}"
                
                # Check for rate limit retry-delay
                retry_delay = 0.0
                retry_match = re.search(r'retryDelay["\']?:\s*["\']?(\d+)', body)
                if retry_match:
                    retry_delay = float(retry_match.group(1)) + 2.0

                if err.code == 429:
                    logger.warning("Model %s returned HTTP 429 (Quota/Rate limit). Reason: %s", model, body[:150])
                    # If this is a daily quota (e.g. gemini-3.8-flash-tts 10 RPD), cascade immediately
                    if "PerDay" in body:
                        logger.info("Daily quota exhausted for %s. Cascading to fallback model...", model)
                        continue
                    # If this is a per-minute rate limit (e.g. gemini-3.8-flash-lite-tts 3 RPM), back off and retry
                    wait_time = max(retry_delay, 25.0)
                    logger.info("Rate limit (per-minute) requires %.1fs backoff. Waiting and retrying on %s...", wait_time, model)
                    self._wait_for_rate_limit(extra_wait=wait_time)
                    return self.synthesize(text, voice_name, force_model=model)
                elif err.code in (400, 404):
                    logger.error("Model %s returned HTTP %d: %s", model, err.code, body[:200])
                    continue
                else:
                    logger.warning("Model %s error HTTP %d: %s", model, err.code, body[:150])
                    continue

            except Exception as exc:
                self.last_request_time = time.time()
                last_error = str(exc)
                logger.warning("Network error on %s: %s", model, exc)
                continue

        raise RuntimeError(f"All TTS models failed. Last error: {last_error}")

# ---------------------------------------------------------------------------
# Runner & File Saving
# ---------------------------------------------------------------------------
def run_voice_style_tests(
    api_key: str,
    output_dir: str,
    styles: Optional[List[str]] = None,
    voices_to_test: Optional[List[str]] = None,
    delay: float = 21.0
) -> List[Dict[str, Any]]:
    """Runs tests for selected styles and voices, saving audio files and returning manifest."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    tester = GeminiVoiceTester(api_key=api_key, delay_seconds=delay)
    
    results = []
    styles = styles or ["documentary", "dramatic", "calm_sleep"]

    print("=================================================================")
    print("  GEMINI 3.8 FLASH TTS: VOICE STYLES & EMOTION EVALUATION")
    print(f"  Target Output Directory: {out_path.resolve()}")
    print(f"  Styles to test: {', '.join(styles)}")
    print("=================================================================\n")

    # Step 1: Test the 3 distinct styles
    for style_key in styles:
        if style_key not in STYLE_SPECIFICATIONS:
            logger.warning("Skipping unknown style: %s", style_key)
            continue
        
        spec = STYLE_SPECIFICATIONS[style_key]
        voice = spec["recommended_voice"]
        print(f"\n---> Testing Style: [{style_key.upper()}] - {spec['name_ar']}")
        print(f"     Voice: {voice} ({PREBUILT_VOICES_CATALOG.get(voice, {}).get('pitch_tone', 'N/A')})")
        print(f"     Director Prompt: {spec['director_prompt']}")

        target_file = out_path / f"style_{style_key}_{voice.lower()}.wav"
        try:
            wav_bytes, model_used, meta = tester.synthesize(text=spec["arabic_text"], voice_name=voice)
            target_file.write_bytes(wav_bytes)
            print(f"  [+] Saved: {target_file.name} ({len(wav_bytes):,} bytes, ~{meta['duration_sec']}s, model={model_used})")
            results.append({
                "category": "style_clip",
                "style": style_key,
                "voice": voice,
                "file_path": str(target_file.resolve()),
                "file_size": len(wav_bytes),
                "duration_sec": meta["duration_sec"],
                "model_used": model_used,
                "status": "SUCCESS"
            })
        except Exception as exc:
            logger.error("Failed to generate style [%s] with voice [%s]: %s", style_key, voice, exc)
            results.append({
                "category": "style_clip",
                "style": style_key,
                "voice": voice,
                "error": str(exc),
                "status": "FAILED"
            })

    # Step 2: Test specific additional voices if requested
    if voices_to_test:
        print("\n=================================================================")
        print(f"  Testing Additional Prebuilt Voices ({len(voices_to_test)} voices)...")
        print("=================================================================")
        for voice in voices_to_test:
            if voice not in PREBUILT_VOICES_CATALOG:
                logger.warning("Voice %s is not in standard catalog, testing anyway...", voice)
            
            sample_text = (
                f"[Style: Clear natural storytelling, pleasant cadence]\n"
                f"أهلاً بك يا أحمد. أنا الصوت {voice} في نظام جيمني الصوتي الحديث."
            )
            target_file = out_path / f"voice_sample_{voice.lower()}.wav"
            print(f"\n---> Generating voice clip: [{voice}]")
            try:
                wav_bytes, model_used, meta = tester.synthesize(text=sample_text, voice_name=voice)
                target_file.write_bytes(wav_bytes)
                print(f"  [+] Saved: {target_file.name} ({len(wav_bytes):,} bytes, ~{meta['duration_sec']}s)")
                results.append({
                    "category": "voice_sample",
                    "voice": voice,
                    "file_path": str(target_file.resolve()),
                    "file_size": len(wav_bytes),
                    "duration_sec": meta["duration_sec"],
                    "model_used": model_used,
                    "status": "SUCCESS"
                })
            except Exception as exc:
                logger.error("Failed to generate sample for voice [%s]: %s", voice, exc)
                results.append({
                    "category": "voice_sample",
                    "voice": voice,
                    "error": str(exc),
                    "status": "FAILED"
                })

    # Save test manifest
    manifest_file = out_path / "test_results_manifest.json"
    manifest_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] Testing completed. Test results manifest written to: {manifest_file.resolve()}")
    return results

# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gemini 3.8 Flash TTS Voice Styles & Emotion Tester")
    parser.add_argument("--key", default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API Key")
    parser.add_argument("--out-dir", default="/data/data/com.termux/files/home/gemini_audiobook_tts/output_sample/voice_styles", help="Output directory for audio files")
    parser.add_argument("--styles", nargs="+", choices=["documentary", "dramatic", "calm_sleep"], default=["documentary", "dramatic", "calm_sleep"], help="Styles to generate")
    parser.add_argument("--voices", nargs="+", help="Specific prebuilt voices to test")
    parser.add_argument("--all-voices", action="store_true", help="Test all 30 prebuilt voices (takes ~10-15 mins due to rate limits)")
    parser.add_argument("--delay", type=float, default=21.0, help="Seconds between API calls (default: 21.0 to fit 3 RPM)")

    args = parser.parse_args()
    api_key = args.key.strip()
    if not api_key:
        print("[-] Error: Gemini API key must be provided via --key or GEMINI_API_KEY env var.")
        sys.exit(1)

    voices_list = None
    if args.all_voices:
        voices_list = list(PREBUILT_VOICES_CATALOG.keys())
    elif args.voices:
        voices_list = args.voices

    run_voice_style_tests(
        api_key=api_key,
        output_dir=args.out_dir,
        styles=args.styles,
        voices_to_test=voices_list,
        delay=args.delay
    )
