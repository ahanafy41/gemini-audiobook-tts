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
        private const val KEY_GEMINI_VOICE = "gemini_voice"
        private const val DEFAULT_GEMINI_VOICE = "Kore"
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
            try {
                filePickerLauncher.launch(arrayOf("text/plain", "text/markdown", "*/*"))
            } catch (e: Exception) {
                Log.e(TAG, "Error launching file picker: ${e.message}")
                Toast.makeText(this, "تعذر فتح منتقي الملفات", Toast.LENGTH_SHORT).show()
            }
        }

        btnSettings.setOnClickListener {
            showSettingsDialog()
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
            if (position in booksList.indices) {
                val book = booksList[position]
                playBook(book, chapterIndex = 1)
            }
        }

        listViewBooks.setOnItemLongClickListener { _, _, position, _ ->
            if (position in booksList.indices) {
                val book = booksList[position]
                showDeleteConfirmation(book)
            }
            true
        }
    }

    private fun initMediaController() {
        try {
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
        } catch (e: Exception) {
            Log.e(TAG, "Error initializing MediaController: ${e.message}")
        }
    }

    private fun announceStatus(message: String) {
        textStatusLiveRegion.text = message
    }

    private fun showSettingsDialog() {
        var currentApiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        var currentGeminiVoice = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_GEMINI_VOICE) ?: DEFAULT_GEMINI_VOICE

        val context = this
        val layout = android.widget.LinearLayout(context).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        // 1. API Key Input
        val labelApiKey = TextView(context).apply {
            text = "مفتاح Gemini API (إلزامي للتحويل بالذكاء الاصطناعي):"
            textSize = 14f
            setPadding(0, 0, 0, (4 * resources.displayMetrics.density).toInt())
            contentDescription = "عنوان: مفتاح Gemini API"
        }
        val inputApiKey = EditText(context).apply {
            hint = "أدخل مفتاح Gemini API الخاص بك"
            setText(currentApiKey)
            contentDescription = "حقل إدخال مفتاح Gemini API"
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        layout.addView(labelApiKey)
        layout.addView(inputApiKey)

        // 2. Button for Gemini Cloud Voice selection
        val btnSelectGeminiVoice = Button(context).apply {
            text = "صوت الذكاء الاصطناعي: $currentGeminiVoice"
            contentDescription = "زر اختيار صوت الذكاء الاصطناعي، الصوت المختار حالياً هو $currentGeminiVoice"
            setOnClickListener {
                showGeminiVoicePicker(currentGeminiVoice) { selected ->
                    currentGeminiVoice = selected
                    text = "صوت الذكاء الاصطناعي: $selected"
                    contentDescription = "زر اختيار صوت الذكاء الاصطناعي، الصوت المختار حالياً هو $selected"
                    announceStatus("تم اختيار صوت Gemini: $selected")
                }
            }
        }
        layout.addView(btnSelectGeminiVoice)

        // 3. Button for Test Audio Voice
        val btnTestVoice = Button(context).apply {
            text = "تجربة صوت الذكاء الاصطناعي في السماعة (Test Voice)"
            contentDescription = "زر تجربة وفحص صوت الذكاء الاصطناعي فوراً في السماعة"
            setOnClickListener {
                val enteredKey = inputApiKey.text.toString().trim()
                testAudioVoice(enteredKey, currentGeminiVoice)
            }
        }
        layout.addView(btnTestVoice)

        val scrollView = android.widget.ScrollView(context).apply {
            addView(layout)
        }

        AlertDialog.Builder(context)
            .setTitle("إعدادات صوت الذكاء الاصطناعي (Gemini TTS)")
            .setView(scrollView)
            .setPositiveButton(R.string.action_save) { _, _ ->
                val newKey = inputApiKey.text.toString().trim()
                settingsPrefs.edit()
                    .putString(KEY_API_KEY, newKey)
                    .putString(KEY_GEMINI_VOICE, currentGeminiVoice)
                    .apply()

                val msg = if (newKey.isNotBlank()) {
                    "تم حفظ إعدادات الذكاء الاصطناعي: صوت $currentGeminiVoice"
                } else {
                    "يرجى إدخال مفتاح Gemini API لتفعيل تحويل الكتب"
                }
                announceStatus(msg)
                Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showGeminiVoicePicker(currentSelected: String, onSelected: (String) -> Unit) {
        val voices = GeminiTtsClient.APPROVED_VOICES.toTypedArray()
        var selectedIdx = voices.indexOf(currentSelected)
        if (selectedIdx < 0) selectedIdx = 0

        AlertDialog.Builder(this)
            .setTitle("اختر صوت الذكاء الاصطناعي (Gemini Voice)")
            .setSingleChoiceItems(voices, selectedIdx) { dialog, which ->
                val chosenVoice = voices[which]
                onSelected(chosenVoice)
                dialog.dismiss()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun testAudioVoice(apiKey: String, geminiVoice: String) {
        val trimmedKey = apiKey.trim()
        if (trimmedKey.isBlank() || trimmedKey.length < 15) {
            announceStatus("يرجى إدخال مفتاح Gemini API أولاً لتجربة الصوت!")
            Toast.makeText(this, "يرجى إدخال مفتاح Gemini API أولاً", Toast.LENGTH_SHORT).show()
            return
        }

        announceStatus("جارِ تجربة صوت الذكاء الاصطناعي ($geminiVoice)...")
        lifecycleScope.launch {
            try {
                val client = GeminiTtsClient(apiKey = trimmedKey)
                val audioData = withContext(Dispatchers.IO) {
                    client.synthesize("مرحباً يا أحمد، هذا فحص واختبار صوت جيميني بالذكاء الاصطناعي.", voiceName = geminiVoice)
                }
                val previewFile = File(cacheDir, "preview_gemini.wav")
                client.saveAudioAtomically(previewFile, audioData)
                playAudioFileDirectly(previewFile)
                announceStatus("تم تشغيل صوت الذكاء الاصطناعي بنجاح: $geminiVoice")
            } catch (e: Exception) {
                Log.e(TAG, "Gemini preview failed: ${e.message}")
                announceStatus("فشل توليد الصوت: ${e.localizedMessage ?: e.message}")
                Toast.makeText(this@MainActivity, "خطأ: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun playAudioFileDirectly(file: File) {
        try {
            android.media.MediaPlayer().apply {
                setDataSource(file.absolutePath)
                prepare()
                start()
                setOnCompletionListener { mp ->
                    mp.release()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error playing audio file: ${e.message}")
        }
    }

    private fun showApiKeyDialog() {
        showSettingsDialog()
    }

    private fun showDeleteConfirmation(book: BookItem) {
        val totalChapters = book.manifest.optInt("total_chapters", book.chaptersCount)
        val isInProgress = totalChapters > book.chaptersCount

        val options = if (isInProgress) {
            arrayOf("تشغيل الفصول المتاحة", "استئناف تحويل باقي الفصول", "حذف الكتاب")
        } else {
            arrayOf("تشغيل الكتاب", "حذف الكتاب")
        }

        AlertDialog.Builder(this)
            .setTitle(book.title)
            .setItems(options) { _, which ->
                if (isInProgress) {
                    when (which) {
                        0 -> playBook(book, chapterIndex = 1)
                        1 -> {
                            announceStatus("لاستئناف الكتاب، اختر ملف النص الأصلي وسيتم إكمال الفصول المتبقية تلقائياً.")
                            try {
                                filePickerLauncher.launch(arrayOf("text/plain", "text/markdown", "*/*"))
                            } catch (e: Exception) {
                                Toast.makeText(this, "تعذر فتح منتقي الملفات", Toast.LENGTH_SHORT).show()
                            }
                        }
                        2 -> confirmActualDeletion(book)
                    }
                } else {
                    when (which) {
                        0 -> playBook(book, chapterIndex = 1)
                        1 -> confirmActualDeletion(book)
                    }
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun confirmActualDeletion(book: BookItem) {
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_delete_title)
            .setMessage("هل أنت متأكد من حذف '${book.title}' ومقاطعه الصوتية؟")
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
            try {
                announceStatus("جارِ استيراد الكتاب وقراءة الملف...")
                val rawName = getFileNameFromUri(uri)
                val safeName = if (!rawName.isNullOrBlank()) {
                    rawName.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_")
                } else {
                    "كتاب_${System.currentTimeMillis()}.txt"
                }
                val tempFile = File(cacheDir, safeName)

                withContext(Dispatchers.IO) {
                    contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(tempFile).use { output ->
                            input.copyTo(output)
                        }
                    } ?: throw IllegalStateException("تعذر فتح ملف الإدخال")
                }

                if (!tempFile.exists() || tempFile.length() == 0L) {
                    announceStatus("الملف المختار فارغ!")
                    Toast.makeText(this@MainActivity, "الملف المختار فارغ", Toast.LENGTH_LONG).show()
                    return@launch
                }

                val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
                val geminiVoice = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_GEMINI_VOICE) ?: DEFAULT_GEMINI_VOICE

                if (apiKey.isBlank() || apiKey.length < 15) {
                    announceStatus("يرجى إدخال مفتاح Gemini API في الإعدادات أولاً لتحويل الكتاب بالذكاء الاصطناعي")
                    Toast.makeText(this@MainActivity, "يرجى إدخال مفتاح Gemini API أولاً في الإعدادات", Toast.LENGTH_LONG).show()
                    showSettingsDialog()
                    return@launch
                }

                val bookTitle = tempFile.nameWithoutExtension.ifBlank { "كتاب صوتي" }
                val bookDir = File(File(filesDir, "audiobooks"), bookTitle)
                val ttsClient = GeminiTtsClient(apiKey = apiKey)
                val engine = AudiobookEngine(
                    context = this@MainActivity,
                    outputDir = bookDir,
                    ttsClient = ttsClient,
                    voiceName = geminiVoice
                )

                announceStatus("جارِ تحويل فصول الكتاب عبر الذكاء الاصطناعي Gemini TTS (صوت: $geminiVoice)...")

                withContext(Dispatchers.IO) {
                    engine.processBook(tempFile) { current, total, title ->
                        lifecycleScope.launch(Dispatchers.Main) {
                            announceStatus("تحويل الفصل $current من $total: $title")
                        }
                    }
                }

                announceStatus("اكتمل تجهيز الكتاب الصوتي بنجاح! اضغط عليه للاستماع.")
                Toast.makeText(this@MainActivity, "تم تجهيز الكتاب بنجاح", Toast.LENGTH_SHORT).show()
                refreshBooksList()
            } catch (e: Exception) {
                Log.e(TAG, "Error importing book: ${e.message}", e)
                refreshBooksList()
                announceStatus("حدث توقف أثناء المعالجة: ${e.localizedMessage ?: e.message}. تم حفظ الفصول المنجزة ويمكنك تشغيلها أو استئناف الباقي.")
                Toast.makeText(this@MainActivity, "تم حفظ الفصول المنجزة: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun getFileNameFromUri(uri: Uri): String? {
        var name: String? = null
        try {
            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (cursor.moveToFirst() && nameIndex >= 0) {
                    name = cursor.getString(nameIndex)
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to resolve display name from uri: ${e.message}")
        }
        return name
    }

    private fun playBook(book: BookItem, chapterIndex: Int) {
        currentActiveBook = book
        currentChapterIndex = chapterIndex

        val chapters = book.manifest.optJSONArray("chapters") ?: return
        if (chapterIndex < 1 || chapterIndex > chapters.length()) return

        val chapterObj = chapters.getJSONObject(chapterIndex - 1)
        val audioPath = chapterObj.optString("audio_path", "")
        val audioFile = chapterObj.optString("audio_file", "")
        val chapterTitle = chapterObj.optString("title", "فصل $chapterIndex")

        val candidate1 = File(audioPath)
        val candidate2 = File(book.bookDir, audioFile)
        val candidate3 = File(book.bookDir, "chapters/chapter_%03d.wav".format(chapterIndex))

        val resolvedFile = when {
            candidate1.exists() && candidate1.length() > 0 -> candidate1
            candidate2.exists() && candidate2.length() > 0 -> candidate2
            candidate3.exists() && candidate3.length() > 0 -> candidate3
            else -> null
        }

        if (resolvedFile == null) {
            announceStatus("الملف الصوتي لهذا الفصل غير متوفر")
            Toast.makeText(this, "الملف الصوتي غير موجود", Toast.LENGTH_SHORT).show()
            return
        }

        textNowPlayingTitle.text = book.title
        textNowPlayingChapter.text = chapterTitle
        announceStatus("تشغيل: ${book.title} - $chapterTitle")
        updatePlayPauseButton(true)

        val intent = Intent(this, AudiobookPlayerService::class.java).apply {
            action = AudiobookPlayerService.ACTION_PLAY_CHAPTER
            putExtra(AudiobookPlayerService.EXTRA_AUDIO_PATH, resolvedFile.absolutePath)
            putExtra(AudiobookPlayerService.EXTRA_BOOK_TITLE, book.title)
            putExtra(AudiobookPlayerService.EXTRA_CHAPTER_TITLE, chapterTitle)
            putExtra(AudiobookPlayerService.EXTRA_CHAPTER_INDEX, chapterIndex)
        }
        try {
            ContextCompat.startForegroundService(this, intent)
        } catch (e: Exception) {
            Log.e(TAG, "Error starting player service: ${e.message}")
            startService(intent)
        }
    }

    private fun togglePlayPause() {
        val mc = mediaController
        if (currentActiveBook == null && booksList.isNotEmpty()) {
            playBook(booksList[0], chapterIndex = 1)
            return
        }
        if (mc == null) {
            currentActiveBook?.let { playBook(it, currentChapterIndex) }
            return
        }
        if (mc.isPlaying) {
            mc.pause()
            updatePlayPauseButton(false)
            announceStatus("تم الإيقاف المؤقت")
        } else {
            if (mc.mediaItemCount == 0 && currentActiveBook != null) {
                playBook(currentActiveBook!!, currentChapterIndex)
            } else {
                mc.play()
                updatePlayPauseButton(true)
                announceStatus("جارِ التشغيل")
            }
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
        btnSpeed.text = "${currentSpeed}x"
        announceStatus("سرعة القراءة: ${currentSpeed} ضعف")
    }

    private fun updatePlayPauseButton(isPlaying: Boolean) {
        btnPlayPause.text = if (isPlaying) getString(R.string.action_pause) else getString(R.string.action_play)
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        updatePlayPauseButton(isPlaying)
    }

    override fun onDestroy() {
        controllerFuture?.let { MediaController.releaseFuture(it) }
        super.onDestroy()
    }

    private inner class BooksAdapter(
        private val context: Context,
        private val items: List<BookItem>
    ) : BaseAdapter() {

        override fun getCount(): Int = items.size
        override fun getItem(position: Int): Any = items[position]
        override fun getItemId(position: Int): Long = position.toLong()

        override fun getView(position: Int, convertView: View?, parent: ViewGroup?): View {
            val view = convertView ?: LayoutInflater.from(context).inflate(R.layout.item_book, parent, false)
            val book = items[position]

            val totalChapters = book.manifest.optInt("total_chapters", book.chaptersCount)
            val status = book.manifest.optString("status", if (book.chaptersCount >= totalChapters) "completed" else "in_progress")

            val textTitle = view.findViewById<TextView>(R.id.textBookTitle)
            val textSubtitle = view.findViewById<TextView>(R.id.textBookSubtitle)

            textTitle.text = book.title
            if (status == "in_progress" && totalChapters > book.chaptersCount) {
                textSubtitle.text = "${book.chaptersCount} من أصل $totalChapters فصول جاهزة (قيد الإكمال)"
                view.contentDescription = "${book.title}، يحتوي على ${book.chaptersCount} فصول جاهزة من أصل $totalChapters (قيد الإكمال). اضغط للتشغيل، أو اضغط مطولاً للخيارات والاستئناف"
            } else {
                textSubtitle.text = "${book.chaptersCount} فصل (مكتمل)"
                view.contentDescription = "${book.title}، مكتمل، يحتوي على ${book.chaptersCount} فصول. اضغط للتشغيل، أو اضغط مطولاً للخيارات"
            }

            view.setOnClickListener {
                playBook(book, chapterIndex = 1)
            }
            view.setOnLongClickListener {
                showDeleteConfirmation(book)
                true
            }

            return view
        }
    }
}
