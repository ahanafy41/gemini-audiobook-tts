#!/usr/bin/env python3
"""
Smart Text Chunker for Gemini Audiobook TTS.
Handles intelligent text chunking at natural sentence and paragraph boundaries,
supporting both Arabic and English punctuation without breaking words.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("SmartTextChunker")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_adaptive_chunk_limits(model_id: str = "gemini-3.8-flash-tts") -> Dict[str, int]:
    """
    Returns adaptive chunk sizing parameters (target, min_window, max_window)
    tailored to the selected Gemini TTS model generation.
    - 3.8 models: target 8000 chars (flexible window 7500 - 8500)
    - Legacy 3.1 / 2.5 models: target 2000 chars (flexible window 1800 - 2300)
    """
    clean_model = (model_id or "gemini-3.8-flash-tts").strip().lower()
    if "3.8" in clean_model:
        return {
            "target": 8000,
            "min_window": 7500,
            "max_window": 8500,
        }
    return {
        "target": 2000,
        "min_window": 1800,
        "max_window": 2300,
    }


class SmartTextChunker:
    """
    Intelligent text chunker designed for Text-to-Speech synthesis pipelines.
    Splits long narrative texts into segments respecting model-adaptive limits,
    paragraph/sentence boundaries, Arabic conjunctions, and strict word integrity.
    """

    DEFAULT_MAX_CHUNK_SIZE: int = 8000
    STRICT_UPPER_LIMIT: int = 8500

    SENTENCE_ENDINGS = re.compile(r"([.!?؟؛;:\n»\"]+)")
    PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")

    HIERARCHICAL_BOUNDARIES: List[re.Pattern[str]] = [
        re.compile(r"\n\s*\n"),
        re.compile(r"\n+"),
        re.compile(r"(?<=[.!?؟؛;:»\"])\s+"),
        re.compile(r"(?:،\s*و|،\s*ثم|،\s*لكن|،\s*بل|،\s*حيث|،\s*كما|،\s*فإن|،\s*إذ|،\s*بينما|،|,)\s+"),
        re.compile(r"\s+(?:و|ثم|أو|لكن|بل|حتى|حيث|لأن|بينما|عندما|الذي|التي|الذين)\s+"),
        re.compile(r"\s+"),
    ]

    def __init__(
        self,
        max_chunk_size: Optional[int] = None,
        model_id: str = "gemini-3.8-flash-tts",
    ) -> None:
        self.model_id = model_id or "gemini-3.8-flash-tts"
        adaptive = get_adaptive_chunk_limits(self.model_id)
        self.target_size: int = adaptive["target"]
        self.min_window: int = adaptive["min_window"]
        self.max_window: int = adaptive["max_window"]

        if max_chunk_size is not None and max_chunk_size > 0:
            if max_chunk_size > self.STRICT_UPPER_LIMIT:
                logger.warning(
                    "Requested chunk size %d exceeds strict ceiling of %d. Clamping.",
                    max_chunk_size,
                    self.STRICT_UPPER_LIMIT,
                )
                self.max_chunk_size = self.STRICT_UPPER_LIMIT
            else:
                self.max_chunk_size = max(20, int(max_chunk_size))
        else:
            self.max_chunk_size = self.target_size

    def configure_for_model(self, model_id: str) -> Dict[str, int]:
        """Updates chunker limits dynamically when the active TTS model changes."""
        self.model_id = model_id or "gemini-3.8-flash-tts"
        adaptive = get_adaptive_chunk_limits(self.model_id)
        self.target_size = adaptive["target"]
        self.min_window = adaptive["min_window"]
        self.max_window = adaptive["max_window"]
        self.max_chunk_size = self.target_size
        return adaptive

    def split_into_sentences(self, text: str) -> List[str]:
        """
        Splits text into coherent sentences without losing punctuation.
        Works across Arabic (؟ ، ؛) and Western (. ! ?) punctuation.
        """
        tokens = self.SENTENCE_ENDINGS.split(text)
        sentences: List[str] = []

        for i in range(0, len(tokens) - 1, 2):
            sentence_body = tokens[i].strip()
            delimiter = tokens[i + 1]
            if sentence_body:
                sentences.append(f"{sentence_body}{delimiter}".strip())
            else:
                if sentences:
                    sentences[-1] = f"{sentences[-1]}{delimiter}".strip()
                elif delimiter.strip():
                    sentences.append(delimiter.strip())

        if len(tokens) % 2 == 1:
            tail = tokens[-1].strip()
            if tail:
                sentences.append(tail)

        return [s for s in sentences if s]

    @classmethod
    def _find_best_cut_index(cls, text: str, min_pos: int, max_pos: int) -> int:
        """
        Finds the most natural linguistic boundary within [min_pos, max_pos]
        following the strict 6-level priority hierarchy without ever cutting a word.
        """
        if len(text) <= max_pos:
            return len(text)

        window = text[min_pos:max_pos]

        # Priority 1: Paragraph break (\n\n)
        para_idx = window.rfind("\n\n")
        if para_idx != -1:
            return min_pos + para_idx + 2

        # Priority 2: Single line break (\n)
        line_idx = window.rfind("\n")
        if line_idx != -1:
            return min_pos + line_idx + 1

        # Priority 3: Terminal punctuation (. ؟ ? ! : ؛ ; » ")
        best_punct = -1
        for m in re.finditer(r"[.!?؟؛;:»\"]+\s*", window):
            best_punct = m.end()
        if best_punct != -1:
            return min_pos + best_punct

        # Priority 4: Clauses, Arabic commas, and conjunctions
        best_clause = -1
        for m in re.finditer(
            r"(?:،\s*(?:و|ثم|لكن|بل|حيث|كما|فإن|إذ)|[،,;–—\-])\s*",
            window,
        ):
            best_clause = m.end()
        if best_clause != -1:
            return min_pos + best_clause

        # Priority 5: Whitespace inside [min_pos, max_pos]
        space_idx = window.rfind(" ")
        if space_idx != -1:
            return min_pos + space_idx + 1

        # Priority 6: Fallback to any whitespace before max_pos (from 0 to max_pos)
        full_prefix = text[:max_pos]
        fallback_space = max(full_prefix.rfind(" "), full_prefix.rfind("\n"), full_prefix.rfind("\t"))
        if fallback_space > 0:
            return fallback_space + 1

        # Last resort if a single continuous token has no spaces at all
        return max_pos

    def split_long_sentence(self, sentence: str, limit: int) -> List[str]:
        """
        Splits a single oversized sentence or unformatted text block by clauses or words
        without breaking words.
        """
        cleaned = sentence.strip()
        if not cleaned:
            return []
        if len(cleaned) <= limit:
            return [cleaned]

        sub_chunks: List[str] = []
        remaining = cleaned
        min_win = max(1, int(limit * 0.75))

        while remaining:
            if len(remaining) <= limit:
                sub_chunks.append(remaining.strip())
                break

            cut_at = self._find_best_cut_index(remaining, min_pos=min_win, max_pos=limit)
            piece = remaining[:cut_at].strip()
            if piece:
                sub_chunks.append(piece)
            remaining = remaining[cut_at:].strip()

        return [c for c in sub_chunks if c]

    def chunk_text(
        self,
        text: str,
        max_chunk_size: int = 0,
        model_id: Optional[str] = None,
    ) -> List[str]:
        """
        Chunks text into segments <= limit characters.
        If model_id is provided (and max_chunk_size is not explicitly set), uses model-adaptive sizing.
        Prioritizes paragraph breaks, then sentence breaks, then clauses, then word spaces.
        """
        if max_chunk_size > 0:
            limit = min(max_chunk_size, self.STRICT_UPPER_LIMIT)
        elif model_id:
            adaptive = get_adaptive_chunk_limits(model_id)
            limit = adaptive["target"]
        else:
            limit = self.max_chunk_size

        normalized = text.strip()
        if not normalized:
            return []

        if len(normalized) <= limit:
            return [normalized]

        paragraphs = self.PARAGRAPH_SPLIT.split(normalized)
        chunks: List[str] = []
        current_chunk_parts: List[str] = []
        current_length = 0

        for para in paragraphs:
            para_clean = para.strip()
            if not para_clean:
                continue

            if len(para_clean) <= limit:
                projected_length = current_length + (2 if current_chunk_parts else 0) + len(para_clean)
                if projected_length <= limit:
                    current_chunk_parts.append(para_clean)
                    current_length = projected_length
                else:
                    if current_chunk_parts:
                        chunks.append("\n\n".join(current_chunk_parts))
                    current_chunk_parts = [para_clean]
                    current_length = len(para_clean)
            else:
                if current_chunk_parts:
                    chunks.append("\n\n".join(current_chunk_parts))
                    current_chunk_parts = []
                    current_length = 0

                sentences = self.split_into_sentences(para_clean)
                for sentence in sentences:
                    sub_parts = self.split_long_sentence(sentence, limit)
                    for part in sub_parts:
                        part_len = len(part)
                        projected_len = current_length + (1 if current_chunk_parts else 0) + part_len
                        if projected_len <= limit:
                            current_chunk_parts.append(part)
                            current_length = projected_len
                        else:
                            if current_chunk_parts:
                                chunks.append(" ".join(current_chunk_parts))
                            current_chunk_parts = [part]
                            current_length = part_len

        if current_chunk_parts:
            chunks.append("\n\n".join(current_chunk_parts))

        logger.info(
            "Chunked input text of %d characters into %d chunks (limit: %d chars).",
            len(text),
            len(chunks),
            limit,
        )
        return chunks


SmartChunker = SmartTextChunker

