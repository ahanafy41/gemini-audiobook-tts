package com.antigravity.audiobook.domain

/**
 * يمثل ملف تعريف الصوت الصادر عن Gemini 3.8 Flash TTS،
 * سواء كان صوتاً مسبق الصنع (Prebuilt) أو معرف صوت مخصص من Voice Design.
 */
data class VoiceProfile(
    val id: String,
    val displayNameArabic: String,
    val isCustomVoiceDesign: Boolean = false,
    val descriptionArabic: String = ""
) {
    companion object {
        val PREBUILT_VOICES = listOf(
            VoiceProfile("Charon", "شارون (Charon) - باريتون فخم ورصين", false, "رجالي وقور، رائع للتاريخ والوثائقيات والروايات الجادة"),
            VoiceProfile("Kore", "كوري (Kore) - ألتو متوازن وقوي", false, "نسائي واثق رصين، مثالي للمتون والمقالات والروايات"),
            VoiceProfile("Fenrir", "فنرير (Fenrir) - تينور حماسي سريع", false, "رجالي قوي ذو طابع حركي ومسرحي"),
            VoiceProfile("Zephyr", "زيفير (Zephyr) - سوبرانو ناعم خفيف", false, "نسائي هادئ دافئ، مثالي للتأمل وقصص ما قبل النوم"),
            VoiceProfile("Puck", "باك (Puck) - تينور مرح ومبهج", false, "رجالي رشيق وتفاعلي للقصص والحوارات السريعة"),
            VoiceProfile("Aoede", "أويدي (Aoede) - سوبرانو دافئ انسيابي", false, "نسائي شجي وطبيعي للمذكرات وأدب الرحلات"),
            VoiceProfile("Orus", "أوروس (Orus) - باريتون حكيم ومستقر", false, "رجالي رزين ومتزن للفلسفة والدراسات الفكرية"),
            VoiceProfile("Leda", "ليدا (Leda) - سوبرانو مبهج شبابي", false, "نسائي حيوي مشرق لليافعين والحكايات"),
            VoiceProfile("Achird", "أشيرد (Achird) - باريتون ودود محادث", false, "رجالي اجتماعي ومريح للبودكاست وتطوير الذات"),
            VoiceProfile("Alnilam", "النيلام (Alnilam) - باريتون قاطع وصارم", false, "رجالي حاسم للتاريخ العسكري والتحليلات"),
            VoiceProfile("Despina", "ديسبينا (Despina) - ألتو مخملي راقٍ", false, "نسائي فاره وفصيح للأدب الكلاسيكي"),
            VoiceProfile("Gacrux", "جاكروكس (Gacrux) - باس وقور مهيب", false, "رجالي شيخوخي حكيم للأساطير والملاحم التراثية"),
            VoiceProfile("Sadaltager", "سعد التاجر (Sadaltager) - باريتون أكاديمي عالم", false, "رجالي متأنٍ لأمهات كتب الفكر والحضارة")
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
                descriptionArabic = "معرف صوت مخصص مولد بالذكاء الاصطناعي عبر Voice Design"
            )
        }
    }
}
