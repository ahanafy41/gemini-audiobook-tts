#!/usr/bin/env python3
"""
Comprehensive Book Parser for Gemini Audiobook TTS.
Handles parsing of .md and .txt files, automatically detecting Arabic and English
chapters, or partitioning continuous novels into balanced spoken chapters.
"""

import dataclasses
import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Union

from markdown_stripper import CleanedChapter, MarkdownStripper

logger = logging.getLogger("BookParser")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclasses.dataclass
class ParsedBook:
    """Represents a fully ingested book with structural metadata and chapters."""
    title: str
    file_path: str
    total_characters: int
    chapters: List[CleanedChapter]


class BookParser:
    """
    Ingests text and markdown books and decomposes them into speech-ready chapters.
    """

    ARABIC_ORDINAL_MAP = {
        "الأول": "1", "الاول": "1",
        "الثاني": "2", "الثالث": "3", "الرابع": "4", "الخامس": "5",
        "السادس": "6", "السابع": "7", "الثامن": "8", "التاسع": "9",
        "العاشر": "10", "الحادي عشر": "11", "الثاني عشر": "12",
        "الثالث عشر": "13", "الرابع عشر": "14", "الخامس عشر": "15",
    }

    ARABIC_CHAPTER_PATTERNS = [
        re.compile(
            r"^\s*(الفصل|الباب|الجزء|المبحث|المطلب|القسم)\s+([^\n:–—\-]+)[:–—\-\s]*(.*?)$",
            re.MULTILINE,
        ),
        re.compile(
            r"^\s*(مقدمة|تمهيد|فاتحة الكتاب|مدخل|توطئة|خاتمة|خلاصة)\s*$",
            re.MULTILINE,
        ),
        re.compile(
            r"^\s*(Chapter|Section|Part|Book)\s+([0-9IVXLCDMivxlcdm]+)[:–—\-\s]*(.*?)$",
            re.MULTILINE | re.IGNORECASE,
        ),
    ]

    CONTINUOUS_CHUNK_SIZE: int = 15000  # Default ~2,500 words per spoken chapter

    def __init__(self, continuous_chapter_size: int = CONTINUOUS_CHUNK_SIZE) -> None:
        self.continuous_chapter_size = max(100, continuous_chapter_size)
        self.markdown_stripper = MarkdownStripper()

    @staticmethod
    def read_file_safe(file_path: Union[str, Path]) -> str:
        """Reads a file trying multiple text encodings."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Book file does not exist: {file_path}")

        encodings = ["utf-8", "utf-8-sig", "cp1256", "iso-8859-6", "latin1"]
        raw_bytes = path.read_bytes()

        for enc in encodings:
            try:
                return raw_bytes.decode(enc)
            except UnicodeDecodeError:
                continue

        return raw_bytes.decode("utf-8", errors="replace")

    def parse_file(self, file_path: Union[str, Path]) -> ParsedBook:
        """
        Parses a book from disk (.md or .txt), returning a ParsedBook structure.
        """
        path = Path(file_path)
        content = self.read_file_safe(path)
        book_title = path.stem.replace("_", " ").strip()

        return self.parse_content(content, filename=book_title, file_path=str(path.resolve()))

    def parse_content(self, content: str, filename: str = "Audiobook", file_path: str = "") -> ParsedBook:
        """
        Analyzes and segments raw content into chapters.
        """
        text = content.strip()
        if not text:
            return ParsedBook(
                title=filename,
                file_path=file_path,
                total_characters=0,
                chapters=[],
            )

        # 1. If Markdown headings are present, prioritize Markdown parsing
        if re.search(r"^#{1,6}\s+.+", text, re.MULTILINE):
            logger.info("Markdown headers detected. Using Markdown chapter extraction.")
            chapters = self.markdown_stripper.extract_chapters(text)
            return ParsedBook(
                title=filename,
                file_path=file_path,
                total_characters=len(text),
                chapters=chapters,
            )

        # 2. Plain Text: Scan for Arabic & English chapter headings
        matches = []
        for pattern in self.ARABIC_CHAPTER_PATTERNS:
            for m in pattern.finditer(text):
                matches.append((m.start(), m.end(), m.group(0).strip()))

        matches.sort(key=lambda x: x[0])

        # Filter overlapping or very close duplicate matches
        filtered_matches = []
        last_end = -1
        for start, end, match_text in matches:
            if start >= last_end:
                filtered_matches.append((start, end, match_text))
                last_end = end

        if len(filtered_matches) >= 2:
            logger.info("Detected %d chapter headings in plain text.", len(filtered_matches))
            chapters: List[CleanedChapter] = []

            # Preface before first chapter
            if filtered_matches[0][0] > 0:
                preface = text[: filtered_matches[0][0]].strip()
                if preface:
                    clean_pref = self.markdown_stripper.clean_markdown_text(preface)
                    chapters.append(
                        CleanedChapter(
                            chapter_title="مقدمة",
                            level=1,
                            text=f"مقدمة. <short pause>\n\n{clean_pref}",
                            raw_length=len(preface),
                        )
                    )

            for i, (start, end, title) in enumerate(filtered_matches):
                next_start = filtered_matches[i + 1][0] if (i + 1 < len(filtered_matches)) else len(text)
                body = text[end:next_start].strip()
                clean_body = self.markdown_stripper.clean_markdown_text(body)
                title_clean = title.strip()
                spoken = f"{title_clean}. <short pause>\n\n{clean_body}" if clean_body else title_clean

                chapters.append(
                    CleanedChapter(
                        chapter_title=title_clean,
                        level=1,
                        text=spoken,
                        raw_length=(next_start - start),
                    )
                )

            return ParsedBook(
                title=filename,
                file_path=file_path,
                total_characters=len(text),
                chapters=chapters,
            )

        # 3. Continuous Novel / Unstructured Text: Balanced segmentation
        logger.info(
            "No structural chapter headings detected. Segmenting continuous novel (target size: %d chars).",
            self.continuous_chapter_size,
        )
        chapters = self._segment_continuous_text(text)

        return ParsedBook(
            title=filename,
            file_path=file_path,
            total_characters=len(text),
            chapters=chapters,
        )

    def _segment_continuous_text(self, text: str) -> List[CleanedChapter]:
        """
        Segments long continuous prose at natural paragraph or sentence boundaries
        into balanced listening segments.
        """
        paragraphs = text.split("\n\n")
        chapters: List[CleanedChapter] = []
        current_paragraphs: List[str] = []
        current_len = 0
        chapter_index = 1

        for para in paragraphs:
            clean_para = para.strip()
            if not clean_para:
                continue

            if current_len + len(clean_para) <= self.continuous_chapter_size or not current_paragraphs:
                current_paragraphs.append(clean_para)
                current_len += len(clean_para)
            else:
                body = "\n\n".join(current_paragraphs)
                cleaned = self.markdown_stripper.clean_markdown_text(body)
                title = f"الجزء {chapter_index}"
                spoken = f"{title}. <short pause>\n\n{cleaned}"
                chapters.append(
                    CleanedChapter(
                        chapter_title=title,
                        level=1,
                        text=spoken,
                        raw_length=current_len,
                    )
                )
                chapter_index += 1
                current_paragraphs = [clean_para]
                current_len = len(clean_para)

        if current_paragraphs:
            body = "\n\n".join(current_paragraphs)
            cleaned = self.markdown_stripper.clean_markdown_text(body)
            title = f"الجزء {chapter_index}" if chapters else "الكتاب كاملاً"
            spoken = f"{title}. <short pause>\n\n{cleaned}"
            chapters.append(
                CleanedChapter(
                    chapter_title=title,
                    level=1,
                    text=spoken,
                    raw_length=current_len,
                )
            )

        return chapters
