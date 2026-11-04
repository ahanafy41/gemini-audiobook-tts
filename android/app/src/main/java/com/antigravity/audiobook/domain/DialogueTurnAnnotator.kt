package com.antigravity.audiobook.domain

import java.util.regex.Pattern

data class DialogueTurn(
    val speaker: String,
    val text: String,
    val stylePrompt: String = ""
)

/**
 * محرك تحليل وتقسيم الحوار لنموذج Gemini 3.8 Flash TTS وفقاً لتوثيق Google الرسمي.
 * يدعم:
 * 1. صيغة السيناريو والبودكاست (Script Format)
 * 2. صيغة الروايات والاقتباس (Quotation & Inquit Format):
 *    - فرز نصوص الشخصيات والراوي
 *    - تقطيع أفعال القول (Inquit Verbs)
 *    - استنتاج المشاعر والحالة التعبيرية (Emotion Inference) تلقائياً من سياق السرد
 */
class DialogueTurnAnnotator(
    private val narratorSpeakerName: String = "Narrator",
    private val characterSpeakerName: String = "Character"
) {
    companion object {
        // أنماط التنصيص العالمية: «...» أو "..." أو “...” أو „...“ أو 「...」
        private val DIALOGUE_REGEX = Regex("([«“\"„「『][^»”\"“」』]+[»”\"“」』])")

        // نمط سطر يبدأ باسم المتحدث يليه نقطتان فوق بعض
        private val SCRIPT_LINE_REGEX = Regex("^\\s*([^:\\r\\n]{1,30})\\s*[:：]\\s*(.+)$")

        // قائمة أفعال القول (Inquit Verbs) عبر لغات متعددة
        val DIALOGUE_VERBS = setOf(
            // Arabic
            "قال", "قالت", "يقول", "تقول", "سأل", "سألت", "يسأل", "تسأل",
            "أجاب", "أجابت", "يجيب", "تجيب", "صاح", "صاحت", "يصيح", "تصيح",
            "هتف", "هتفت", "يهتف", "تهتف", "همس", "همست", "يهمس", "تهمس",
            "تمتم", "تمتمت", "غمغم", "غمغمت", "رد", "ردت", "يرد", "ترد",
            "أردف", "أردفت", "تابع", "تابعت", "قاطع", "قاطعت", "أضاف", "أضافت",
            // English
            "said", "says", "asked", "asks", "replied", "replies", "answered", "answers",
            "shouted", "whispered", "cried", "exclaimed", "muttered", "added", "continued",
            // French
            "dit", "disait", "demanda", "répondit", "s'écria", "chuchota",
            // Spanish
            "dijo", "preguntó", "respondió", "exclamó", "susurró",
            // German
            "sagte", "fragte", "antwortete", "rief", "flüsterte"
        )

        // قواعد استنتاج المشاعر من سياق السرد العربي
        val EMOTION_CUES = listOf(
            Pair(
                Regex("(همس|بهمس|بصوت خافت|بصوت منخفض|همست|يهمس|تسرّ|بسرية)"),
                "whispered urgently, quiet hushed tone"
            ),
            Pair(
                Regex("(صرخ|بغضب|صاح|هتف|بانفعال|بحدة|صرخت|صاحت|غاضب|بصوت عال)"),
                "shouting with anger, intense and forceful delivery"
            ),
            Pair(
                Regex("(بحزن|ببكاء|بأسى|بألم|دموع|بكى|بكت|حزين|متأثراً|بصوت متهدج)"),
                "sad, emotional, tearful and trembling voice"
            ),
            Pair(
                Regex("(مبتسماً|بفرح|بسعادة|ضاحكاً|بابتسامة|مبتهجاً|فرحاً|بمرح)"),
                "cheerful, warm smiling and joyful tone"
            ),
            Pair(
                Regex("(بدهشة|بخوف|بذهول|برعب|مذعوراً|متفاجئاً|بارتباك|مرتجفاً)"),
                "gasping, fearful and surprised tone"
            ),
            Pair(
                Regex("(بهدوء|بسكينة|برزانة|بوَقار|بثقة|بصوت هادئ|بحكمة)"),
                "calm, composed, steady and reassuring tone"
            )
        )
    }

    fun inferEmotionStyle(surroundingText: String): String {
        for ((regex, style) in EMOTION_CUES) {
            if (regex.containsMatchIn(surroundingText)) {
                return style
            }
        }
        return ""
    }

    fun annotateText(rawText: String, inferEmotions: Boolean = true): List<DialogueTurn> {
        val trimmed = rawText.trim()
        if (trimmed.isEmpty()) return emptyList()

        // 1. أولاً: التحقق مما إذا كان النص مكتوباً بنمط السيناريو والبودكاست (Script Format)
        val scriptTurns = parseScriptFormat(trimmed)
        if (scriptTurns.size >= 2) {
            return scriptTurns
        }

        // 2. ثانياً: إذا لم يكن سيناريو، التحقق من نمط الاقتباس وعلامات التنصيص (Quotation Format)
        val quoteTurns = parseQuotationFormat(trimmed, inferEmotions)
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

    private fun parseQuotationFormat(trimmed: String, inferEmotions: Boolean): List<DialogueTurn> {
        val turns = mutableListOf<DialogueTurn>()
        var lastIndex = 0

        for (match in DIALOGUE_REGEX.findAll(trimmed)) {
            val start = match.range.first
            val end = match.range.last + 1

            var inferredStyle = ""
            if (start > lastIndex) {
                val narration = trimmed.substring(lastIndex, start).trim()
                if (narration.isNotEmpty()) {
                    turns.add(DialogueTurn(narratorSpeakerName, narration))
                    if (inferEmotions) {
                        inferredStyle = inferEmotionStyle(narration)
                    }
                }
            }

            val quote = match.value.trim()
            val cleanQuote = quote
                .removePrefix("«").removeSuffix("»")
                .removePrefix("“").removeSuffix("”")
                .removePrefix("\"").removeSuffix("\"")
                .removePrefix("„").removeSuffix("“")
                .removePrefix("「").removeSuffix("」")
                .removePrefix("『").removeSuffix("』")
                .trim()

            // Check if trailing narrative has emotion cue if leading didn't
            if (inferredStyle.isEmpty() && inferEmotions && end < trimmed.length) {
                val nextWindow = trimmed.substring(end, (end + 60).coerceAtMost(trimmed.length))
                inferredStyle = inferEmotionStyle(nextWindow)
            }

            if (cleanQuote.isNotEmpty()) {
                turns.add(DialogueTurn(characterSpeakerName, cleanQuote, inferredStyle))
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
