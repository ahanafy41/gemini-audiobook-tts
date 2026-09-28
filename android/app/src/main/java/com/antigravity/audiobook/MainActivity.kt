package com.antigravity.audiobook

import android.app.AlertDialog
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.antigravity.audiobook.data.GeminiTtsClient
import com.antigravity.audiobook.engine.AudiobookEngine
import com.antigravity.audiobook.player.AudiobookPlayerService
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

data class BookItem(
    val title: String,
    val bookDir: File,
    val chaptersCount: Int,
    val manifest: JSONObject
)

class MainActivity : AppCompatActivity(), Player.Listener {

    companion object {
        private const val TAG = "MainActivity"
        private const val PREFS_SETTINGS = "gemini_audiobook_settings"
        private const val KEY_API_KEY = "api_key"
    }

    private lateinit var btnAddBook: Button
    private lateinit var btnSettings: Button
    private lateinit var textStatusLiveRegion: TextView
    private lateinit var listViewBooks: ListView
    private lateinit var textEmptyBooks: TextView

    private lateinit var textNowPlayingTitle: TextView
    private lateinit var textNowPlayingChapter: TextView
    private lateinit var btnPrevChapter: Button
    private lateinit var btnRewind: Button
    private lateinit var btnPlayPause: Button
    private lateinit var btnFastForward: Button
    private lateinit var btnNextChapter: Button
    private lateinit var btnSpeed: Button

    private lateinit var settingsPrefs: SharedPreferences
    private var controllerFuture: ListenableFuture<MediaController>? = null
    private var mediaController: MediaController? = null

    private val booksList = mutableListOf<BookItem>()
    private lateinit var booksAdapter: BooksAdapter

    private var currentActiveBook: BookItem? = null
    private var currentChapterIndex: Int = 1
    private var currentSpeed: Float = 1.0f

    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            importAndProcessBook(uri)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        settingsPrefs = getSharedPreferences(PREFS_SETTINGS, Context.MODE_PRIVATE)

