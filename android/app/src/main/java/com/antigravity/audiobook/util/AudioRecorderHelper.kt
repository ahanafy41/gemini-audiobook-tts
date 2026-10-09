package com.antigravity.audiobook.util

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.antigravity.audiobook.data.GeminiTtsClient
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.atomic.AtomicBoolean

/**
 * مساعد تسجيل ومعاينة الصوت لتسجيل عينات استنساخ الأصوات (Voice Replication).
 * يسجل بصيغة PCM أحادية القناة 16-bit بتردد 24000 هرتز (أو 16000 كبديل)،
 * ويحولها تلقائياً إلى ملف WAV قياسي متوافق مع معايير Gemini 3.8 Flash TTS.
 */
class AudioRecorderHelper(private val context: Context) {

    companion object {
        private const val TAG = "AudioRecorderHelper"
        private const val PREFERRED_SAMPLE_RATE = 24000
        private const val FALLBACK_SAMPLE_RATE = 16000
    }

    private var audioRecord: AudioRecord? = null
    private var recordingThread: Thread? = null
    private val isRecording = AtomicBoolean(false)
    private var currentPcmFile: File? = null
    private var currentWavFile: File? = null
    private var actualSampleRate = PREFERRED_SAMPLE_RATE
    private var mediaPlayer: MediaPlayer? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    fun isRecordingActive(): Boolean = isRecording.get()

    private fun determineOptimalSampleRate(): Int {
        val rates = intArrayOf(PREFERRED_SAMPLE_RATE, FALLBACK_SAMPLE_RATE, 44100)
        for (rate in rates) {
            val minBuf = AudioRecord.getMinBufferSize(
                rate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            if (minBuf > 0) return rate
        }
        return FALLBACK_SAMPLE_RATE
    }

    fun startRecording(
        outputWavFile: File,
        onTick: ((Int) -> Unit)? = null
    ): Boolean {
        if (isRecording.get()) return false
        stopPlayback()

        actualSampleRate = determineOptimalSampleRate()
        val minBufferSize = AudioRecord.getMinBufferSize(
            actualSampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        if (minBufferSize <= 0) {
            Log.e(TAG, "AudioRecord buffer size invalid for sample rate $actualSampleRate")
            return false
        }

        val bufferSize = maxOf(minBufferSize * 2, 4096)
        return try {
            val record = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                actualSampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize
            )
            if (record.state != AudioRecord.STATE_INITIALIZED) {
                Log.e(TAG, "AudioRecord failed to initialize")
                record.release()
                return false
            }

            audioRecord = record
            currentWavFile = outputWavFile
            val pcmFile = File(outputWavFile.parentFile, "${outputWavFile.name}.pcm")
            currentPcmFile = pcmFile
            isRecording.set(true)
            record.startRecording()

            recordingThread = Thread {
                val buffer = ByteArray(bufferSize)
                var fos: FileOutputStream? = null
                val startTime = System.currentTimeMillis()
                var lastSecond = -1
                try {
                    fos = FileOutputStream(pcmFile)
                    while (isRecording.get()) {
                        val read = record.read(buffer, 0, buffer.size)
                        if (read > 0) {
                            fos.write(buffer, 0, read)
                        }
                        val elapsed = ((System.currentTimeMillis() - startTime) / 1000).toInt()
                        if (elapsed != lastSecond) {
                            lastSecond = elapsed
                            mainHandler.post {
                                onTick?.invoke(elapsed)
                            }
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Exception during recording: ${e.message}")
                } finally {
                    try {
                        fos?.flush()
                        fos?.close()
                    } catch (_: Exception) {}
                }
            }.apply { start() }

            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start recording: ${e.message}")
            false
        }
    }

    fun stopRecording(): File? {
        if (!isRecording.getAndSet(false)) return null

        try {
            audioRecord?.stop()
            audioRecord?.release()
            audioRecord = null
            recordingThread?.join(1500)
            recordingThread = null
        } catch (e: Exception) {
            Log.e(TAG, "Error stopping AudioRecord: ${e.message}")
        }

        val pcm = currentPcmFile
        val wav = currentWavFile
        if (pcm != null && pcm.exists() && wav != null) {
            val pcmBytes = pcm.readBytes()
            pcm.delete()
            if (pcmBytes.isNotEmpty()) {
                val wavBytes = GeminiTtsClient.createWavHeader(
                    pcmData = pcmBytes,
                    sampleRate = actualSampleRate,
                    channels = 1,
                    bitsPerSample = 16
                )
                wav.writeBytes(wavBytes)
                return wav
            }
        }
        return null
    }

    fun playAudio(file: File, onCompletion: () -> Unit): Boolean {
        stopPlayback()
        if (!file.exists() || file.length() == 0L) return false

        return try {
            mediaPlayer = MediaPlayer().apply {
                setDataSource(file.absolutePath)
                prepare()
                setOnCompletionListener {
                    stopPlayback()
                    onCompletion()
                }
                start()
            }
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to play audio file: ${e.message}")
            stopPlayback()
            onCompletion()
            false
        }
    }

    fun stopPlayback() {
        try {
            mediaPlayer?.stop()
            mediaPlayer?.release()
        } catch (_: Exception) {}
        mediaPlayer = null
    }

    fun isPlaying(): Boolean {
        return try {
            mediaPlayer?.isPlaying ?: false
        } catch (_: Exception) {
            false
        }
    }

    fun release() {
        stopPlayback()
        if (isRecording.get()) {
            stopRecording()
        }
    }
}
