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
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import List, Optional, Union

from markdown_stripper import CleanedChapter, MarkdownStripper
from smart_chunker import SmartTextChunker

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
    Ingests .txt, .md, and .docx books and decomposes them into speech-ready chapters.
    """

    WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    ARABIC_ORDINAL_MAP = {
        "الأول": "1", "الاول": "1",
        "الثاني": "2", "الثالث": "3", "الرابع": "4", "الخامس": "5",
        "السادس": "6", "السابع": "7", "الثامن": "8", "التاسع": "9",
        "العاشر": "10", "الحادي عشر": "11", "الثاني عشر": "12",
        "الثالث عشر": "13", "الرابع عشر": "14", "الخامس عشر": "15",
    }

    ARABIC_CHAPTER_PATTERNS = [
        re.compile(
            r"^[ \t]*(الفصل|الباب|الجزء|القسم|المبحث|المطلب|الكتاب)\s+([^\r\n:–—\-]+)[:–—\-]?[ \t]*(.*?)$",
            re.MULTILINE,
        ),
        re.compile(
            r"^[ \t]*(مقدمة|تمهيد|فاتحة الكتاب|مدخل|توطئة)[:–—\-]?[ \t]*(.*?)$",
            re.MULTILINE,
        ),
        re.compile(
            r"^[ \t]*(خاتمة|الخاتمة|خلاصة)[:–—\-]?[ \t]*(.*?)$",
            re.MULTILINE,
        ),
        re.compile(
            r"^[ \t]*(Chapter|Section|Part|Book|Volume|Act|Scene)\s+([0-9IVXLCDMivxlcdm]+)[:–—\-]?[ \t]*(.*?)$",
            re.MULTILINE | re.IGNORECASE,
        ),
        re.compile(
            r"^[ \t]*([0-9]{1,3}|[IVXLCDM]{1,8})[.:–—\-][ \t]+([^\r\n]{1,60})$",
            re.MULTILINE,
        ),
    ]

    CONTINUOUS_CHUNK_SIZE: int = 15000  # Default ~2,500 words per spoken chapter

    def __init__(self, continuous_chapter_size: int = CONTINUOUS_CHUNK_SIZE) -> None:
        self.continuous_chapter_size = max(100, continuous_chapter_size)
        self.markdown_stripper = MarkdownStripper()
        self.chunker = SmartTextChunker(max_chunk_size=self.continuous_chapter_size)

    @classmethod
    def extract_docx_text(cls, file_path: Union[str, Path]) -> str:
        """
        Extracts text from a Microsoft Word (.docx) file.
        Attempts python-docx if installed, and uses native zipfile + xml.etree.ElementTree
        as a zero-dependency standard-library parser.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"[BookParser] فشل فتح ملف وورد: الملف غير موجود في المسار '{file_path}'. "
                f"الإجراء: تأكد من صحة مسار الملف."
            )

        # Try python-docx first if available
        try:
            import docx  # type: ignore
            doc = docx.Document(str(path))
            paragraphs: List[str] = []
            for p in doc.paragraphs:
                txt = (p.text or "").strip()
                if txt:
                    style_name = getattr(getattr(p, "style", None), "name", "") or ""
                    if style_name.lower().startswith("heading"):
                        level_match = re.search(r"(\d+)", style_name)
                        lvl = int(level_match.group(1)) if level_match else 1
                        lvl = max(1, min(6, lvl))
                        paragraphs.append(f"{'#' * lvl} {txt}")
                    else:
                        paragraphs.append(txt)
            if paragraphs:
                return "\n\n".join(paragraphs)
        except Exception:
            pass

        # Native zero-dependency OpenXML extraction via zipfile + ElementTree
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "word/document.xml" not in zf.namelist():
                    raise ValueError("Archive does not contain 'word/document.xml'.")
                xml_bytes = zf.read("word/document.xml")
        except Exception as exc:
            raise ValueError(
                f"[BookParser] تعذر قراءة ملف وورد '{path.name}': الملف تالف أو ليس بصيغة .docx قياسية ({exc}). "
                f"الإجراء: احفظ الملف بصيغة Word (.docx) أو نص عادي (.txt) ثم أعد المحاولة."
            ) from exc

        root = ET.fromstring(xml_bytes)
        p_tag = f"{cls.WORD_NAMESPACE}p"
        t_tag = f"{cls.WORD_NAMESPACE}t"
        pPr_tag = f"{cls.WORD_NAMESPACE}pPr"
        pStyle_tag = f"{cls.WORD_NAMESPACE}pStyle"
        val_attr = f"{cls.WORD_NAMESPACE}val"

        extracted_paragraphs: List[str] = []
        for para_elem in root.iter(p_tag):
            runs: List[str] = []
            for t_elem in para_elem.iter(t_tag):
                if t_elem.text:
                    runs.append(t_elem.text)
            para_text = "".join(runs).strip()
            if not para_text:
                continue

            heading_prefix = ""
            pPr = para_elem.find(pPr_tag)
            if pPr is not None:
                pStyle = pPr.find(pStyle_tag)
                if pStyle is not None:
                    style_val = pStyle.attrib.get(val_attr, "")
                    if style_val.lower().startswith("heading"):
                        m = re.search(r"(\d+)", style_val)
                        lvl = int(m.group(1)) if m else 1
                        heading_prefix = "#" * max(1, min(6, lvl)) + " "

            extracted_paragraphs.append(f"{heading_prefix}{para_text}")

        return "\n\n".join(extracted_paragraphs)

    @classmethod
    def normalize_unformatted_text(cls, raw_text: str) -> str:
        """
        Cleans up unformatted raw text (e.g. OCR output or PDF copy-paste):
        - Removes invisible control characters while preserving Arabic diacritics.
        - Rejoins lines that were arbitrarily broken mid-sentence without terminal punctuation
          or chapter heading markers.
        """
        if not raw_text:
            return ""

        text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        # Remove zero-width / control chars except newline and tab
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)

        # If text already has double newlines, preserve paragraph structure while tidying broken lines inside paragraphs
        raw_lines = text.split("\n")
        reconstructed: List[str] = []
        buffer_line = ""

        terminal_punct = (".", "!", "?", "؟", "؛", ":", "»", '"', "”")

        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                if buffer_line:
                    reconstructed.append(buffer_line)
                    buffer_line = ""
                reconstructed.append("")
                continue

            is_heading = bool(re.match(r"^#{1,6}\s+", stripped)) or any(
                pat.match(stripped) for pat in cls.ARABIC_CHAPTER_PATTERNS
            )

            if is_heading:
                if buffer_line:
                    reconstructed.append(buffer_line)
                    buffer_line = ""
                reconstructed.append(stripped)
                continue

            if not buffer_line:
                buffer_line = stripped
            else:
                if buffer_line.endswith(terminal_punct) or len(buffer_line) >= 220:
                    reconstructed.append(buffer_line)
                    buffer_line = stripped
                else:
                    buffer_line = f"{buffer_line} {stripped}"

        if buffer_line:
            reconstructed.append(buffer_line)

        joined = "\n".join(reconstructed)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()

    @classmethod
    def read_file_safe(cls, file_path: Union[str, Path]) -> str:
        """Reads a .txt, .md, or .docx file safely across multiple encodings."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Book file does not exist: {file_path}")

        if path.suffix.lower() == ".docx":
            return cls.extract_docx_text(path)

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
        Parses a book from disk (.md, .txt, or .docx), returning a ParsedBook structure.
        """
        path = Path(file_path)
        content = self.read_file_safe(path)
        book_title = path.stem.replace("_", " ").strip()

        return self.parse_content(content, filename=book_title, file_path=str(path.resolve()))

    def parse_content(self, content: str, filename: str = "Audiobook", file_path: str = "") -> ParsedBook:
        """
        Analyzes and segments raw content into chapters.
        """
        text = self.normalize_unformatted_text(content)
        if not text:
            return ParsedBook(
                title=filename,
                file_path=file_path,
                total_characters=0,
                chapters=[],
            )

        # 1. First scan for explicit Arabic & English chapter headings (highest semantic authority)
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
            logger.info("Detected %d explicit chapter headings.", len(filtered_matches))
            chapters: List[CleanedChapter] = []

            # Preface / Front-matter handling before first chapter
            front_matter = text[: filtered_matches[0][0]].strip() if filtered_matches[0][0] > 0 else ""
            first_is_preface = any(k in filtered_matches[0][2] for k in ["مقدمة", "تمهيد", "فاتحة", "مدخل", "توطئة"])

            if front_matter and len(front_matter) > 30 and not first_is_preface:
                clean_pref = self.markdown_stripper.clean_markdown_text(front_matter)
                chapters.append(
                    CleanedChapter(
                        chapter_title="مقدمة",
                        level=1,
                        text=f"مقدمة. <short pause>\n\n{clean_pref}",
                        raw_length=len(front_matter),
                    )
                )

            for i, (start, end, title) in enumerate(filtered_matches):
                next_start = filtered_matches[i + 1][0] if (i + 1 < len(filtered_matches)) else len(text)
                body = text[end:next_start].strip()
                if i == 0 and front_matter and first_is_preface:
                    body = f"{front_matter}\n\n{body}"
                clean_body = self.markdown_stripper.clean_markdown_text(body)
                title_clean = title.strip().split('\n')[0].strip()[:60]
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

        # 2. If no explicit chapter headings found, check for Markdown headers
        if re.search(r"^#{1,6}\s+.+", text, re.MULTILINE):
            logger.info("Markdown headers detected. Using Markdown chapter extraction.")
            chapters = self.markdown_stripper.extract_chapters(text)
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
        Segments long continuous prose at natural paragraph, sentence, or word boundaries
        into balanced listening segments—even if the input is a single massive block without '\\n\\n'.
        """
        raw_blocks = [b.strip() for b in re.split(r"\n\s*\n|\n", text) if b.strip()]
        paragraphs: List[str] = []
        for block in raw_blocks:
            if len(block) > self.continuous_chapter_size:
                paragraphs.extend(
                    self.chunker.split_long_sentence(block, self.continuous_chapter_size)
                )
            else:
                paragraphs.append(block)

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
                title = f"Part {chapter_index} - الجزء {chapter_index}"
                spoken = cleaned
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
            title = f"Part {chapter_index} - الجزء {chapter_index}" if chapters else "Full Book"
            spoken = cleaned
            chapters.append(
                CleanedChapter(
                    chapter_title=title,
                    level=1,
                    text=spoken,
                    raw_length=current_len,
                )
            )

        return chapters

