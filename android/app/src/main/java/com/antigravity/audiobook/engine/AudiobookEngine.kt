package com.antigravity.audiobook.engine

import android.content.Context
import android.util.Log
import com.antigravity.audiobook.data.GeminiTtsClient
import com.antigravity.audiobook.domain.BookParser
import com.antigravity.audiobook.domain.CleanedChapter
import com.antigravity.audiobook.domain.ParsedBook
import com.antigravity.audiobook.domain.SmartTextChunker
import kotlinx.coroutines.Dispatchers
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
 * Uses Gemini Flash TTS with prebuilt high-fidelity neural voices.
 */
class AudiobookEngine(
    private val context: Context,
    private val outputDir: File,
    private val ttsClient: GeminiTtsClient,
    private val voiceName: String = "Kore",
    private val deliveryStyle: String = "narrator, natural pacing"
) {

    companion object {
        private const val TAG = "AudiobookEngine"
    }

    private val bookParser = BookParser()
    private val chunker = SmartTextChunker(7500)
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

    suspend fun processBook(
        bookFile: File,
        onProgressUpdate: (currentChapter: Int, totalChapters: Int, chapterTitle: String) -> Unit = { _, _, _ -> }
    ): JSONObject = withContext(Dispatchers.IO) {
        val parsedBook: ParsedBook = bookParser.parseFile(bookFile)
        val progress = loadProgress()
        val completedChapters = progress.optJSONObject("completed_chapters") ?: JSONObject()

        val chaptersDir = File(outputDir, "chapters").apply { mkdirs() }
        val rawChunksDir = File(outputDir, "raw_chunks").apply { mkdirs() }

        val chaptersArray = JSONArray()

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

                if (!chunkFile.exists() || chunkFile.length() <= 1000) {
                    if (!ttsClient.hasApiKey()) {
                        throw IllegalArgumentException("مفتاح Gemini API غير متوفر. يرجى إدخال المفتاح في الإعدادات أولاً.")
                    }

                    try {
                        val audioData = ttsClient.synthesize(chunkText, voiceName, deliveryStyle)
                        if (audioData.size > 1000) {
                            ttsClient.saveAudioAtomically(chunkFile, audioData)
                            Log.i(TAG, "Synthesized chunk ${cIdx + 1} via Gemini AI TTS (${audioData.size} bytes).")
                        } else {
                            throw IllegalStateException("استجابة الصوت غير مكتملة.")
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Gemini AI synthesis failed for chunk ${cIdx + 1}: ${e.message}")
                        throw e
                    }
                }
                chunkFiles.add(chunkFile)
            }

            // Concatenate chunk WAVs
            val durationMs = concatenateWavs(chunkFiles, chapterWav)
            val durationSec = durationMs / 1000

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
        }

        val manifest = JSONObject().apply {
            put("title", parsedBook.title)
            put("chapters_count", parsedBook.chapters.size)
            put("chapters", chaptersArray)
        }

        val tempManifest = File(outputDir, "book_manifest.json.tmp")
        tempManifest.writeText(manifest.toString(2))
        tempManifest.renameTo(manifestFile)

        return@withContext manifest
    }

    private fun concatenateWavs(files: List<File>, outputFile: File): Long {
        if (files.isEmpty()) return 0L

        var sampleRate = 24000
        var channels: Short = 1
        var bitsPerSample: Short = 16
        val pcmStreams = mutableListOf<ByteArray>()

        for (f in files) {
            if (!f.exists() || f.length() < 44) continue
            val bytes = f.readBytes()
            if (bytes.size >= 44 && String(bytes.copyOfRange(0, 4)) == "RIFF") {
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
}
