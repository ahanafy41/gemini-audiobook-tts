package com.antigravity.audiobook.data

import android.util.Base64
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import com.antigravity.audiobook.domain.DialogueTurnAnnotator
import com.antigravity.audiobook.domain.MultiSpeakerConfig
import com.antigravity.audiobook.domain.VoiceProfile
import com.antigravity.audiobook.domain.VoiceStylePreset
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import kotlin.math.sin

/**
 * Gemini 3.8 Flash TTS Client for Android.
 * Communicates with Google's Gemini TTS endpoint using OkHttp,
 * supports style presets, multi-speaker dialogue, and custom Voice Design IDs.
 */
class GeminiTtsClient(
    private val apiKey: String,
    private val modelId: String = DEFAULT_MODEL_ID,
    private val customEndpoint: String? = null
) {

    companion object {
        const val DEFAULT_MODEL_ID = "gemini-3.8-flash-tts"
        val APPROVED_VOICES = VoiceProfile.PREBUILT_VOICES.map { it.id }
        val GEMINI_VOICES = APPROVED_VOICES
        private const val BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
        private const val TAG = "GeminiTtsClient"
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        fun createWavHeader(
            pcmData: ByteArray,
            sampleRate: Int = 24000,
            channels: Short = 1,
            bitsPerSample: Short = 16
        ): ByteArray {
            val byteRate = sampleRate * channels * (bitsPerSample / 8)
            val blockAlign = (channels * (bitsPerSample / 8)).toShort()
            val dataSize = pcmData.size
            val fileSize = 36 + dataSize

            val buffer = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
            buffer.put("RIFF".toByteArray())
            buffer.putInt(fileSize)
            buffer.put("WAVE".toByteArray())
            buffer.put("fmt ".toByteArray())
            buffer.putInt(16) // Subchunk1Size for PCM
            buffer.putShort(1) // AudioFormat 1 = Linear PCM
            buffer.putShort(channels)
            buffer.putInt(sampleRate)
            buffer.putInt(byteRate)
            buffer.putShort(blockAlign)
            buffer.putShort(bitsPerSample)
            buffer.put("data".toByteArray())
            buffer.putInt(dataSize)

            val header = buffer.array()
            val fullWav = ByteArray(header.size + pcmData.size)
            System.arraycopy(header, 0, fullWav, 0, header.size)
            System.arraycopy(pcmData, 0, fullWav, header.size, pcmData.size)
            return fullWav
        }

        fun generateSyntheticWav(durationSeconds: Double = 1.0, sampleRate: Int = 24000): ByteArray {
            val totalSamples = (durationSeconds * sampleRate).toInt()
            val amplitude = 12000.0
            val frequencyHz = 440.0
            val pcmBuffer = ByteBuffer.allocate(totalSamples * 2).order(ByteOrder.LITTLE_ENDIAN)

            for (i in 0 until totalSamples) {
                val envelope = sin(Math.PI * i / totalSamples)
                val sampleVal = (amplitude * envelope * sin(2.0 * Math.PI * frequencyHz * (i.toDouble() / sampleRate))).toInt()
                pcmBuffer.putShort(sampleVal.coerceIn(-32768, 32767).toShort())
            }

            return createWavHeader(pcmBuffer.array(), sampleRate = sampleRate)
        }
    }

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    fun hasApiKey(): Boolean = apiKey.isNotBlank() && apiKey.trim().length >= 15

    suspend fun synthesize(
        text: String,
        voiceName: String = "Charon",
        stylePreset: VoiceStylePreset = VoiceStylePreset.NATURAL,
        multiSpeakerConfig: MultiSpeakerConfig? = null
    ): ByteArray = withContext(Dispatchers.IO) {
        val cleanText = text.trim()
        if (cleanText.isEmpty()) {
            return@withContext generateSyntheticWav(0.1)
        }

        if (!hasApiKey()) {
            throw IllegalArgumentException("API key is not configured.")
        }

        val url = customEndpoint ?: "$BASE_URL/$modelId:generateContent?key=$apiKey"

        val payload = JSONObject()
        val generationConfig = JSONObject().apply {
            put("responseModalities", JSONArray().apply {
                put("AUDIO")
            })
        }

        if (multiSpeakerConfig != null && multiSpeakerConfig.isEnabled) {
            val annotator = DialogueTurnAnnotator("Narrator", "Character")
            val turns = annotator.annotateText(cleanText)
            val partsArray = JSONArray()
            for (index in turns.indices) {
                val turn = turns[index]
                val turnText = if (index == 0 && stylePreset != VoiceStylePreset.NATURAL) {
                    "${stylePreset.directorPrompt}\n${turn.text}"
                } else {
                    turn.text
                }
                partsArray.put(JSONObject().apply {
                    put("text", turnText)
                    put("speechMetadata", JSONObject().apply {
                        put("speaker", turn.speaker)
                    })
                })
            }
            payload.put("contents", JSONArray().apply {
                put(JSONObject().apply {
                    put("parts", partsArray)
                })
            })
            generationConfig.put("speechConfig", multiSpeakerConfig.toSpeechConfigJson())
        } else {
            val promptText = if (stylePreset != VoiceStylePreset.NATURAL) {
                "${stylePreset.directorPrompt}\n$cleanText"
            } else {
                cleanText
            }
            val partsArray = JSONArray().apply {
                put(JSONObject().apply {
                    put("text", promptText)
                })
            }
            payload.put("contents", JSONArray().apply {
                put(JSONObject().apply {
                    put("parts", partsArray)
                })
            })

            val isCustomVoice = voiceName.startsWith("voice_") || voiceName.startsWith("voices/")
            val cleanVoiceId = voiceName.removePrefix("voices/")
            val voiceConfigObj = JSONObject().apply {
                if (isCustomVoice) {
                    put("voice", cleanVoiceId)
                } else {
                    put("prebuiltVoiceConfig", JSONObject().apply {
                        put("voiceName", voiceName)
                    })
                }
            }
            generationConfig.put("speechConfig", JSONObject().apply {
                put("voiceConfig", voiceConfigObj)
            })
        }
        payload.put("generationConfig", generationConfig)

        val requestBody = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url(url)
            .post(requestBody)
            .header("User-Agent", "GeminiAudiobookAndroid/1.0")
            .build()

        var attempt = 0
        val maxAttempts = 3
        while (attempt < maxAttempts) {
            attempt++
            var shouldRetry = false
            val retryDelayMs = 20000L
            var audioResult: ByteArray? = null

            httpClient.newCall(request).execute().use { response ->
                if (response.code == 429) {
                    val errorBody = response.body?.string() ?: ""
                    Log.w(TAG, "Gemini HTTP 429 Rate Limit (attempt $attempt/$maxAttempts): $errorBody")
                    if (attempt < maxAttempts) {
                        shouldRetry = true
                    } else {
                        throw IllegalStateException("API error 429: تم تجاوز حد الطلبات للدقيقة (Rate limit). يرجى الانتظار دقيقة والمحاولة مجدداً.")
                    }
                } else if (!response.isSuccessful) {
                    val errorBody = response.body?.string() ?: ""
                    Log.e(TAG, "Gemini HTTP error ${response.code}: $errorBody")
                    throw IllegalStateException("API error ${response.code}: $errorBody")
                } else {
                    val responseStr = response.body?.string() ?: ""
                    val json = JSONObject(responseStr)
                    val audioBytes = extractAudioBytes(json)
                    audioResult = if (audioBytes.size >= 4 &&
                        audioBytes[0] == 'R'.code.toByte() &&
                        audioBytes[1] == 'I'.code.toByte() &&
                        audioBytes[2] == 'F'.code.toByte() &&
                        audioBytes[3] == 'F'.code.toByte()
                    ) {
                        audioBytes
                    } else {
                        createWavHeader(audioBytes, sampleRate = 24000)
                    }
                }
            }

            if (audioResult != null) {
                return@withContext audioResult!!
            }

            if (shouldRetry) {
                Log.i(TAG, "Waiting 20 seconds before retry attempt $attempt/$maxAttempts...")
                delay(retryDelayMs)
            }
        }

        throw IllegalStateException("فشل توليد الصوت بعد $maxAttempts محاولات بسبب ضغط الطلبات على الحساب.")
    }

    private fun extractAudioBytes(json: JSONObject): ByteArray {
        if (json.has("audioContent")) {
            return Base64.decode(json.getString("audioContent"), Base64.DEFAULT)
        }
        if (json.has("audio")) {
            return Base64.decode(json.getString("audio"), Base64.DEFAULT)
        }
        if (json.has("candidates")) {
            val candidates = json.getJSONArray("candidates")
            if (candidates.length() > 0) {
                val candidate = candidates.getJSONObject(0)
                val content = candidate.optJSONObject("content")
                val parts = content?.optJSONArray("parts")
                if (parts != null && parts.length() > 0) {
                    val part = parts.getJSONObject(0)
                    val inlineData = part.optJSONObject("inlineData")
                    if (inlineData != null && inlineData.has("data")) {
                        return Base64.decode(inlineData.getString("data"), Base64.DEFAULT)
                    }
                    val audioData = part.optJSONObject("audioData")
                    if (audioData != null && audioData.has("data")) {
                        return Base64.decode(audioData.getString("data"), Base64.DEFAULT)
                    }
                }
            }
        }
        if (json.has("output")) {
            return Base64.decode(json.getString("output"), Base64.DEFAULT)
        }

        throw IllegalArgumentException("Audio data not found in response JSON.")
    }

    suspend fun synthesize(
        text: String,
        voiceName: String,
        style: String
    ): ByteArray = synthesize(text, voiceName, VoiceStylePreset.fromId(style), null)

    suspend fun createCustomVoice(
        displayName: String,
        promptDescription: String
    ): Pair<String, ByteArray?> = withContext(Dispatchers.IO) {
        if (!hasApiKey()) {
            throw IllegalArgumentException("API key is not configured.")
        }
        val url = "https://generativelanguage.googleapis.com/v1beta/voices?key=$apiKey"
        val payload = JSONObject().apply {
            put("store", true)
            put("voice", JSONObject().apply {
                put("model", modelId)
                put("type", "prompted")
                put("display_name", displayName)
                put("prompted", JSONObject().apply {
                    put("input", promptDescription)
                })
            })
        }
        val requestBody = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url(url)
            .post(requestBody)
            .header("User-Agent", "GeminiAudiobookAndroid/1.1.0")
            .build()

        httpClient.newCall(request).execute().use { response ->
            val body = response.body?.string() ?: ""
            if (!response.isSuccessful) {
                Log.e(TAG, "Voice design failed (${response.code}): $body")
                throw IllegalStateException("فشل تصميم الصوت (${response.code}): $body")
            }
            val json = JSONObject(body)
            val fullName = json.optString("name", "")
            val voiceId = fullName.removePrefix("voices/")
            val sampleB64 = json.optString("sample_audio", "")
            val sampleBytes = if (sampleB64.isNotEmpty()) {
                try {
                    val raw = Base64.decode(sampleB64, Base64.DEFAULT)
                    if (raw.size >= 4 &&
                        raw[0] == 'R'.code.toByte() &&
                        raw[1] == 'I'.code.toByte() &&
                        raw[2] == 'F'.code.toByte() &&
                        raw[3] == 'F'.code.toByte()
                    ) {
                        raw
                    } else {
                        createWavHeader(raw, sampleRate = 24000)
                    }
                } catch (e: Exception) {
                    null
                }
            } else null

            Pair(voiceId, sampleBytes)
        }
    }

    suspend fun listCustomVoices(): List<VoiceProfile> = withContext(Dispatchers.IO) {
        if (!hasApiKey()) return@withContext emptyList()
        val url = "https://generativelanguage.googleapis.com/v1beta/voices?key=$apiKey&type=prompted"
        val request = Request.Builder()
            .url(url)
            .get()
            .header("User-Agent", "GeminiAudiobookAndroid/1.1.0")
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext emptyList()
                val body = response.body?.string() ?: ""
                val json = JSONObject(body)
                val voicesArray = json.optJSONArray("voices") ?: return@withContext emptyList()
                val list = mutableListOf<VoiceProfile>()
                for (i in 0 until voicesArray.length()) {
                    val v = voicesArray.getJSONObject(i)
                    val rawName = v.optString("name", "")
                    val id = rawName.removePrefix("voices/")
                    val disp = v.optString("display_name", id)
                    list.add(
                        VoiceProfile(
                            id = id,
                            displayNameArabic = "$disp (مخصص)",
                            isCustomVoiceDesign = true,
                            descriptionArabic = "صوت تم تصميمه بالذكاء الاصطناعي: $disp"
                        )
                    )
                }
                list
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to list custom voices: ${e.message}")
            emptyList()
        }
    }

    fun saveAudioAtomically(targetFile: File, audioBytes: ByteArray) {
        targetFile.parentFile?.mkdirs()
        val tempFile = File(targetFile.parentFile, "${targetFile.name}.tmp_${System.currentTimeMillis()}")
        FileOutputStream(tempFile).use { fos ->
            fos.write(audioBytes)
            fos.flush()
        }
        if (!tempFile.renameTo(targetFile)) {
            tempFile.copyTo(targetFile, overwrite = true)
            tempFile.delete()
        }
    }
}
