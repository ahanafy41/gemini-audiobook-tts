package com.antigravity.audiobook.domain

import android.util.Log
import java.io.File
import java.nio.charset.Charset

data class ParsedBook(
    val title: String,
    val filePath: String,
    val totalCharacters: Int,
    val chapters: List<CleanedChapter>
)

/**
 * Universal text and markdown book parser for Android.
 * Extracts structural chapters via regex patterns or provides balanced segmentation.
 */
class BookParser(
    private val continuousChapterSize: Int = 15000
) {

    companion object {
        private const val TAG = "BookParser"

        private val CHAPTER_PATTERNS = listOf(
            Regex("^\\s*(الفصل|الباب|الجزء|المبحث|القسم)\\s+([^\\n:–—\\-]+)[:–—\\-\\s]*(.*?)$", RegexOption.MULTILINE),
            Regex("^\\s*(مقدمة|تمهيد|فاتحة الكتاب|توطئة|خاتمة|خلاصة)\\s*$", RegexOption.MULTILINE),
            Regex("^\\s*(Chapter|Section|Part|Book)\\s+([0-9IVXLCDMivxlcdm]+)[:–—\\-\\s]*(.*?)$", setOf(RegexOption.MULTILINE, RegexOption.IGNORE_CASE))
        )
    }

    private val markdownStripper = MarkdownStripper()

    fun parseFile(file: File): ParsedBook {
        val content = readFileSafe(file)
        val title = file.nameWithoutExtension.replace('_', ' ').trim()
        return parseContent(content, title, file.absolutePath)
    }

    fun parseContent(content: String, title: String = "كتاب صوتي", filePath: String = ""): ParsedBook {
        val trimmed = content.trim()
        if (trimmed.isEmpty()) {
            return ParsedBook(title, filePath, 0, emptyList())
        }

        // 1. Check for Markdown headers
        if (Regex("^#{1,6}\\s+.+", RegexOption.MULTILINE).containsMatchIn(trimmed)) {
            Log.i(TAG, "Markdown headers detected for '$title'.")
            val chapters = markdownStripper.extractChapters(trimmed)
            return ParsedBook(title, filePath, trimmed.length, chapters)
        }

        // 2. Scan for Arabic & English chapter headings
        data class HeadingMatch(val start: Int, val end: Int, val title: String)
        val allMatches = mutableListOf<HeadingMatch>()

        for (pattern in CHAPTER_PATTERNS) {
            for (match in pattern.findAll(trimmed)) {
                allMatches.add(HeadingMatch(match.range.first, match.range.last + 1, match.value.trim()))
            }
        }

        allMatches.sortBy { it.start }

        val filtered = mutableListOf<HeadingMatch>()
        var lastEnd = -1
        for (m in allMatches) {
            if (m.start >= lastEnd) {
                filtered.add(m)
                lastEnd = m.end
            }
        }

        if (filtered.size >= 2) {
            Log.i(TAG, "Detected ${filtered.size} headings in plain text for '$title'.")
            val chapters = mutableListOf<CleanedChapter>()

            if (filtered[0].start > 0) {
                val preface = trimmed.substring(0, filtered[0].start).trim()
                if (preface.isNotEmpty()) {
                    val cleanPref = markdownStripper.cleanMarkdownText(preface)
                    chapters.add(
                        CleanedChapter(
                            chapterTitle = "مقدمة",
                            level = 1,
                            text = "مقدمة. <short pause>\n\n$cleanPref",
                            rawLength = preface.length
                        )
                    )
                }
            }

            for (i in filtered.indices) {
                val current = filtered[i]
                val nextStart = if (i + 1 < filtered.size) filtered[i + 1].start else trimmed.length
                val body = trimmed.substring(current.end, nextStart).trim()
                val cleanBody = markdownStripper.cleanMarkdownText(body)
                val spoken = if (cleanBody.isNotEmpty()) {
                    "${current.title}. <short pause>\n\n$cleanBody"
                } else {
                    current.title
                }

                chapters.add(
                    CleanedChapter(
                        chapterTitle = current.title,
                        level = 1,
                        text = spoken,
                        rawLength = nextStart - current.start
                    )
                )
            }

            return ParsedBook(title, filePath, trimmed.length, chapters)
        }

        // 3. Fallback: Segment continuous text
        Log.i(TAG, "Segmenting continuous novel into balanced segments.")
        val chapters = segmentContinuousText(trimmed)
        return ParsedBook(title, filePath, trimmed.length, chapters)
    }

    private fun segmentContinuousText(text: String): List<CleanedChapter> {
        val paragraphs = text.split("\n\n")
        val chapters = mutableListOf<CleanedChapter>()
        val currentParagraphs = mutableListOf<String>()
        var currentLength = 0
        var chapterIndex = 1

        for (para in paragraphs) {
            val cleanPara = para.trim()
            if (cleanPara.isEmpty()) continue

            if (currentLength + cleanPara.length <= continuousChapterSize || currentParagraphs.isEmpty()) {
                currentParagraphs.add(cleanPara)
                currentLength += cleanPara.length
            } else {
                val body = currentParagraphs.joinToString("\n\n")
                val cleanBody = markdownStripper.cleanMarkdownText(body)
                val title = "الجزء $chapterIndex"
                chapters.add(
                    CleanedChapter(
                        chapterTitle = title,
                        level = 1,
                        text = "$title. <short pause>\n\n$cleanBody",
                        rawLength = currentLength
                    )
                )
                chapterIndex++
                currentParagraphs.clear()
                currentParagraphs.add(cleanPara)
                currentLength = cleanPara.length
            }
        }

        if (currentParagraphs.isNotEmpty()) {
            val body = currentParagraphs.joinToString("\n\n")
            val cleanBody = markdownStripper.cleanMarkdownText(body)
            val title = if (chapters.isNotEmpty()) "الجزء $chapterIndex" else "الكتاب كاملاً"
            chapters.add(
                CleanedChapter(
                    chapterTitle = title,
                    level = 1,
                    text = "$title. <short pause>\n\n$cleanBody",
                    rawLength = currentLength
                )
            )
        }

        return chapters
    }

    private fun readFileSafe(file: File): String {
        val encodings = listOf("UTF-8", "windows-1256", "ISO-8859-6", "US-ASCII")
        val bytes = file.readBytes()

        for (enc in encodings) {
            try {
                val charset = Charset.forName(enc)
                val decoded = charset.newDecoder().decode(java.nio.ByteBuffer.wrap(bytes)).toString()
                return decoded
            } catch (e: Exception) {
                // Try next charset
            }
        }
        return String(bytes, Charset.defaultCharset())
    }
}
