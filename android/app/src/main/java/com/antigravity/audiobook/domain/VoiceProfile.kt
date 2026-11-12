package com.antigravity.audiobook.domain

/**
 * يمثل ملف تعريف الصوت الصادر عن Gemini 3.8 Flash TTS،
 * سواء كان صوتاً مسبق الصنع (Prebuilt) أو معرف صوت مخصص من Voice Design.
 */
data class VoiceProfile(
    val id: String,
    val displayNameArabic: String,
    val isCustomVoiceDesign: Boolean = false,
    val descriptionArabic: String = "",
    val displayNameEnglish: String = displayNameArabic,
    val descriptionEnglish: String = descriptionArabic
) {
    fun displayName(isArabic: Boolean): String = if (isArabic) displayNameArabic else displayNameEnglish
    fun description(isArabic: Boolean): String = if (isArabic) descriptionArabic else descriptionEnglish

    companion object {
        val PREBUILT_VOICES = listOf(
            VoiceProfile(
                "Charon",
                "شارون (Charon) - باريتون فخم ورصين",
                false,
                "رجالي وقور، رائع للتاريخ والوثائقيات والروايات الجادة",
                "Charon - Deep Resonant Baritone",
                "Male authoritative tone; great for history, documentaries, and serious literature"
            ),
            VoiceProfile(
                "Kore",
                "كوري (Kore) - ألتو متوازن وقوي",
                false,
                "نسائي واثق رصين، مثالي للمتون والمقالات والروايات",
                "Kore - Balanced Dynamic Alto",
                "Female confident tone; ideal for essays, novels, and general reading"
            ),
            VoiceProfile(
                "Fenrir",
                "فنرير (Fenrir) - تينور حماسي سريع",
                false,
                "رجالي قوي ذو طابع حركي ومسرحي",
                "Fenrir - Energetic Theatrical Tenor",
                "Male powerful voice with lively dramatic pacing"
            ),
            VoiceProfile(
                "Zephyr",
                "زيفير (Zephyr) - سوبرانو ناعم خفيف",
                false,
                "نسائي هادئ دافئ، مثالي للتأمل وقصص ما قبل النوم",
                "Zephyr - Gentle Soft Soprano",
                "Female soothing warm voice; perfect for meditation and bedtime stories"
            ),
            VoiceProfile(
                "Puck",
                "باك (Puck) - تينور مرح ومبهج",
                false,
                "رجالي رشيق وتفاعلي للقصص والحوارات السريعة",
                "Puck - Playful Cheerful Tenor",
                "Male agile, friendly voice for dialogues and fast-paced stories"
            ),
            VoiceProfile(
                "Aoede",
                "أويدي (Aoede) - سوبرانو دافئ انسيابي",
                false,
                "نسائي شجي وطبيعي للمذكرات وأدب الرحلات",
                "Aoede - Melodic Flowing Soprano",
                "Female natural, lyrical voice for memoirs and travel literature"
            ),
            VoiceProfile(
                "Orus",
                "أوروس (Orus) - باريتون حكيم ومستقر",
                false,
                "رجالي رزين ومتزن للفلسفة والدراسات الفكرية",
                "Orus - Wise Philosophical Baritone",
                "Male steady and reflective voice for philosophy and deep studies"
            ),
            VoiceProfile(
                "Leda",
                "ليدا (Leda) - سوبرانو مبهج شبابي",
                false,
                "نسائي حيوي مشرق لليافعين والحكايات",
                "Leda - Bright Youthful Soprano",
                "Female vibrant, engaging voice for young adult books and fables"
            ),
            VoiceProfile(
                "Achird",
                "أشيرد (Achird) - باريتون ودود محادث",
                false,
                "رجالي اجتماعي ومريح للبودكاست وتطوير الذات",
                "Achird - Conversational Warm Baritone",
                "Male approachable voice for podcasts, biographies, and self-help"
            ),
            VoiceProfile(
                "Alnilam",
                "النيلام (Alnilam) - باريتون قاطع وصارم",
                false,
                "رجالي حاسم للتاريخ العسكري والتحليلات",
                "Alnilam - Crisp Decisive Baritone",
                "Male clear and firm voice for military history and analysis"
            ),
            VoiceProfile(
                "Despina",
                "ديسبينا (Despina) - ألتو مخملي راقٍ",
                false,
                "نسائي فاره وفصيح للأدب الكلاسيكي",
                "Despina - Elegant Velvet Alto",
                "Female polished, articulate voice for classical literature"
            ),
            VoiceProfile(
                "Gacrux",
                "جاكروكس (Gacrux) - باس وقور مهيب",
                false,
                "رجالي شيخوخي حكيم للأساطير والملاحم التراثية",
                "Gacrux - Venerable Solemn Bass",
                "Male deep, grand voice for epics, folklore, and heritage sagas"
            ),
            VoiceProfile(
                "Sadaltager",
                "سعد التاجر (Sadaltager) - باريتون أكاديمي عالم",
                false,
                "رجالي متأنٍ لأمهات كتب الفكر والحضارة",
                "Sadaltager - Scholarly Academic Baritone",
                "Male measured, deliberate voice for foundational texts and humanities"
            )
        )

        fun defaultNarrator(): VoiceProfile = PREBUILT_VOICES[0] // Charon
        fun defaultCharacter(): VoiceProfile = PREBUILT_VOICES[1] // Kore

        fun fromStoredString(stored: String): VoiceProfile {
            val trimmed = stored.trim()
            if (trimmed.isEmpty()) return defaultNarrator()

            val prebuilt = PREBUILT_VOICES.firstOrNull { it.id.equals(trimmed, ignoreCase = true) }
            if (prebuilt != null) return prebuilt

            return VoiceProfile(
                id = trimmed,
                displayNameArabic = "صوت مخصص: $trimmed",
                isCustomVoiceDesign = true,
                descriptionArabic = "معرف صوت مخصص مولد بالذكاء الاصطناعي عبر Voice Design",
                displayNameEnglish = "Custom Voice: $trimmed",
                descriptionEnglish = "Custom AI-generated voice design identifier"
            )
        }
    }
}
