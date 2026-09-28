#!/usr/bin/env python3
"""
Comprehensive Test Suite for Gemini Audiobook TTS Engine.
Tests smart chunking, markdown stripping, book parsing, WAV header generation,
Base64 audio decoding, and full end-to-end audiobook compilation.
"""

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


if __name__ == "__main__":
    unittest.main()
