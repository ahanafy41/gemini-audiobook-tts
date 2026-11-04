package com.antigravity.audiobook.util

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import androidx.core.content.FileProvider
import com.antigravity.audiobook.BookItem
import org.json.JSONObject
import java.io.File

/**
 * Utility for exporting and sharing converted audiobook WAV files
 * to public storage (/sdcard/Download/Audiobooks/) and system share sheet.
 */
import android.media.MediaScannerConnection
import java.util.Locale

data class ChapterAudioMeta(
    val index: Int,
    val title: String,
    val durationMs: Long,
    val audioRelativePath: String = ""
)

object AudioExporter {

    private const val TAG = "AudioExporter"
    private const val AUTHORITY = "com.antigravity.audiobook.fileprovider"

    const val DEDICATED_DIR = "GeminiAudiobook"

    fun generateCueSheet(
        bookTitle: String,
        chapters: List<ChapterAudioMeta>,
        unifiedWavFileName: String = "full_book.wav",
        silencePaddingMs: Long = 400L
    ): String {
        val cleanBookTitle = bookTitle.replace('"', '\'').trim()
        val lines = mutableListOf(
            "REM GENRE Audiobook",
            "REM DATE 2026",
            "PERFORMER \"Gemini Audiobook\"",
            "TITLE \"$cleanBookTitle\"",
            "FILE \"$unifiedWavFileName\" WAVE"
        )

        var currentMs = 0L
        for (i in chapters.indices) {
            val ch = chapters[i]
            val trackNum = i + 1
            val cleanTitle = ch.title.replace('"', '\'').trim()
            val totalSeconds = currentMs / 1000.0
            val minutes = (totalSeconds / 60).toInt()
            val seconds = (totalSeconds % 60).toInt()
            val frames = ((totalSeconds - totalSeconds.toInt()) * 75.0).toInt()

            lines.add(String.format(Locale.US, "  TRACK %02d AUDIO", trackNum))
            lines.add("    TITLE \"$cleanTitle\"")
            lines.add(String.format(Locale.US, "    INDEX 01 %02d:%02d:%02d", minutes, seconds, frames))

            currentMs += ch.durationMs + silencePaddingMs
        }

        return lines.joinToString("\n") + "\n"
    }

    fun generateM3uPlaylist(
        bookTitle: String,
        chapters: List<ChapterAudioMeta>
    ): String {
        val lines = mutableListOf(
            "#EXTM3U",
            "#PLAYLIST:$bookTitle"
        )

        for (ch in chapters) {
            val durSec = (ch.durationMs / 1000).coerceAtLeast(1)
            val relPath = if (ch.audioRelativePath.isNotBlank()) {
                ch.audioRelativePath
            } else {
                String.format(Locale.US, "chapters/chapter_%03d.wav", ch.index)
            }
            lines.add("#EXTINF:$durSec,${ch.title}")
            lines.add(relPath)
        }

        return lines.joinToString("\n") + "\n"
    }

    fun writeCueAndM3uFiles(
        outputDir: File,
        bookTitle: String,
        chapters: List<ChapterAudioMeta>,
        unifiedWavName: String = "full_book.wav"
    ) {
        try {
            outputDir.mkdirs()
            val cueContent = generateCueSheet(bookTitle, chapters, unifiedWavName)
            File(outputDir, "book.cue").writeText(cueContent, Charsets.UTF_8)

            val m3uContent = generateM3uPlaylist(bookTitle, chapters)
            File(outputDir, "playlist.m3u").writeText(m3uContent, Charsets.UTF_8)
            Log.i(TAG, "Generated book.cue and playlist.m3u in ${outputDir.absolutePath}")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to write CUE/M3U files: ${e.message}")
        }
    }

