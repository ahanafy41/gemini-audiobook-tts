#!/usr/bin/env python3
"""
Markdown Stripper and Chapter Extractor for Gemini Audiobook TTS.
Cleans formatting tags and noise from Markdown files, extracts structural chapters,
injects acoustic pause markers (<short pause>), and preserves Arabic diacritics.
"""

import dataclasses
import logging
import re
from typing import List

logger = logging.getLogger("MarkdownStripper")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@dataclasses.dataclass
class CleanedChapter:
    """Represents a sanitized chapter ready for speech synthesis."""
    chapter_title: str
    level: int
    text: str
    raw_length: int


class MarkdownStripper:
    """
    Strips visual Markdown syntax into clear spoken prose.
    Injects point-in-time acoustic cues like <short pause> for natural narration.
    """

    HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    IMAGE_REGEX = re.compile(r"!\[(.*?)\]\([^)]+\)")
    LINK_REGEX = re.compile(r"\[(.*?)\]\([^)]+\)")
    BOLD_ITALIC_STARS = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
    BOLD_ITALIC_UNDER = re.compile(r"_{1,3}([^_]+)_{1,3}")
    STRIKETHROUGH = re.compile(r"~~([^~]+)~~")
    CODE_BLOCK_REGEX = re.compile(r"```[a-zA-Z0-9_\-]*\n[\s\S]*?\n```")
    INLINE_CODE_REGEX = re.compile(r"`([^`]+)`")
    BLOCKQUOTE_REGEX = re.compile(r"^\s*>\s?", re.MULTILINE)
    HORIZONTAL_RULE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
    MULTIPLE_NEWLINES = re.compile(r"\n{3,}")
    MULTIPLE_SPACES = re.compile(r"[ \t]{2,}")

    def __init__(self) -> None:
        pass

    def clean_markdown_text(self, text: str) -> str:
        """
        Strips markdown formatting while retaining Arabic diacritics (tashkeel),
        punctuation, and paragraph flow. Injects vocal markers for pauses.
        """
        if not text:
            return ""

        # Remove code blocks with a brief pause
        cleaned = self.CODE_BLOCK_REGEX.sub(" <short pause> ", text)

        # Replace horizontal rules with short pause
        cleaned = self.HORIZONTAL_RULE.sub("\n<short pause>\n", cleaned)

        # Remove images completely
        cleaned = self.IMAGE_REGEX.sub("", cleaned)

        # Convert links to anchor text
        cleaned = self.LINK_REGEX.sub(r"\1", cleaned)

        # Inline code
        cleaned = self.INLINE_CODE_REGEX.sub(r"\1", cleaned)

        # Bold and italic text (stars and underscores)
        cleaned = self.BOLD_ITALIC_STARS.sub(r"\1", cleaned)
        cleaned = self.BOLD_ITALIC_UNDER.sub(r"\1", cleaned)

        # Strikethrough
        cleaned = self.STRIKETHROUGH.sub(r"\1", cleaned)

        # Blockquotes
        cleaned = self.BLOCKQUOTE_REGEX.sub("", cleaned)

        # Normalize spacing
        cleaned = self.MULTIPLE_SPACES.sub(" ", cleaned)
        cleaned = self.MULTIPLE_NEWLINES.sub("\n\n", cleaned)

        return cleaned.strip()

    def clean_chapter(self, raw_markdown: str) -> CleanedChapter:
        """
        Cleans a single chapter markdown fragment into a CleanedChapter instance.
        """
        first_line = raw_markdown.strip().splitlines()[0] if raw_markdown.strip() else ""
        heading_match = self.HEADING_REGEX.match(first_line)

        if heading_match:
            hashes, title = heading_match.groups()
            level = len(hashes)
            body = raw_markdown.strip()[len(first_line):].strip()
            chapter_title = title.strip()
        else:
            level = 1
            chapter_title = "مقدمة"
            body = raw_markdown.strip()

        cleaned_body = self.clean_markdown_text(body)
        narrative_text = f"{chapter_title}. <short pause>\n\n{cleaned_body}" if cleaned_body else chapter_title

        return CleanedChapter(
            chapter_title=chapter_title,
            level=level,
            text=narrative_text.strip(),
            raw_length=len(raw_markdown),
        )

    def extract_chapters(self, markdown_content: str) -> List[CleanedChapter]:
        """
        Extracts chapters delineated by markdown headers (# or ##).
        If no headers are present, returns the entire text as a single chapter.
        """
        content = markdown_content.strip()
        if not content:
            return []

        heading_positions = list(self.HEADING_REGEX.finditer(content))
        if not heading_positions:
            logger.info("No markdown headings found. Processing as unified chapter.")
            return [self.clean_chapter(content)]

        chapters: List[CleanedChapter] = []

        # If there is content before the first heading, capture it as introduction
        if heading_positions[0].start() > 0:
            intro_text = content[:heading_positions[0].start()].strip()
            if intro_text:
                cleaned_intro = self.clean_markdown_text(intro_text)
                if cleaned_intro:
                    chapters.append(
                        CleanedChapter(
                            chapter_title="مقدمة",
                            level=1,
                            text=cleaned_intro,
                            raw_length=len(intro_text),
                        )
                    )

        for i, match in enumerate(heading_positions):
            hashes, title = match.groups()
            level = len(hashes)
            start_pos = match.end()
            end_pos = heading_positions[i + 1].start() if (i + 1 < len(heading_positions)) else len(content)

            section_raw = content[start_pos:end_pos].strip()
            cleaned_section = self.clean_markdown_text(section_raw)
            chapter_title = title.strip()

            spoken_text = f"{chapter_title}. <short pause>\n\n{cleaned_section}" if cleaned_section else chapter_title
            chapters.append(
                CleanedChapter(
                    chapter_title=chapter_title,
                    level=level,
                    text=spoken_text.strip(),
                    raw_length=(end_pos - match.start()),
                )
            )

        logger.info("Extracted %d chapters from Markdown text.", len(chapters))
        return chapters
