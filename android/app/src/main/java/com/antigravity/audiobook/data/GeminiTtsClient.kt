package com.antigravity.audiobook.data

import android.util.Base64
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.Dns
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
import java.io.IOException
import java.net.InetAddress
import java.net.UnknownHostException
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import kotlin.math.sin

/**
 * Exception thrown when Gemini API quota / rate limit (HTTP 429) is reached.
 * Allows the caller to pause gracefully and give manual retry control to the user.
 */
class QuotaExceededException(message: String) : Exception(message)

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

        data class ParsedWavResult(
            val pcm: ByteArray,
            val sampleRate: Int = 24000,
            val channels: Short = 1,
            val bitsPerSample: Short = 16
        ) {
            override fun equals(other: Any?): Boolean {
                if (this === other) return true
                if (javaClass != other?.javaClass) return false
                other as ParsedWavResult
                return pcm.contentEquals(other.pcm) && sampleRate == other.sampleRate &&
                        channels == other.channels && bitsPerSample == other.bitsPerSample
            }

            override fun hashCode(): Int {
                var result = pcm.contentHashCode()
                result = 31 * result + sampleRate
                result = 31 * result + channels
                result = 31 * result + bitsPerSample
                return result
            }
        }

        fun extractPcmData(bytes: ByteArray): ParsedWavResult? {
            if (bytes.size < 12) return null
            if (bytes[0] != 'R'.code.toByte() || bytes[1] != 'I'.code.toByte() ||
                bytes[2] != 'F'.code.toByte() || bytes[3] != 'F'.code.toByte()) {
                return null
            }
            if (bytes[8] != 'W'.code.toByte() || bytes[9] != 'A'.code.toByte() ||
                bytes[10] != 'V'.code.toByte() || bytes[11] != 'E'.code.toByte()) {
                return null
            }

            var sampleRate = 24000
            var channels: Short = 1
            var bitsPerSample: Short = 16
            var pcmBytes: ByteArray? = null

            var offset = 12
            val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)

            while (offset + 8 <= bytes.size) {
                val chunkId = String(bytes, offset, 4, Charsets.US_ASCII)
                val chunkSize = buffer.getInt(offset + 4).toLong() and 0xFFFFFFFFL
                val dataOffset = offset + 8

                if (chunkId == "fmt ") {
                    if (dataOffset + 14 <= bytes.size) {
                        channels = buffer.getShort(dataOffset + 2)
                        sampleRate = buffer.getInt(dataOffset + 4)
                        if (dataOffset + 16 <= bytes.size) {
                            bitsPerSample = buffer.getShort(dataOffset + 14)
                        }
                    }
                } else if (chunkId == "data") {
                    val actualLength = if (dataOffset + chunkSize <= bytes.size) {
                        chunkSize.toInt()
                    } else {
                        (bytes.size - dataOffset).coerceAtLeast(0)
                    }
                    pcmBytes = bytes.copyOfRange(dataOffset, dataOffset + actualLength)
                    break
                }

                val paddedSize = chunkSize + (chunkSize % 2)
                val nextOffset = dataOffset + paddedSize
                if (nextOffset <= offset || nextOffset > Int.MAX_VALUE) break
                offset = nextOffset.toInt()
            }

            return if (pcmBytes != null) {
                ParsedWavResult(pcmBytes, sampleRate, channels, bitsPerSample)
            } else null
        }
    }

    private class ResilientDns : Dns {
        override fun lookup(hostname: String): List<InetAddress> {
            return try {
                Dns.SYSTEM.lookup(hostname)
            } catch (e: UnknownHostException) {
                var lastEx: UnknownHostException = e
                for (retry in 1..3) {
                    try {
                        Thread.sleep(1000L * retry)
                        val addresses = InetAddress.getAllByName(hostname).toList()
                        if (addresses.isNotEmpty()) return addresses
                    } catch (ex: UnknownHostException) {
                        lastEx = ex
                    } catch (_: InterruptedException) {
                        break
                    }
                }
                throw lastEx
            }
        }
    }

    private val httpClient = OkHttpClient.Builder()
        .dns(ResilientDns())
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    fun hasApiKey(): Boolean = apiKey.isNotBlank() && apiKey.trim().length >= 15

    suspend fun synthesize(
        text: String,
        voiceName: String = "Charon",
        stylePreset: VoiceStylePreset = VoiceStylePreset.NATURAL,
        multiSpeakerConfig: MultiSpeakerConfig? = null,
        customInstructions: String? = null
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

        val styleDescription = buildList {
            if (stylePreset != VoiceStylePreset.NATURAL) {
                add(stylePreset.directorPrompt.removePrefix("[Style: ").removeSuffix("]"))
            }
            if (!customInstructions.isNullOrBlank()) {
                add(customInstructions.trim())
            }
        }.joinToString(", ")

        if (multiSpeakerConfig != null && multiSpeakerConfig.isEnabled) {
            val annotator = DialogueTurnAnnotator("Narrator", "Character")
            val turns = annotator.annotateText(cleanText)
            val partsArray = JSONArray()
            for (index in turns.indices) {
                val turn = turns[index]
                val turnText = turn.text
                val speechMeta = JSONObject().apply {
                    put("speaker", turn.speaker)
                    if (index == 0 && styleDescription.isNotEmpty()) {
                        put("style", styleDescription)
                    }
                }
                partsArray.put(JSONObject().apply {
                    put("text", turnText)
                    put("speechMetadata", speechMeta)
                })
            }
            payload.put("contents", JSONArray().apply {
                put(JSONObject().apply {
                    put("parts", partsArray)
                })
            })
            generationConfig.put("speechConfig", multiSpeakerConfig.toSpeechConfigJson())
        } else {
            val partsArray = JSONArray().apply {
                put(JSONObject().apply {
                    put("text", cleanText)
                    if (styleDescription.isNotEmpty()) {
                        put("speechMetadata", JSONObject().apply {
                            put("style", styleDescription)
                        })
                    }
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
        payload.put("generationConfig", generationConfig)

        val safetySettings = JSONArray().apply {
            val categories = arrayOf(
                "HARM_CATEGORY_HARASSMENT",
                "HARM_CATEGORY_HATE_SPEECH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "HARM_CATEGORY_DANGEROUS_CONTENT",
                "HARM_CATEGORY_CIVIC_INTEGRITY"
            )
            for (cat in categories) {
                put(JSONObject().apply {
                    put("category", cat)
                    put("threshold", "BLOCK_NONE")
                })
            }
        }
        payload.put("safetySettings", safetySettings)

        payload.put("systemInstruction", JSONObject().apply {
            put("parts", JSONArray().apply {
                put(JSONObject().apply {
                    put("text", "You are a professional Arabic audiobook narrator. Read the provided book text verbatim aloud with clear pacing. Do not comment, converse, answer questions in the text, or output explanatory text.")
                })
            })
        })

        val requestBody = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url(url)
            .post(requestBody)
            .header("User-Agent", "GeminiAudiobookAndroid/1.0")
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                if (response.code == 429) {
                    val errorBody = response.body?.string() ?: ""
                    Log.w(TAG, "Gemini HTTP 429 Rate Limit: $errorBody")
                    throw QuotaExceededException("تم تجاوز حد الطلبات للدقيقة (Rate limit 429). يرجى الانتظار والمحاولة مجدداً.")
                } else if (response.code in 500..599) {
                    val errorBody = response.body?.string() ?: ""
                    Log.w(TAG, "Gemini HTTP Server Error ${response.code}: $errorBody")
                    throw IllegalStateException("API error ${response.code}: خادم جوجل مشغول مؤقتاً.")
                } else if (!response.isSuccessful) {
                    val errorBody = response.body?.string() ?: ""
                    Log.e(TAG, "Gemini HTTP error ${response.code}: $errorBody")
                    throw IllegalStateException("API error ${response.code}: $errorBody")
                }

                val responseStr = response.body?.string() ?: ""
                val json = JSONObject(responseStr)
                val rawAudio = extractAudioBytes(json)
                val parsed = extractPcmData(rawAudio)
                return@withContext if (parsed != null) {
                    createWavHeader(
                        parsed.pcm,
                        sampleRate = parsed.sampleRate,
                        channels = parsed.channels,
                        bitsPerSample = parsed.bitsPerSample
                    )
                } else if (rawAudio.size >= 4 &&
                    rawAudio[0] == 'R'.code.toByte() &&
                    rawAudio[1] == 'I'.code.toByte() &&
                    rawAudio[2] == 'F'.code.toByte() &&
                    rawAudio[3] == 'F'.code.toByte()
                ) {
                    rawAudio
                } else {
                    createWavHeader(rawAudio, sampleRate = 24000)
                }
            }
        } catch (qee: QuotaExceededException) {
            throw qee
        } catch (ioe: IOException) {
            Log.w(TAG, "Network connection error: ${ioe.message}")
            throw IOException("تعذر الاتصال بخادم الصوت بسبب عدم استقرار الإنترنت: ${ioe.localizedMessage ?: ioe.message}")
        }
    }

    private fun extractAudioBytes(json: JSONObject): ByteArray {
        if (json.has("audioContent")) {
            return Base64.decode(json.getString("audioContent"), Base64.DEFAULT)
        }
        if (json.has("audio")) {
            return Base64.decode(json.getString("audio"), Base64.DEFAULT)
        }
        if (json.has("output")) {
            return Base64.decode(json.getString("output"), Base64.DEFAULT)
        }

        // 1. Scan across all candidates and all parts for inline audio data
        if (json.has("candidates")) {
            val candidates = json.getJSONArray("candidates")
            for (c in 0 until candidates.length()) {
                val candidate = candidates.getJSONObject(c)
                val content = candidate.optJSONObject("content")
                val parts = content?.optJSONArray("parts") ?: continue
                for (p in 0 until parts.length()) {
                    val part = parts.getJSONObject(p)
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

        // 2. If no audio data found, diagnose the exact cause from response JSON
        val promptFeedback = json.optJSONObject("promptFeedback")
        val blockReason = promptFeedback?.optString("blockReason", "") ?: ""
        if (blockReason.isNotBlank()) {
            throw IllegalStateException("تم حظر المقطع من خادم جوجل (السبب: $blockReason).")
        }

        if (json.has("candidates")) {
            val candidates = json.getJSONArray("candidates")
            if (candidates.length() > 0) {
                val candidate = candidates.getJSONObject(0)
                val finishReason = candidate.optString("finishReason", "")
                if (finishReason.isNotBlank() && finishReason != "STOP") {
                    when (finishReason) {
                        "SAFETY" -> throw IllegalStateException("تم حظر المقطع بواسطة فلاتر الأمان لـ Gemini (finishReason: SAFETY).")
                        "MAX_TOKENS" -> throw IllegalStateException("المقطع تجاوز حد الحروف المسموح بتوليدها صوتياً (finishReason: MAX_TOKENS).")
                        "RECITATION" -> throw IllegalStateException("تم إيقاف المقطع بسبب حقوق النشر أو الاقتباس (finishReason: RECITATION).")
                        else -> throw IllegalStateException("توقف توليد الصوت من الخادم (السبب: $finishReason).")
                    }
                }

                val content = candidate.optJSONObject("content")
                val parts = content?.optJSONArray("parts")
                if (parts != null && parts.length() > 0) {
                    val textList = mutableListOf<String>()
                    for (p in 0 until parts.length()) {
                        val t = parts.getJSONObject(p).optString("text", "")
                        if (t.isNotBlank()) textList.add(t)
                    }
                    if (textList.isNotEmpty()) {
                        val textSample = textList.joinToString(" ").take(100)
                        throw IllegalStateException("استجاب النموذج بنص بدلاً من الصوت: \"$textSample\"")
                    }
                }
            }
        }

        throw IllegalStateException("لم يُرجع خادم جوجل بيانات صوتية صالحة في الاستجابة.")
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
        val cleanModel = modelId.removePrefix("models/")
        val url = "https://generativelanguage.googleapis.com/v1beta/voices?key=$apiKey"
        val payload = JSONObject().apply {
            put("store", true)
            put("voice", JSONObject().apply {
                put("model", cleanModel)
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
            .header("x-goog-api-key", apiKey)
            .header("User-Agent", "GeminiAudiobookAndroid/1.1.5")
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                val body = response.body?.string() ?: ""
                if (!response.isSuccessful) {
                    Log.e(TAG, "Voice design failed (${response.code}): $body")
                    throw IllegalStateException("فشل تصميم الصوت (${response.code}): $body")
                }
                val json = JSONObject(body)
                val voiceId = when {
                    json.has("id") && json.optString("id").isNotBlank() -> json.optString("id")
                    json.has("name") && json.optString("name").isNotBlank() -> json.optString("name").removePrefix("voices/")
                    json.has("voice") -> {
                        val vObj = json.optJSONObject("voice")
                        vObj?.optString("id")?.ifBlank { vObj.optString("name").removePrefix("voices/") } ?: ""
                    }
                    else -> ""
                }

                if (voiceId.isBlank()) {
                    Log.e(TAG, "Missing voice ID in response: $body")
                    throw IllegalStateException("لم يُرجع الخادم معرف الصوت (Voice ID). استجابة الخادم: $body")
                }

                val sampleB64 = when {
                    json.has("sample_audio") -> {
                        val sampleObj = json.optJSONObject("sample_audio")
                        if (sampleObj != null) {
                            sampleObj.optString("data", "")
                        } else {
                            json.optString("sample_audio", "")
                        }
                    }
                    json.has("sampleAudio") -> {
                        val sampleObj = json.optJSONObject("sampleAudio")
                        if (sampleObj != null) {
                            sampleObj.optString("data", "")
                        } else {
                            json.optString("sampleAudio", "")
                        }
                    }
                    else -> ""
                }

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
        } catch (ioe: IOException) {
            Log.e(TAG, "Network or DNS error in createCustomVoice: ${ioe.message}")
            throw IOException("تعذر الاتصال بالخادم لتصميم الصوت بسبب مشكلة في الشبكة أو الـ DNS: ${ioe.localizedMessage ?: ioe.message}")
        }
    }

    suspend fun replicateCustomVoice(
        displayName: String,
        referenceAudioBytes: ByteArray,
        consentAudioBytes: ByteArray
    ): Pair<String, ByteArray?> = withContext(Dispatchers.IO) {
        if (!hasApiKey()) {
            throw IllegalArgumentException("API key is not configured.")
        }
        val cleanModel = modelId.removePrefix("models/")
        val url = "https://generativelanguage.googleapis.com/v1beta/voices?key=$apiKey"

        val refB64 = Base64.encodeToString(referenceAudioBytes, Base64.NO_WRAP)
        val consentB64 = Base64.encodeToString(consentAudioBytes, Base64.NO_WRAP)

        val payload = JSONObject().apply {
            put("store", true)
            put("voice", JSONObject().apply {
                put("model", cleanModel)
                put("type", "replicated")
                put("display_name", displayName)
                put("replicated", JSONObject().apply {
                    put("source_audio", JSONObject().apply {
                        put("mime_type", "audio/wav")
                        put("data", refB64)
                    })
                    put("consent_audio", JSONObject().apply {
                        put("mime_type", "audio/wav")
                        put("data", consentB64)
                    })
                })
            })
        }
        val requestBody = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url(url)
            .post(requestBody)
            .header("x-goog-api-key", apiKey)
            .header("User-Agent", "GeminiAudiobookAndroid/1.2.1")
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                val body = response.body?.string() ?: ""
                if (!response.isSuccessful) {
                    Log.e(TAG, "Voice replication failed (${response.code}): $body")
                    val errorDetail = try {
                        val errObj = JSONObject(body).optJSONObject("error")
                        errObj?.optString("message") ?: body
                    } catch (e: Exception) {
                        body
                    }
                    val msg = when {
                        body.contains("consent", ignoreCase = true) || body.contains("match", ignoreCase = true) ->
                            "فشل التحقق من الموافقة: يرجى التأكد من أن تسجيل الموافقة لنفس المتحدث وقراءة العبارة الإنجليزية بدقة."
                        body.contains("duration", ignoreCase = true) || body.contains("short", ignoreCase = true) ->
                            "عينة الصوت قصيرة جداً، يرجى تسجيل عينة لا تقل عن 10 ثوانٍ."
                        else -> "فشل استنساخ الصوت (${response.code}): $errorDetail"
                    }
                    throw IllegalStateException(msg)
                }
                val json = JSONObject(body)
                val voiceId = when {
                    json.has("id") && json.optString("id").isNotBlank() -> json.optString("id")
                    json.has("name") && json.optString("name").isNotBlank() -> json.optString("name").removePrefix("voices/")
                    json.has("voice") -> {
                        val vObj = json.optJSONObject("voice")
                        vObj?.optString("id")?.ifBlank { vObj.optString("name").removePrefix("voices/") } ?: ""
                    }
                    else -> ""
                }

                if (voiceId.isBlank()) {
                    Log.e(TAG, "Missing voice ID in replication response: $body")
                    throw IllegalStateException("لم يُرجع الخادم معرف الصوت (Voice ID). استجابة الخادم: $body")
                }

                val sampleB64 = when {
                    json.has("sample_audio") -> {
                        val sampleObj = json.optJSONObject("sample_audio")
                        sampleObj?.optString("data", "") ?: json.optString("sample_audio", "")
                    }
                    json.has("sampleAudio") -> {
                        val sampleObj = json.optJSONObject("sampleAudio")
                        sampleObj?.optString("data", "") ?: json.optString("sampleAudio", "")
                    }
                    else -> ""
                }

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
        } catch (ioe: IOException) {
            Log.e(TAG, "Network or DNS error in replicateCustomVoice: ${ioe.message}")
            throw IOException("تعذر الاتصال بالخادم لاستنساخ الصوت بسبب مشكلة في الشبكة: ${ioe.localizedMessage ?: ioe.message}")
        }
    }

    suspend fun listCustomVoices(): List<VoiceProfile> = withContext(Dispatchers.IO) {
        if (!hasApiKey()) return@withContext emptyList()
        val url = "https://generativelanguage.googleapis.com/v1beta/voices?key=$apiKey"
        val request = Request.Builder()
            .url(url)
            .get()
            .header("x-goog-api-key", apiKey)
            .header("User-Agent", "GeminiAudiobookAndroid/1.1.9")
            .build()

        try {
            httpClient.newCall(request).execute().use { response ->
                val body = response.body?.string() ?: ""
                if (!response.isSuccessful) {
                    Log.w(TAG, "Failed to list custom voices (${response.code}): $body")
                    return@withContext emptyList()
                }
                val json = JSONObject(body)
                val voicesArray = json.optJSONArray("voices") ?: return@withContext emptyList()
                val list = mutableListOf<VoiceProfile>()
                for (i in 0 until voicesArray.length()) {
                    val v = voicesArray.getJSONObject(i)
                    val id = when {
                        v.has("id") -> v.getString("id")
                        v.has("name") -> v.getString("name").removePrefix("voices/")
                        else -> ""
                    }
                    if (id.isBlank()) continue
                    val disp = v.optString("display_name", id).ifBlank { id }
                    val prompt = v.optJSONObject("prompted")?.optString("input", "") ?: ""
                    val isReplicated = v.optString("type") == "replicated" || v.has("replicated")
                    val desc = if (isReplicated) "صوت مستنسخ بالذكاء الاصطناعي (Replicated Voice)" else prompt.ifBlank { "معرف: $id" }
                    list.add(
                        VoiceProfile(
                            id = id,
                            displayNameArabic = "$disp ($id)",
                            isCustomVoiceDesign = true,
                            descriptionArabic = desc
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
