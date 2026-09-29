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
object AudioExporter {

    private const val TAG = "AudioExporter"
    private const val AUTHORITY = "com.antigravity.audiobook.fileprovider"

    fun exportChapterToDownloads(
        context: Context,
        chapterWav: File,
        bookTitle: String,
        chapterIndex: Int,
        chapterTitle: String
    ): Uri? {
        if (!chapterWav.exists() || chapterWav.length() <= 1000) return null

        val safeBook = bookTitle.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "audiobook" }
        val safeChapter = chapterTitle.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "chapter_$chapterIndex" }
        val fileName = "${safeBook}_فصل_${String.format("%03d", chapterIndex)}_${safeChapter}.wav"

        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val resolver = context.contentResolver
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                    put(MediaStore.MediaColumns.MIME_TYPE, "audio/wav")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/Audiobooks/$safeBook")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
                val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                if (uri != null) {
                    resolver.openOutputStream(uri)?.use { out ->
                        chapterWav.inputStream().use { inp ->
                            inp.copyTo(out)
                        }
                    }
                    values.clear()
                    values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                    Log.i(TAG, "Exported chapter $chapterIndex to MediaStore: $fileName")
                    uri
                } else null
            } else {
                val pubDir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "Audiobooks/$safeBook").apply { mkdirs() }
                val target = File(pubDir, fileName)
                chapterWav.copyTo(target, overwrite = true)
                Log.i(TAG, "Exported chapter $chapterIndex to public file: ${target.absolutePath}")
                Uri.fromFile(target)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to export chapter $chapterIndex to downloads: ${e.message}", e)
            null
        }
    }

    fun exportBookToDownloads(context: Context, book: BookItem): Pair<Int, String> {
        val chapters = book.manifest.optJSONArray("chapters") ?: return Pair(0, "")
        val safeBook = book.title.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").trim().ifBlank { "audiobook" }
        val destPathDisplay = "Download/Audiobooks/$safeBook"
        var exportedCount = 0

        for (i in 0 until chapters.length()) {
            val chObj = chapters.getJSONObject(i)
            val audioPath = chObj.optString("audio_path", "")
            val audioFile = chObj.optString("audio_file", "")
            val title = chObj.optString("title", "فصل ${i + 1}")
            val chIdx = chObj.optInt("index", i + 1)

            val resolved = listOf(
                File(audioPath),
                File(book.bookDir, audioFile),
                File(book.bookDir, "chapters/chapter_%03d.wav".format(chIdx))
            ).firstOrNull { it.exists() && it.length() > 0 } ?: continue

            val uri = exportChapterToDownloads(context, resolved, book.title, chIdx, title)
            if (uri != null) {
                exportedCount++
            }
        }

        return Pair(exportedCount, destPathDisplay)
    }

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
