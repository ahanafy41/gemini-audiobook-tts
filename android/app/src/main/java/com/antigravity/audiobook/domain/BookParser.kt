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
    private val continuousChapterSize: Int = 7500
) {

    companion object {
        private const val TAG = "BookParser"

        private val CHAPTER_PATTERNS = listOf(
            Regex("^\\s*(الفصل|الباب|الجزء|المبحث|المطلب|القسم|الكتاب)\\s+([^\\n:–—\\-]+)[:–—\\-\\s]*(.*?)$", RegexOption.MULTILINE),
            Regex("^\\s*(مقدمة|تمهيد|فاتحة الكتاب|مدخل|توطئة|خاتمة|الخاتمة|خلاصة)\\s*$", RegexOption.MULTILINE),
            Regex("^\\s*(Chapter|Section|Part|Book|Volume|Act|Scene)\\s+([0-9IVXLCDMivxlcdm]+)[:–—\\-\\s]*(.*?)$", setOf(RegexOption.MULTILINE, RegexOption.IGNORE_CASE)),
            Regex("^[ \\t]*([0-9]{1,3}|[IVXLCDM]{1,8})[.:–—\\-][ \\t]+([^\\r\\n]{1,60})$", RegexOption.MULTILINE)
        )
    }

    private val markdownStripper = MarkdownStripper()

    fun parseFile(file: File, explicitTitle: String? = null): ParsedBook {
        val content = readFileSafe(file)
        val fileTitle = file.nameWithoutExtension.replace('_', ' ').trim()
        val titleCandidate = when {
            !explicitTitle.isNullOrBlank() -> explicitTitle.trim()
            fileTitle.isNotBlank() && fileTitle != "source_book" && fileTitle != "source book" -> fileTitle
            else -> "بدون اسم"
        }
        return parseContent(content, titleCandidate, file.absolutePath)
    }

    fun parseContent(content: String, title: String = "بدون اسم", filePath: String = ""): ParsedBook {
        val trimmed = content.trim()
        val resolvedTitle = if (title.isBlank()) "بدون اسم" else title.trim()
        if (trimmed.isEmpty()) {
            return ParsedBook(resolvedTitle, filePath, 0, emptyList())
        }

        // 1. Check for Markdown headers
        if (Regex("^#{1,6}\\s+.+", RegexOption.MULTILINE).containsMatchIn(trimmed)) {
            Log.i(TAG, "Markdown headers detected for '$resolvedTitle'.")
            val rawChapters = markdownStripper.extractChapters(trimmed)
            var chapters = aggregateSections(rawChapters, continuousChapterSize)

            // If the book title was default, and first heading is # Title, adopt it as book title
            var effectiveTitle = resolvedTitle
            if ((resolvedTitle == "بدون اسم" || resolvedTitle == "كتاب صوتي") && chapters.isNotEmpty()) {
                val firstCandidate = chapters.first().chapterTitle.trim()
                if (firstCandidate.isNotBlank() && firstCandidate != "مقدمة") {
                    effectiveTitle = firstCandidate
                    // If this chapter only contained the title itself, remove it from chapters list
                    if (chapters.size > 1 && chapters.first().text.trim().equals(effectiveTitle, ignoreCase = true)) {
                        chapters = chapters.drop(1)
                    }
                }
            }

            return ParsedBook(effectiveTitle, filePath, trimmed.length, chapters)
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
            val rawChapters = mutableListOf<CleanedChapter>()

            if (filtered[0].start > 0) {
                val preface = trimmed.substring(0, filtered[0].start).trim()
                if (preface.isNotEmpty()) {
                    val cleanPref = markdownStripper.cleanMarkdownText(preface)
                    rawChapters.add(
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
                val titleClean = current.title.trim().lines().firstOrNull()?.trim()?.take(60) ?: current.title
                val spoken = if (cleanBody.isNotEmpty()) {
                    "$titleClean. <short pause>\n\n$cleanBody"
                } else {
                    titleClean
                }

                rawChapters.add(
                    CleanedChapter(
                        chapterTitle = current.title,
                        level = 1,
                        text = spoken,
                        rawLength = nextStart - current.start
                    )
                )
            }

            val chapters = aggregateSections(rawChapters, continuousChapterSize)
            return ParsedBook(title, filePath, trimmed.length, chapters)
        }

        // 3. Fallback: Segment continuous text
        Log.i(TAG, "Segmenting continuous novel into balanced segments.")
        val chapters = segmentContinuousText(trimmed)
        return ParsedBook(title, filePath, trimmed.length, chapters)
    }

    private fun aggregateSections(sections: List<CleanedChapter>, targetSize: Int): List<CleanedChapter> {
        if (sections.isEmpty()) return emptyList()
        val result = mutableListOf<CleanedChapter>()
        val currentGroup = mutableListOf<CleanedChapter>()
        var currentLength = 0

        for (sec in sections) {
            val secLen = sec.text.length
            if (currentLength + secLen <= targetSize || currentGroup.isEmpty()) {
                currentGroup.add(sec)
                currentLength += secLen
            } else {
                result.add(mergeChapters(currentGroup))
                currentGroup.clear()
                currentGroup.add(sec)
                currentLength = secLen
            }
        }

        if (currentGroup.isNotEmpty()) {
            result.add(mergeChapters(currentGroup))
        }

        return result
    }

    private fun mergeChapters(group: List<CleanedChapter>): CleanedChapter {
        if (group.size == 1) return group[0]

        val combinedTitle = if (group.size <= 3) {
            group.joinToString(" - ") { it.chapterTitle }
        } else {
            "${group.first().chapterTitle} إلى ${group.last().chapterTitle}"
        }

        val combinedText = group.joinToString("\n\n\n\n") { it.text }
        val totalRawLength = group.sumOf { it.rawLength }

        return CleanedChapter(
            chapterTitle = combinedTitle,
            level = 1,
            text = combinedText,
            rawLength = totalRawLength
        )
    }

    private fun segmentContinuousText(text: String): List<CleanedChapter> {
        val paragraphs = if (text.contains(Regex("\\r?\\n\\s*\\r?\\n"))) {
            text.split(Regex("\\r?\\n\\s*\\r?\\n"))
        } else {
            text.split(Regex("\\r?\\n"))
        }
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
                        text = cleanBody,
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
                    text = cleanBody,
                    rawLength = currentLength
                )
            )
        }

        return chapters
    }

    fun extractDocxText(file: File): String {
        val sb = StringBuilder()
        try {
            java.util.zip.ZipFile(file).use { zip ->
                val entry = zip.getEntry("word/document.xml") ?: return ""
                zip.getInputStream(entry).use { stream ->
                    val factory = javax.xml.parsers.DocumentBuilderFactory.newInstance()
                    val builder = factory.newDocumentBuilder()
                    val doc = builder.parse(stream)
                    val pNodes = doc.getElementsByTagName("w:p")
                    for (i in 0 until pNodes.length) {
                        val pNode = pNodes.item(i)
                        val tNodes = (pNode as org.w3c.dom.Element).getElementsByTagName("w:t")
                        val pText = StringBuilder()
                        for (j in 0 until tNodes.length) {
                            pText.append(tNodes.item(j).textContent)
                        }
                        val trimmedP = pText.toString().trim()
                        if (trimmedP.isNotEmpty()) {
                            sb.append(trimmedP).append("\n\n")
                        }
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to parse docx XML: ${e.message}")
        }
        return sb.toString().trim()
    }

    private fun readFileSafe(file: File): String {
        if (file.extension.equals("docx", ignoreCase = true)) {
            val docxText = extractDocxText(file)
            if (docxText.isNotEmpty()) return docxText
        }

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
