package com.antigravity.audiobook.data

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.util.Locale

/**
 * High-reliability on-device Android TextToSpeech engine.
 * Synthesizes text directly to WAV audio files using the device's native TTS voices (e.g. Google TTS).
 * Completely offline, zero-quota, 100% free, and guarantees natural Arabic speech playback.
 */
class LocalTtsEngine(private val context: Context) {

    companion object {
        private const val TAG = "LocalTtsEngine"
    }

    private var tts: TextToSpeech? = null
    private val initDeferred = CompletableDeferred<Boolean>()

    init {
        tts = TextToSpeech(context.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val arabic = Locale("ar")
                val langResult = tts?.setLanguage(arabic)
                if (langResult == TextToSpeech.LANG_MISSING_DATA || langResult == TextToSpeech.LANG_NOT_SUPPORTED) {
                    Log.w(TAG, "Arabic TTS language missing or not supported, falling back to default locale.")
                    tts?.language = Locale.getDefault()
                }
                Log.i(TAG, "Native Android TextToSpeech initialized successfully.")
                initDeferred.complete(true)
            } else {
                Log.e(TAG, "Failed to initialize Native TextToSpeech: status=$status")
                initDeferred.complete(false)
            }
        }
    }

    suspend fun synthesizeToFile(text: String, outputFile: File): Boolean = withContext(Dispatchers.IO) {
        val ready = withTimeoutOrNull(5000L) {
            initDeferred.await()
        } ?: false

        if (!ready || tts == null) {
            Log.e(TAG, "TextToSpeech engine not ready for synthesis.")
            return@withContext false
        }

        outputFile.parentFile?.mkdirs()
        val utteranceId = "utt_${System.currentTimeMillis()}_${outputFile.nameWithoutExtension}"
        val doneDeferred = CompletableDeferred<Boolean>()

        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {
                Log.d(TAG, "Started TTS synthesis for: $id")
            }

            override fun onDone(id: String?) {
                if (id == utteranceId) {
                    Log.i(TAG, "Completed TTS synthesis to file: ${outputFile.name}")
                    doneDeferred.complete(true)
                }
            }

            override fun onError(id: String?) {
                if (id == utteranceId) {
                    Log.e(TAG, "Error in TTS synthesis for: $id")
                    doneDeferred.complete(false)
                }
            }
        })

        val params = Bundle().apply {
            putString(TextToSpeech.Engine.KEY_PARAM_UTTERANCE_ID, utteranceId)
        }

        val result = tts?.synthesizeToFile(text, params, outputFile, utteranceId)
        if (result != TextToSpeech.SUCCESS) {
            Log.e(TAG, "synthesizeToFile call returned error: $result")
            return@withContext false
        }

        // Wait for file writing to finish (timeout 60 seconds per chunk)
        val success = withTimeoutOrNull(60000L) {
            doneDeferred.await()
        } ?: false

        return@withContext success && outputFile.exists() && outputFile.length() > 100
    }

    fun shutdown() {
        try {
            tts?.stop()
            tts?.shutdown()
            tts = null
        } catch (e: Exception) {
            Log.e(TAG, "Error shutting down TTS: ${e.message}")
        }
    }
}
