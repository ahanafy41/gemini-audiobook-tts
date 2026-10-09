package com.antigravity.audiobook.domain

data class DialogueTurn(
    val speaker: String,
    val text: String
)

/**
 * محرك تحليل وتقسيم الحوار لنموذج Gemini 3.8 Flash TTS وفقاً لتوثيق Google الرسمي.
 * يدعم صيغتين قياسيتين:
 * 1. صيغة السيناريو والبودكاست الرسمية من Google (Script Format):
 *    كل سطر يبدأ باسم المتحدث متبوعاً بنقطتين فوق بعض:
 *    مثال: "Speaker1: مرحباً" أو "أحمد: أهلاً بك".
 * 2. صيغة الروايات والكتب (Quotation Format):
 *    فرز النصوص المحصورة بين علامات التنصيص («...» أو "..." أو “...”) ككلام للشخصيات،
 *    والسرد الخارجي ككلام للراوي.
 */
class DialogueTurnAnnotator(
    private val narratorSpeakerName: String = "Narrator",
    private val characterSpeakerName: String = "Character"
) {
    companion object {
        // أنماط التنصيص العربية والإنجليزية: «...» أو "..." أو “...”
        private val DIALOGUE_REGEX = Regex("([«“\"][^»”\"]+[»”\"])")

        // نمط سطر يبدأ باسم المتحدث يليه نقطتان فوق بعض
        private val SCRIPT_LINE_REGEX = Regex("^\\s*([^:\\r\\n]{1,30})\\s*[:：]\\s*(.+)$")
    }

    fun annotateText(rawText: String): List<DialogueTurn> {
        val trimmed = rawText.trim()
        if (trimmed.isEmpty()) return emptyList()

        // 1. أولاً: التحقق مما إذا كان النص مكتوباً بنمط السيناريو والبودكاست (Script Format)
        val scriptTurns = parseScriptFormat(trimmed)
        if (scriptTurns.size >= 2) {
            return scriptTurns
        }

        // 2. ثانياً: إذا لم يكن سيناريو، التحقق من نمط الاقتباس وعلامات التنصيص (Quotation Format)
        val quoteTurns = parseQuotationFormat(trimmed)
        if (quoteTurns.any { it.speaker == characterSpeakerName }) {
            return quoteTurns
        }

        // 3. ثالثاً: نص فردي بدون حوار (الراوي فقط)
        return listOf(DialogueTurn(narratorSpeakerName, trimmed))
    }

    private fun parseScriptFormat(text: String): List<DialogueTurn> {
        val lines = text.lines()
        val detectedSpeakers = mutableListOf<String>()

        for (line in lines) {
            val match = SCRIPT_LINE_REGEX.find(line)
            if (match != null) {
                val speakerName = match.groupValues[1].trim()
                if (speakerName.isNotEmpty() && !detectedSpeakers.any { it.equals(speakerName, ignoreCase = true) }) {
                    detectedSpeakers.add(speakerName)
                }
            }
        }

        if (detectedSpeakers.isEmpty()) return emptyList()

        val speaker1Alias = detectedSpeakers[0]
        val speaker2Alias = if (detectedSpeakers.size > 1) detectedSpeakers[1] else null

        val turns = mutableListOf<DialogueTurn>()
        var currentSpeaker = narratorSpeakerName
        val currentBuffer = StringBuilder()

        for (line in lines) {
            val match = SCRIPT_LINE_REGEX.find(line)
            if (match != null) {
                if (currentBuffer.isNotBlank()) {
                    turns.add(DialogueTurn(currentSpeaker, currentBuffer.toString().trim()))
                    currentBuffer.clear()
                }

                val speakerName = match.groupValues[1].trim()
                val lineContent = match.groupValues[2].trim()

                currentSpeaker = when {
                    speakerName.equals(speaker1Alias, ignoreCase = true) -> narratorSpeakerName
                    speaker2Alias != null && speakerName.equals(speaker2Alias, ignoreCase = true) -> characterSpeakerName
                    speakerName.contains("راوي", ignoreCase = true) || speakerName.contains("narrator", ignoreCase = true) || speakerName.contains("speaker1", ignoreCase = true) -> narratorSpeakerName
                    else -> characterSpeakerName
                }

                currentBuffer.append(lineContent)
            } else {
                val lineTrimmed = line.trim()
                if (lineTrimmed.isNotEmpty()) {
                    if (currentBuffer.isNotEmpty()) currentBuffer.append("\n")
                    currentBuffer.append(lineTrimmed)
                }
            }
        }

        if (currentBuffer.isNotBlank()) {
            turns.add(DialogueTurn(currentSpeaker, currentBuffer.toString().trim()))
        }

        return turns
    }

    private fun parseQuotationFormat(trimmed: String): List<DialogueTurn> {
        val turns = mutableListOf<DialogueTurn>()
        var lastIndex = 0

        for (match in DIALOGUE_REGEX.findAll(trimmed)) {
            val start = match.range.first
            val end = match.range.last + 1

            if (start > lastIndex) {
                val narration = trimmed.substring(lastIndex, start).trim()
                if (narration.isNotEmpty()) {
                    turns.add(DialogueTurn(narratorSpeakerName, narration))
                }
            }

            val quote = match.value.trim()
            val cleanQuote = quote
                .removePrefix("«").removeSuffix("»")
                .removePrefix("“").removeSuffix("”")
                .removePrefix("\"").removeSuffix("\"")
                .trim()

            if (cleanQuote.isNotEmpty()) {
                turns.add(DialogueTurn(characterSpeakerName, cleanQuote))
            }

            lastIndex = end
        }

        if (lastIndex < trimmed.length) {
            val tailNarration = trimmed.substring(lastIndex).trim()
            if (tailNarration.isNotEmpty()) {
                turns.add(DialogueTurn(narratorSpeakerName, tailNarration))
            }
        }

        return turns
    }

    fun summarizeText(rawText: String): String {
        val turns = annotateText(rawText)
        val narratorCount = turns.count { it.speaker == narratorSpeakerName }
        val characterCount = turns.count { it.speaker == characterSpeakerName }

        return if (characterCount > 0) {
            "حوار ثنائي: $narratorCount للراوي | $characterCount للشخصيات"
        } else {
            "نص فردي: بصوت الراوي فقط"
        }
    }
}
