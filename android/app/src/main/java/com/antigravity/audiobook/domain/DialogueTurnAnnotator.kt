package com.antigravity.audiobook.domain

data class DialogueTurn(
    val speaker: String,
    val text: String
)

/**
 * محلل الحوار الذكي للكتب والروايات العربية.
 * يفرز النصوص المحصورة بين علامات التنصيص العربية والإنجليزية ككلام للشخصيات،
 * ويخصص باقي النص لصوت الراوي الأساسي.
 */
class DialogueTurnAnnotator(
    private val narratorSpeakerName: String = "Narrator",
    private val characterSpeakerName: String = "Character"
) {
    companion object {
        // أنماط التنصيص العربية والإنجليزية: «...» أو "..." أو “...”
        private val DIALOGUE_REGEX = Regex("([«“\"][^»”\"]+[»”\"])")
    }

    fun annotateText(rawText: String): List<DialogueTurn> {
        val trimmed = rawText.trim()
        if (trimmed.isEmpty()) return emptyList()

        val turns = mutableListOf<DialogueTurn>()
        var lastIndex = 0

        for (match in DIALOGUE_REGEX.findAll(trimmed)) {
            val start = match.range.first
            val end = match.range.last + 1

            // النص السابق لعلامة التنصيص (كلام الراوي)
            if (start > lastIndex) {
                val narration = trimmed.substring(lastIndex, start).trim()
                if (narration.isNotEmpty()) {
                    turns.add(DialogueTurn(narratorSpeakerName, narration))
                }
            }

            // النص المحصور بين علامات التنصيص (كلام الشخصية)
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

        // النص المتبقي بعد آخر حوار
        if (lastIndex < trimmed.length) {
            val tailNarration = trimmed.substring(lastIndex).trim()
            if (tailNarration.isNotEmpty()) {
                turns.add(DialogueTurn(narratorSpeakerName, tailNarration))
            }
        }

        return if (turns.isNotEmpty()) turns else listOf(DialogueTurn(narratorSpeakerName, trimmed))
    }
}
