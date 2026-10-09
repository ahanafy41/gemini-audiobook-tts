package com.antigravity.audiobook.domain

/**
 * أنماط الإلقاء الصوتي الموجهة لنموذج Gemini 3.8 Flash TTS.
 * يتم حقن بادئة التوجيه الإخراجي (Director Prompt) في بداية النص لتحفيز الأداء بدون نطق الوسم.
 */
enum class VoiceStylePreset(
    val id: String,
    val titleArabic: String,
    val descriptionArabic: String,
    val directorPrompt: String
) {
    NATURAL(
        id = "natural",
        titleArabic = "طبيعي",
        descriptionArabic = "قراءة هادئة وواضحة تناسب معظم الكتب والمقالات العامة.",
        directorPrompt = "[Style: Natural, warm, balanced audiobook narration]"
    ),
    DOCUMENTARY(
        id = "documentary",
        titleArabic = "وثائقي",
        descriptionArabic = "نبرة وقورة وموضوعية ذات إيقاع متزن، ممتازة للمراجع وكتب التاريخ والدراسات العلمية.",
        directorPrompt = "[Style: Authoritative, solemn historical documentary narration, grave baritone, deliberate and measured cadence]"
    ),
    DRAMATIC(
        id = "dramatic",
        titleArabic = "درامي",
        descriptionArabic = "نبرة تعبيرية غنية بالمشاعر والإثارة السينمائية، مثالية للروايات والقصص المشوقة.",
        directorPrompt = "[Style: Dramatic, cinematic, intense suspense, breathless anticipation and emotional charge]"
    ),
    CALM(
        id = "calm",
        titleArabic = "هادئ",
        descriptionArabic = "صوت ناعم ومسترخٍ بإيقاع بطيء، مثالي لكتب ما قبل النوم والتأمل والاسترخاء.",
        directorPrompt = "[Style: Whispering, gentle bedtime story, deeply relaxing, slow peaceful pacing]"
    );

    companion object {
        fun fromId(id: String?): VoiceStylePreset {
            return entries.firstOrNull { it.id.equals(id, ignoreCase = true) } ?: NATURAL
        }

        fun getAccessibleDisplayList(): Array<String> {
            return entries.map { "${it.titleArabic}: ${it.descriptionArabic}" }.toTypedArray()
        }
    }
}
