package com.antigravity.audiobook

import android.app.AlertDialog
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.media.MediaPlayer
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
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.antigravity.audiobook.data.GeminiTtsClient
import com.antigravity.audiobook.domain.MultiSpeakerConfig
import com.antigravity.audiobook.domain.VoiceProfile
import com.antigravity.audiobook.domain.VoiceStylePreset
import com.antigravity.audiobook.engine.AudiobookEngine
import com.antigravity.audiobook.player.AudiobookPlayerService
import com.antigravity.audiobook.util.AudioExporter
import com.google.android.material.bottomnavigation.BottomNavigationView
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
        private const val KEY_VOICE_STYLE = "gemini_voice_style"
        private const val KEY_MULTI_SPEAKER = "gemini_multi_speaker"
        private const val KEY_CHARACTER_VOICE = "gemini_character_voice"
        private const val KEY_MODEL_ID = "gemini_model_id"
        private const val KEY_CUSTOM_VOICES_JSON = "custom_voices_json"

        private const val DEFAULT_NARRATOR_VOICE = "Charon"
        private const val DEFAULT_CHARACTER_VOICE = "Kore"
        private const val DEFAULT_STYLE_ID = "natural"
        private const val DEFAULT_MODEL_ID = "gemini-3.8-flash-tts"
    }

    // Navigation and Tab Containers
    private lateinit var bottomNav: BottomNavigationView
    private lateinit var textStatusLiveRegion: TextView
    private lateinit var layoutTabLibrary: View
    private lateinit var layoutTabPlayer: View
    private lateinit var layoutTabStudio: View
    private lateinit var layoutTabSettings: View

    // Tab 1: Library Views
    private lateinit var btnAddBook: Button
    private lateinit var listViewBooks: ListView
    private lateinit var textEmptyBooks: TextView
    private lateinit var textNowPlayingTitle: TextView
    private lateinit var textNowPlayingChapter: TextView
    private lateinit var btnPlayPauseMini: Button
    private lateinit var btnOpenFullPlayer: Button

    // Tab 2: Full Player Views
    private lateinit var textPlayerBookTitle: TextView
    private lateinit var textPlayerChapterTitle: TextView
    private lateinit var textPlayerProgress: TextView
    private lateinit var btnPrevChapter: Button
    private lateinit var btnRewind: Button
    private lateinit var btnPlayPause: Button
    private lateinit var btnFastForward: Button
    private lateinit var btnNextChapter: Button
    private lateinit var btnSpeed: Button

    // Tab 3: Voice Studio Views
    private lateinit var btnSelectNarratorVoice: Button
    private lateinit var btnSelectVoiceStyle: Button
    private lateinit var btnToggleMultiSpeaker: Button
    private lateinit var btnSelectCharacterVoice: Button
    private lateinit var btnTestVoiceAudition: Button
    private lateinit var btnCreateCustomVoice: Button
    private lateinit var btnSyncCustomVoices: Button

    // Tab 4: Settings Views
    private lateinit var textApiKeyStatus: TextView
    private lateinit var btnEditApiKey: Button
    private lateinit var btnTestApiKey: Button
    private lateinit var btnSelectModel: Button

    // State & Controllers
    private lateinit var settingsPrefs: SharedPreferences
    private val customVoices = mutableListOf<VoiceProfile>()
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

        loadCachedCustomVoices()
        initViews()
        setupBottomNavigation()
        setupListeners()
        initMediaController()
        refreshBooksList()
        updateStudioUI()
        updateSettingsUI()
        fetchAndLoadCustomVoices(userTriggered = false)
    }

    private fun initViews() {
        bottomNav = findViewById(R.id.bottomNav)
        textStatusLiveRegion = findViewById(R.id.textStatusLiveRegion)
        layoutTabLibrary = findViewById(R.id.layoutTabLibrary)
        layoutTabPlayer = findViewById(R.id.layoutTabPlayer)
        layoutTabStudio = findViewById(R.id.layoutTabStudio)
        layoutTabSettings = findViewById(R.id.layoutTabSettings)

        // Library Views
        btnAddBook = findViewById(R.id.btnAddBook)
        listViewBooks = findViewById(R.id.listViewBooks)
        textEmptyBooks = findViewById(R.id.textEmptyBooks)
        textNowPlayingTitle = findViewById(R.id.textNowPlayingTitle)
        textNowPlayingChapter = findViewById(R.id.textNowPlayingChapter)
        btnPlayPauseMini = findViewById(R.id.btnPlayPauseMini)
        btnOpenFullPlayer = findViewById(R.id.btnOpenFullPlayer)

        // Full Player Views
        textPlayerBookTitle = findViewById(R.id.textPlayerBookTitle)
        textPlayerChapterTitle = findViewById(R.id.textPlayerChapterTitle)
        textPlayerProgress = findViewById(R.id.textPlayerProgress)
        btnPrevChapter = findViewById(R.id.btnPrevChapter)
        btnRewind = findViewById(R.id.btnRewind)
        btnPlayPause = findViewById(R.id.btnPlayPause)
        btnFastForward = findViewById(R.id.btnFastForward)
        btnNextChapter = findViewById(R.id.btnNextChapter)
        btnSpeed = findViewById(R.id.btnSpeed)

        // Voice Studio Views
        btnSelectNarratorVoice = findViewById(R.id.btnSelectNarratorVoice)
        btnSelectVoiceStyle = findViewById(R.id.btnSelectVoiceStyle)
        btnToggleMultiSpeaker = findViewById(R.id.btnToggleMultiSpeaker)
        btnSelectCharacterVoice = findViewById(R.id.btnSelectCharacterVoice)
        btnTestVoiceAudition = findViewById(R.id.btnTestVoiceAudition)
        btnCreateCustomVoice = findViewById(R.id.btnCreateCustomVoice)
        btnSyncCustomVoices = findViewById(R.id.btnSyncCustomVoices)

        // Settings Views
        textApiKeyStatus = findViewById(R.id.textApiKeyStatus)
        btnEditApiKey = findViewById(R.id.btnEditApiKey)
        btnTestApiKey = findViewById(R.id.btnTestApiKey)
        btnSelectModel = findViewById(R.id.btnSelectModel)

        booksAdapter = BooksAdapter(this, booksList)
        listViewBooks.adapter = booksAdapter
    }

    private fun setupBottomNavigation() {
        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.tab_library -> {
                    switchTab(layoutTabLibrary)
                    announceStatus("تبويب المكتبة والكتب الصوتية")
                    true
                }
                R.id.tab_player -> {
                    switchTab(layoutTabPlayer)
                    announceStatus("تبويب المشغل الصوتي الكامل")
                    true
                }
                R.id.tab_studio -> {
                    switchTab(layoutTabStudio)
                    announceStatus("تبويب استوديو الأصوات وأنماط الإلقاء")
                    if (customVoices.isEmpty()) {
                        fetchAndLoadCustomVoices(userTriggered = false)
                    }
                    true
                }
                R.id.tab_settings -> {
                    switchTab(layoutTabSettings)
                    announceStatus("تبويب إعدادات التطبيق")
                    true
                }
                else -> false
            }
        }
    }

    private fun switchTab(targetView: View) {
        layoutTabLibrary.visibility = if (targetView == layoutTabLibrary) View.VISIBLE else View.GONE
        layoutTabPlayer.visibility = if (targetView == layoutTabPlayer) View.VISIBLE else View.GONE
        layoutTabStudio.visibility = if (targetView == layoutTabStudio) View.VISIBLE else View.GONE
        layoutTabSettings.visibility = if (targetView == layoutTabSettings) View.VISIBLE else View.GONE
    }

    private fun setupListeners() {
        // Library Actions
        btnAddBook.setOnClickListener {
            try {
                filePickerLauncher.launch(arrayOf("text/plain", "text/markdown", "*/*"))
            } catch (e: Exception) {
                Log.e(TAG, "Error launching file picker: ${e.message}")
                Toast.makeText(this, "تعذر فتح منتقي الملفات", Toast.LENGTH_SHORT).show()
            }
        }

        btnPlayPauseMini.setOnClickListener {
            togglePlayPause()
        }

        btnOpenFullPlayer.setOnClickListener {
            bottomNav.selectedItemId = R.id.tab_player
        }

        // Full Player Controls
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

        // Voice Studio Actions
        btnSelectNarratorVoice.setOnClickListener {
            showNarratorVoicePicker()
        }

        btnSelectVoiceStyle.setOnClickListener {
            showVoiceStylePicker()
        }

        btnToggleMultiSpeaker.setOnClickListener {
            toggleMultiSpeaker()
        }

        btnSelectCharacterVoice.setOnClickListener {
            showCharacterVoicePicker()
        }

        btnTestVoiceAudition.setOnClickListener {
            testCurrentAudition()
        }

        btnCreateCustomVoice.setOnClickListener {
            showVoiceDesignDialog()
        }

        btnSyncCustomVoices.setOnClickListener {
            fetchAndLoadCustomVoices(userTriggered = true)
        }

        // Settings Actions
        btnEditApiKey.setOnClickListener {
            showApiKeyEditDialog()
        }

        btnTestApiKey.setOnClickListener {
            testApiKeyConnection()
        }

        btnSelectModel.setOnClickListener {
            showModelSelectionDialog()
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

    // -------------------------------------------------------------------------
    // Voice Studio Management & Custom Voice Cloud Sync
    // -------------------------------------------------------------------------

    private fun loadCachedCustomVoices() {
        customVoices.clear()
        val rawJson = settingsPrefs.getString(KEY_CUSTOM_VOICES_JSON, null) ?: return
        try {
            val array = org.json.JSONArray(rawJson)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val id = obj.optString("id")
                val disp = obj.optString("displayNameArabic", id)
                val desc = obj.optString("descriptionArabic", "")
                if (id.isNotBlank()) {
                    customVoices.add(VoiceProfile(id, disp, isCustomVoiceDesign = true, descriptionArabic = desc))
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Error parsing cached custom voices: ${e.message}")
        }
    }

    private fun saveCustomVoicesToPrefs(list: List<VoiceProfile>) {
        val array = org.json.JSONArray()
        for (v in list) {
            val obj = org.json.JSONObject().apply {
                put("id", v.id)
                put("displayNameArabic", v.displayNameArabic)
                put("descriptionArabic", v.descriptionArabic)
            }
            array.put(obj)
        }
        settingsPrefs.edit().putString(KEY_CUSTOM_VOICES_JSON, array.toString()).apply()
    }

    private fun fetchAndLoadCustomVoices(userTriggered: Boolean = false) {
        val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        if (apiKey.isBlank() || apiKey.length < 15) {
            if (userTriggered) {
                announceStatus("يرجى إدخال مفتاح Gemini API في الإعدادات أولاً لمزامنة الأصوات")
                Toast.makeText(this, "يرجى تسجيل المفتاح في الإعدادات أولاً", Toast.LENGTH_SHORT).show()
            }
            return
        }

        if (userTriggered) {
            announceStatus("جارِ مزامنة واسترجاع الأصوات المصممة من حسابك على Google...")
        }

        lifecycleScope.launch {
            try {
                val client = GeminiTtsClient(apiKey = apiKey)
                val fetched = client.listCustomVoices()
                if (fetched.isNotEmpty()) {
                    customVoices.clear()
                    customVoices.addAll(fetched)
                    saveCustomVoicesToPrefs(fetched)
                    updateStudioUI()
                    val msg = "تم العثور على ${fetched.size} أصوات مصممة خاصة بمفتاحك ومزامنتها بنجاح!"
                    announceStatus(msg)
                    if (userTriggered) {
                        Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
                    }
                } else if (userTriggered) {
                    announceStatus("لم يتم العثور على أصوات مصممة محفوظة على هذا المفتاح حتى الآن")
                    Toast.makeText(this@MainActivity, "لم يتم العثور على أصوات مصممة محفوظة", Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Log.w(TAG, "Failed to fetch custom voices: ${e.message}")
                if (userTriggered) {
                    announceStatus("تعذر مزامنة الأصوات: ${e.localizedMessage ?: e.message}")
                    Toast.makeText(this@MainActivity, "خطأ في المزامنة: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun getVoiceProfile(id: String): VoiceProfile {
        val custom = customVoices.firstOrNull { it.id.equals(id, ignoreCase = true) }
        if (custom != null) return custom
        return VoiceProfile.fromStoredString(id)
    }

    private fun updateStudioUI() {
        val narratorId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        val narratorProfile = getVoiceProfile(narratorId)
        btnSelectNarratorVoice.text = "صوت الراوي: ${narratorProfile.displayNameArabic}"
        btnSelectNarratorVoice.contentDescription = "زر اختيار صوت الراوي الأساسي، المختار حالياً هو ${narratorProfile.displayNameArabic}"

        val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        val stylePreset = VoiceStylePreset.fromId(styleId)
        btnSelectVoiceStyle.text = "نمط الإلقاء: ${stylePreset.titleArabic}"
        btnSelectVoiceStyle.contentDescription = "زر اختيار نمط الإلقاء الصوتي، النمط المختار هو ${stylePreset.titleArabic}"

        val isMultiSpeaker = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        btnToggleMultiSpeaker.text = if (isMultiSpeaker) "الحوار متعدد الرواة: مفعّل" else "الحوار متعدد الرواة: معطّل"
        btnToggleMultiSpeaker.contentDescription = "زر تبديل الحوار متعدد الرواة، الحالة الحالية هي ${if (isMultiSpeaker) "مفعل" else "معطل"}"
        btnSelectCharacterVoice.visibility = if (isMultiSpeaker) View.VISIBLE else View.GONE

        val characterId = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
        val characterProfile = getVoiceProfile(characterId)
        btnSelectCharacterVoice.text = "صوت الشخصيات: ${characterProfile.displayNameArabic}"
        btnSelectCharacterVoice.contentDescription = "زر اختيار صوت الشخصيات والحوار، المختار حالياً هو ${characterProfile.displayNameArabic}"
    }

    private fun showNarratorVoicePicker() {
        val combinedVoices = mutableListOf<VoiceProfile>()
        combinedVoices.addAll(customVoices)
        combinedVoices.addAll(VoiceProfile.PREBUILT_VOICES)

        val displayItems = mutableListOf<String>()
        for (v in customVoices) {
            displayItems.add("⭐ [صوت مصمم] ${v.displayNameArabic}")
        }
        for (v in VoiceProfile.PREBUILT_VOICES) {
            displayItems.add("${v.displayNameArabic} (${v.descriptionArabic})")
        }
        displayItems.add("+ إدخال معرف صوت مخصص يدوياً (Voice ID)")
        displayItems.add("🔄 مزامنة واسترجاع الأصوات من السحابة")

        val currentVoiceId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        var selectedIdx = combinedVoices.indexOfFirst { it.id.equals(currentVoiceId, ignoreCase = true) }
        if (selectedIdx < 0) selectedIdx = customVoices.size

        AlertDialog.Builder(this)
            .setTitle("اختر صوت الراوي الأساسي")
            .setSingleChoiceItems(displayItems.toTypedArray(), selectedIdx) { dialog, which ->
                when {
                    which < combinedVoices.size -> {
                        val chosen = combinedVoices[which]
                        settingsPrefs.edit().putString(KEY_GEMINI_VOICE, chosen.id).apply()
                        updateStudioUI()
                        announceStatus("تم اختيار صوت الراوي: ${chosen.displayNameArabic}")
                        dialog.dismiss()
                    }
                    which == combinedVoices.size -> {
                        dialog.dismiss()
                        showManualVoiceIdDialog(isCharacter = false)
                    }
                    else -> {
                        dialog.dismiss()
                        fetchAndLoadCustomVoices(userTriggered = true)
                    }
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showCharacterVoicePicker() {
        val combinedVoices = mutableListOf<VoiceProfile>()
        combinedVoices.addAll(customVoices)
        combinedVoices.addAll(VoiceProfile.PREBUILT_VOICES)

        val displayItems = mutableListOf<String>()
        for (v in customVoices) {
            displayItems.add("⭐ [صوت مصمم] ${v.displayNameArabic}")
        }
        for (v in VoiceProfile.PREBUILT_VOICES) {
            displayItems.add("${v.displayNameArabic} (${v.descriptionArabic})")
        }
        displayItems.add("+ إدخال معرف صوت مخصص يدوياً (Voice ID)")
        displayItems.add("🔄 مزامنة واسترجاع الأصوات من السحابة")

        val currentVoiceId = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
        var selectedIdx = combinedVoices.indexOfFirst { it.id.equals(currentVoiceId, ignoreCase = true) }
        if (selectedIdx < 0) selectedIdx = if (customVoices.isNotEmpty()) customVoices.size + 1 else 1

        AlertDialog.Builder(this)
            .setTitle("اختر صوت شخصيات الحوار")
            .setSingleChoiceItems(displayItems.toTypedArray(), selectedIdx) { dialog, which ->
                when {
                    which < combinedVoices.size -> {
                        val chosen = combinedVoices[which]
                        settingsPrefs.edit().putString(KEY_CHARACTER_VOICE, chosen.id).apply()
                        updateStudioUI()
                        announceStatus("تم اختيار صوت الشخصيات: ${chosen.displayNameArabic}")
                        dialog.dismiss()
                    }
                    which == combinedVoices.size -> {
                        dialog.dismiss()
                        showManualVoiceIdDialog(isCharacter = true)
                    }
                    else -> {
                        dialog.dismiss()
                        fetchAndLoadCustomVoices(userTriggered = true)
                    }
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showManualVoiceIdDialog(isCharacter: Boolean) {
        val input = EditText(this).apply {
            hint = "أدخل معرف الصوت (مثال: voice_42n103zlznqt)"
            contentDescription = "حقل إدخال معرف الصوت المخصص"
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        AlertDialog.Builder(this)
            .setTitle("إدخال معرف صوت مخصص (Voice ID)")
            .setView(input)
            .setPositiveButton("اعتماد الصوت") { _, _ ->
                val enteredId = input.text.toString().trim()
                if (enteredId.isBlank()) {
                    Toast.makeText(this, "يرجى إدخال معرف الصوت", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                val newProfile = VoiceProfile(
                    id = enteredId,
                    displayNameArabic = "صوت مخصص ($enteredId)",
                    isCustomVoiceDesign = true,
                    descriptionArabic = "معرف مخصص مدخل يدوياً"
                )
                if (customVoices.none { it.id.equals(enteredId, ignoreCase = true) }) {
                    customVoices.add(0, newProfile)
                    saveCustomVoicesToPrefs(customVoices)
                }
                val prefKey = if (isCharacter) KEY_CHARACTER_VOICE else KEY_GEMINI_VOICE
                settingsPrefs.edit().putString(prefKey, enteredId).apply()
                updateStudioUI()
                announceStatus("تم تفعيل الصوت المخصص: $enteredId")
                Toast.makeText(this, "تم تفعيل الصوت المخصص بنجاح", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showVoiceStylePicker() {
        val styles = VoiceStylePreset.entries.toTypedArray()
        val displayItems = styles.map { "${it.titleArabic}: ${it.descriptionArabic}" }.toTypedArray()
        val currentStyleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        var selectedIdx = styles.indexOfFirst { it.id.equals(currentStyleId, ignoreCase = true) }
        if (selectedIdx < 0) selectedIdx = 0

        AlertDialog.Builder(this)
            .setTitle("اختر نمط الإلقاء الصوتي")
            .setSingleChoiceItems(displayItems, selectedIdx) { dialog, which ->
                val chosen = styles[which]
                settingsPrefs.edit().putString(KEY_VOICE_STYLE, chosen.id).apply()
                updateStudioUI()
                announceStatus("تم اختيار نمط الإلقاء: ${chosen.titleArabic}")
                dialog.dismiss()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun toggleMultiSpeaker() {
        val current = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        val updated = !current
        settingsPrefs.edit().putBoolean(KEY_MULTI_SPEAKER, updated).apply()
        updateStudioUI()
        announceStatus(if (updated) "تم تفعيل الحوار متعدد الرواة" else "تم تعطيل الحوار متعدد الرواة")
    }

    private fun testCurrentAudition() {
        val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        if (apiKey.isBlank() || apiKey.length < 15) {
            announceStatus("يرجى إدخال مفتاح Gemini API في تبويب الإعدادات أولاً")
            Toast.makeText(this, "يرجى إدخال مفتاح API أولاً", Toast.LENGTH_SHORT).show()
            bottomNav.selectedItemId = R.id.tab_settings
            return
        }

        val narratorId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        val stylePreset = VoiceStylePreset.fromId(styleId)
        val isMultiSpeaker = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        val characterId = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
        val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID

        announceStatus("جارِ توليد عينة صوتية بالذكاء الاصطناعي...")
        lifecycleScope.launch {
            try {
                val client = GeminiTtsClient(apiKey = apiKey, modelId = modelId)
                val audioData = withContext(Dispatchers.IO) {
                    if (isMultiSpeaker) {
                        val multiConfig = MultiSpeakerConfig(
                            isEnabled = true,
                            narratorVoice = VoiceProfile.fromStoredString(narratorId),
                            characterVoice = VoiceProfile.fromStoredString(characterId)
                        )
                        val text = "قال الراوي بصوت وقور ومدروس: «أهلاً بكم في عالم الكتب الصوتية الذكية». فأصغى الجميع في اهتمام."
                        client.synthesize(text, voiceName = narratorId, stylePreset = stylePreset, multiSpeakerConfig = multiConfig)
                    } else {
                        val text = "مرحباً يا أحمد، هذا فحص واختبار لصوت جيميني بالذكاء الاصطناعي بنمط ${stylePreset.titleArabic}."
                        client.synthesize(text, voiceName = narratorId, stylePreset = stylePreset)
                    }
                }
                val previewFile = File(cacheDir, "audition_test.wav")
                client.saveAudioAtomically(previewFile, audioData)
                playAudioFileDirectly(previewFile)
                announceStatus("تم تشغيل المعاينة الصوتية بنجاح")
            } catch (e: Exception) {
                Log.e(TAG, "Audition test failed: ${e.message}")
                announceStatus("فشل توليد الصوت: ${e.localizedMessage ?: e.message}")
                Toast.makeText(this@MainActivity, "خطأ: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun showVoiceDesignDialog() {
        val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        if (apiKey.isBlank() || apiKey.length < 15) {
            announceStatus("يرجى إدخال مفتاح Gemini API في تبويب الإعدادات أولاً")
            Toast.makeText(this, "يرجى إدخال مفتاح API أولاً", Toast.LENGTH_SHORT).show()
            bottomNav.selectedItemId = R.id.tab_settings
            return
        }

        val context = this
        val layout = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        val inputName = EditText(context).apply {
            hint = getString(R.string.dialog_voice_design_name_hint)
            contentDescription = "اسم الصوت الجديد"
        }
        val inputPrompt = EditText(context).apply {
            hint = getString(R.string.dialog_voice_design_prompt_hint)
            contentDescription = "وصف النبرة بالإنجليزية"
            minLines = 3
        }

        layout.addView(TextView(context).apply {
            text = "اسم الصوت:"
            textSize = 14f
            setTextColor(ContextCompat.getColor(context, R.color.text_high_contrast))
        })
        layout.addView(inputName)
        layout.addView(TextView(context).apply {
            text = "وصف الصوت (باللغة الإنجليزية):"
            textSize = 14f
            setTextColor(ContextCompat.getColor(context, R.color.text_high_contrast))
            setPadding(0, (12 * resources.displayMetrics.density).toInt(), 0, 0)
        })
        layout.addView(inputPrompt)

        AlertDialog.Builder(context)
            .setTitle(R.string.dialog_voice_design_title)
            .setView(layout)
            .setPositiveButton(R.string.btn_generate_voice) { _, _ ->
                val name = inputName.text.toString().trim()
                val prompt = inputPrompt.text.toString().trim()
                if (name.isBlank() || prompt.isBlank()) {
                    Toast.makeText(context, "يرجى إدخال اسم الصوت ووصفه", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                announceStatus("جارِ تصميم الصوت الجديد بالذكاء الاصطناعي...")
                lifecycleScope.launch {
                    try {
                        val client = GeminiTtsClient(apiKey = apiKey)
                        val (voiceId, sampleBytes) = client.createCustomVoice(name, prompt)
                        val newProfile = VoiceProfile(
                            id = voiceId,
                            displayNameArabic = "$name ($voiceId)",
                            isCustomVoiceDesign = true,
                            descriptionArabic = prompt
                        )
                        if (customVoices.none { it.id.equals(voiceId, ignoreCase = true) }) {
                            customVoices.add(0, newProfile)
                            saveCustomVoicesToPrefs(customVoices)
                        }
                        settingsPrefs.edit().putString(KEY_GEMINI_VOICE, voiceId).apply()
                        updateStudioUI()
                        announceStatus("تم إنشاء الصوت بنجاح بمعرف: $voiceId")
                        Toast.makeText(context, "تم حفظ وتفعيل الصوت المخصص!", Toast.LENGTH_SHORT).show()

                        sampleBytes?.let { bytes ->
                            val sampleFile = File(cacheDir, "sample_designed_$voiceId.wav")
                            client.saveAudioAtomically(sampleFile, bytes)
                            playAudioFileDirectly(sampleFile)
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Voice design creation failed: ${e.message}")
                        announceStatus("تعذر تصميم الصوت: ${e.localizedMessage ?: e.message}")
                        Toast.makeText(context, "خطأ: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    // -------------------------------------------------------------------------
    // Settings Tab Management
    // -------------------------------------------------------------------------

    private fun updateSettingsUI() {
        val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        if (apiKey.isNotBlank() && apiKey.length >= 15) {
            val masked = "${apiKey.take(6)}...${apiKey.takeLast(4)}"
            textApiKeyStatus.text = "المفتاح مسجل ونشط: $masked"
            textApiKeyStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
        } else {
            textApiKeyStatus.text = "المفتاح غير مسجل، يرجى إدخال مفتاح Gemini API لتفعيل التحويل"
            textApiKeyStatus.setTextColor(ContextCompat.getColor(this, R.color.text_secondary))
        }

        val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
        btnSelectModel.text = "النموذج المعتمد: $modelId"
    }

    private fun showApiKeyEditDialog() {
        val currentKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        val input = EditText(this).apply {
            hint = "أدخل مفتاح Gemini API الخاص بك"
            setText(currentKey)
            contentDescription = "حقل إدخال مفتاح Gemini API"
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.dialog_enter_api_key)
            .setView(input)
            .setPositiveButton(R.string.action_save) { _, _ ->
                val newKey = input.text.toString().trim()
                settingsPrefs.edit().putString(KEY_API_KEY, newKey).apply()
                updateSettingsUI()
                announceStatus("تم حفظ مفتاح Gemini API بنجاح")
                Toast.makeText(this, "تم حفظ المفتاح", Toast.LENGTH_SHORT).show()
                fetchAndLoadCustomVoices(userTriggered = false)
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun testApiKeyConnection() {
        val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        if (apiKey.isBlank() || apiKey.length < 15) {
            announceStatus("يرجى إدخال مفتاح Gemini API أولاً لفحصه")
            Toast.makeText(this, "المفتاح غير مسجل بعد", Toast.LENGTH_SHORT).show()
            return
        }

        announceStatus("جارِ فحص الاتصال بمفتاح Gemini API...")
        lifecycleScope.launch {
            try {
                val client = GeminiTtsClient(apiKey = apiKey)
                val testAudio = withContext(Dispatchers.IO) {
                    client.synthesize("فحص الاتصال ناجح، المفتاح يعمل بكفاءة.", voiceName = "Charon")
                }
                if (testAudio.size > 1000) {
                    val previewFile = File(cacheDir, "test_conn.wav")
                    client.saveAudioAtomically(previewFile, testAudio)
                    playAudioFileDirectly(previewFile)
                    announceStatus("الاتصال ناجح تماماً! المفتاح صالح ومستعد لتوليد الكتب الصوتية.")
                    Toast.makeText(this@MainActivity, "الاتصال ناجح ومفتاحك فعال 100%", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                Log.e(TAG, "API Connection test failed: ${e.message}")
                announceStatus("فشل فحص الاتصال: ${e.localizedMessage ?: e.message}")
                Toast.makeText(this@MainActivity, "خطأ في المفتاح: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun showModelSelectionDialog() {
        val models = arrayOf("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
        val currentModel = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
        var selectedIdx = models.indexOf(currentModel)
        if (selectedIdx < 0) selectedIdx = 0

        AlertDialog.Builder(this)
            .setTitle("اختر نموذج الذكاء الاصطناعي")
            .setSingleChoiceItems(models, selectedIdx) { dialog, which ->
                val chosen = models[which]
                settingsPrefs.edit().putString(KEY_MODEL_ID, chosen).apply()
                updateSettingsUI()
                announceStatus("تم اعتماد النموذج: $chosen")
                dialog.dismiss()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    // -------------------------------------------------------------------------
    // Audio Playback & Book Management
    // -------------------------------------------------------------------------

    private fun playAudioFileDirectly(file: File) {
        try {
            MediaPlayer().apply {
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

    private fun showDeleteConfirmation(book: BookItem) {
        val totalChapters = book.manifest.optInt("total_chapters", book.chaptersCount)
        val isInProgress = totalChapters > book.chaptersCount

        val options = if (isInProgress) {
            arrayOf(
                "تشغيل الفصول المتاحة",
                "استئناف تحويل باقي الفصول",
                "تصدير الفصول المنجزة إلى التنزيلات (Downloads)",
                "مشاركة الملفات الصوتية (Share)",
                "حذف الكتاب"
            )
        } else {
            arrayOf(
                "تشغيل الكتاب",
                "تصدير الصوت إلى مجلد التنزيلات (Downloads)",
                "مشاركة الملفات الصوتية (Share)",
                "حذف الكتاب"
            )
        }

        AlertDialog.Builder(this)
            .setTitle(book.title)
            .setItems(options) { _, which ->
                if (isInProgress) {
                    when (which) {
                        0 -> playBook(book, chapterIndex = 1)
                        1 -> resumeIncompleteBook(book)
                        2 -> exportBook(book)
                        3 -> shareBook(book)
                        4 -> confirmActualDeletion(book)
                    }
                } else {
                    when (which) {
                        0 -> playBook(book, chapterIndex = 1)
                        1 -> exportBook(book)
                        2 -> shareBook(book)
                        3 -> confirmActualDeletion(book)
                    }
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun exportBook(book: BookItem) {
        announceStatus("جارِ تصدير فصول الكتاب إلى مجلد التنزيلات...")
        lifecycleScope.launch(Dispatchers.IO) {
            val (count, path) = AudioExporter.exportBookToDownloads(this@MainActivity, book)
            withContext(Dispatchers.Main) {
                if (count > 0) {
                    val msg = "تم تصدير $count فصول بنجاح إلى: $path"
                    announceStatus(msg)
                    Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
                } else {
                    announceStatus("لم يتم العثور على فصول جاهزة لتصديرها")
                    Toast.makeText(this@MainActivity, "لا توجد فصول جاهزة", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun shareBook(book: BookItem) {
        val ok = AudioExporter.shareBookAudio(this, book)
        if (!ok) {
            announceStatus("تعذر مشاركة الملفات الصوتية")
            Toast.makeText(this, "تعذر مشاركة الملفات الصوتية", Toast.LENGTH_SHORT).show()
        }
    }

    private fun resumeIncompleteBook(book: BookItem) {
        val persistentSource = File(book.bookDir, "source_book.txt")
        if (persistentSource.exists() && persistentSource.length() > 0) {
            announceStatus("استئناف معالجة الفصول المتبقية لكتاب «${book.title}»...")
            startBookProcessing(persistentSource, book.bookDir, book.title)
        } else {
            announceStatus("يرجى اختيار ملف النص الأصلي للكتاب لاستئناف معالجته.")
            try {
                filePickerLauncher.launch(arrayOf("text/plain", "text/markdown", "*/*"))
            } catch (e: Exception) {
                Toast.makeText(this, "تعذر فتح منتقي الملفات", Toast.LENGTH_SHORT).show()
            }
        }
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

                val bookTitle = tempFile.nameWithoutExtension.ifBlank { "كتاب صوتي" }
                val bookDir = File(File(filesDir, "audiobooks"), bookTitle)
                startBookProcessing(tempFile, bookDir, bookTitle)
            } catch (e: Exception) {
                Log.e(TAG, "Error importing book: ${e.message}", e)
                announceStatus("فشل استيراد الملف: ${e.localizedMessage ?: e.message}")
                Toast.makeText(this@MainActivity, "فشل الاستيراد: ${e.localizedMessage ?: e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun startBookProcessing(sourceFile: File, bookDir: File, bookTitle: String) {
        lifecycleScope.launch {
            try {
                val apiKey = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
                val narratorVoice = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
                val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
                val stylePreset = VoiceStylePreset.fromId(styleId)
                val isMultiSpeaker = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
                val characterVoice = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
                val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID

                if (apiKey.isBlank() || apiKey.length < 15) {
                    announceStatus("يرجى إدخال مفتاح Gemini API في الإعدادات أولاً لتحويل الكتاب بالذكاء الاصطناعي")
                    Toast.makeText(this@MainActivity, "يرجى إدخال مفتاح Gemini API أولاً في الإعدادات", Toast.LENGTH_LONG).show()
                    bottomNav.selectedItemId = R.id.tab_settings
                    return@launch
                }

                bookDir.mkdirs()
                val persistentSource = File(bookDir, "source_book.txt")
                if (sourceFile.absolutePath != persistentSource.absolutePath) {
                    sourceFile.copyTo(persistentSource, overwrite = true)
                }

                val ttsClient = GeminiTtsClient(apiKey = apiKey, modelId = modelId)
                val multiConfig = if (isMultiSpeaker) {
                    MultiSpeakerConfig(
                        isEnabled = true,
                        narratorVoice = getVoiceProfile(narratorVoice),
                        characterVoice = getVoiceProfile(characterVoice)
                    )
                } else null

                val engine = AudiobookEngine(
                    context = this@MainActivity,
                    outputDir = bookDir,
                    ttsClient = ttsClient,
                    voiceName = narratorVoice,
                    stylePreset = stylePreset,
                    multiSpeakerConfig = multiConfig
                )

                announceStatus("جارِ تحويل فصول «$bookTitle» عبر الذكاء الاصطناعي (نمط: ${stylePreset.titleArabic})...")

                withContext(Dispatchers.IO) {
                    engine.processBook(persistentSource) { current, total, title ->
                        lifecycleScope.launch(Dispatchers.Main) {
                            announceStatus("تحويل الفصل $current من $total: $title")
                        }
                    }
                }

                announceStatus("اكتمل تجهيز الكتاب الصوتي بنجاح! اضغط عليه للاستماع.")
                Toast.makeText(this@MainActivity, "تم تجهيز الكتاب بنجاح", Toast.LENGTH_SHORT).show()
                refreshBooksList()
            } catch (e: Exception) {
                Log.e(TAG, "Error processing book: ${e.message}", e)
                refreshBooksList()
                announceStatus("حدث توقف أثناء المعالجة: ${e.localizedMessage ?: e.message}. تم حفظ الفصول المنجزة.")
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
        textPlayerBookTitle.text = book.title
        textPlayerChapterTitle.text = chapterTitle
        textPlayerProgress.text = "فصل $chapterIndex من أصل ${chapters.length()}"

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
        val playText = if (isPlaying) getString(R.string.action_pause) else getString(R.string.action_play)
        btnPlayPause.text = playText
        btnPlayPauseMini.text = playText
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
                if (book.chaptersCount == 0) {
                    view.contentDescription = "${book.title}، قيد الإكمال، 0 فصول جاهزة من أصل $totalChapters. اضغط للاستئناف، أو اضغط مطولاً للخيارات"
                } else {
                    view.contentDescription = "${book.title}، يحتوي على ${book.chaptersCount} فصول جاهزة من أصل $totalChapters (قيد الإكمال). اضغط للتشغيل، أو اضغط مطولاً للخيارات والاستئناف"
                }
            } else {
                textSubtitle.text = "${book.chaptersCount} فصل (مكتمل)"
                view.contentDescription = "${book.title}، مكتمل، يحتوي على ${book.chaptersCount} فصول. اضغط للتشغيل، أو اضغط مطولاً للخيارات"
            }

            view.setOnClickListener {
                if (status == "in_progress" && book.chaptersCount == 0) {
                    resumeIncompleteBook(book)
                } else {
                    playBook(book, chapterIndex = 1)
                }
            }
            view.setOnLongClickListener {
                showDeleteConfirmation(book)
                true
            }

            return view
        }
    }
}
