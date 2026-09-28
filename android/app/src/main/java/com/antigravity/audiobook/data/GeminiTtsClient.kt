package com.antigravity.audiobook.data

import android.util.Base64
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit
import kotlin.math.sin

/**
 * Gemini 2.0 Flash TTS Client for Android.
 * Communicates with Google's Gemini TTS endpoint using OkHttp,
 * handles Base64 audio decoding, and adds standard 44-byte WAV headers for PCM data.
 */
class GeminiTtsClient(
    private val apiKey: String,
    private val modelId: String = DEFAULT_MODEL_ID,
    private val customEndpoint: String? = null
) {

    companion object {
        const val DEFAULT_MODEL_ID = "gemini-3.8-flash-tts"
        val APPROVED_VOICES = listOf("Kore", "Puck", "Charon", "Fenrir", "Aoede")
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
        voiceName: String = "Kore",
        style: String = "narrator, natural pacing"
    ): ByteArray = withContext(Dispatchers.IO) {
        val cleanText = text.trim()
        if (cleanText.isEmpty()) {
            return@withContext generateSyntheticWav(0.1)
        }

        if (!hasApiKey()) {
            throw IllegalArgumentException("API key is not configured.")
        }

        val url = customEndpoint ?: "$BASE_URL/$modelId:generateContent?key=$apiKey"

        // Structured payload with generationConfig and speechConfig
        val payload = JSONObject().apply {
            put("contents", JSONArray().apply {
                put(JSONObject().apply {
                    put("parts", JSONArray().apply {
                        put(JSONObject().apply {
                            put("text", cleanText)
                        })
                    })
                })
            })
            put("generationConfig", JSONObject().apply {
                put("responseModalities", JSONArray().apply {
                    put("AUDIO")
                })
                put("speechConfig", JSONObject().apply {
                    put("voiceConfig", JSONObject().apply {
                        put("prebuiltVoiceConfig", JSONObject().apply {
                            put("voiceName", voiceName)
                        })
                    })
                })
            })
        }

        val requestBody = payload.toString().toRequestBody(JSON_MEDIA_TYPE)
        val request = Request.Builder()
            .url(url)
            .post(requestBody)
            .header("User-Agent", "GeminiAudiobookAndroid/1.0")
            .build()

        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val errorBody = response.body?.string() ?: ""
                Log.e(TAG, "Gemini HTTP error ${response.code}: $errorBody")
                throw IllegalStateException("API error ${response.code}: $errorBody")
            }

            val responseStr = response.body?.string() ?: ""
            val json = JSONObject(responseStr)
            val audioBytes = extractAudioBytes(json)

            if (audioBytes.size >= 4 &&
                audioBytes[0] == 'R'.code.toByte() &&
                audioBytes[1] == 'I'.code.toByte() &&
                audioBytes[2] == 'F'.code.toByte() &&
                audioBytes[3] == 'F'.code.toByte()
            ) {
                return@withContext audioBytes
            }

            return@withContext createWavHeader(audioBytes, sampleRate = 24000)
        }
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
