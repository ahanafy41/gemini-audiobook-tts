package com.antigravity.audiobook.domain

/**
 * أنماط الإلقاء الصوتي الموجهة لنموذج Gemini 3.8 Flash TTS.
 * يتم حقن بادئة التوجيه الإخراجي (Director Prompt) في بداية النص لتحفيز الأداء بدون نطق الوسم.
 */
enum class VoiceStylePreset(
    val id: String,
    val titleArabic: String,
    val descriptionArabic: String,
    val titleEnglish: String,
    val descriptionEnglish: String,
    val directorPrompt: String
) {
    NATURAL(
        id = "natural",
        titleArabic = "طبيعي",
        descriptionArabic = "قراءة هادئة وواضحة تناسب معظم الكتب والمقالات العامة.",
        titleEnglish = "Natural",
        descriptionEnglish = "Calm, balanced narration ideal for most books and general articles.",
        directorPrompt = "[Style: Natural, warm, balanced audiobook narration]"
    ),
    DOCUMENTARY(
        id = "documentary",
        titleArabic = "وثائقي",
        descriptionArabic = "نبرة وقورة وموضوعية ذات إيقاع متزن، ممتازة للمراجع وكتب التاريخ والدراسات العلمية.",
        titleEnglish = "Documentary",
        descriptionEnglish = "Authoritative, solemn historical tone with measured cadence; great for history and academic studies.",
        directorPrompt = "[Style: Authoritative, solemn historical documentary narration, grave baritone, deliberate and measured cadence]"
    ),
    DRAMATIC(
        id = "dramatic",
        titleArabic = "درامي",
        descriptionArabic = "نبرة تعبيرية غنية بالمشاعر والإثارة السينمائية، مثالية للروايات والقصص المشوقة.",
        titleEnglish = "Dramatic",
        descriptionEnglish = "Expressive cinematic narration filled with suspense and emotion; perfect for novels and fiction.",
        directorPrompt = "[Style: Dramatic, cinematic, intense suspense, breathless anticipation and emotional charge]"
    ),
    CALM(
        id = "calm",
        titleArabic = "هادئ",
        descriptionArabic = "صوت ناعم ومسترخٍ بإيقاع بطيء، مثالي لكتب ما قبل النوم والتأمل والاسترخاء.",
        titleEnglish = "Calm & Soothing",
        descriptionEnglish = "Gentle, whispery voice with slow pacing; ideal for bedtime stories and relaxation.",
        directorPrompt = "[Style: Whispering, gentle bedtime story, deeply relaxing, slow peaceful pacing]"
    );

    fun title(isArabic: Boolean): String = if (isArabic) titleArabic else titleEnglish
    fun description(isArabic: Boolean): String = if (isArabic) descriptionArabic else descriptionEnglish

    companion object {
        fun fromId(id: String?): VoiceStylePreset {
            return entries.firstOrNull { it.id.equals(id, ignoreCase = true) } ?: NATURAL
        }

        fun getAccessibleDisplayList(isArabic: Boolean = true): Array<String> {
            return entries.map { "${it.title(isArabic)}: ${it.description(isArabic)}" }.toTypedArray()
        }
    }
}
