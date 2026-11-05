package com.antigravity.audiobook.domain

data class DialogueTurn(
    val speaker: String,
    val text: String,
    val stylePrompt: String = ""
)

/**
 * محرك تحليل وتقسيم الحوار لنموذج Gemini 3.8 Flash TTS وفقاً لتوثيق Google الرسمي.
 * يدعم:
 * 1. صيغة السيناريو والبودكاست (Script Format)
 * 2. صيغة الحوار بالشرطات (Dashed Dialogue Format: - / — / – / ـ)
 * 3. صيغة الروايات والاقتباس (Quotation & Inquit Format):
 *    - فرز نصوص الشخصيات والراوي
 *    - تقطيع أفعال القول (Inquit Verbs) ودعم الصرف العربي للأفعال
 *    - تمييز المصطلحات المفردة وعناوين الكتب والاقتباسات المنعزلة وإبقاؤها بصوت الراوي
 *    - استنتاج المشاعر والحالة التعبيرية (Emotion Inference) تلقائياً من سياق السرد
 */
class DialogueTurnAnnotator(
    private val narratorSpeakerName: String = "Narrator",
    private val characterSpeakerName: String = "Character"
) {
    companion object {
        // أنماط التنصيص المزدوجة المقترنة لمنع تداخل الاقتباسات المتداخلة وتفادي بتر الجمل
        private val DIALOGUE_REGEX = Regex(
            "([«][^»]+[»]|[“][^”]+[”]|[\"][^\"]+[\"]|[„][^“]+[“]|[「][^」]+[」]|[『][^』]+[』])"
        )

        // نمط سطر يبدأ باسم المتحدث يليه نقطتان فوق بعض
        private val SCRIPT_LINE_REGEX = Regex("^\\s*([^:\\r\\n]{1,30})\\s*[:：]\\s*(.+)$")

        // أنماط أسطر الحوار بالشرطات (Dashed dialogue lines)
        private val DASH_LINE_REGEX = Regex("^\\s*[-—–ـ]\\s*(.+)$")
        private val DASH_SPLIT_REGEX = Regex("\\s+[-—–ـ]\\s+")
        private val DASH_PREFIX_CHECK = Regex("^\\s*[-—–ـ]")

        // قائمة أفعال القول (Inquit Verbs) عبر لغات متعددة مع توسيع الصيغ الصرفية العربية
        val DIALOGUE_VERBS = setOf(
            // Arabic - Base verbs and common inflections
            "قال", "قالت", "يقول", "تقول", "قلت", "قلنا", "يقولون",
            "سأل", "سألت", "يسأل", "تسأل",
            "أجاب", "أجابت", "يجيب", "تجيب",
            "صاح", "صاحت", "يصيح", "تصيح",
            "هتف", "هتفت", "يهتف", "تهتف",
            "همس", "همست", "يهمس", "تهمس",
            "تمتم", "تمتمت", "يتمتم", "تتمتم",
            "غمغم", "غمغمت", "يغمغم", "تغمغم",
            "رد", "ردت", "يرد", "ترد",
            "أردف", "أردفت", "يردف", "تردف",
            "تابع", "تابعت", "يتابع", "تتابع",
            "واصل", "واصلت", "يواصل", "تواصل",
            "قاطع", "قاطعت", "يقاطع", "تقاطع",
            "أضاف", "أضافت", "يضيف", "تضيف",
            "علق", "علقت", "يعلق", "تعلق",
            "استطرد", "استطردت", "يستطرد", "تستطرد",
            "أوضح", "أوضحت", "يوضح", "توضح",
            // Arabic - Prefixed narrative forms (fa- / wa-)
            "فقال", "فقالت", "وقال", "وقالت", "فيقول", "فتقول", "ويقول", "وتقول",
            "فسأل", "فسألت", "وسأل", "وسألت", "فيسأل", "فتسأل", "ويسأل", "وتسأل",
            "فأجاب", "فأجابت", "وأجاب", "وأجابت", "فيجيب", "فتجيب", "ويجيب", "وتجيب",
            "فصاح", "فصاحت", "وصاح", "وصاحت",
            "فهتف", "فهتفت", "وهتف", "وهتفت",
            "فهمس", "فهمست", "وهمس", "وهمست",
            "فرد", "فردت", "ورد", "وردت",
            "فأردف", "فأردفت", "وأردف", "وأردفت",
            "فتابع", "فتابعت", "وتابع", "وتابعت",
            "فواصل", "فواصلت", "وواصل", "وواصلت",
            "فقاطع", "فقاطعت", "وقاطع", "وقاطعت",
            "فأضاف", "فأضافت", "وأضاف", "وأضافت",
            "فعلق", "فعلقت", "وعلق", "وعلقت",
            // Arabic - Inquit verbal nouns and active participles (Hal / forms)
            "قائل", "قائلاً", "قائلة", "وقائلاً", "فقائلاً",
            "متسائل", "متسائلاً", "متسائلة", "ومتسائلاً", "فمتسائلاً",
            "مجيب", "مجيباً", "مجيبة", "ومجيباً", "فمجيباً",
            "مردف", "مردفاً", "مردفة", "ومردفاً", "فمردفاً",
            "مضيف", "مضيفاً", "مضيفة", "ومضيفاً", "فمضيفاً",
            "هامس", "هامساً", "هامسة",
            "هاتف", "هاتفاً", "هاتفة",
            "صائح", "صائحاً", "صائحة",
            // English
            "said", "says", "asked", "asks", "replied", "replies", "answered", "answers",
            "shouted", "whispered", "cried", "exclaimed", "muttered", "added", "continued",
            // French
            "dit", "disait", "demanda", "répondit", "repondit", "s'écria", "chuchota", "ajouta",
            // Spanish
            "dijo", "decía", "decia", "preguntó", "pregunto", "respondió", "respondio", "exclamó", "susurró", "añadió",
            // German
            "sagte", "fragte", "antwortete", "rief", "flüsterte", "erwiderte",
            // Russian
            "сказаل", "сказала", "спросил", "спросила", "ответил", "ответила"
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

        /**
         * تنظيف الكلمة من علامات الترقيم والأقواس المحيطة
         */
        fun cleanPunctuation(token: String): String {
            return token.trim(
                '،', ',', '.', ':', ';', '؛', '!', '؟', '?', '-', '—', '–', '_',
                '«', '»', '"', '“', '”', '„', '「', '」', '『', '』'
            )
        }

        /**
         * التحقق مما إذا كانت الكلمة فعل قول مع دعم الصرف العربي (السوابق فـ/وـ والتجريد)
         */
        fun isDialogueVerb(word: String): Boolean {
            val clean = cleanPunctuation(word).lowercase()
            if (clean.isEmpty()) return false
            if (clean in DIALOGUE_VERBS) return true

            // تجريد التشكيل والتطويل إن وجد
            val stripped = clean.replace(Regex("[\\u064B-\\u065F\\u0670\\u0640]"), "")
            if (stripped in DIALOGUE_VERBS) return true

            // فحص سوابق العطف والتعقيب العربية: فـ (fa-) أو وـ (wa-)
            if ((stripped.startsWith("ف") || stripped.startsWith("و")) && stripped.length > 3) {
                val withoutPrefix = stripped.substring(1)
                if (withoutPrefix in DIALOGUE_VERBS) return true
            }

            return false
        }

        /**
         * تجريد علامات الاقتباس الخارجية المزدوجة مع الحفاظ على أي اقتباس داخلي
         */
        fun stripOuterQuotes(rawQuote: String): String {
            val trimmed = rawQuote.trim()
            if (trimmed.length < 2) return ""
            return when {
                trimmed.startsWith("«") && trimmed.endsWith("»") -> trimmed.substring(1, trimmed.length - 1)
                trimmed.startsWith("“") && trimmed.endsWith("”") -> trimmed.substring(1, trimmed.length - 1)
                trimmed.startsWith("\"") && trimmed.endsWith("\"") -> trimmed.substring(1, trimmed.length - 1)
                trimmed.startsWith("„") && trimmed.endsWith("“") -> trimmed.substring(1, trimmed.length - 1)
                trimmed.startsWith("「") && trimmed.endsWith("」") -> trimmed.substring(1, trimmed.length - 1)
                trimmed.startsWith("『") && trimmed.endsWith("』") -> trimmed.substring(1, trimmed.length - 1)
                else -> trimmed.trim('«', '»', '“', '”', '"', '„', '「', '」', '『', '』')
            }.trim()
        }

        /**
         * التحقق مما إذا كان النص المقتبس يمثل حواراً أصيلاً لشخصية أم مجرد لفظ منعزل/عنوان/لقب.
         * يطابق قواعد محرك البايثون في gemini_tts_client.py:is_dialogue_quote
         */
        fun isDialogueQuote(
            quoteContent: String,
            precedingText: String,
            followingText: String,
            quoteRaw: String = ""
        ): Boolean {
            val content = quoteContent.trim()
            if (content.isEmpty()) return false

            // أقواس الاقتباس شرق الآسيوية 「...」 و 『...』 تدل حصراً على حوار منطوق
            if (quoteRaw.startsWith("「") || quoteRaw.startsWith("『") ||
                content.startsWith("「") || content.startsWith("『")
            ) {
                return true
            }

            // الجمل الحوارية المحتوية على علامات استفهام أو تعجب
            if (content.any { it in listOf('?', '؟', '!', '！', '؟') }) {
                return true
            }

            // أكثر من كلمتين أو طول لا يقل عن 15 حرفاً
            val words = content.split(Regex("\\s+")).filter { it.isNotEmpty() }
            if (words.size >= 3 || content.length >= 15) {
                return true
            }

            // السياق السابق ينتهي بنقطتين أو شرطة توحي بالحوار
            val precTail = precedingText.trim().takeLast(30)
            if (precTail.endsWith(":") || precTail.endsWith("：") ||
                precTail.endsWith("—") || precTail.endsWith("-") || precTail.endsWith("–")
            ) {
                return true
            }

            // وجود أفعال قول في الكلمات الثلاث الأخيرة قبل الاقتباس
            val precWords = precTail.split(Regex("\\s+"))
                .map { cleanPunctuation(it) }
                .filter { it.isNotEmpty() }
            if (precWords.takeLast(3).any { isDialogueVerb(it) }) {
                return true
            }

            // وجود أفعال قول في الكلمات الثلاث الأولى بعد الاقتباس
            val follHead = followingText.trim().take(30)
            val follWords = follHead.split(Regex("\\s+"))
                .map { cleanPunctuation(it) }
                .filter { it.isNotEmpty() }
            if (follWords.take(3).any { isDialogueVerb(it) }) {
                return true
            }

            return false
        }
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

        // 2. ثانياً: التحقق من نمط الحوار بالشرطات (Dashed Dialogue Format)
        val dashedTurns = parseDashedDialogueFormat(trimmed, inferEmotions)
        if (dashedTurns.any { it.speaker == characterSpeakerName }) {
            return dashedTurns
        }

        // 3. ثالثاً: التحقق من نمط الاقتباس وعلامات التنصيص (Quotation Format)
        val quoteTurns = parseQuotationFormat(trimmed, inferEmotions)
        if (quoteTurns.any { it.speaker == characterSpeakerName }) {
            return quoteTurns
        }

        // 4. رابعاً: نص فردي بدون حوار (الراوي فقط)
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

    /**
     * استخراج أدوار الحوار من أسطر الروايات المبدوءة بشرطات (- / — / – / ـ)
     * مع فصل نصوص السرد المتخللة أو اللاحقة تلقائياً
     */
    private fun parseDashedDialogueFormat(text: String, inferEmotions: Boolean): List<DialogueTurn> {
        val lines = text.lines().map { it.trim() }.filter { it.isNotEmpty() }
        val hasDashes = lines.any { DASH_PREFIX_CHECK.containsMatchIn(it) }
        if (!hasDashes) return emptyList()

        val rawTurns = mutableListOf<DialogueTurn>()
        var lastNarratorContext = ""

        for (line in lines) {
            val dashMatch = DASH_LINE_REGEX.find(line)
            if (dashMatch != null) {
                val contentLine = dashMatch.groupValues[1].trim()
                val parts = contentLine.split(DASH_SPLIT_REGEX).map { it.trim() }.filter { it.isNotEmpty() }

                if (parts.size <= 1) {
                    val inferredStyle = if (inferEmotions) inferEmotionStyle(lastNarratorContext) else ""
                    rawTurns.add(DialogueTurn(characterSpeakerName, contentLine, inferredStyle))
                } else if (parts.size == 2) {
                    val p1 = parts[0]
                    val p2 = parts[1]
                    val firstWord = p2.split(Regex("\\s+")).firstOrNull()?.let { cleanPunctuation(it) } ?: ""
                    val isInquit = isDialogueVerb(firstWord) || (firstWord.isNotEmpty() && firstWord[0].isLowerCase())

                    if (isInquit) {
                        val inferredStyle = if (inferEmotions) {
                            val leadingStyle = inferEmotionStyle(lastNarratorContext)
                            if (leadingStyle.isNotEmpty()) leadingStyle else inferEmotionStyle(p2)
                        } else ""
                        rawTurns.add(DialogueTurn(characterSpeakerName, p1, inferredStyle))
                        rawTurns.add(DialogueTurn(narratorSpeakerName, p2))
                        lastNarratorContext = p2
                    } else {
                        val inferredStyle = if (inferEmotions) inferEmotionStyle(lastNarratorContext) else ""
                        rawTurns.add(DialogueTurn(characterSpeakerName, contentLine, inferredStyle))
                    }
                } else {
                    // 3 أجزاء أو أكثر: حوار - سرد/فعل قول - حوار
                    for ((idx, seg) in parts.withIndex()) {
                        if (idx % 2 == 0) {
                            val inferredStyle = if (inferEmotions) inferEmotionStyle(lastNarratorContext) else ""
                            rawTurns.add(DialogueTurn(characterSpeakerName, seg, inferredStyle))
                        } else {
                            rawTurns.add(DialogueTurn(narratorSpeakerName, seg))
                            lastNarratorContext = seg
                        }
                    }
                }
            } else {
                rawTurns.add(DialogueTurn(narratorSpeakerName, line))
                lastNarratorContext = line
            }
        }

        // دمج الأدوار المتتالية لنفس المتحدث لضمان سلاسة الإلقاء
        val merged = mutableListOf<DialogueTurn>()
        for (turn in rawTurns) {
            val txt = turn.text.trim()
            if (txt.isEmpty()) continue
            if (merged.isNotEmpty() && merged.last().speaker == turn.speaker) {
                val prev = merged.removeAt(merged.size - 1)
                val combinedStyle = if (prev.stylePrompt.isNotEmpty()) prev.stylePrompt else turn.stylePrompt
                merged.add(DialogueTurn(prev.speaker, "${prev.text} $txt", combinedStyle))
            } else {
                merged.add(turn.copy(text = txt))
            }
        }

        return merged
    }

    private fun parseQuotationFormat(trimmed: String, inferEmotions: Boolean): List<DialogueTurn> {
        val rawTurns = mutableListOf<DialogueTurn>()
        var lastIndex = 0
        var lastNarratorContext = ""

        val matches = DIALOGUE_REGEX.findAll(trimmed).toList()
        for (match in matches) {
            val start = match.range.first
            val end = match.range.last + 1

            if (start > lastIndex) {
                val narration = trimmed.substring(lastIndex, start).trim()
                if (cleanPunctuation(narration).isNotEmpty()) {
                    rawTurns.add(DialogueTurn(narratorSpeakerName, narration))
                    lastNarratorContext = narration
                }
            }

            val quoteRaw = match.value.trim()
            val cleanQuote = stripOuterQuotes(quoteRaw)

            val prec = trimmed.substring(0, start)
            val foll = trimmed.substring(end)

            if (isDialogueQuote(cleanQuote, prec, foll, quoteRaw)) {
                var inferredStyle = ""
                if (inferEmotions) {
                    if (lastNarratorContext.isNotEmpty()) {
                        inferredStyle = inferEmotionStyle(lastNarratorContext)
                    }
                    if (inferredStyle.isEmpty() && end < trimmed.length) {
                        val nextWindow = trimmed.substring(end, (end + 60).coerceAtMost(trimmed.length))
                        inferredStyle = inferEmotionStyle(nextWindow)
                    }
                }
                if (cleanQuote.isNotEmpty()) {
                    rawTurns.add(DialogueTurn(characterSpeakerName, cleanQuote, inferredStyle))
                }
            } else {
                // مصطلح أو اسم كتاب أو لقب معزول - يحفظ لصوت الراوي
                rawTurns.add(DialogueTurn(narratorSpeakerName, quoteRaw))
                lastNarratorContext = quoteRaw
            }

            lastIndex = end
        }

        if (lastIndex < trimmed.length) {
            val tailNarration = trimmed.substring(lastIndex).trim()
            if (cleanPunctuation(tailNarration).isNotEmpty()) {
                rawTurns.add(DialogueTurn(narratorSpeakerName, tailNarration))
            }
        }

        // دمج الأدوار المتتالية لنفس المتحدث
        val merged = mutableListOf<DialogueTurn>()
        for (turn in rawTurns) {
            val txt = turn.text.trim()
            if (txt.isEmpty()) continue
            if (merged.isNotEmpty() && merged.last().speaker == turn.speaker) {
                val prev = merged.removeAt(merged.size - 1)
                val combinedStyle = if (prev.stylePrompt.isNotEmpty()) prev.stylePrompt else turn.stylePrompt
                merged.add(DialogueTurn(prev.speaker, "${prev.text} $txt", combinedStyle))
            } else {
                merged.add(turn.copy(text = txt))
            }
        }

        return merged
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