    fun hasDirectStorageAccess(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            true
        }
    }

    fun exportChapterToDedicatedFolder(
        context: Context,
        chapterWav: File,
        bookTitle: String,
        chapterIndex: Int,
        chapterTitle: String
    ): Uri? {
        if (!chapterWav.exists() || chapterWav.length() <= 1000) return null

        val safeBook = bookTitle.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "audiobook" }
        val safeChapter = chapterTitle.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "chapter_$chapterIndex" }
        val fileName = "${safeBook}_فصل_${String.format(Locale.US, "%03d", chapterIndex)}_${safeChapter}.wav"

        return try {
            if (hasDirectStorageAccess()) {
                val pubDir = File(Environment.getExternalStorageDirectory(), "$DEDICATED_DIR/$safeBook").apply { mkdirs() }
                val target = File(pubDir, fileName)
                chapterWav.copyTo(target, overwrite = true)
                Log.i(TAG, "Directly saved chapter $chapterIndex to: ${target.absolutePath}")
                MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), arrayOf("audio/wav"), null)
                Uri.fromFile(target)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val resolver = context.contentResolver
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "audio/wav")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_MUSIC}/$DEDICATED_DIR/$safeBook")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
                val uri = resolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values)
                if (uri != null) {
                    resolver.openOutputStream(uri)?.use { out ->
                        chapterWav.inputStream().use { inp ->
                            inp.copyTo(out)
                        }
                    }
                    values.clear()
                    values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                    Log.i(TAG, "Exported chapter $chapterIndex to GeminiAudiobook MediaStore: $fileName")
                    uri
                } else null
            } else {
                val pubDir = File(Environment.getExternalStorageDirectory(), "$DEDICATED_DIR/$safeBook").apply { mkdirs() }
                val target = File(pubDir, fileName)
                chapterWav.copyTo(target, overwrite = true)
                Log.i(TAG, "Exported chapter $chapterIndex to public file: ${target.absolutePath}")
                MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), arrayOf("audio/wav"), null)
                Uri.fromFile(target)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to export chapter $chapterIndex to GeminiAudiobook: ${e.message}", e)
            null
        }
    }

    // Alias for backward compatibility
    fun exportChapterToDownloads(
        context: Context,
        chapterWav: File,
        bookTitle: String,
        chapterIndex: Int,
        chapterTitle: String
    ): Uri? = exportChapterToDedicatedFolder(context, chapterWav, bookTitle, chapterIndex, chapterTitle)

    fun exportFullBookAudio(
        context: Context,
        fullWav: File,
        bookTitle: String
    ): Uri? {
        if (!fullWav.exists() || fullWav.length() <= 1000) return null
        val safeBook = bookTitle.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "audiobook" }
        val fileName = "${safeBook}_كامل.wav"

        return try {
            if (hasDirectStorageAccess()) {
                val pubDir = File(Environment.getExternalStorageDirectory(), "$DEDICATED_DIR/$safeBook").apply { mkdirs() }
                val target = File(pubDir, fileName)
                fullWav.copyTo(target, overwrite = true)
                Log.i(TAG, "Directly saved full audiobook to: ${target.absolutePath}")
                MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), arrayOf("audio/wav"), null)
                Uri.fromFile(target)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val resolver = context.contentResolver
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "audio/wav")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_MUSIC}/$DEDICATED_DIR/$safeBook")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
                val uri = resolver.insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, values)
                if (uri != null) {
                    resolver.openOutputStream(uri)?.use { out ->
                        fullWav.inputStream().use { inp ->
                            inp.copyTo(out)
                        }
                    }
                    values.clear()
                    values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                    Log.i(TAG, "Exported full merged audiobook to GeminiAudiobook MediaStore: $fileName")
                    uri
                } else null
            } else {
                val pubDir = File(Environment.getExternalStorageDirectory(), "$DEDICATED_DIR/$safeBook").apply { mkdirs() }
                val target = File(pubDir, fileName)
                fullWav.copyTo(target, overwrite = true)
                Log.i(TAG, "Exported full merged audiobook to public file: ${target.absolutePath}")
                MediaScannerConnection.scanFile(context, arrayOf(target.absolutePath), arrayOf("audio/wav"), null)
                Uri.fromFile(target)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to export full audiobook: ${e.message}", e)
            null
        }
    }

    fun exportBookToDedicatedFolder(context: Context, book: BookItem): Pair<Int, String> {
        val chapters = book.manifest.optJSONArray("chapters") ?: return Pair(0, "")
        val safeBook = book.title.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "audiobook" }
        val destPathDisplay = "$DEDICATED_DIR/$safeBook"
        var exportedCount = 0

        val fullWav = File(book.bookDir, "full_book.wav")
        if (fullWav.exists() && fullWav.length() > 1000) {
            exportFullBookAudio(context, fullWav, book.title)
        }

        for (i in 0 until chapters.length()) {
            val chObj = chapters.getJSONObject(i)
            val audioPath = chObj.optString("audio_path", "")
            val audioFile = chObj.optString("audio_file", "")
            val title = chObj.optString("title", "فصل ${i + 1}")
            val chIdx = chObj.optInt("index", i + 1)

            val resolved = listOf(
                File(audioPath),
                File(book.bookDir, audioFile),
                File(book.bookDir, "chapters/chapter_${String.format(Locale.US, "%03d", chIdx)}.wav")
            ).firstOrNull { it.exists() && it.length() > 0 } ?: continue

            val uri = exportChapterToDedicatedFolder(context, resolved, book.title, chIdx, title)
            if (uri != null) {
                exportedCount++
            }
        }

        val fullDisplayPath = if (hasDirectStorageAccess()) {
            "/sdcard/$DEDICATED_DIR/$safeBook"
        } else {
            "Music/$DEDICATED_DIR/$safeBook"
        }
        return Pair(exportedCount, fullDisplayPath)
    }

    fun exportBookToDownloads(context: Context, book: BookItem): Pair<Int, String> =
        exportBookToDedicatedFolder(context, book)

    fun shareBookAudio(context: Context, book: BookItem): Boolean {
        val chapters = book.manifest.optJSONArray("chapters") ?: return false
        val uris = ArrayList<Uri>()

        for (i in 0 until chapters.length()) {
            val chObj = chapters.getJSONObject(i)
            val audioPath = chObj.optString("audio_path", "")
            val audioFile = chObj.optString("audio_file", "")
            val chIdx = chObj.optInt("index", i + 1)

            val resolved = listOf(
                File(audioPath),
                File(book.bookDir, audioFile),
                File(book.bookDir, "chapters/chapter_%03d.wav".format(chIdx))
            ).firstOrNull { it.exists() && it.length() > 0 } ?: continue

            try {
                val contentUri = FileProvider.getUriForFile(context, AUTHORITY, resolved)
                uris.add(contentUri)
            } catch (e: Exception) {
                Log.w(TAG, "Failed to get content URI for chapter $chIdx: ${e.message}")
            }
        }

        if (uris.isEmpty()) return false

        return try {
            val intent = if (uris.size == 1) {
                Intent(Intent.ACTION_SEND).apply {
                    type = "audio/wav"
                    putExtra(Intent.EXTRA_STREAM, uris[0])
                    putExtra(Intent.EXTRA_SUBJECT, book.title)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
            } else {
                Intent(Intent.ACTION_SEND_MULTIPLE).apply {
                    type = "audio/wav"
                    putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                    putExtra(Intent.EXTRA_SUBJECT, book.title)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
            }
            val chooser = Intent.createChooser(intent, "مشاركة فصول: ${book.title}").apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(chooser)
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to launch share intent: ${e.message}")
            false
        }
    }
}
