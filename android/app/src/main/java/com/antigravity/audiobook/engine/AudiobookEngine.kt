package com.antigravity.audiobook.engine

import android.content.Context
import android.util.Log
import com.antigravity.audiobook.data.GeminiTtsClient
import com.antigravity.audiobook.domain.BookParser
import com.antigravity.audiobook.domain.CleanedChapter
import com.antigravity.audiobook.domain.MultiSpeakerConfig
import com.antigravity.audiobook.domain.ParsedBook
import com.antigravity.audiobook.domain.SmartTextChunker
import com.antigravity.audiobook.domain.VoiceStylePreset
import com.antigravity.audiobook.util.AudioExporter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Android Audiobook Engine powered purely by Google Gemini AI TTS.
 * Converts books (.md or .txt) into multi-chapter audiobooks with resume caching.
 * Uses Gemini Flash TTS with prebuilt high-fidelity neural voices, style presets,
 * and multi-speaker dialogue synthesis.
 */
class AudiobookEngine(
    private val context: Context,
    private val outputDir: File,
    private val ttsClient: GeminiTtsClient,
    private val voiceName: String = "Charon",
    private val stylePreset: VoiceStylePreset = VoiceStylePreset.NATURAL,
    private val multiSpeakerConfig: MultiSpeakerConfig? = null,
    private val customInstructions: String? = null
) {

    companion object {
        private const val TAG = "AudiobookEngine"
    }

    private val bookParser = BookParser()
    private val chunker = SmartTextChunker(12000)
    private val progressFile = File(outputDir, "progress.json")
    private val manifestFile = File(outputDir, "book_manifest.json")

    init {
        outputDir.mkdirs()
    }

    private fun loadProgress(): JSONObject {
        if (progressFile.exists()) {
            return try {
                JSONObject(progressFile.readText())
            } catch (e: Exception) {
                JSONObject()
            }
        }
        return JSONObject()
    }

    private fun saveProgress(progress: JSONObject) {
        val temp = File(outputDir, "progress.json.tmp")
        temp.writeText(progress.toString(2))
        temp.renameTo(progressFile)
    }

    private fun saveBookSettings() {
        try {
            val settings = JSONObject().apply {
                put("voice_name", voiceName)
                put("style_preset", stylePreset.id)
                if (!customInstructions.isNullOrBlank()) {
                    put("custom_instructions", customInstructions)
                }
                if (multiSpeakerConfig != null) {
                    put("multi_speaker", multiSpeakerConfig.toSpeechConfigJson())
                }
            }
            File(outputDir, "book_settings.json").writeText(settings.toString(2))
        } catch (e: Exception) {
            Log.w(TAG, "Failed to save book_settings.json: ${e.message}")
        }
    }

    suspend fun processBook(
        bookFile: File,
        customTitle: String? = null,
        onProgressUpdate: (currentChapter: Int, totalChapters: Int, chapterTitle: String) -> Unit = { _, _, _ -> }
    ): JSONObject = withContext(Dispatchers.IO) {
        saveBookSettings()
        val parsedBook: ParsedBook = bookParser.parseFile(bookFile, customTitle)
        val progress = loadProgress()
        val completedChapters = progress.optJSONObject("completed_chapters") ?: JSONObject()

        val chaptersDir = File(outputDir, "chapters").apply { mkdirs() }
        val rawChunksDir = File(outputDir, "raw_chunks").apply { mkdirs() }

        val chaptersArray = JSONArray()

        // Initialize manifest if not existing
        if (!manifestFile.exists() || manifestFile.length() == 0L) {
            val initialManifest = JSONObject().apply {
                put("title", parsedBook.title)
                put("chapters_count", completedChapters.length())
                put("total_chapters", parsedBook.chapters.size)
                put("chapters", JSONArray())
                put("status", "in_progress")
            }
            saveManifest(initialManifest)
        }

        for (i in parsedBook.chapters.indices) {
            val chapter = parsedBook.chapters[i]
            val chapterIdx = i + 1
            val chapterKey = String.format("chapter_%03d", chapterIdx)
            val chapterWav = File(chaptersDir, "$chapterKey.wav")

            onProgressUpdate(chapterIdx, parsedBook.chapters.size, chapter.chapterTitle)

            if (completedChapters.has(chapterKey) && chapterWav.exists() && chapterWav.length() > 1000) {
                Log.i(TAG, "Chapter $chapterIdx already processed. Reusing.")
                chaptersArray.put(completedChapters.getJSONObject(chapterKey))
                continue
            }

            val textChunks = chunker.chunkText(chapter.text)
            val chunkFiles = mutableListOf<File>()

            for (cIdx in textChunks.indices) {
                val chunkText = textChunks[cIdx]
                val chunkFilename = String.format("%s_part_%03d.wav", chapterKey, cIdx + 1)
                val chunkFile = File(rawChunksDir, chunkFilename)
                var synthesizedNetwork = false

                if (!chunkFile.exists() || chunkFile.length() <= 1000) {
                    if (!ttsClient.hasApiKey()) {
                        throw IllegalArgumentException("مفتاح Gemini API غير متوفر. يرجى إدخال المفتاح في الإعدادات أولاً.")
                    }

                    try {
                        val audioData = ttsClient.synthesize(
                            text = chunkText,
                            voiceName = voiceName,
                            stylePreset = stylePreset,
                            multiSpeakerConfig = multiSpeakerConfig,
                            customInstructions = customInstructions
                        )
                        if (audioData.size > 1000) {
                            ttsClient.saveAudioAtomically(chunkFile, audioData)
                            synthesizedNetwork = true
                            Log.i(TAG, "Synthesized chunk ${cIdx + 1} via Gemini AI TTS (${audioData.size} bytes).")
                        } else {
                            throw IllegalStateException("استجابة الصوت غير مكتملة.")
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Gemini AI synthesis failed for chunk ${cIdx + 1}: ${e.message}")
                        markManifestPaused(parsedBook.title, parsedBook.chapters.size, chaptersArray)
                        throw e
                    }
                }
                chunkFiles.add(chunkFile)

                // 5s pacing delay between network synthesis requests to maintain healthy RPM quota
                if (synthesizedNetwork && (cIdx < textChunks.size - 1 || i < parsedBook.chapters.size - 1)) {
                    Log.i(TAG, "Pacing delay (5s) between Gemini TTS requests to maintain healthy RPM quota...")
                    delay(5000L)
                }
            }

            // Concatenate chunk WAVs
            val durationMs = concatenateWavs(chunkFiles, chapterWav)
            val durationSec = durationMs / 1000

            try {
                AudioExporter.exportChapterToDedicatedFolder(
                    context = context,
                    chapterWav = chapterWav,
                    bookTitle = parsedBook.title,
                    chapterIndex = chapterIdx,
                    chapterTitle = chapter.chapterTitle
                )
            } catch (e: Exception) {
                Log.w(TAG, "Background export to GeminiAudiobook skipped: ${e.message}")
            }

            val chapterObj = JSONObject().apply {
                put("index", chapterIdx)
                put("id", chapterKey)
                put("title", chapter.chapterTitle)
                put("audio_path", chapterWav.absolutePath)
                put("audio_file", "chapters/$chapterKey.wav")
                put("duration_seconds", durationSec)
                put("duration_ms", durationMs)
            }

            chaptersArray.put(chapterObj)
            completedChapters.put(chapterKey, chapterObj)
            progress.put("completed_chapters", completedChapters)
            saveProgress(progress)

            // Incrementally update book_manifest.json so completed chapters appear immediately in library
            val isAllCompleted = chaptersArray.length() == parsedBook.chapters.size
            val currentManifest = JSONObject().apply {
                put("title", parsedBook.title)
                put("chapters_count", chaptersArray.length())
                put("total_chapters", parsedBook.chapters.size)
                put("chapters", chaptersArray)
                put("status", if (isAllCompleted) "completed" else "in_progress")
            }
            saveManifest(currentManifest)
        }

        // Auto-merge or create full unified audiobook file when synthesis finishes
        if (parsedBook.chapters.isNotEmpty()) {
            try {
                val allChapterFiles = (1..parsedBook.chapters.size).mapNotNull { idx ->
                    val f = File(chaptersDir, String.format(java.util.Locale.US, "chapter_%03d.wav", idx))
                    if (f.exists() && f.length() > 1000) f else null
                }
                if (allChapterFiles.size == parsedBook.chapters.size) {
                    val fullBookWav = File(outputDir, "full_book.wav")
                    if (allChapterFiles.size > 1) {
                        val fullDurationMs = concatenateWavs(allChapterFiles, fullBookWav)
                        val fullDurationSec = fullDurationMs / 1000
                        Log.i(TAG, "Successfully auto-merged ${allChapterFiles.size} chapters into full_book.wav ($fullDurationSec s)")
                    } else if (allChapterFiles.size == 1) {
                        allChapterFiles[0].copyTo(fullBookWav, overwrite = true)
                        Log.i(TAG, "Single chapter book prepared as full_book.wav")
                    }
                    AudioExporter.exportFullBookAudio(context, fullBookWav, parsedBook.title)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error generating full audiobook: ${e.message}", e)
            }
        }

        val finalManifest = JSONObject().apply {
            put("title", parsedBook.title)
            put("chapters_count", chaptersArray.length())
            put("total_chapters", parsedBook.chapters.size)
            put("chapters", chaptersArray)
            put("status", "completed")
            val fullWav = File(outputDir, "full_book.wav")
            if (fullWav.exists() && fullWav.length() > 1000) {
                put("full_audiobook_file", "full_book.wav")
            }
        }
        saveManifest(finalManifest)

        return@withContext finalManifest
    }

    private fun saveManifest(manifest: JSONObject) {
        val tempManifest = File(outputDir, "book_manifest.json.tmp")
        tempManifest.writeText(manifest.toString(2))
        tempManifest.renameTo(manifestFile)
    }

    private fun markManifestPaused(title: String, totalChapters: Int, chaptersArray: JSONArray) {
        try {
            val pausedManifest = if (manifestFile.exists()) {
                JSONObject(manifestFile.readText())
            } else {
                JSONObject().apply {
                    put("title", title)
                    put("total_chapters", totalChapters)
                }
            }
            pausedManifest.put("status", "paused")
            pausedManifest.put("chapters_count", chaptersArray.length())
            pausedManifest.put("chapters", chaptersArray)
            saveManifest(pausedManifest)
        } catch (saveEx: Exception) {
            Log.w(TAG, "Failed to save paused status: ${saveEx.message}")
        }
    }

    private fun concatenateWavs(files: List<File>, outputFile: File): Long {
        if (files.isEmpty()) return 0L

        var sampleRate = 24000
        var channels: Short = 1
        var bitsPerSample: Short = 16
        val pcmStreams = mutableListOf<ByteArray>()

        for (f in files) {
            if (!f.exists() || f.length() < 12) continue
            val bytes = f.readBytes()
            val parsed = GeminiTtsClient.extractPcmData(bytes)
            if (parsed != null) {
                channels = parsed.channels
                sampleRate = parsed.sampleRate
                bitsPerSample = parsed.bitsPerSample
                val smoothedPcm = applyGentleFadeOut(parsed.pcm, sampleRate, channels, bitsPerSample, 50)
                pcmStreams.add(smoothedPcm)
            } else if (bytes.size >= 44 && String(bytes.copyOfRange(0, 4)) == "RIFF") {
                val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
                channels = buffer.getShort(22)
                sampleRate = buffer.getInt(24)
                bitsPerSample = buffer.getShort(34)
                val pcm = bytes.copyOfRange(44, bytes.size)
                pcmStreams.add(pcm)
            } else {
                pcmStreams.add(bytes)
            }
        }

        val totalPcmSize = pcmStreams.sumOf { it.size }
        val combinedPcm = ByteArray(totalPcmSize)
        var offset = 0
        for (pcm in pcmStreams) {
            System.arraycopy(pcm, 0, combinedPcm, offset, pcm.size)
            offset += pcm.size
        }

        val fullWav = GeminiTtsClient.createWavHeader(
            combinedPcm,
            sampleRate = sampleRate,
            channels = channels,
            bitsPerSample = bitsPerSample
        )

        ttsClient.saveAudioAtomically(outputFile, fullWav)

        val bytesPerSec = sampleRate * channels * (bitsPerSample / 8)
        return if (bytesPerSec > 0) (totalPcmSize.toLong() * 1000) / bytesPerSec else 0L
    }

    private fun applyGentleFadeOut(
        pcm: ByteArray,
        sampleRate: Int,
        channels: Short,
        bitsPerSample: Short,
        fadeMs: Int = 50
    ): ByteArray {
        if (bitsPerSample != 16.toShort() || pcm.size < 4) return pcm
        val bytesPerSample = (channels * 2).toInt()
        val totalSamples = pcm.size / bytesPerSample
        val fadeSamples = ((sampleRate * fadeMs) / 1000).coerceAtMost(totalSamples)
        if (fadeSamples <= 0) return pcm

        val output = pcm.copyOf()
        val startSample = totalSamples - fadeSamples
        val buffer = ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN)

        for (i in 0 until fadeSamples) {
            val sampleIndex = startSample + i
            val gain = 1.0 - (i.toDouble() / fadeSamples.toDouble())
            for (ch in 0 until channels) {
                val bytePos = sampleIndex * bytesPerSample + ch * 2
                val originalVal = buffer.getShort(bytePos)
                val fadedVal = (originalVal * gain).toInt().coerceIn(-32768, 32767).toShort()
                buffer.putShort(bytePos, fadedVal)
            }
        }
        return output
    }
}
