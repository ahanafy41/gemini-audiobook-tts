#!/usr/bin/env python3
"""
Smart Text Chunker for Gemini Audiobook TTS.
Handles intelligent text chunking at natural sentence and paragraph boundaries,
supporting both Arabic and English punctuation without breaking words.
"""

import logging
import re
from typing import List

logger = logging.getLogger("SmartTextChunker")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class SmartTextChunker:
    """
    Intelligent text chunker designed for Text-to-Speech synthesis pipelines.
    Splits long narrative texts into segments of <= max_chunk_size characters,
    respecting paragraph and sentence boundaries for seamless acoustic delivery.
    """

    DEFAULT_MAX_CHUNK_SIZE: int = 7500
    STRICT_UPPER_LIMIT: int = 8000

    SENTENCE_ENDINGS = re.compile(r"([.!?؟؛\n]+)")
    PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")

    def __init__(self, max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE) -> None:
        if max_chunk_size > self.STRICT_UPPER_LIMIT:
            logger.warning(
                "Requested chunk size %d exceeds strict ceiling of %d. Clamping.",
                max_chunk_size,
                self.STRICT_UPPER_LIMIT,
            )
            self.max_chunk_size = self.STRICT_UPPER_LIMIT
        else:
            self.max_chunk_size = max(100, max_chunk_size)

    def split_into_sentences(self, text: str) -> List[str]:
        """
        Splits text into coherent sentences without losing punctuation.
        Works across Arabic (؟ ، ؛) and Western (. ! ?) punctuation.
        """
        tokens = self.SENTENCE_ENDINGS.split(text)
        sentences: List[str] = []
        current = ""

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

    def split_long_sentence(self, sentence: str, limit: int) -> List[str]:
        """
        Splits a single oversized sentence by clauses or words without breaking words.
        """
        if len(sentence) <= limit:
            return [sentence]

        clause_delimiters = re.compile(r"([،,;:\-–—\s]+)")
        tokens = clause_delimiters.split(sentence)
        sub_chunks: List[str] = []
        accumulator = ""

        for part in tokens:
            if not part:
                continue
            if len(accumulator) + len(part) <= limit:
                accumulator += part
            else:
                stripped = accumulator.strip()
                if stripped:
                    sub_chunks.append(stripped)
                if len(part) > limit:
                    words = part.split()
                    word_acc = ""
                    for w in words:
                        if len(word_acc) + len(w) + 1 <= limit:
                            word_acc = f"{word_acc} {w}".strip()
                        else:
                            if word_acc:
                                sub_chunks.append(word_acc)
                            word_acc = w
                    if word_acc:
                        accumulator = word_acc
                    else:
                        accumulator = ""
                else:
                    accumulator = part

        if accumulator.strip():
            sub_chunks.append(accumulator.strip())

        return sub_chunks

    def chunk_text(self, text: str, max_chunk_size: int = 0) -> List[str]:
        """
        Chunks text into segments <= max_chunk_size characters.
        Prioritizes paragraph breaks, then sentence breaks, then clauses.
        """
        limit = max_chunk_size if (max_chunk_size > 0) else self.max_chunk_size
        limit = min(limit, self.STRICT_UPPER_LIMIT)

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
