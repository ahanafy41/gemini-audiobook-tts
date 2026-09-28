package com.antigravity.audiobook.domain

import android.util.Log

data class CleanedChapter(
    val chapterTitle: String,
    val level: Int,
    val text: String,
    val rawLength: Int
)

/**
 * Strips visual Markdown formatting and noise for acoustic playback,
 * extracting chapters and inserting audio pause tags (<short pause>).
 */
class MarkdownStripper {

    companion object {
        private const val TAG = "MarkdownStripper"
        private val HEADING_REGEX = Regex("^(#{1,6})\\s+(.+)$", RegexOption.MULTILINE)
        private val IMAGE_REGEX = Regex("!\\[(.*?)\\]\\([^)]+\\)")
        private val LINK_REGEX = Regex("\\[(.*?)\\]\\([^)]+\\)")
        private val BOLD_ITALIC_STARS = Regex("\\*{1,3}([^*]+)\\*{1,3}")
        private val BOLD_ITALIC_UNDER = Regex("_{1,3}([^_]+)_{1,3}")
        private val STRIKETHROUGH = Regex("~~([^~]+)~~")
        private val CODE_BLOCK_REGEX = Regex("```[a-zA-Z0-9_\\-]*\\n[\\s\\S]*?\\n```")
        private val INLINE_CODE_REGEX = Regex("`([^`]+)`")
        private val BLOCKQUOTE_REGEX = Regex("^\\s*>\\s?", RegexOption.MULTILINE)
        private val HORIZONTAL_RULE = Regex("^[-*_]{3,}\\s*$", RegexOption.MULTILINE)
        private val MULTIPLE_NEWLINES = Regex("\\n{3,}")
        private val MULTIPLE_SPACES = Regex("[ \\t]{2,}")
    }

    fun cleanMarkdownText(text: String): String {
        if (text.isBlank()) return ""

        var cleaned = CODE_BLOCK_REGEX.replace(text, " <short pause> ")
        cleaned = HORIZONTAL_RULE.replace(cleaned, "\n<short pause>\n")
        cleaned = IMAGE_REGEX.replace(cleaned, "")
        cleaned = LINK_REGEX.replace(cleaned, "$1")
        cleaned = INLINE_CODE_REGEX.replace(cleaned, "$1")
        cleaned = BOLD_ITALIC_STARS.replace(cleaned, "$1")
        cleaned = BOLD_ITALIC_UNDER.replace(cleaned, "$1")
        cleaned = STRIKETHROUGH.replace(cleaned, "$1")
        cleaned = BLOCKQUOTE_REGEX.replace(cleaned, "")
        cleaned = MULTIPLE_SPACES.replace(cleaned, " ")
        cleaned = MULTIPLE_NEWLINES.replace(cleaned, "\n\n")

        return cleaned.trim()
    }

    fun cleanChapter(rawMarkdown: String): CleanedChapter {
        val trimmed = rawMarkdown.trim()
        val firstLine = trimmed.lines().firstOrNull() ?: ""
        val match = HEADING_REGEX.find(firstLine)

        val level: Int
        val chapterTitle: String
        val body: String

        if (match != null) {
            val hashes = match.groupValues[1]
            level = hashes.length
            chapterTitle = match.groupValues[2].trim()
            body = trimmed.removePrefix(firstLine).trim()
        } else {
            level = 1
            chapterTitle = "مقدمة"
            body = trimmed
        }

        val cleanedBody = cleanMarkdownText(body)
        val narrative = if (cleanedBody.isNotEmpty()) {
            "$chapterTitle. <short pause>\n\n$cleanedBody"
        } else {
            chapterTitle
        }

        return CleanedChapter(
            chapterTitle = chapterTitle,
            level = level,
            text = narrative.trim(),
            rawLength = trimmed.length
        )
    }

    fun extractChapters(markdownContent: String): List<CleanedChapter> {
        val content = markdownContent.trim()
        if (content.isEmpty()) return emptyList()

        val matches = HEADING_REGEX.findAll(content).toList()
        if (matches.isEmpty()) {
            Log.i(TAG, "No Markdown headings found. Processing as unified chapter.")
            return listOf(cleanChapter(content))
        }

        val chapters = mutableListOf<CleanedChapter>()

        // Capture introductory text preceding the first heading
        val firstStart = matches[0].range.first
        if (firstStart > 0) {
            val introText = content.substring(0, firstStart).trim()
            if (introText.isNotEmpty()) {
                val cleanedIntro = cleanMarkdownText(introText)
                if (cleanedIntro.isNotEmpty()) {
                    chapters.add(
                        CleanedChapter(
                            chapterTitle = "مقدمة",
                            level = 1,
                            text = cleanedIntro,
                            rawLength = introText.length
                        )
                    )
                }
            }
        }

        for (i in matches.indices) {
            val currentMatch = matches[i]
            val hashes = currentMatch.groupValues[1]
            val title = currentMatch.groupValues[2].trim()
            val level = hashes.length

            val bodyStart = currentMatch.range.last + 1
            val bodyEnd = if (i + 1 < matches.size) matches[i + 1].range.first else content.length

            val rawBody = content.substring(bodyStart, bodyEnd).trim()
            val cleanedBody = cleanMarkdownText(rawBody)

            val spokenText = if (cleanedBody.isNotEmpty()) {
                "$title. <short pause>\n\n$cleanedBody"
            } else {
                title
            }

            chapters.add(
                CleanedChapter(
                    chapterTitle = title,
                    level = level,
                    text = spokenText.trim(),
                    rawLength = bodyEnd - currentMatch.range.first
                )
            )
        }

        Log.i(TAG, "Extracted ${chapters.size} chapters from Markdown document.")
        return chapters
    }
}
