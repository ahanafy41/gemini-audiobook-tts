#!/usr/bin/env python3
"""
Comprehensive Test Suite for Gemini Audiobook TTS Engine.
Tests smart chunking, markdown stripping, book parsing, WAV header generation,
Base64 audio decoding, and full end-to-end audiobook compilation.
"""

from key_quota_manager import (
    KeyQuotaManager,
    compute_key_id,
    mask_key,
    parse_retry_delay_from_error,
    get_model_daily_cap,
)

import json
import logging
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from book_parser import BookParser, ParsedBook
from gemini_audiobook_engine import AudiobookEngine
from gemini_tts_client import GeminiTtsClient
from markdown_stripper import CleanedChapter, MarkdownStripper
from smart_chunker import SmartTextChunker

logger = logging.getLogger("TestEngine")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class TestSmartChunker(unittest.TestCase):
    """Unit tests for SmartTextChunker."""

    def setUp(self) -> None:
        self.chunker = SmartTextChunker(max_chunk_size=100)

    def test_arabic_sentence_splitting(self) -> None:
        text = "هذا هو السطر الأول. هل فهمت المغزى؟ بالتأكيد! وهذا أمر رائع؛ سنواصل التقدم."
        sentences = self.chunker.split_into_sentences(text)
        self.assertGreaterEqual(len(sentences), 3)
        self.assertTrue(any("؟" in s for s in sentences))
        self.assertTrue(any("!" in s for s in sentences))

    def test_strict_chunk_size_adherence(self) -> None:
        long_paragraph = "قال الراوي إن الرحلة كانت طويلة وشاقة وممتلئة بالأسرار الغامضة. " * 30
        chunks = self.chunker.chunk_text(long_paragraph, max_chunk_size=200)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 200)

    def test_zero_broken_words(self) -> None:
        arabic_text = "كلمةأولى كلمةثانية كلمةثالثة كلمةرابعة كلمةخامسة كلمةسادسة"
        chunks = self.chunker.chunk_text(arabic_text, max_chunk_size=30)
        for chunk in chunks:
            words = chunk.split()
            for w in words:
                self.assertIn(w, arabic_text)


class TestMarkdownStripper(unittest.TestCase):
    """Unit tests for MarkdownStripper."""

    def setUp(self) -> None:
        self.stripper = MarkdownStripper()

    def test_formatting_cleanup(self) -> None:
        raw_md = "**نص عريض** مع *نص مائل* ورابط [اضغط هنا](https://example.com) وصورة ![غلاف](cover.png)."
        cleaned = self.stripper.clean_markdown_text(raw_md)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("https://example.com", cleaned)
        self.assertNotIn("![", cleaned)
        self.assertIn("نص عريض", cleaned)
        self.assertIn("اضغط هنا", cleaned)

    def test_pause_injection_for_code_and_rules(self) -> None:
        raw_md = "فقرة أولى.\n\n```python\nprint('hello')\n```\n\n---\n\nفقرة ثانية."
        cleaned = self.stripper.clean_markdown_text(raw_md)
        self.assertIn("<short pause>", cleaned)

    def test_diacritics_preservation(self) -> None:
        tashkeel_text = "قالَ الرَّجُلُ: السَّلَامُ عَلَيْكُمْ وَرَحْمَةُ اللَّهِ."
        cleaned = self.stripper.clean_markdown_text(tashkeel_text)
        self.assertIn("الرَّجُلُ", cleaned)
        self.assertIn("السَّلَامُ", cleaned)

    def test_chapter_extraction_from_headings(self) -> None:
        doc = (
            "# الفصل الأول: البداية\n"
            "هذه هي البداية المشوقة.\n\n"
            "## الفصل الثاني: المغامرة\n"
            "وهنا تبدأ المغامرة الحقيقية.\n"
        )
        chapters = self.stripper.extract_chapters(doc)
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[0].chapter_title, "الفصل الأول: البداية")
        self.assertEqual(chapters[1].chapter_title, "الفصل الثاني: المغامرة")


