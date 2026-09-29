package com.antigravity.audiobook.domain

import org.json.JSONArray
import org.json.JSONObject

/**
 * إعدادات الحوار ثنائي الرواة (Multi-Speaker) لنموذج Gemini 3.8 Flash TTS.
 * تدعم متحدثين اثنين: الراوي الأساسي (Narrator) والمتحدث الحواري (Character).
 */
data class MultiSpeakerConfig(
    val isEnabled: Boolean = false,
    val narratorVoice: VoiceProfile = VoiceProfile.defaultNarrator(),
    val characterVoice: VoiceProfile = VoiceProfile.defaultCharacter()
) {
    fun toSpeechConfigJson(): JSONObject {
        val config = JSONObject()
        val multiSpeaker = JSONObject()
        val speakerArray = JSONArray()

        // المتحدث 1: الراوي
        val speaker1 = JSONObject().apply {
            put("speaker", "Narrator")
            put("voiceConfig", JSONObject().apply {
                if (narratorVoice.isCustomVoiceDesign) {
                    put("voice", narratorVoice.id)
                } else {
                    put("prebuiltVoiceConfig", JSONObject().apply {
                        put("voiceName", narratorVoice.id)
                    })
                }
            })
        }
        speakerArray.put(speaker1)

        // المتحدث 2: الشخصية
        val speaker2 = JSONObject().apply {
            put("speaker", "Character")
            put("voiceConfig", JSONObject().apply {
                if (characterVoice.isCustomVoiceDesign) {
                    put("voice", characterVoice.id)
                } else {
                    put("prebuiltVoiceConfig", JSONObject().apply {
                        put("voiceName", characterVoice.id)
                    })
                }
            })
        }
        speakerArray.put(speaker2)

        multiSpeaker.put("speakerVoiceConfigs", speakerArray)
        config.put("multiSpeakerVoiceConfig", multiSpeaker)
        return config
    }
}