        initViews()
        setupListeners()
        initMediaController()
        refreshBooksList()
    }

    private fun initViews() {
        btnAddBook = findViewById(R.id.btnAddBook)
        btnSettings = findViewById(R.id.btnSettings)
        textStatusLiveRegion = findViewById(R.id.textStatusLiveRegion)
        listViewBooks = findViewById(R.id.listViewBooks)
        textEmptyBooks = findViewById(R.id.textEmptyBooks)

        textNowPlayingTitle = findViewById(R.id.textNowPlayingTitle)
        textNowPlayingChapter = findViewById(R.id.textNowPlayingChapter)
        btnPrevChapter = findViewById(R.id.btnPrevChapter)
        btnRewind = findViewById(R.id.btnRewind)
        btnPlayPause = findViewById(R.id.btnPlayPause)
        btnFastForward = findViewById(R.id.btnFastForward)
        btnNextChapter = findViewById(R.id.btnNextChapter)
        btnSpeed = findViewById(R.id.btnSpeed)

        booksAdapter = BooksAdapter(this, booksList)
        listViewBooks.adapter = booksAdapter
    }

    private fun setupListeners() {
        btnAddBook.setOnClickListener {
            filePickerLauncher.launch(arrayOf("text/plain", "text/markdown", "*/*"))
        }

        btnSettings.setOnClickListener {
            showApiKeyDialog()
        }

        btnPlayPause.setOnClickListener {
            togglePlayPause()
        }

        btnRewind.setOnClickListener {
            mediaController?.let { mc ->
                val newPos = (mc.currentPosition - 15000L).coerceAtLeast(0L)
                mc.seekTo(newPos)
                announceStatus("تم إرجاع 15 ثانية")
            }
        }

        btnFastForward.setOnClickListener {
            mediaController?.let { mc ->
                val newPos = mc.currentPosition + 30000L
                mc.seekTo(newPos)
                announceStatus("تم تقديم 30 ثانية")
            }
        }

        btnPrevChapter.setOnClickListener {
            playPreviousChapter()
        }

        btnNextChapter.setOnClickListener {
            playNextChapter()
        }

        btnSpeed.setOnClickListener {
            cycleSpeed()
        }

        listViewBooks.setOnItemClickListener { _, _, position, _ ->
            val book = booksList[position]
            playBook(book, chapterIndex = 1)
        }

        listViewBooks.setOnItemLongClickListener { _, _, position, _ ->
            val book = booksList[position]
            showDeleteConfirmation(book)
            true
        }
    }

    private fun initMediaController() {
        val sessionToken = SessionToken(this, ComponentName(this, AudiobookPlayerService::class.java))
        controllerFuture = MediaController.Builder(this, sessionToken).buildAsync()
        controllerFuture?.addListener({
            try {
                mediaController = controllerFuture?.get()
                mediaController?.addListener(this)
                updatePlayPauseButton(mediaController?.isPlaying == true)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to connect to MediaController: ${e.message}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun announceStatus(message: String) {
        textStatusLiveRegion.text = message
    }

    private fun showApiKeyDialog() {
        val input = EditText(this).apply {
            hint = getString(R.string.hint_api_key)
            setText(settingsPrefs.getString(KEY_API_KEY, ""))
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.dialog_enter_api_key)
            .setView(input)
            .setPositiveButton(R.string.action_save) { _, _ ->
                val key = input.text.toString().trim()
                settingsPrefs.edit().putString(KEY_API_KEY, key).apply()
                announceStatus("تم حفظ مفتاح API بنجاح")
                Toast.makeText(this, "تم حفظ المفتاح", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showDeleteConfirmation(book: BookItem) {
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_delete_title)
            .setMessage("هل تريد حذف '${book.title}'؟")
            .setPositiveButton(R.string.action_delete) { _, _ ->
                book.bookDir.deleteRecursively()
                refreshBooksList()
                announceStatus("تم حذف الكتاب")
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun refreshBooksList() {
        val audiobooksRoot = File(filesDir, "audiobooks")
        if (!audiobooksRoot.exists()) audiobooksRoot.mkdirs()

        booksList.clear()
        val dirs = audiobooksRoot.listFiles { f -> f.isDirectory } ?: emptyArray()
        for (dir in dirs) {
            val manifestFile = File(dir, "book_manifest.json")
            if (manifestFile.exists()) {
                try {
                    val json = JSONObject(manifestFile.readText())
                    val title = json.optString("title", dir.name)
                    val chapters = json.optJSONArray("chapters")
                    val count = chapters?.length() ?: 0
                    booksList.add(BookItem(title, dir, count, json))
                } catch (e: Exception) {
                    Log.w(TAG, "Error parsing manifest for ${dir.name}: ${e.message}")
                }
            }
        }

        booksAdapter.notifyDataSetChanged()
        textEmptyBooks.visibility = if (booksList.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun importAndProcessBook(uri: Uri) {
        lifecycleScope.launch {
            announceStatus("جارِ استيراد الكتاب وقراءة الملف...")
            val fileName = getFileNameFromUri(uri) ?: "كتاب_${System.currentTimeMillis()}"
            val tempFile = File(cacheDir, fileName)

            withContext(Dispatchers.IO) {
                contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(tempFile).use { output ->
                        input.copyTo(output)
                    }
                }
            }

            val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
            val bookDir = File(File(filesDir, "audiobooks"), tempFile.nameWithoutExtension)
            val ttsClient = GeminiTtsClient(apiKey = apiKey)
            val engine = AudiobookEngine(this@MainActivity, bookDir, ttsClient)

            announceStatus("جارِ تحويل فصول الكتاب عبر Gemini 3.8 Flash TTS...")

            withContext(Dispatchers.IO) {
                engine.processBook(tempFile) { current, total, title ->
                    lifecycleScope.launch(Dispatchers.Main) {
                        announceStatus("تحويل الفصل $current من $total: $title")
                    }
                }
            }

            announceStatus("اكتمل تجهيز الكتاب الصوتي!")
            refreshBooksList()
        }
    }

    private fun getFileNameFromUri(uri: Uri): String? {
        var name: String? = null
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (cursor.moveToFirst() && nameIndex >= 0) {
                name = cursor.getString(nameIndex)
            }
        }
        return name
    }

    private fun playBook(book: BookItem, chapterIndex: Int) {
        currentActiveBook = book
        currentChapterIndex = chapterIndex

        val chapters = book.manifest.optJSONArray("chapters") ?: return
        if (chapterIndex < 1 || chapterIndex > chapters.length()) return

        val chapterObj = chapters.getJSONObject(chapterIndex - 1)
        val audioPath = chapterObj.optString("audio_path")
        val chapterTitle = chapterObj.optString("title", "فصل $chapterIndex")

        textNowPlayingTitle.text = book.title
        textNowPlayingChapter.text = chapterTitle
        announceStatus("تشغيل: ${book.title} - $chapterTitle")

        val intent = Intent(this, AudiobookPlayerService::class.java).apply {
            action = AudiobookPlayerService.ACTION_PLAY_CHAPTER
            putExtra(AudiobookPlayerService.EXTRA_AUDIO_PATH, audioPath)
            putExtra(AudiobookPlayerService.EXTRA_BOOK_TITLE, book.title)
            putExtra(AudiobookPlayerService.EXTRA_CHAPTER_TITLE, chapterTitle)
            putExtra(AudiobookPlayerService.EXTRA_CHAPTER_INDEX, chapterIndex)
        }
        startService(intent)
    }

    private fun togglePlayPause() {
        val mc = mediaController ?: return
        if (mc.isPlaying) {
            mc.pause()
            updatePlayPauseButton(false)
            announceStatus("تم الإيقاف المؤقت")
        } else {
            mc.play()
            updatePlayPauseButton(true)
            announceStatus("جارِ التشغيل")
        }
    }

    private fun playNextChapter() {
        val book = currentActiveBook ?: return
        val total = book.manifest.optJSONArray("chapters")?.length() ?: 1
        if (currentChapterIndex < total) {
            playBook(book, currentChapterIndex + 1)
        } else {
            announceStatus("وصلت إلى نهاية الكتاب")
        }
    }

    private fun playPreviousChapter() {
        val book = currentActiveBook ?: return
        if (currentChapterIndex > 1) {
            playBook(book, currentChapterIndex - 1)
        } else {
            announceStatus("أنت بالفعل في الفصل الأول")
        }
    }

    private fun cycleSpeed() {
        val speeds = floatArrayOf(0.75f, 1.0f, 1.25f, 1.5f, 1.75f, 2.0f)
        var nextIdx = 0
        for (i in speeds.indices) {
            if (kotlin.math.abs(speeds[i] - currentSpeed) < 0.05f) {
                nextIdx = (i + 1) % speeds.size
                break
            }
        }
        currentSpeed = speeds[nextIdx]
        mediaController?.setPlaybackSpeed(currentSpeed)
        btnSpeed.text = "السرعة: ${currentSpeed}x"
        announceStatus("تم ضبط سرعة الصوت على ${currentSpeed}")
    }

    private fun updatePlayPauseButton(isPlaying: Boolean) {
        if (isPlaying) {
            btnPlayPause.text = getString(R.string.action_pause)
            btnPlayPause.contentDescription = getString(R.string.action_pause)
        } else {
            btnPlayPause.text = getString(R.string.action_play)
            btnPlayPause.contentDescription = getString(R.string.action_play)
        }
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        updatePlayPauseButton(isPlaying)
    }

    override fun onDestroy() {
        controllerFuture?.let { MediaController.releaseFuture(it) }
        super.onDestroy()
    }

    private class BooksAdapter(
        private val context: Context,
        private val items: List<BookItem>
    ) : BaseAdapter() {
        override fun getCount(): Int = items.size
        override fun getItem(pos: Int): Any = items[pos]
        override fun getItemId(pos: Int): Long = pos.toLong()

        override fun getView(pos: Int, convertView: View?, parent: ViewGroup?): View {
            val view = convertView ?: LayoutInflater.from(context).inflate(R.layout.item_book, parent, false)
            val item = items[pos]

            val textTitle = view.findViewById<TextView>(R.id.textBookTitle)
            val textSubtitle = view.findViewById<TextView>(R.id.textBookSubtitle)

            textTitle.text = item.title
            textSubtitle.text = "${item.chaptersCount} فصول • انقر للاستماع • اضغط مطولاً للحذف"
            view.contentDescription = "${item.title}، يحتوي على ${item.chaptersCount} فصول. اضغط للتشغيل أو اضغط مطولاً للحذف."

            return view
        }
    }
}