class TestBookParser(unittest.TestCase):
    """Unit tests for BookParser."""

    def setUp(self) -> None:
        self.parser = BookParser(continuous_chapter_size=500)

    def test_plain_text_arabic_chapters(self) -> None:
        plain_book = (
            "الفصل الأول: نشأة البطل\n"
            "ولد البطل في قرية هادئة تحيط بها الجبال.\n\n"
            "الفصل الثاني: رحلة البحث\n"
            "انطلق البطل في رحلته بحثاً عن الحقيقة.\n"
        )
        parsed: ParsedBook = self.parser.parse_content(plain_book, filename="رحلة البطل")
        self.assertEqual(len(parsed.chapters), 2)
        self.assertIn("الفصل الأول", parsed.chapters[0].chapter_title)
        self.assertIn("الفصل الثاني", parsed.chapters[1].chapter_title)

    def test_continuous_novel_segmentation(self) -> None:
        continuous_text = "كان ياما كان في قديم الزمان وفي سالف العصر والأوان.\n\n" * 30
        parsed = self.parser.parse_content(continuous_text, filename="رواية طويلة")
        self.assertGreater(len(parsed.chapters), 1)
        self.assertIn("الجزء 1", parsed.chapters[0].chapter_title)


class TestGeminiTtsClient(unittest.TestCase):
    """Unit tests for GeminiTtsClient and audio decoding."""

    def setUp(self) -> None:
        self.client = GeminiTtsClient(mock_mode=True)

    def test_wav_header_structure(self) -> None:
        dummy_pcm = b"\x00\x00" * 2400  # 0.1s at 24000Hz mono 16-bit
        wav_bytes = self.client.create_wav_header(dummy_pcm, sample_rate=24000, channels=1, bits_per_sample=16)

        self.assertTrue(wav_bytes.startswith(b"RIFF"))
        self.assertEqual(wav_bytes[8:12], b"WAVE")
        self.assertEqual(wav_bytes[12:16], b"fmt ")

        # Sample rate at byte 24
        sample_rate = struct.unpack_from("<I", wav_bytes, 24)[0]
        self.assertEqual(sample_rate, 24000)

        # Total file length matches
        total_size = len(wav_bytes)
        riff_size = struct.unpack_from("<I", wav_bytes, 4)[0]
        self.assertEqual(riff_size, total_size - 8)

    def test_mock_audio_synthesis(self) -> None:
        audio = self.client.synthesize("مرحباً بكم في الكتاب الصوتي.")
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertGreater(len(audio), 44)

    def test_response_audio_extraction(self) -> None:
        import base64
        synthetic_payload = b"RIFFfakeaudiodata"
        encoded = base64.b64encode(synthetic_payload).decode("ascii")

        # Test schema 1: audioContent
        resp1 = {"audioContent": encoded}
        extracted1 = self.client._extract_audio_bytes(resp1)
        self.assertEqual(extracted1, synthetic_payload)

        # Test schema 2: candidates inlineData
        resp2 = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"data": encoded, "mimeType": "audio/wav"}}
                        ]
                    }
                }
            ]
        }
        extracted2 = self.client._extract_audio_bytes(resp2)
        self.assertEqual(extracted2, synthetic_payload)


