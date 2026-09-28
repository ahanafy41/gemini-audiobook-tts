package com.antigravity.audiobook.domain

import android.util.Log

/**
 * Intelligent text chunker for Gemini 3.8 Flash TTS.
 * Splits continuous narrative texts into chunks <= maxChunkSize characters,
 * respecting sentence boundaries across Arabic and English punctuation.
 */
class SmartTextChunker(
    private val maxChunkSize: Int = DEFAULT_MAX_CHUNK_SIZE
) {

    companion object {
        const val DEFAULT_MAX_CHUNK_SIZE = 7500
        const val STRICT_LIMIT = 8000
        private const val TAG = "SmartTextChunker"
        private val SENTENCE_ENDINGS = Regex("([.!?؟؛\\n]+)")
        private val PARAGRAPH_SPLIT = Regex("\\r?\\n\\s*\\r?\\n")
        private val CLAUSE_DELIMITERS = Regex("([،,;:\\-–—\\s]+)")
    }

    private val effectiveLimit: Int = maxChunkSize.coerceIn(100, STRICT_LIMIT)

    fun splitIntoSentences(text: String): List<String> {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return emptyList()

        val sentences = mutableListOf<String>()
        val sentenceRegex = Regex("([^.!?؟؛\\n]+[.!?؟؛\\n]*|.+)")
        for (match in sentenceRegex.findAll(trimmed)) {
            val item = match.value.trim()
            if (item.isNotEmpty()) {
                sentences.add(item)
            }
        }
        return sentences
    }

    private fun splitLongSentence(sentence: String, limit: Int): List<String> {
        if (sentence.length <= limit) return listOf(sentence)

        val parts = CLAUSE_DELIMITERS.split(sentence)
        val chunks = mutableListOf<String>()
        var accumulator = ""

        for (part in parts) {
            if (part.isEmpty()) continue
            if (accumulator.length + part.length <= limit) {
                accumulator += part
            } else {
                val trimmed = accumulator.trim()
                if (trimmed.isNotEmpty()) {
                    chunks.add(trimmed)
                }
                if (part.length > limit) {
                    val words = part.split("\\s+".toRegex())
                    var wordAcc = ""
                    for (word in words) {
                        if (wordAcc.length + word.length + 1 <= limit) {
                            wordAcc = if (wordAcc.isEmpty()) word else "$wordAcc $word"
                        } else {
                            if (wordAcc.isNotEmpty()) chunks.add(wordAcc)
                            wordAcc = word
                        }
                    }
                    accumulator = wordAcc
                } else {
                    accumulator = part
                }
            }
        }

        if (accumulator.trim().isNotEmpty()) {
            chunks.add(accumulator.trim())
        }

        return chunks
    }

    fun chunkText(text: String, customLimit: Int = 0): List<String> {
        val limit = if (customLimit in 100..STRICT_LIMIT) customLimit else effectiveLimit
        val normalized = text.trim()
        if (normalized.isEmpty()) return emptyList()
        if (normalized.length <= limit) return listOf(normalized)

        val paragraphs = PARAGRAPH_SPLIT.split(normalized)
        val chunks = mutableListOf<String>()
        val currentParts = mutableListOf<String>()
        var currentLength = 0

        for (para in paragraphs) {
            val cleanPara = para.trim()
            if (cleanPara.isEmpty()) continue

            if (cleanPara.length <= limit) {
                val projected = currentLength + (if (currentParts.isNotEmpty()) 2 else 0) + cleanPara.length
                if (projected <= limit) {
                    currentParts.add(cleanPara)
                    currentLength = projected
                } else {
                    if (currentParts.isNotEmpty()) {
                        chunks.add(currentParts.joinToString("\n\n"))
                    }
                    currentParts.clear()
                    currentParts.add(cleanPara)
                    currentLength = cleanPara.length
                }
            } else {
                if (currentParts.isNotEmpty()) {
                    chunks.add(currentParts.joinToString("\n\n"))
                    currentParts.clear()
                    currentLength = 0
                }

                val sentences = splitIntoSentences(cleanPara)
                for (sentence in sentences) {
                    val subParts = splitLongSentence(sentence, limit)
                    for (part in subParts) {
                        val partLen = part.length
                        val projected = currentLength + (if (currentParts.isNotEmpty()) 1 else 0) + partLen
                        if (projected <= limit) {
                            currentParts.add(part)
                            currentLength = projected
                        } else {
                            if (currentParts.isNotEmpty()) {
                                chunks.add(currentParts.joinToString(" "))
                            }
                            currentParts.clear()
                            currentParts.add(part)
                            currentLength = partLen
                        }
                    }
                }
            }
        }

        if (currentParts.isNotEmpty()) {
            chunks.add(currentParts.joinToString("\n\n"))
        }

        Log.i(TAG, "Chunked ${text.length} chars into ${chunks.size} chunks (limit $limit).")
        return chunks
    }
}