class TestAudiobookEngineIntegration(unittest.TestCase):
    """End-to-end integration tests for AudiobookEngine."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="audiobook_test_"))
        self.tts_client = GeminiTtsClient(mock_mode=True)
        self.engine = AudiobookEngine(
            output_dir=self.temp_dir,
            tts_client=self.tts_client,
            chunk_size=200,
        )

    def tearDown(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_book_processing(self) -> None:
        sample_book = self.temp_dir / "sample_book.md"
        sample_book_content = (
            "# الباب الأول: مقدمة في علوم التاريخ\n\n"
            "التاريخ هو ذاكرة الأمم وسجل تطور الحضارات الإنسانية عبر العصور.\n\n"
            "# الباب الثاني: الحضارة المصرية القديمة\n\n"
            "قامت الحضارة المصرية على ضفاف النيل الخالد تاركة إرثاً معمارياً وفكرياً مبهراً.\n"
        )
        sample_book.write_text(sample_book_content, encoding="utf-8")

        manifest = self.engine.process_book(sample_book)

        # Verify output manifest
        self.assertEqual(manifest["total_chapters"], 2)
        self.assertGreater(manifest["total_duration_seconds"], 0)
        self.assertTrue((self.temp_dir / "playlist.m3u").exists())
        self.assertTrue((self.temp_dir / "book_manifest.json").exists())

        # Verify generated chapter files
        chapter1_path = self.temp_dir / "chapters" / "chapter_001.wav"
        chapter2_path = self.temp_dir / "chapters" / "chapter_002.wav"
        self.assertTrue(chapter1_path.exists())
        self.assertTrue(chapter2_path.exists())
        self.assertGreater(chapter1_path.stat().st_size, 44)

        # Verify resume capability: running again should not fail and reuse progress
        manifest_resume = self.engine.process_book(sample_book)
        self.assertEqual(manifest_resume["total_chapters"], 2)

    def test_adaptive_chunking_and_unformatted_text(self) -> None:
        from smart_chunker import get_adaptive_chunk_limits

        limits_38 = get_adaptive_chunk_limits("gemini-3.8-flash-tts")
        self.assertEqual(limits_38["target"], 8000)
        self.assertEqual(limits_38["max_window"], 8500)

        limits_legacy = get_adaptive_chunk_limits("gemini-3.1-flash-tts-preview")
        self.assertEqual(limits_legacy["target"], 2000)
        self.assertEqual(limits_legacy["max_window"], 2300)

        chunker_legacy = SmartTextChunker(model_id="gemini-3.1-flash-tts-preview")
        raw_unpunctuated = " ".join(["كلمة"] * 900)
        chunks = chunker_legacy.chunk_text(raw_unpunctuated)
        self.assertGreater(len(chunks), 1)
        for ch in chunks:
            self.assertLessEqual(len(ch), 2300)

    def test_docx_extraction_and_dialogue_annotator(self) -> None:
        import zipfile
        from gemini_tts_client import DialogueTurnAnnotator

        docx_path = self.temp_dir / "sample_story.docx"
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>الفصل الأول: البداية</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>همس الرجل بصوت خافت: «لا تقترب من الباب! (تنهيدة)»</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        with zipfile.ZipFile(docx_path, "w") as zf:
            zf.writestr("word/document.xml", xml_content.encode("utf-8"))

        parser = BookParser()
        parsed_book = parser.parse_file(docx_path)
        self.assertGreaterEqual(len(parsed_book.chapters), 1)
        self.assertIn("الباب", parsed_book.chapters[0].text)

        turns = DialogueTurnAnnotator.extract_turns(
            "همس الرجل بصوت خافت: «لا تقترب من الباب! (تنهيدة)»"
        )
        self.assertGreaterEqual(len(turns), 2)
        dialogue_turn = [t for t in turns if t["speaker"] == "Speaker2"][0]
        self.assertIn("whisper", dialogue_turn["style"])
        self.assertIn("<sigh>", dialogue_turn["text"])

    def test_multi_key_rotation_and_model_commitment(self) -> None:
        client = GeminiTtsClient(
            api_keys=["key_one", "key_two"],
            model_id="gemini-3.8-flash-tts",
            mock_mode=True,
        )
        self.assertEqual(client.get_model_daily_limit("gemini-3.8-flash-tts"), 100)
        self.assertEqual(client.get_model_daily_limit("gemini-3.1-flash-tts-preview"), 10)
        self.assertEqual(client.get_active_api_key(), "key_one")
        rotated = client._rotate_to_next_key(reason="unit_test")
        self.assertTrue(rotated)
        self.assertEqual(client.get_active_api_key(), "key_two")
        rotated_end = client._rotate_to_next_key(reason="unit_test_exhausted")
        self.assertFalse(rotated_end)
        self.assertEqual(client.model_id, "gemini-3.8-flash-tts")


class TestUniversalMultilingualDialogue(unittest.TestCase):
    """Tests universal structural dialogue detection across multiple world languages."""

    def test_arabic_dashed_dialogue(self) -> None:
        from gemini_tts_client import DialogueTurnAnnotator
        text = "وقف الضابط أمام الباب ثم سأل:\n- هل أنتِ ليلى؟\nقال أبي مدافعاً:\n- نعم، هذه ابنتي."
        turns = DialogueTurnAnnotator.extract_turns(text)
        spk2 = [t for t in turns if t["speaker"] == "Speaker2"]
        self.assertEqual(len(spk2), 2)
        self.assertIn("هل أنتِ ليلى؟", spk2[0]["text"])
        self.assertIn("نعم، هذه ابنتي.", spk2[1]["text"])

    def test_french_dashed_dialogue(self) -> None:
        from gemini_tts_client import DialogueTurnAnnotator
        text = "Pierre regarda la mer avec tristesse.\n— Bonjour mon ami, — dit-il doucement.\n— Comment vas-tu ?"
        turns = DialogueTurnAnnotator.extract_turns(text)
        spk2 = [t for t in turns if t["speaker"] == "Speaker2"]
        self.assertGreaterEqual(len(spk2), 1)
        self.assertIn("Bonjour mon ami", spk2[0]["text"])

    def test_english_em_dash_dialogue(self) -> None:
        from gemini_tts_client import DialogueTurnAnnotator
        text = "The inspector stepped into the room.\n— Where were you last night? — asked the detective.\n— I was at home, — replied John."
        turns = DialogueTurnAnnotator.extract_turns(text)
        spk2 = [t for t in turns if t["speaker"] == "Speaker2"]
        self.assertGreaterEqual(len(spk2), 2)
        self.assertIn("Where were you", spk2[0]["text"])
        self.assertIn("I was at home", spk2[1]["text"])

    def test_german_quoted_dialogue(self) -> None:
        from gemini_tts_client import DialogueTurnAnnotator
        text = "Der alte Mann stand am Fenster.\n„Guten Tag!“, sagte er leise."
        turns = DialogueTurnAnnotator.extract_turns(text)
        spk2 = [t for t in turns if t["speaker"] == "Speaker2"]
        self.assertEqual(len(spk2), 1)
        self.assertIn("Guten Tag!", spk2[0]["text"])

    def test_japanese_bracket_dialogue(self) -> None:
        from gemini_tts_client import DialogueTurnAnnotator
        text = "田中さんはドアを開けた。\n「こんにちは」と田中さんは笑顔で言いました。"
        turns = DialogueTurnAnnotator.extract_turns(text)
        spk2 = [t for t in turns if t["speaker"] == "Speaker2"]
        self.assertEqual(len(spk2), 1)
        self.assertIn("こんにちは", spk2[0]["text"])




class TestKeyQuotaManager(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="quota_test_")
        self.quota_file = Path(self.tmp_dir) / "test_key_quotas.json"
        self.manager = KeyQuotaManager(self.quota_file)
        self.key1 = "AIzaSyKey111111111111111111111111"
        self.key2 = "AIzaSyKey222222222222222222222222"
        self.key3 = "AIzaSyKey333333333333333333333333"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_key_identification_and_masking(self) -> None:
        key_id = compute_key_id(self.key1)
        self.assertEqual(len(key_id), 16)
        masked = mask_key(self.key1)
        self.assertTrue(masked.startswith("AIzaSy..."))
        self.assertTrue(masked.endswith("1111"))

    def test_parse_retry_delay_from_error(self) -> None:
        # 1. JSON RetryInfo
        json_err = '{"error": {"code": 429, "message": "RESOURCE_EXHAUSTED", "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1800s"}]}}'
        self.assertEqual(parse_retry_delay_from_error(json_err), 1800)

        # 2. Text regex: Xh Ym Zs
        text_err1 = "Quota exceeded. Please retry in 4h 15m 30s."
        self.assertEqual(parse_retry_delay_from_error(text_err1), 4 * 3600 + 15 * 60 + 30)

        # 3. Text regex: Xm Ys
        text_err2 = "Limit reached. Retry in 10m 20s."
        self.assertEqual(parse_retry_delay_from_error(text_err2), 10 * 60 + 20)

        # 4. Text regex: Xs
        text_err3 = "RESOURCE_EXHAUSTED. Retry after 45s."
        self.assertEqual(parse_retry_delay_from_error(text_err3), 45)

    def test_quota_exhaustion_and_auto_renewal(self) -> None:
        model = "gemini-3.8-flash-tts"
        self.assertTrue(self.manager.is_key_available(self.key1, model))

        # Record 429 with 1 hour delay
        self.manager.record_429_exhaustion(self.key1, model, retry_delay_seconds=3600)
        self.assertFalse(self.manager.is_key_available(self.key1, model))

        info = self.manager.get_key_status_info(self.key1, model)
        self.assertEqual(info["status"], "EXHAUSTED")
        self.assertGreater(info["seconds_until_reset"], 0)

        # Simulate renewal in the past
        self.manager.record_429_exhaustion(self.key1, model, retry_delay_seconds=-5)
        self.assertTrue(self.manager.is_key_available(self.key1, model))
        info_renewed = self.manager.get_key_status_info(self.key1, model)
        self.assertEqual(info_renewed["status"], "AVAILABLE")
        self.assertEqual(info_renewed["requests_today"], 0)

    def test_model_quota_isolation(self) -> None:
        # Exhaust on 3.8
        self.manager.record_429_exhaustion(self.key1, "gemini-3.8-flash-tts", retry_delay_seconds=3600)
        self.assertFalse(self.manager.is_key_available(self.key1, "gemini-3.8-flash-tts"))

        # Should remain completely available on legacy models (separate Google quotas)
        self.assertTrue(self.manager.is_key_available(self.key1, "gemini-2.5-flash-preview-tts"))
        self.assertTrue(self.manager.is_key_available(self.key1, "gemini-3.1-flash-tts-preview"))

    def test_key_selection_and_skipping(self) -> None:
        model = "gemini-3.8-flash-tts"
        keys = [self.key1, self.key2, self.key3]

        # Exhaust key 1 and key 2
        self.manager.record_429_exhaustion(self.key1, model, retry_delay_seconds=3600)
        self.manager.record_429_exhaustion(self.key2, model, retry_delay_seconds=7200)

        # Automatically picks key 3 (index 2)
        first_idx = self.manager.find_first_available_key_index(keys, model)
        self.assertEqual(first_idx, 2)

        # If searching from index 0, skips index 1 and returns index 2
        next_idx, next_key = self.manager.get_next_available_key(keys, 0, model)
        self.assertEqual(next_idx, 2)
        self.assertEqual(next_key, self.key3)

    def test_atomic_persistence(self) -> None:
        model = "gemini-3.8-flash-tts"
        self.manager.record_429_exhaustion(self.key1, model, retry_delay_seconds=5000)

        # Create a fresh manager instance reading the same file
        fresh_mgr = KeyQuotaManager(self.quota_file)
        self.assertFalse(fresh_mgr.is_key_available(self.key1, model))
        info = fresh_mgr.get_key_status_info(self.key1, model)
        self.assertEqual(info["status"], "EXHAUSTED")

    def test_worker_skips_exhausted_key_on_startup(self) -> None:
        from desktop.worker import SynthesisWorker
        model = "gemini-3.8-flash-tts"
        # Mark key1 exhausted
        self.manager.record_429_exhaustion(self.key1, model, retry_delay_seconds=3600)

        worker = SynthesisWorker(
            book_text="نص تجريبي لاختبار المفاتيح.",
            book_title="كتاب_تجريبي",
            output_dir=self.tmp_dir,
            api_keys=[self.key1, self.key2],
            model_id=model,
            mock_mode=True,
            quota_manager=self.manager,
        )
        # Advance selection as worker does on start
        first_ready = worker.quota_manager.find_first_available_key_index(
            worker.api_keys,
            worker.model_id,
            preferred_index=worker.active_key_index,
        )
        self.assertEqual(first_ready, 1)  # Skipped key1 (index 0), picked key2 (index 1)


if __name__ == "__main__":
    unittest.main()

