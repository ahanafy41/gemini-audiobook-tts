package com.antigravity.audiobook

import android.Manifest
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import com.antigravity.audiobook.util.AudioRecorderHelper
import android.content.Intent
import android.content.SharedPreferences
import android.media.MediaPlayer
import android.net.Uri
import android.text.Editable
import android.text.TextWatcher
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.OpenableColumns
import android.provider.Settings
import android.util.Log
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import java.util.concurrent.CancellationException
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import okhttp3.OkHttpClient
import okhttp3.Request
import android.os.PowerManager
import androidx.lifecycle.lifecycleScope
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.antigravity.audiobook.data.GeminiTtsClient
import com.antigravity.audiobook.data.KeyQuotaManager
import com.antigravity.audiobook.data.QuotaExceededException
import com.antigravity.audiobook.domain.DialogueTurnAnnotator
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
        private const val KEY_API_KEYS = "api_keys"
        private const val KEY_GEMINI_VOICE = "gemini_voice"
        private const val KEY_VOICE_STYLE = "gemini_voice_style"
        private const val KEY_MULTI_SPEAKER = "gemini_multi_speaker"
        private const val KEY_CHARACTER_VOICE = "gemini_character_voice"
        private const val KEY_MODEL_ID = "gemini_model_id"
        private const val KEY_CUSTOM_VOICES_JSON = "custom_voices_json"
        private const val KEY_CUSTOM_VOICE_INSTRUCTIONS = "custom_voice_instructions"
        private const val KEY_APP_LANGUAGE = "gemini_app_language"

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
    private lateinit var btnPasteText: Button
    private lateinit var cardResumeIncompleteBook: View
    private lateinit var textResumeBookInfo: TextView
    private lateinit var btnResumeBook: Button
    private lateinit var btnDismissResumeBook: Button
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
    private lateinit var btnCustomVoiceInstructions: Button
    private lateinit var btnToggleMultiSpeaker: Button
    private lateinit var btnSelectCharacterVoice: Button
    private lateinit var btnMultiSpeakerHelp: Button
    private lateinit var btnTestVoiceAudition: Button
    private lateinit var btnCreateCustomVoice: Button
    private lateinit var btnReplicateVoice: Button
    private lateinit var btnSyncCustomVoices: Button

    // Tab 4: Settings Views
    private lateinit var textApiKeyStatus: TextView
    private lateinit var btnEditApiKey: Button
    private lateinit var btnTestApiKey: Button
    private lateinit var btnSelectModel: Button
    private lateinit var btnSelectLanguage: Button
    private lateinit var textStorageFolderInfo: TextView
    private lateinit var btnStoragePermission: Button
    private lateinit var textAppVersion: TextView
    private lateinit var btnCheckAppUpdate: Button

    // State & Controllers
    private lateinit var settingsPrefs: SharedPreferences
    private val keyQuotaManager by lazy { KeyQuotaManager(filesDir) }

    private fun getStoredApiKeys(): List<String> {
        val raw = settingsPrefs.getString(KEY_API_KEYS, "") ?: ""
        if (raw.isNotBlank()) {
            return raw.lines().map { it.trim() }.filter { it.isNotEmpty() }
        }
        val single = settingsPrefs.getString(KEY_API_KEY, "") ?: ""
        return if (single.isNotBlank()) listOf(single.trim()) else emptyList()
    }

    private fun saveApiKeys(keys: List<String>) {
        val cleanList = keys.map { it.trim() }.filter { it.isNotEmpty() }
        val joined = cleanList.joinToString("\n")
        settingsPrefs.edit()
            .putString(KEY_API_KEYS, joined)
            .putString(KEY_API_KEY, cleanList.firstOrNull() ?: "")
            .apply()
    }

    private fun getActiveTtsClient(modelId: String = DEFAULT_MODEL_ID): GeminiTtsClient {
        return GeminiTtsClient(
            apiKeys = getStoredApiKeys(),
            modelId = modelId,
            quotaManager = keyQuotaManager
        )
    }

    private val customVoices = mutableListOf<VoiceProfile>()
    private var controllerFuture: ListenableFuture<MediaController>? = null
    private var mediaController: MediaController? = null
    private var wakeLock: PowerManager.WakeLock? = null

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

    private var onAudioPickedCallback: ((ByteArray, String) -> Unit)? = null
    private val audioPickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) {
            try {
                val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                val name = getFileNameFromUri(uri) ?: "audio"
                if (bytes != null && bytes.isNotEmpty()) {
                    onAudioPickedCallback?.invoke(bytes, name)
                } else {
                    Toast.makeText(this, getString(R.string.toast_empty_audio_file), Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to read audio file: ${e.message}")
                Toast.makeText(this, getString(R.string.toast_error_reading_file, e.message ?: ""), Toast.LENGTH_SHORT).show()
            }
        }
    }

    private var onRecordAudioPermissionResult: ((Boolean) -> Unit)? = null
    private val requestRecordAudioPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        onRecordAudioPermissionResult?.invoke(isGranted)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        settingsPrefs = getSharedPreferences(PREFS_SETTINGS, Context.MODE_PRIVATE)

        // Apply saved language locale if explicitly set
        val savedLang = settingsPrefs.getString(KEY_APP_LANGUAGE, null)
        if (savedLang != null) {
            val currentLocales = AppCompatDelegate.getApplicationLocales()
            if (savedLang.isEmpty() && !currentLocales.isEmpty) {
                AppCompatDelegate.setApplicationLocales(LocaleListCompat.getEmptyLocaleList())
            } else if (savedLang.isNotEmpty() && currentLocales.toLanguageTags() != savedLang) {
                AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(savedLang))
            }
        }

        loadCachedCustomVoices()
        initViews()
        setupBottomNavigation()
        setupListeners()
        initMediaController()
        refreshBooksList()
        updateStudioUI()
        updateSettingsUI()
        fetchAndLoadCustomVoices(userTriggered = false)
        checkForAppUpdates(userTriggered = false)
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
        btnPasteText = findViewById(R.id.btnPasteText)
        cardResumeIncompleteBook = findViewById(R.id.cardResumeIncompleteBook)
        textResumeBookInfo = findViewById(R.id.textResumeBookInfo)
        btnResumeBook = findViewById(R.id.btnResumeBook)
        btnDismissResumeBook = findViewById(R.id.btnDismissResumeBook)
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
        btnCustomVoiceInstructions = findViewById(R.id.btnCustomVoiceInstructions)
        btnToggleMultiSpeaker = findViewById(R.id.btnToggleMultiSpeaker)
        btnSelectCharacterVoice = findViewById(R.id.btnSelectCharacterVoice)
        btnMultiSpeakerHelp = findViewById(R.id.btnMultiSpeakerHelp)
        btnTestVoiceAudition = findViewById(R.id.btnTestVoiceAudition)
        btnCreateCustomVoice = findViewById(R.id.btnCreateCustomVoice)
        btnReplicateVoice = findViewById(R.id.btnReplicateVoice)
        btnSyncCustomVoices = findViewById(R.id.btnSyncCustomVoices)

        // Settings Views
        textApiKeyStatus = findViewById(R.id.textApiKeyStatus)
        btnEditApiKey = findViewById(R.id.btnEditApiKey)
        btnTestApiKey = findViewById(R.id.btnTestApiKey)
        btnSelectModel = findViewById(R.id.btnSelectModel)
        btnSelectLanguage = findViewById(R.id.btnSelectLanguage)
        textStorageFolderInfo = findViewById(R.id.textStorageFolderInfo)
        btnStoragePermission = findViewById(R.id.btnStoragePermission)
        textAppVersion = findViewById(R.id.textAppVersion)
        btnCheckAppUpdate = findViewById(R.id.btnCheckAppUpdate)

        booksAdapter = BooksAdapter(this, booksList)
        listViewBooks.adapter = booksAdapter
    }

    private fun setupBottomNavigation() {
        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.tab_library -> {
                    switchTab(layoutTabLibrary)
                    announceStatus(getString(R.string.status_tab_library))
                    true
                }
                R.id.tab_player -> {
                    switchTab(layoutTabPlayer)
                    announceStatus(getString(R.string.status_tab_player))
                    true
                }
                R.id.tab_studio -> {
                    switchTab(layoutTabStudio)
                    announceStatus(getString(R.string.status_tab_studio))
                    if (customVoices.isEmpty()) {
                        fetchAndLoadCustomVoices(userTriggered = false)
                    }
                    true
                }
                R.id.tab_settings -> {
                    switchTab(layoutTabSettings)
                    announceStatus(getString(R.string.status_tab_settings))
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
                filePickerLauncher.launch(arrayOf(
                    "text/plain",
                    "text/markdown",
                    "text/x-markdown",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/msword",
                    "*/*"
                ))
            } catch (e: Exception) {
                Log.e(TAG, "Error launching file picker: ${e.message}")
                Toast.makeText(this, getString(R.string.toast_cannot_open_file_picker), Toast.LENGTH_SHORT).show()
            }
        }

        btnPasteText.setOnClickListener {
            showPasteTextDialog()
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
                announceStatus(getString(R.string.announce_rewind_15))
            }
        }

        btnFastForward.setOnClickListener {
            mediaController?.let { mc ->
                val newPos = mc.currentPosition + 30000L
                mc.seekTo(newPos)
                announceStatus(getString(R.string.announce_forward_30))
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

        btnCustomVoiceInstructions.setOnClickListener {
            showCustomVoiceInstructionsDialog()
        }

        btnToggleMultiSpeaker.setOnClickListener {
            toggleMultiSpeaker()
        }

        btnSelectCharacterVoice.setOnClickListener {
            showCharacterVoicePicker()
        }

        btnMultiSpeakerHelp.setOnClickListener {
            showMultiSpeakerHelpDialog()
        }

        btnTestVoiceAudition.setOnClickListener {
            testCurrentAudition()
        }

        btnCreateCustomVoice.setOnClickListener {
            showVoiceDesignDialog()
        }

        btnReplicateVoice.setOnClickListener {
            showVoiceReplicationDialog()
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

        btnSelectLanguage.setOnClickListener {
            showLanguageSelectionDialog()
        }

        btnStoragePermission.setOnClickListener {
            requestOrCheckStoragePermission()
        }

        btnCheckAppUpdate.setOnClickListener {
            checkForAppUpdates(userTriggered = true)
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
        val keys = getStoredApiKeys()
        if (keys.isEmpty()) {
            if (userTriggered) {
                announceStatus(getString(R.string.announce_require_api_key_sync))
                Toast.makeText(this, getString(R.string.toast_require_api_key), Toast.LENGTH_SHORT).show()
            }
            return
        }

        if (userTriggered) {
            announceStatus(getString(R.string.announce_syncing_voices))
        }

        lifecycleScope.launch {
            try {
                val client = getActiveTtsClient()
                val fetched = client.listCustomVoices()
                if (fetched.isNotEmpty()) {
                    customVoices.clear()
                    customVoices.addAll(fetched)
                    saveCustomVoicesToPrefs(fetched)
                    updateStudioUI()
                    val msg = getString(R.string.announce_sync_voices_found, fetched.size)
                    announceStatus(msg)
                    if (userTriggered) {
                        Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
                    }
                } else if (userTriggered) {
                    announceStatus(getString(R.string.announce_sync_voices_none))
                    Toast.makeText(this@MainActivity, getString(R.string.announce_sync_voices_none), Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Log.w(TAG, "Failed to fetch custom voices: ${e.message}")
                if (userTriggered) {
                    val errMsg = e.localizedMessage ?: (e.message ?: "")
                    announceStatus(getString(R.string.announce_sync_voices_failed, errMsg))
                    Toast.makeText(this@MainActivity, getString(R.string.toast_sync_voices_error, errMsg), Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun getVoiceProfile(id: String): VoiceProfile {
        val custom = customVoices.firstOrNull { it.id.equals(id, ignoreCase = true) }
        if (custom != null) return custom
        return VoiceProfile.fromStoredString(id)
    }

    private fun isCurrentLocaleArabic(): Boolean {
        val currentLocales = AppCompatDelegate.getApplicationLocales()
        if (!currentLocales.isEmpty) {
            val tag = currentLocales.get(0)?.language ?: ""
            return tag.startsWith("ar", ignoreCase = true)
        }
        val configLocale = resources.configuration.locales.get(0)
        return configLocale.language.startsWith("ar", ignoreCase = true)
    }

    private fun updateStudioUI() {
        val isArabic = isCurrentLocaleArabic()
        val narratorId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        val narratorProfile = getVoiceProfile(narratorId)
        val narratorName = narratorProfile.displayName(isArabic)
        btnSelectNarratorVoice.text = String.format(getString(R.string.label_narrator_format), narratorName)
        btnSelectNarratorVoice.contentDescription = btnSelectNarratorVoice.text

        val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        val stylePreset = VoiceStylePreset.fromId(styleId)
        val styleName = stylePreset.title(isArabic)
        btnSelectVoiceStyle.text = String.format(getString(R.string.label_style_format), styleName)
        btnSelectVoiceStyle.contentDescription = btnSelectVoiceStyle.text

        val customInst = settingsPrefs.getString(KEY_CUSTOM_VOICE_INSTRUCTIONS, null)
        if (!customInst.isNullOrBlank()) {
            btnCustomVoiceInstructions.text = getString(R.string.label_instructions_custom)
            btnCustomVoiceInstructions.contentDescription = "${getString(R.string.label_instructions_custom)}: $customInst"
        } else {
            btnCustomVoiceInstructions.text = getString(R.string.label_instructions_none)
            btnCustomVoiceInstructions.contentDescription = getString(R.string.label_instructions_none)
        }

        val isMultiSpeaker = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        btnToggleMultiSpeaker.text = if (isMultiSpeaker) getString(R.string.multi_speaker_enabled) else getString(R.string.multi_speaker_disabled)
        btnToggleMultiSpeaker.contentDescription = btnToggleMultiSpeaker.text
        btnSelectCharacterVoice.visibility = if (isMultiSpeaker) View.VISIBLE else View.GONE
        btnMultiSpeakerHelp.visibility = if (isMultiSpeaker) View.VISIBLE else View.GONE

        val characterId = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
        val characterProfile = getVoiceProfile(characterId)
        val characterName = characterProfile.displayName(isArabic)
        btnSelectCharacterVoice.text = String.format(getString(R.string.label_character_format), characterName)
        btnSelectCharacterVoice.contentDescription = btnSelectCharacterVoice.text
    }

    private fun showNarratorVoicePicker() {
        val isArabic = isCurrentLocaleArabic()
        val combinedVoices = mutableListOf<VoiceProfile>()
        combinedVoices.addAll(customVoices)
        combinedVoices.addAll(VoiceProfile.PREBUILT_VOICES)

        val displayItems = mutableListOf<String>()
        for (v in customVoices) {
            val desc = v.description(isArabic)
            val badge = if (desc.contains("مستنسخ") || desc.contains("Replicated", ignoreCase = true)) {
                getString(R.string.voice_badge_replicated)
            } else {
                getString(R.string.voice_badge_designed)
            }
            displayItems.add("⭐ $badge ${v.displayName(isArabic)}")
        }
        for (v in VoiceProfile.PREBUILT_VOICES) {
            displayItems.add("${v.displayName(isArabic)} (${v.description(isArabic)})")
        }
        displayItems.add(getString(R.string.voice_picker_add_custom_manual))
        displayItems.add(getString(R.string.voice_picker_sync_cloud))

        val currentVoiceId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        var selectedIdx = combinedVoices.indexOfFirst { it.id.equals(currentVoiceId, ignoreCase = true) }
        if (selectedIdx < 0) selectedIdx = customVoices.size

        AlertDialog.Builder(this)
            .setTitle(R.string.voice_picker_title_narrator)
            .setSingleChoiceItems(displayItems.toTypedArray(), selectedIdx) { dialog, which ->
                when {
                    which < combinedVoices.size -> {
                        val chosen = combinedVoices[which]
                        settingsPrefs.edit().putString(KEY_GEMINI_VOICE, chosen.id).apply()
                        updateStudioUI()
                        announceStatus(getString(R.string.announce_narrator_selected, chosen.displayName(isArabic)))
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
        val isArabic = isCurrentLocaleArabic()
        val combinedVoices = mutableListOf<VoiceProfile>()
        combinedVoices.addAll(customVoices)
        combinedVoices.addAll(VoiceProfile.PREBUILT_VOICES)

        val displayItems = mutableListOf<String>()
        for (v in customVoices) {
            val desc = v.description(isArabic)
            val badge = if (desc.contains("مستنسخ") || desc.contains("Replicated", ignoreCase = true)) {
                getString(R.string.voice_badge_replicated)
            } else {
                getString(R.string.voice_badge_designed)
            }
            displayItems.add("⭐ $badge ${v.displayName(isArabic)}")
        }
        for (v in VoiceProfile.PREBUILT_VOICES) {
            displayItems.add("${v.displayName(isArabic)} (${v.description(isArabic)})")
        }
        displayItems.add(getString(R.string.voice_picker_add_custom_manual))
        displayItems.add(getString(R.string.voice_picker_sync_cloud))

        val currentVoiceId = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
        var selectedIdx = combinedVoices.indexOfFirst { it.id.equals(currentVoiceId, ignoreCase = true) }
        if (selectedIdx < 0) selectedIdx = if (customVoices.isNotEmpty()) customVoices.size + 1 else 1

        AlertDialog.Builder(this)
            .setTitle(R.string.voice_picker_title_character)
            .setSingleChoiceItems(displayItems.toTypedArray(), selectedIdx) { dialog, which ->
                when {
                    which < combinedVoices.size -> {
                        val chosen = combinedVoices[which]
                        settingsPrefs.edit().putString(KEY_CHARACTER_VOICE, chosen.id).apply()
                        updateStudioUI()
                        announceStatus(getString(R.string.announce_character_selected, chosen.displayName(isArabic)))
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
            hint = getString(R.string.dialog_enter_voice_id_hint)
            contentDescription = getString(R.string.dialog_enter_voice_id_desc)
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.dialog_enter_voice_id_title)
            .setView(input)
            .setPositiveButton(R.string.voice_manual_apply) { _, _ ->
                val enteredId = input.text.toString().trim()
                if (enteredId.isBlank()) {
                    Toast.makeText(this, getString(R.string.toast_require_voice_id), Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                val newProfile = VoiceProfile(
                    id = enteredId,
                    displayNameArabic = "صوت مخصص ($enteredId)",
                    displayNameEnglish = "Custom Voice ($enteredId)",
                    isCustomVoiceDesign = true,
                    descriptionArabic = "معرف مخصص مدخل يدوياً",
                    descriptionEnglish = "Manually entered custom Voice ID"
                )
                if (customVoices.none { it.id.equals(enteredId, ignoreCase = true) }) {
                    customVoices.add(0, newProfile)
                    saveCustomVoicesToPrefs(customVoices)
                }
                val prefKey = if (isCharacter) KEY_CHARACTER_VOICE else KEY_GEMINI_VOICE
                settingsPrefs.edit().putString(prefKey, enteredId).apply()
                updateStudioUI()
                announceStatus(getString(R.string.announce_custom_voice_activated, enteredId))
                Toast.makeText(this, getString(R.string.toast_custom_voice_activated), Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showVoiceStylePicker() {
        val isArabic = isCurrentLocaleArabic()
        val styles = VoiceStylePreset.entries.toTypedArray()
        val displayItems = VoiceStylePreset.getAccessibleDisplayList(isArabic)
        val currentStyleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        var selectedIdx = styles.indexOfFirst { it.id.equals(currentStyleId, ignoreCase = true) }
        if (selectedIdx < 0) selectedIdx = 0

        AlertDialog.Builder(this)
            .setTitle(R.string.style_picker_title)
            .setSingleChoiceItems(displayItems, selectedIdx) { dialog, which ->
                val chosen = styles[which]
                settingsPrefs.edit().putString(KEY_VOICE_STYLE, chosen.id).apply()
                updateStudioUI()
                announceStatus(getString(R.string.announce_style_selected, chosen.title(isArabic)))
                dialog.dismiss()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showCustomVoiceInstructionsDialog() {
        val currentInstructions = settingsPrefs.getString(KEY_CUSTOM_VOICE_INSTRUCTIONS, "") ?: ""
        val input = EditText(this).apply {
            hint = getString(R.string.custom_instructions_hint)
            setText(currentInstructions)
            contentDescription = getString(R.string.custom_instructions_desc)
            minLines = 3
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.custom_instructions_title)
            .setView(input)
            .setPositiveButton(R.string.action_save) { _, _ ->
                val newInstructions = input.text.toString().trim()
                if (newInstructions.isNotBlank()) {
                    settingsPrefs.edit().putString(KEY_CUSTOM_VOICE_INSTRUCTIONS, newInstructions).apply()
                    announceStatus(getString(R.string.announce_custom_instructions_saved))
                    Toast.makeText(this, getString(R.string.toast_custom_instructions_saved), Toast.LENGTH_SHORT).show()
                } else {
                    settingsPrefs.edit().remove(KEY_CUSTOM_VOICE_INSTRUCTIONS).apply()
                    announceStatus(getString(R.string.announce_custom_instructions_cleared))
                }
                updateStudioUI()
            }
            .setNeutralButton(R.string.custom_instructions_clear) { _, _ ->
                settingsPrefs.edit().remove(KEY_CUSTOM_VOICE_INSTRUCTIONS).apply()
                updateStudioUI()
                announceStatus(getString(R.string.announce_custom_instructions_cleared))
                Toast.makeText(this, getString(R.string.toast_custom_instructions_cleared), Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun toggleMultiSpeaker() {
        val current = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        val updated = !current
        settingsPrefs.edit().putBoolean(KEY_MULTI_SPEAKER, updated).apply()
        updateStudioUI()
        announceStatus(if (updated) getString(R.string.announce_multi_speaker_on) else getString(R.string.announce_multi_speaker_off))
    }

    private fun showMultiSpeakerHelpDialog() {
        val isArabic = isCurrentLocaleArabic()
        val sampleDialogue = if (isArabic) {
            """Speaker1: مرحباً يا أحمد، أهلاً بك في تجربة الحوار الصوتي بالذكاء الاصطناعي.
Speaker2: أهلاً بك يا صديقي! هل يتغير الصوت تلقائياً الآن بحسب المتحدث؟
Speaker1: نعم تماماً، هذا نموذج الحوار الرسمي لنموذج Gemini 3.8 Flash TTS.
Speaker2: رائع جداً، الصوتان يبدوان طبيعيين ومنسجمين تماماً!"""
        } else {
            """Speaker1: Hello Ahmed! Welcome to the AI multi-speaker voice test.
Speaker2: Glad to be here! Does the voice switch dynamically based on speaker?
Speaker1: Yes, exactly! This is the official Gemini 3.8 Flash TTS dialogue standard.
Speaker2: Outstanding! Both voices sound remarkably authentic and smooth!"""
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.dialogue_help_title)
            .setMessage(getString(R.string.dialogue_help_msg))
            .setPositiveButton(R.string.dialogue_help_btn_copy) { _, _ ->
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("Dialogue Sample", sampleDialogue)
                clipboard.setPrimaryClip(clip)
                announceStatus(getString(R.string.announce_dialogue_template_copied))
                Toast.makeText(this, getString(R.string.toast_dialogue_template_copied), Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun testCurrentAudition() {
        val keys = getStoredApiKeys()
        if (keys.isEmpty()) {
            announceStatus(getString(R.string.announce_require_api_key_sync))
            Toast.makeText(this, getString(R.string.toast_require_api_key), Toast.LENGTH_SHORT).show()
            bottomNav.selectedItemId = R.id.tab_settings
            return
        }

        val narratorId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        val stylePreset = VoiceStylePreset.fromId(styleId)
        val isMultiSpeaker = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        val characterId = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
        val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
        val isArabic = isCurrentLocaleArabic()

        announceStatus(getString(R.string.audition_generating))
        lifecycleScope.launch {
            try {
                val client = getActiveTtsClient(modelId)
                val audioData = withContext(Dispatchers.IO) {
                    if (isMultiSpeaker) {
                        val multiConfig = MultiSpeakerConfig(
                            isEnabled = true,
                            narratorVoice = VoiceProfile.fromStoredString(narratorId),
                            characterVoice = VoiceProfile.fromStoredString(characterId)
                        )
                        val text = if (isArabic) {
                            """Speaker1: مرحباً يا أحمد، هذا فحص واختبار لصوت الراوي بنمط ${stylePreset.title(true)}.
Speaker2: أهلاً بك يا صديقي! وهذا فحص لصوت الشخصيات، للتأكد من سلاسة الحوار بين الصوتين."""
                        } else {
                            """Speaker1: Hello Ahmed! This is a test for the narrator voice in ${stylePreset.title(false)} style.
Speaker2: Glad to be here! And this tests the character voice for smooth multi-speaker dialogue."""
                        }
                        client.synthesize(text, voiceName = narratorId, stylePreset = stylePreset, multiSpeakerConfig = multiConfig)
                    } else {
                        val text = getString(R.string.audition_sample_single_format, stylePreset.title(isArabic))
                        client.synthesize(text, voiceName = narratorId, stylePreset = stylePreset)
                    }
                }
                val previewFile = File(cacheDir, "audition_test.wav")
                client.saveAudioAtomically(previewFile, audioData)
                playAudioFileDirectly(previewFile)
                announceStatus(getString(R.string.audition_success))
            } catch (e: Exception) {
                Log.e(TAG, "Audition test failed: ${e.message}")
                val err = getString(R.string.audition_failed, e.localizedMessage ?: e.message)
                announceStatus(err)
                Toast.makeText(this@MainActivity, err, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun showVoiceDesignDialog() {
        val keys = getStoredApiKeys()
        if (keys.isEmpty()) {
            announceStatus(getString(R.string.announce_require_api_key_sync))
            Toast.makeText(this, getString(R.string.toast_require_api_key), Toast.LENGTH_SHORT).show()
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
            contentDescription = getString(R.string.dialog_voice_design_name_label)
        }
        val inputPrompt = EditText(context).apply {
            hint = getString(R.string.dialog_voice_design_prompt_hint)
            contentDescription = getString(R.string.dialog_voice_design_prompt_label)
            minLines = 3
        }

        layout.addView(TextView(context).apply {
            text = getString(R.string.dialog_voice_design_name_label)
            textSize = 14f
            setTextColor(ContextCompat.getColor(context, R.color.text_high_contrast))
        })
        layout.addView(inputName)
        layout.addView(TextView(context).apply {
            text = getString(R.string.dialog_voice_design_prompt_label)
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
                    Toast.makeText(context, getString(R.string.toast_voice_design_blank), Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                announceStatus(getString(R.string.announce_voice_design_wait))
                Toast.makeText(context, getString(R.string.toast_voice_design_wait), Toast.LENGTH_SHORT).show()
                val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
                lifecycleScope.launch {
                    try {
                        val client = getActiveTtsClient(modelId)
                        val (voiceId, sampleBytes) = client.createCustomVoice(name, prompt)
                        if (voiceId.isBlank()) {
                            throw IllegalStateException(getString(R.string.error_voice_design_no_id))
                        }
                        val newProfile = VoiceProfile(
                            id = voiceId,
                            displayNameArabic = "$name ($voiceId)",
                            displayNameEnglish = "$name ($voiceId)",
                            isCustomVoiceDesign = true,
                            descriptionArabic = prompt,
                            descriptionEnglish = prompt
                        )
                        customVoices.removeAll { it.id.equals(voiceId, ignoreCase = true) }
                        customVoices.add(0, newProfile)
                        saveCustomVoicesToPrefs(customVoices)
                        settingsPrefs.edit().putString(KEY_GEMINI_VOICE, voiceId).apply()
                        updateStudioUI()
                        announceStatus(getString(R.string.design_success, voiceId))
                        Toast.makeText(context, getString(R.string.design_success, voiceId), Toast.LENGTH_SHORT).show()

                        sampleBytes?.let { bytes ->
                            val sampleFile = File(cacheDir, "sample_designed_$voiceId.wav")
                            client.saveAudioAtomically(sampleFile, bytes)
                            playAudioFileDirectly(sampleFile)
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Voice design creation failed: ${e.message}")
                        val err = getString(R.string.design_failed, e.localizedMessage ?: e.message)
                        announceStatus(err)
                        Toast.makeText(context, err, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showVoiceReplicationDialog() {
        val keys = getStoredApiKeys()
        if (keys.isEmpty()) {
            announceStatus(getString(R.string.announce_require_api_key_sync))
            Toast.makeText(this, getString(R.string.toast_require_api_key), Toast.LENGTH_SHORT).show()
            bottomNav.selectedItemId = R.id.tab_settings
            return
        }

        val dialogView = layoutInflater.inflate(R.layout.dialog_voice_replication, null)
        val editVoiceName = dialogView.findViewById<EditText>(R.id.editReplicationVoiceName)
        val textRefAudioStatus = dialogView.findViewById<TextView>(R.id.textRefAudioStatus)
        val btnRecordRefAudio = dialogView.findViewById<Button>(R.id.btnRecordRefAudio)
        val btnPickRefAudio = dialogView.findViewById<Button>(R.id.btnPickRefAudio)
        val btnPlayRefAudio = dialogView.findViewById<Button>(R.id.btnPlayRefAudio)

        val btnCopyConsent = dialogView.findViewById<Button>(R.id.btnCopyConsent)
        val textConsentAudioStatus = dialogView.findViewById<TextView>(R.id.textConsentAudioStatus)
        val btnRecordConsentAudio = dialogView.findViewById<Button>(R.id.btnRecordConsentAudio)
        val btnPickConsentAudio = dialogView.findViewById<Button>(R.id.btnPickConsentAudio)
        val btnPlayConsentAudio = dialogView.findViewById<Button>(R.id.btnPlayConsentAudio)

        val btnSubmitReplication = dialogView.findViewById<Button>(R.id.btnSubmitReplication)
        val btnCancelReplication = dialogView.findViewById<Button>(R.id.btnCancelReplication)

        val recorderHelper = AudioRecorderHelper(this)
        var refAudioBytes: ByteArray? = null
        var consentAudioBytes: ByteArray? = null
        val refAudioFile = File(cacheDir, "ref_voice_sample.wav")
        val consentAudioFile = File(cacheDir, "consent_voice_sample.wav")

        var isRecordingRef = false
        var isRecordingConsent = false

        val dialog = AlertDialog.Builder(this)
            .setView(dialogView)
            .create()

        dialog.setOnDismissListener {
            recorderHelper.release()
        }

        // Copy consent statement
        val consentPhraseText = "I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model."
        btnCopyConsent.setOnClickListener {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = ClipData.newPlainText("Google Consent Statement", consentPhraseText)
            clipboard.setPrimaryClip(clip)
            announceStatus(getString(R.string.repl_toast_consent_copied))
            Toast.makeText(this, getString(R.string.repl_toast_consent_copied), Toast.LENGTH_SHORT).show()
        }

        // 1. Reference Audio Recording
        val startRecordingRef = {
            if (isRecordingConsent) {
                recorderHelper.stopRecording()
                isRecordingConsent = false
                btnRecordConsentAudio.text = getString(R.string.repl_btn_record_consent)
            }
            refAudioFile.delete()
            val started = recorderHelper.startRecording(refAudioFile) { elapsed ->
                btnRecordRefAudio.text = getString(R.string.repl_btn_record_sample_stop, elapsed)
            }
            if (started) {
                isRecordingRef = true
                textRefAudioStatus.text = getString(R.string.repl_status_recording_sample)
                textRefAudioStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                announceStatus(getString(R.string.repl_status_recording_sample))
            } else {
                Toast.makeText(this, getString(R.string.toast_cannot_start_recording), Toast.LENGTH_SHORT).show()
            }
        }

        btnRecordRefAudio.setOnClickListener {
            if (!isRecordingRef) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    startRecordingRef()
                } else {
                    onRecordAudioPermissionResult = { granted ->
                        if (granted) startRecordingRef()
                        else Toast.makeText(this, getString(R.string.toast_mic_perm_required), Toast.LENGTH_SHORT).show()
                    }
                    requestRecordAudioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            } else {
                val wav = recorderHelper.stopRecording()
                isRecordingRef = false
                btnRecordRefAudio.text = getString(R.string.repl_btn_record_sample_again)
                if (wav != null && wav.exists() && wav.length() > 0) {
                    refAudioBytes = wav.readBytes()
                    val kb = refAudioBytes!!.size / 1024
                    textRefAudioStatus.text = getString(R.string.repl_status_sample_recorded, kb)
                    textRefAudioStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                    btnPlayRefAudio.visibility = View.VISIBLE
                    announceStatus(getString(R.string.repl_status_sample_recorded, kb))
                } else {
                    textRefAudioStatus.text = getString(R.string.repl_status_low_audio)
                }
            }
        }

        btnPickRefAudio.setOnClickListener {
            onAudioPickedCallback = { bytes, fileName ->
                refAudioBytes = bytes
                val kb = bytes.size / 1024
                textRefAudioStatus.text = getString(R.string.repl_status_sample_file_chosen, fileName, kb)
                textRefAudioStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                try {
                    refAudioFile.writeBytes(bytes)
                    btnPlayRefAudio.visibility = View.VISIBLE
                } catch (_: Exception) {}
                announceStatus(getString(R.string.repl_sample_selected, fileName))
            }
            audioPickerLauncher.launch(arrayOf("audio/*", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"))
        }

        btnPlayRefAudio.setOnClickListener {
            if (recorderHelper.isPlaying()) {
                recorderHelper.stopPlayback()
                btnPlayRefAudio.text = getString(R.string.repl_btn_preview_sample_play)
            } else {
                if (refAudioFile.exists()) {
                    btnPlayRefAudio.text = getString(R.string.repl_btn_preview_sample_stop)
                    recorderHelper.playAudio(refAudioFile) {
                        btnPlayRefAudio.text = getString(R.string.repl_btn_preview_sample_play)
                    }
                }
            }
        }

        // 2. Consent Audio Recording
        val startRecordingConsent = {
            if (isRecordingRef) {
                recorderHelper.stopRecording()
                isRecordingRef = false
                btnRecordRefAudio.text = getString(R.string.repl_btn_record_sample)
            }
            consentAudioFile.delete()
            val started = recorderHelper.startRecording(consentAudioFile) { elapsed ->
                btnRecordConsentAudio.text = getString(R.string.repl_btn_record_sample_stop, elapsed)
            }
            if (started) {
                isRecordingConsent = true
                textConsentAudioStatus.text = getString(R.string.repl_status_recording_consent)
                textConsentAudioStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                announceStatus(getString(R.string.repl_status_recording_consent))
            } else {
                Toast.makeText(this, getString(R.string.toast_cannot_start_recording), Toast.LENGTH_SHORT).show()
            }
        }

        btnRecordConsentAudio.setOnClickListener {
            if (!isRecordingConsent) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    startRecordingConsent()
                } else {
                    onRecordAudioPermissionResult = { granted ->
                        if (granted) startRecordingConsent()
                        else Toast.makeText(this, getString(R.string.toast_mic_perm_required), Toast.LENGTH_SHORT).show()
                    }
                    requestRecordAudioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            } else {
                val wav = recorderHelper.stopRecording()
                isRecordingConsent = false
                btnRecordConsentAudio.text = getString(R.string.repl_btn_record_sample_again)
                if (wav != null && wav.exists() && wav.length() > 0) {
                    consentAudioBytes = wav.readBytes()
                    val kb = consentAudioBytes!!.size / 1024
                    textConsentAudioStatus.text = getString(R.string.repl_status_consent_recorded, kb)
                    textConsentAudioStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                    btnPlayConsentAudio.visibility = View.VISIBLE
                    announceStatus(getString(R.string.repl_status_consent_recorded, kb))
                } else {
                    textConsentAudioStatus.text = getString(R.string.repl_status_low_consent)
                }
            }
        }

        btnPickConsentAudio.setOnClickListener {
            onAudioPickedCallback = { bytes, fileName ->
                consentAudioBytes = bytes
                val kb = bytes.size / 1024
                textConsentAudioStatus.text = getString(R.string.repl_status_consent_file_chosen, fileName, kb)
                textConsentAudioStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                try {
                    consentAudioFile.writeBytes(bytes)
                    btnPlayConsentAudio.visibility = View.VISIBLE
                } catch (_: Exception) {}
                announceStatus(getString(R.string.repl_consent_selected, fileName))
            }
            audioPickerLauncher.launch(arrayOf("audio/*", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4"))
        }

        btnPlayConsentAudio.setOnClickListener {
            if (recorderHelper.isPlaying()) {
                recorderHelper.stopPlayback()
                btnPlayConsentAudio.text = getString(R.string.repl_btn_preview_consent_play)
            } else {
                if (consentAudioFile.exists()) {
                    btnPlayConsentAudio.text = getString(R.string.repl_btn_preview_consent_stop)
                    recorderHelper.playAudio(consentAudioFile) {
                        btnPlayConsentAudio.text = getString(R.string.repl_btn_preview_consent_play)
                    }
                }
            }
        }

        // Submit Replication
        btnSubmitReplication.setOnClickListener {
            val voiceName = editVoiceName.text.toString().trim()
            if (voiceName.isBlank()) {
                announceStatus(getString(R.string.repl_error_missing_sample))
                Toast.makeText(this, getString(R.string.toast_voice_design_blank), Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val refBytes = refAudioBytes
            if (refBytes == null || refBytes.isEmpty()) {
                announceStatus(getString(R.string.repl_error_missing_sample))
                Toast.makeText(this, getString(R.string.repl_error_missing_sample), Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            val consentBytes = consentAudioBytes
            if (consentBytes == null || consentBytes.isEmpty()) {
                announceStatus(getString(R.string.repl_error_missing_consent))
                Toast.makeText(this, getString(R.string.repl_error_missing_consent), Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            recorderHelper.release()
            btnSubmitReplication.isEnabled = false
            btnSubmitReplication.text = getString(R.string.repl_btn_submit_running)
            announceStatus(getString(R.string.repl_starting))
            Toast.makeText(this, getString(R.string.repl_starting), Toast.LENGTH_SHORT).show()

            val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
            lifecycleScope.launch {
                try {
                    val client = getActiveTtsClient(modelId)
                    val (voiceId, sampleBytes) = client.replicateCustomVoice(voiceName, refBytes, consentBytes)
                    val newProfile = VoiceProfile(
                        id = voiceId,
                        displayNameArabic = "$voiceName ($voiceId)",
                        displayNameEnglish = "$voiceName ($voiceId)",
                        isCustomVoiceDesign = true,
                        descriptionArabic = "صوت مستنسخ بالذكاء الاصطناعي (Replicated Voice)",
                        descriptionEnglish = "Replicated AI Voice"
                    )
                    customVoices.removeAll { it.id.equals(voiceId, ignoreCase = true) }
                    customVoices.add(0, newProfile)
                    saveCustomVoicesToPrefs(customVoices)
                    settingsPrefs.edit().putString(KEY_GEMINI_VOICE, voiceId).apply()
                    updateStudioUI()
                    announceStatus(getString(R.string.repl_success, voiceId))
                    Toast.makeText(this@MainActivity, getString(R.string.repl_success, voiceId), Toast.LENGTH_LONG).show()
                    dialog.dismiss()

                    sampleBytes?.let { bytes ->
                        val sampleFile = File(cacheDir, "sample_replicated_$voiceId.wav")
                        client.saveAudioAtomically(sampleFile, bytes)
                        playAudioFileDirectly(sampleFile)
                    }
                } catch (e: Exception) {
                    btnSubmitReplication.isEnabled = true
                    btnSubmitReplication.text = getString(R.string.repl_btn_start)
                    Log.e(TAG, "Voice replication failed: ${e.message}")
                    val err = getString(R.string.repl_failed, e.localizedMessage ?: e.message)
                    announceStatus(err)
                    Toast.makeText(this@MainActivity, err, Toast.LENGTH_LONG).show()
                }
            }
        }

        btnCancelReplication.setOnClickListener {
            dialog.dismiss()
        }

        dialog.show()
    }

    // -------------------------------------------------------------------------
    // Settings Tab Management
    // -------------------------------------------------------------------------

    private fun updateSettingsUI() {
        val keys = getStoredApiKeys()
        if (keys.isNotEmpty()) {
            val count = keys.size
            val firstMasked = KeyQuotaManager.maskKey(keys[0])
            val statusText = if (count > 1) {
                getString(R.string.settings_keys_status_multi, firstMasked, count - 1)
            } else {
                getString(R.string.settings_keys_status_single, firstMasked)
            }
            textApiKeyStatus.text = statusText
            textApiKeyStatus.contentDescription = getString(R.string.settings_keys_desc_format, count, firstMasked)
            textApiKeyStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
        } else {
            textApiKeyStatus.text = getString(R.string.status_keys_not_registered)
            textApiKeyStatus.contentDescription = getString(R.string.desc_keys_not_registered)
            textApiKeyStatus.setTextColor(ContextCompat.getColor(this, R.color.text_secondary))
        }

        val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
        btnSelectModel.text = getString(R.string.model_selected_format, modelId)
        updateLanguageButtonLabel()

        val currentVer = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "1.5.3"
        } catch (e: Exception) {
            "1.5.3"
        }
        textAppVersion.text = getString(R.string.app_version_label, currentVer)

        val hasStorage = hasStoragePermission()
        if (hasStorage) {
            btnStoragePermission.text = getString(R.string.storage_perm_enabled)
            btnStoragePermission.contentDescription = getString(R.string.desc_storage_perm_enabled)
        } else {
            btnStoragePermission.text = getString(R.string.storage_perm_disabled)
            btnStoragePermission.contentDescription = getString(R.string.desc_storage_perm_disabled)
        }
    }

    override fun onResume() {
        super.onResume()
        updateSettingsUI()
    }

    private fun hasStoragePermission(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun requestOrCheckStoragePermission() {
        if (hasStoragePermission()) {
            announceStatus(getString(R.string.storage_perm_already_granted))
            Toast.makeText(this, getString(R.string.toast_storage_perm_already_granted), Toast.LENGTH_SHORT).show()
        } else {
            showStoragePermissionDialog()
        }
    }

    private fun showStoragePermissionDialog(onDismiss: () -> Unit = {}) {
        AlertDialog.Builder(this)
            .setTitle(R.string.storage_perm_dialog_title)
            .setMessage(R.string.storage_perm_dialog_msg)
            .setPositiveButton(R.string.storage_perm_btn_settings) { _, _ ->
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    try {
                        val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
                            data = Uri.parse("package:$packageName")
                        }
                        startActivity(intent)
                    } catch (e: Exception) {
                        val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                        startActivity(intent)
                    }
                } else {
                    requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), 101)
                }
            }
            .setNegativeButton(R.string.storage_perm_btn_later) { _, _ ->
                onDismiss()
            }
            .show()
    }

    private fun showApiKeyEditDialog() {
        val currentKeys = getStoredApiKeys().joinToString("\n")
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        val input = EditText(this).apply {
            hint = getString(R.string.dialog_api_keys_hint)
            setText(currentKeys)
            contentDescription = getString(R.string.dialog_api_keys_desc)
            minLines = 4
            maxLines = 10
            gravity = android.view.Gravity.TOP
            val pad = (12 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        container.addView(input)

        val btnPaste = Button(this).apply {
            text = getString(R.string.btn_paste_from_clipboard)
            contentDescription = getString(R.string.desc_paste_from_clipboard)
            setOnClickListener {
                val clipManager = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                val clipText = clipManager?.primaryClip?.getItemAt(0)?.text?.toString()?.trim()
                if (!clipText.isNullOrBlank() && clipText.startsWith("AIzaSy")) {
                    val existing = input.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }.toMutableList()
                    if (!existing.contains(clipText)) {
                        existing.add(clipText)
                        input.setText(existing.joinToString("\n"))
                        announceStatus(getString(R.string.announce_key_pasted_success))
                        Toast.makeText(this@MainActivity, getString(R.string.toast_key_saved), Toast.LENGTH_SHORT).show()
                    } else {
                        announceStatus(getString(R.string.announce_key_already_in_list))
                    }
                } else {
                    announceStatus(getString(R.string.announce_clipboard_no_valid_key))
                    Toast.makeText(this@MainActivity, getString(R.string.toast_clipboard_no_valid_key), Toast.LENGTH_SHORT).show()
                }
            }
        }
        container.addView(btnPaste)

        AlertDialog.Builder(this)
            .setTitle(R.string.dialog_api_keys_title)
            .setView(container)
            .setPositiveButton(R.string.action_save) { _, _ ->
                val lines = input.text.toString().lines().map { it.trim() }.filter { it.isNotEmpty() }
                saveApiKeys(lines)
                updateSettingsUI()
                announceStatus(getString(R.string.announce_keys_saved_count, lines.size))
                Toast.makeText(this, getString(R.string.toast_keys_saved_count, lines.size), Toast.LENGTH_SHORT).show()
                fetchAndLoadCustomVoices(userTriggered = false)
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun testApiKeyConnection() {
        val keys = getStoredApiKeys()
        if (keys.isEmpty()) {
            announceStatus(getString(R.string.announce_require_api_key_sync))
            Toast.makeText(this, getString(R.string.toast_require_api_key), Toast.LENGTH_SHORT).show()
            return
        }

        announceStatus(getString(R.string.announce_test_keys_running, keys.size))
        lifecycleScope.launch {
            try {
                val client = GeminiTtsClient(
                    apiKeys = keys,
                    quotaManager = keyQuotaManager
                )
                val audio = client.synthesize(getString(R.string.test_keys_audio_text), voiceName = "Charon")
                if (audio.size > 1000) {
                    val msg = getString(R.string.test_keys_success_msg, keys.size)
                    announceStatus(msg)
                    AlertDialog.Builder(this@MainActivity)
                        .setTitle(R.string.status_connection_success)
                        .setMessage(msg)
                        .setPositiveButton(android.R.string.ok, null)
                        .show()
                }
            } catch (e: Exception) {
                val err = getString(R.string.status_connection_failed, e.message ?: "")
                announceStatus(err)
                AlertDialog.Builder(this@MainActivity)
                    .setTitle(R.string.test_keys_dialog_title)
                    .setMessage(err)
                    .setPositiveButton(android.R.string.ok, null)
                    .show()
            }
        }
    }

    private fun showModelSelectionDialog() {
        val models = arrayOf("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
        val currentModel = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
        var selectedIdx = models.indexOf(currentModel)
        if (selectedIdx < 0) selectedIdx = 0

        AlertDialog.Builder(this)
            .setTitle(R.string.model_picker_title)
            .setSingleChoiceItems(models, selectedIdx) { dialog, which ->
                val chosen = models[which]
                settingsPrefs.edit().putString(KEY_MODEL_ID, chosen).apply()
                updateSettingsUI()
                announceStatus(getString(R.string.model_selected_format, chosen))
                dialog.dismiss()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun showLanguageSelectionDialog() {
        val options = arrayOf(
            getString(R.string.lang_arabic),
            getString(R.string.lang_english),
            getString(R.string.lang_system_default)
        )
        val tags = arrayOf("ar", "en", "")
        val currentTag = settingsPrefs.getString(KEY_APP_LANGUAGE, "") ?: ""
        var selectedIdx = tags.indexOf(currentTag)
        if (selectedIdx < 0) selectedIdx = 2 // System default

        AlertDialog.Builder(this)
            .setTitle(R.string.label_language_selection)
            .setSingleChoiceItems(options, selectedIdx) { dialog, which ->
                val chosenTag = tags[which]
                settingsPrefs.edit().putString(KEY_APP_LANGUAGE, chosenTag).apply()
                applyAppLanguage(chosenTag)
                dialog.dismiss()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun applyAppLanguage(tag: String) {
        val localeList = if (tag.isBlank()) {
            LocaleListCompat.getEmptyLocaleList()
        } else {
            LocaleListCompat.forLanguageTags(tag)
        }
        AppCompatDelegate.setApplicationLocales(localeList)
        updateLanguageButtonLabel()
        announceStatus(getString(R.string.toast_language_changed))
    }

    private fun updateLanguageButtonLabel() {
        val tag = settingsPrefs.getString(KEY_APP_LANGUAGE, "") ?: ""
        val label = when (tag) {
            "ar" -> getString(R.string.lang_arabic)
            "en" -> getString(R.string.lang_english)
            else -> getString(R.string.lang_system_default)
        }
        btnSelectLanguage.text = String.format(getString(R.string.current_language_label), label)
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
        val status = book.manifest.optString("status", "")
        val isInProgress = totalChapters > book.chaptersCount || status == "in_progress" || status == "paused"

        val options = if (isInProgress) {
            arrayOf(
                getString(R.string.action_play_completed_chapters),
                getString(R.string.action_resume_remaining_chapters),
                getString(R.string.action_export_book),
                getString(R.string.action_share_book),
                getString(R.string.action_delete_book)
            )
        } else {
            arrayOf(
                getString(R.string.action_play_book),
                getString(R.string.action_export_book),
                getString(R.string.action_share_book),
                getString(R.string.action_delete_book)
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
        announceStatus(getString(R.string.status_exporting_chapters))
        lifecycleScope.launch(Dispatchers.IO) {
            val (count, path) = AudioExporter.exportBookToDedicatedFolder(this@MainActivity, book)
            withContext(Dispatchers.Main) {
                if (count > 0) {
                    val msg = getString(R.string.status_export_success, count, path)
                    announceStatus(msg)
                    Toast.makeText(this@MainActivity, msg, Toast.LENGTH_LONG).show()
                } else {
                    announceStatus(getString(R.string.status_export_no_chapters))
                    Toast.makeText(this@MainActivity, getString(R.string.status_export_no_chapters), Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun shareBook(book: BookItem) {
        val ok = AudioExporter.shareBookAudio(this, book)
        if (!ok) {
            announceStatus(getString(R.string.status_share_failed))
            Toast.makeText(this, getString(R.string.status_share_failed), Toast.LENGTH_SHORT).show()
        }
    }

    private fun resumeIncompleteBook(book: BookItem) {
        val persistentSource = File(book.bookDir, "source_book.txt")
        if (persistentSource.exists() && persistentSource.length() > 0) {
            announceStatus(getString(R.string.status_resuming_book, book.title))
            startBookProcessing(persistentSource, book.bookDir, book.title)
        } else {
            announceStatus(getString(R.string.status_select_original_file))
            try {
                filePickerLauncher.launch(arrayOf(
                    "text/plain",
                    "text/markdown",
                    "text/x-markdown",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/msword",
                    "*/*"
                ))
            } catch (e: Exception) {
                Toast.makeText(this, getString(R.string.toast_cannot_open_file_picker), Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun confirmActualDeletion(book: BookItem) {
        AlertDialog.Builder(this)
            .setTitle(R.string.confirm_delete_title)
            .setMessage(getString(R.string.confirm_delete_named_msg, book.title))
            .setPositiveButton(R.string.action_delete) { _, _ ->
                book.bookDir.deleteRecursively()
                refreshBooksList()
                announceStatus(getString(R.string.status_book_deleted))
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

        val incompleteBook = booksList.firstOrNull { book ->
            val total = book.manifest.optInt("total_chapters", book.chaptersCount)
            val st = book.manifest.optString("status", "")
            (st == "in_progress" || st == "paused" || book.chaptersCount < total) && total > 0
        }

        if (incompleteBook != null) {
            val total = incompleteBook.manifest.optInt("total_chapters", incompleteBook.chaptersCount)
            cardResumeIncompleteBook.visibility = View.VISIBLE
            val resumeInfo = String.format(getString(R.string.card_resume_info), incompleteBook.title, incompleteBook.chaptersCount, total)
            textResumeBookInfo.text = resumeInfo
            cardResumeIncompleteBook.contentDescription = resumeInfo
            btnResumeBook.setOnClickListener {
                resumeIncompleteBook(incompleteBook)
            }
            btnDismissResumeBook.setOnClickListener {
                cardResumeIncompleteBook.visibility = View.GONE
            }
        } else {
            cardResumeIncompleteBook.visibility = View.GONE
        }
    }

    private fun showPasteTextDialog() {
        val dialogView = LayoutInflater.from(this).inflate(R.layout.dialog_paste_text, null, false)
        val textActiveVoiceSettings = dialogView.findViewById<TextView>(R.id.textActiveVoiceSettings)
        val editPasteTitle = dialogView.findViewById<EditText>(R.id.editPasteTitle)
        val btnPasteFromClipboard = dialogView.findViewById<Button>(R.id.btnPasteFromClipboard)
        val btnInsertDialogueTemplate = dialogView.findViewById<Button>(R.id.btnInsertDialogueTemplate)
        val editPasteContent = dialogView.findViewById<EditText>(R.id.editPasteContent)
        val textPasteCharCount = dialogView.findViewById<TextView>(R.id.textPasteCharCount)
        val textDialogueDetectionStatus = dialogView.findViewById<TextView>(R.id.textDialogueDetectionStatus)

        val annotator = DialogueTurnAnnotator()
        val isArabic = isCurrentLocaleArabic()

        val narratorId = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
        val narratorProfile = getVoiceProfile(narratorId)
        val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
        val stylePreset = VoiceStylePreset.fromId(styleId)
        val isMulti = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
        val multiInfo = if (isMulti) getString(R.string.paste_multi_suffix) else ""

        textActiveVoiceSettings.text = getString(R.string.paste_active_voice_format, narratorProfile.displayName(isArabic), stylePreset.title(isArabic), multiInfo)

        val updateCount = {
            val len = editPasteContent.text?.length ?: 0
            textPasteCharCount.text = getString(R.string.char_count_format, len)
        }

        val updateDialogueStatus = {
            val content = editPasteContent.text?.toString() ?: ""
            if (content.isBlank()) {
                textDialogueDetectionStatus.text = getString(R.string.dialogue_type_empty)
                textDialogueDetectionStatus.setTextColor(ContextCompat.getColor(this, R.color.text_secondary))
            } else {
                val summary = annotator.summarizeText(content)
                textDialogueDetectionStatus.text = getString(R.string.dialogue_type_detected, summary)
                if (summary.contains("حوار ثنائي") || summary.contains("Dialogue", ignoreCase = true)) {
                    textDialogueDetectionStatus.setTextColor(ContextCompat.getColor(this, R.color.primary_accessible))
                } else {
                    textDialogueDetectionStatus.setTextColor(ContextCompat.getColor(this, R.color.text_secondary))
                }
            }
        }

        editPasteContent.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                updateCount()
                updateDialogueStatus()
            }
            override fun afterTextChanged(s: Editable?) {}
        })

        btnPasteFromClipboard.setOnClickListener {
            try {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                val clip = clipboard?.primaryClip
                if (clip != null && clip.itemCount > 0) {
                    val itemText = clip.getItemAt(0)?.coerceToText(this)?.toString() ?: ""
                    if (itemText.isNotBlank()) {
                        editPasteContent.setText(itemText)
                        editPasteContent.setSelection(itemText.length)
                        updateCount()
                        updateDialogueStatus()
                        announceStatus(getString(R.string.paste_dialog_pasted_announcement, itemText.length, annotator.summarizeText(itemText)))
                        Toast.makeText(this, getString(R.string.toast_text_pasted), Toast.LENGTH_SHORT).show()
                    } else {
                        announceStatus(getString(R.string.toast_no_text_or_file))
                        Toast.makeText(this, getString(R.string.toast_no_text_or_file), Toast.LENGTH_SHORT).show()
                    }
                } else {
                    announceStatus(getString(R.string.toast_no_text_or_file))
                    Toast.makeText(this, getString(R.string.toast_no_text_or_file), Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error accessing clipboard: ${e.message}")
            }
        }

        btnInsertDialogueTemplate.setOnClickListener {
            val sampleDialogue = if (isArabic) {
                """Speaker1: مرحباً يا أحمد في تجربة الحوار الصوتي متعدد المتحدثين.
Speaker2: أهلاً بك يا صديقي! هل يتغير الصوت تلقائياً الآن بحسب المتحدث؟
Speaker1: نعم تماماً، هذا نموذج الحوار الرسمي المعتمد من Google Gemini.
Speaker2: رائع جداً، النبرة تبدو طبيعية وسلسة للغاية!"""
            } else {
                """Speaker1: Hello Ahmed! Welcome to the multi-speaker voice test.
Speaker2: Glad to be here! Does the voice switch dynamically based on speaker?
Speaker1: Yes, exactly! This is the official Google Gemini dialogue standard.
Speaker2: Outstanding! The tone sounds remarkably natural and smooth!"""
            }
            editPasteContent.setText(sampleDialogue)
            editPasteContent.setSelection(sampleDialogue.length)
            if (!settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)) {
                settingsPrefs.edit().putBoolean(KEY_MULTI_SPEAKER, true).apply()
                updateStudioUI()
                announceStatus(getString(R.string.announce_multi_speaker_on))
            } else {
                announceStatus(getString(R.string.announce_dialogue_template_copied))
            }
            updateCount()
            updateDialogueStatus()
            Toast.makeText(this, getString(R.string.toast_dialogue_template_copied), Toast.LENGTH_SHORT).show()
        }

        AlertDialog.Builder(this)
            .setTitle(R.string.action_paste_text)
            .setView(dialogView)
            .setPositiveButton(R.string.btn_convert_save_library) { _, _ ->
                val content = editPasteContent.text.toString().trim()
                if (content.isBlank()) {
                    announceStatus(getString(R.string.toast_no_text_or_file))
                    Toast.makeText(this, getString(R.string.toast_no_text_or_file), Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }

                val summary = annotator.summarizeText(content)
                if ((summary.contains("حوار ثنائي") || summary.contains("Dialogue", ignoreCase = true)) && !settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)) {
                    settingsPrefs.edit().putBoolean(KEY_MULTI_SPEAKER, true).apply()
                    updateStudioUI()
                    announceStatus(getString(R.string.announce_multi_speaker_on))
                }

                val customTitle = editPasteTitle.text.toString().trim()
                val finalTitle = if (customTitle.isNotBlank()) {
                    customTitle
                } else {
                    val snippet = content.take(30).replace(Regex("[\\r\\n]+"), " ").trim()
                    if (snippet.isNotBlank()) {
                        "Clip - $snippet"
                    } else {
                        "Clip_${System.currentTimeMillis()}"
                    }
                }

                val safeDirName = finalTitle.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_").take(45)
                val bookDir = File(File(filesDir, "audiobooks"), safeDirName)

                val tempFile = File(cacheDir, "pasted_${System.currentTimeMillis()}.txt")
                try {
                    tempFile.writeText(content, Charsets.UTF_8)
                    announceStatus(getString(R.string.book_processing_started, finalTitle))
                    startBookProcessing(tempFile, bookDir, finalTitle)
                } catch (e: Exception) {
                    Log.e(TAG, "Error saving pasted text: ${e.message}", e)
                    val err = getString(R.string.status_conversion_error, e.message ?: "")
                    announceStatus(err)
                    Toast.makeText(this, err, Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun importAndProcessBook(uri: Uri) {
        lifecycleScope.launch {
            try {
                announceStatus(getString(R.string.status_importing_book))
                val rawName = getFileNameFromUri(uri)
                val ext = rawName?.substringAfterLast('.', "")?.lowercase() ?: ""
                if (ext.isNotEmpty() && ext != "txt" && ext != "md" && ext != "markdown" && ext != "docx") {
                    announceStatus(getString(R.string.toast_unsupported_file_type))
                    Toast.makeText(this@MainActivity, getString(R.string.toast_unsupported_file_type), Toast.LENGTH_LONG).show()
                    return@launch
                }
                val safeName = if (!rawName.isNullOrBlank()) {
                    rawName.replace(Regex("[^a-zA-Z0-9._\\-\\u0600-\\u06FF]"), "_")
                } else {
                    "Book_${System.currentTimeMillis()}.txt"
                }
                val tempFile = File(cacheDir, safeName)

                withContext(Dispatchers.IO) {
                    contentResolver.openInputStream(uri)?.use { input ->
                        FileOutputStream(tempFile).use { output ->
                            input.copyTo(output)
                        }
                    } ?: throw IllegalStateException("Cannot open input stream")
                }

                if (!tempFile.exists() || tempFile.length() == 0L) {
                    announceStatus(getString(R.string.toast_file_empty))
                    Toast.makeText(this@MainActivity, getString(R.string.toast_file_empty), Toast.LENGTH_LONG).show()
                    return@launch
                }

                val bookTitle = tempFile.nameWithoutExtension.ifBlank { "Audiobook" }
                val bookDir = File(File(filesDir, "audiobooks"), bookTitle)
                startBookProcessing(tempFile, bookDir, bookTitle)
            } catch (e: Exception) {
                Log.e(TAG, "Error importing book: ${e.message}", e)
                val err = getString(R.string.status_conversion_error, e.localizedMessage ?: e.message)
                announceStatus(err)
                Toast.makeText(this@MainActivity, err, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun acquireWakeLock() {
        try {
            if (wakeLock == null) {
                val powerManager = getSystemService(Context.POWER_SERVICE) as? PowerManager
                wakeLock = powerManager?.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK,
                    "GeminiAudiobook:ConversionWakeLock"
                )?.apply {
                    setReferenceCounted(false)
                }
            }
            wakeLock?.acquire(120 * 60 * 1000L) // 2 hours maximum safeguard
            Log.i(TAG, "WakeLock acquired for audiobook conversion")
        } catch (e: Exception) {
            Log.w(TAG, "Failed to acquire WakeLock: ${e.message}")
        }
    }

    private fun releaseWakeLock() {
        try {
            if (wakeLock?.isHeld == true) {
                wakeLock?.release()
                Log.i(TAG, "WakeLock released")
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to release WakeLock: ${e.message}")
        }
    }

    private fun showQuotaExceededDialog(sourceFile: File, bookDir: File, bookTitle: String) {
        AlertDialog.Builder(this)
            .setTitle(R.string.dialog_quota_exceeded_title)
            .setMessage(R.string.dialog_quota_exceeded_msg)
            .setPositiveButton(R.string.action_retry_now) { _, _ ->
                announceStatus(getString(R.string.book_retry_started, bookTitle))
                startBookProcessing(sourceFile, bookDir, bookTitle)
            }
            .setNeutralButton(R.string.action_edit_key) { _, _ ->
                bottomNav.selectedItemId = R.id.tab_settings
                showApiKeyEditDialog()
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun startBookProcessing(sourceFile: File, bookDir: File, bookTitle: String) {
        acquireWakeLock()
        lifecycleScope.launch {
            try {
                val keys = getStoredApiKeys()
                val narratorVoice = settingsPrefs.getString(KEY_GEMINI_VOICE, DEFAULT_NARRATOR_VOICE) ?: DEFAULT_NARRATOR_VOICE
                val styleId = settingsPrefs.getString(KEY_VOICE_STYLE, DEFAULT_STYLE_ID) ?: DEFAULT_STYLE_ID
                val stylePreset = VoiceStylePreset.fromId(styleId)
                val isMultiSpeaker = settingsPrefs.getBoolean(KEY_MULTI_SPEAKER, false)
                val characterVoice = settingsPrefs.getString(KEY_CHARACTER_VOICE, DEFAULT_CHARACTER_VOICE) ?: DEFAULT_CHARACTER_VOICE
                val modelId = settingsPrefs.getString(KEY_MODEL_ID, DEFAULT_MODEL_ID) ?: DEFAULT_MODEL_ID
                val isArabic = isCurrentLocaleArabic()

                if (keys.isEmpty()) {
                    announceStatus(getString(R.string.toast_keys_required_conversion))
                    Toast.makeText(this@MainActivity, getString(R.string.toast_keys_required_conversion), Toast.LENGTH_LONG).show()
                    bottomNav.selectedItemId = R.id.tab_settings
                    return@launch
                }

                bookDir.mkdirs()
                val sourceExt = if (sourceFile.extension.isNotBlank()) sourceFile.extension else "txt"
                val persistentSource = File(bookDir, "source_book.$sourceExt")
                if (sourceFile.absolutePath != persistentSource.absolutePath) {
                    sourceFile.copyTo(persistentSource, overwrite = true)
                }

                val ttsClient = GeminiTtsClient(
                    apiKeys = keys,
                    modelId = modelId,
                    quotaManager = keyQuotaManager
                )
                val multiConfig = if (isMultiSpeaker) {
                    MultiSpeakerConfig(
                        isEnabled = true,
                        narratorVoice = getVoiceProfile(narratorVoice),
                        characterVoice = getVoiceProfile(characterVoice)
                    )
                } else null

                val customInstructions = settingsPrefs.getString(KEY_CUSTOM_VOICE_INSTRUCTIONS, null)

                val engine = AudiobookEngine(
                    context = this@MainActivity,
                    outputDir = bookDir,
                    ttsClient = ttsClient,
                    voiceName = narratorVoice,
                    stylePreset = stylePreset,
                    multiSpeakerConfig = multiConfig,
                    customInstructions = customInstructions
                )

                announceStatus(getString(R.string.status_converting_book_format, bookTitle, stylePreset.title(isArabic)))

                withContext(Dispatchers.IO) {
                    engine.processBook(persistentSource, customTitle = bookTitle) { current, total, title ->
                        lifecycleScope.launch(Dispatchers.Main) {
                            announceStatus(getString(R.string.status_converting_chapter_format, current, total, title))
                        }
                    }
                }

                val folderDisplay = if (hasStoragePermission()) {
                    "/sdcard/GeminiAudiobook/$bookTitle"
                } else {
                    "Music/GeminiAudiobook/$bookTitle"
                }
                announceStatus(getString(R.string.status_conversion_success, folderDisplay))
                Toast.makeText(this@MainActivity, getString(R.string.status_conversion_success, folderDisplay), Toast.LENGTH_LONG).show()
                refreshBooksList()
            } catch (e: Exception) {
                Log.e(TAG, "Error processing book: ${e.message}", e)
                refreshBooksList()
                val isQuota = e is QuotaExceededException || e.message?.contains("429") == true || e.message?.contains("Rate limit") == true
                if (isQuota) {
                    announceStatus(getString(R.string.dialog_quota_exceeded_msg))
                    showQuotaExceededDialog(sourceFile, bookDir, bookTitle)
                } else {
                    val err = getString(R.string.status_conversion_error, e.localizedMessage ?: e.message)
                    announceStatus(err)
                    Toast.makeText(this@MainActivity, err, Toast.LENGTH_LONG).show()
                }
            } finally {
                releaseWakeLock()
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
        val defaultChapterTitle = getString(R.string.player_progress_format, chapterIndex, chapters.length())
        val chapterTitle = chapterObj.optString("title", defaultChapterTitle)

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
            announceStatus(getString(R.string.status_audio_not_available))
            Toast.makeText(this, getString(R.string.toast_audio_missing), Toast.LENGTH_SHORT).show()
            return
        }

        textNowPlayingTitle.text = book.title
        textNowPlayingChapter.text = chapterTitle
        textPlayerBookTitle.text = book.title
        textPlayerChapterTitle.text = chapterTitle
        textPlayerProgress.text = getString(R.string.player_progress_format, chapterIndex, chapters.length())

        announceStatus(getString(R.string.announce_playing_format, book.title, chapterTitle))
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
            announceStatus(getString(R.string.announce_playback_paused))
        } else {
            if (mc.mediaItemCount == 0 && currentActiveBook != null) {
                playBook(currentActiveBook!!, currentChapterIndex)
            } else {
                mc.play()
                updatePlayPauseButton(true)
                announceStatus(getString(R.string.announce_playback_resumed))
            }
        }
    }

    private fun playNextChapter() {
        val book = currentActiveBook ?: return
        val total = book.manifest.optJSONArray("chapters")?.length() ?: 1
        if (currentChapterIndex < total) {
            playBook(book, currentChapterIndex + 1)
        } else {
            announceStatus(getString(R.string.announce_end_of_book))
        }
    }

    private fun playPreviousChapter() {
        val book = currentActiveBook ?: return
        if (currentChapterIndex > 1) {
            playBook(book, currentChapterIndex - 1)
        } else {
            announceStatus(getString(R.string.announce_already_first_chapter))
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
        announceStatus(getString(R.string.announce_reading_speed_format, currentSpeed))
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
        releaseWakeLock()
        controllerFuture?.let { MediaController.releaseFuture(it) }
        super.onDestroy()
    }

    // -------------------------------------------------------------------------
    // In-App Updates & Package Installation Management
    // -------------------------------------------------------------------------

    private fun checkForAppUpdates(userTriggered: Boolean) {
        if (userTriggered) {
            announceStatus(getString(R.string.updates_checking))
            Toast.makeText(this, getString(R.string.updates_checking), Toast.LENGTH_SHORT).show()
        }

        lifecycleScope.launch {
            try {
                val currentVersionName = try {
                    packageManager.getPackageInfo(packageName, 0).versionName ?: "1.5.3"
                } catch (e: Exception) {
                    "1.5.3"
                }

                val (latestTag, changelog, apkDownloadUrl) = withContext(Dispatchers.IO) {
                    val client = OkHttpClient.Builder().build()
                    val apiUrl = "https://api.github.com/repos/ahanafy41/gemini-audiobook-tts/releases/latest"
                    val apiRequest = Request.Builder()
                        .url(apiUrl)
                        .header("User-Agent", "GeminiAudiobookApp/$currentVersionName")
                        .header("Accept", "application/vnd.github.v3+json")
                        .build()

                    try {
                        client.newCall(apiRequest).execute().use { response ->
                            if (response.isSuccessful) {
                                val body = response.body?.string() ?: ""
                                val json = JSONObject(body)
                                val tagName = json.optString("tag_name", "").removePrefix("v")
                                val bodyText = json.optString("body", "")
                                val assets = json.optJSONArray("assets")
                                var apkUrl = ""
                                if (assets != null) {
                                    for (i in 0 until assets.length()) {
                                        val asset = assets.getJSONObject(i)
                                        val name = asset.optString("name", "")
                                        if (name.endsWith(".apk", ignoreCase = true)) {
                                            apkUrl = asset.optString("browser_download_url", "")
                                            break
                                        }
                                    }
                                }
                                if (tagName.isNotBlank() && apkUrl.isNotBlank()) {
                                    return@withContext Triple(tagName, bodyText, apkUrl)
                                }
                            }
                        }
                    } catch (e: Exception) {
                        Log.w(TAG, "GitHub API update check failed, attempting web fallback: ${e.message}")
                    }

                    // Fallback to web redirect
                    val noRedirectClient = OkHttpClient.Builder()
                        .followRedirects(false)
                        .followSslRedirects(false)
                        .build()
                    val webRequest = Request.Builder()
                        .url("https://github.com/ahanafy41/gemini-audiobook-tts/releases/latest")
                        .header("User-Agent", "Mozilla/5.0 (Android; Mobile)")
                        .build()

                    noRedirectClient.newCall(webRequest).execute().use { response ->
                        val location = response.header("Location") ?: ""
                        if (location.contains("/releases/tag/")) {
                            val rawTag = location.substringAfterLast("/tag/").trim()
                            val cleanTag = rawTag.removePrefix("v")
                            val apkUrl = "https://github.com/ahanafy41/gemini-audiobook-tts/releases/download/$rawTag/app-debug.apk"
                            Triple(cleanTag, "", apkUrl)
                        } else {
                            throw IllegalStateException("Failed to fetch update info (${response.code})")
                        }
                    }
                }

                val hasNewVersion = isVersionNewer(latestTag, currentVersionName)
                if (hasNewVersion && apkDownloadUrl.isNotBlank()) {
                    announceStatus(getString(R.string.updates_available_title, latestTag))
                    showUpdateAvailableDialog(latestTag, changelog, apkDownloadUrl)
                } else {
                    if (userTriggered) {
                        announceStatus(getString(R.string.updates_latest, currentVersionName))
                        Toast.makeText(this@MainActivity, getString(R.string.updates_latest, currentVersionName), Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Update check failed: ${e.message}")
                if (userTriggered) {
                    val err = getString(R.string.updates_failed, e.localizedMessage ?: e.message)
                    announceStatus(err)
                    Toast.makeText(this@MainActivity, err, Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun isVersionNewer(remote: String, local: String): Boolean {
        if (remote.isBlank() || local.isBlank()) return false
        val rParts = remote.split(".").mapNotNull { it.toIntOrNull() }
        val lParts = local.split(".").mapNotNull { it.toIntOrNull() }
        val maxLen = maxOf(rParts.size, lParts.size)
        for (i in 0 until maxLen) {
            val r = rParts.getOrElse(i) { 0 }
            val l = lParts.getOrElse(i) { 0 }
            if (r > l) return true
            if (r < l) return false
        }
        return false
    }

    private fun showUpdateAvailableDialog(version: String, notes: String, downloadUrl: String) {
        val notesText = if (notes.isNotBlank()) notes else getString(R.string.app_name)
        val msg = getString(R.string.updates_dialog_body_format, notesText)

        AlertDialog.Builder(this)
            .setTitle(getString(R.string.updates_available_title, version))
            .setMessage(msg)
            .setPositiveButton(R.string.updates_action_install) { _, _ ->
                downloadAndInstallUpdate(downloadUrl, version)
            }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun downloadAndInstallUpdate(downloadUrl: String, version: String) {
        val progressLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (20 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }

        val textProgressInfo = TextView(this).apply {
            text = getString(R.string.updates_started_announcement, version)
            textSize = 15f
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.text_high_contrast))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                bottomMargin = (12 * resources.displayMetrics.density).toInt()
            }
        }

        val progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = 100
            progress = 0
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                (20 * resources.displayMetrics.density).toInt()
            )
        }

        progressLayout.addView(textProgressInfo)
        progressLayout.addView(progressBar)

        var isCancelled = false
        var callRef: okhttp3.Call? = null

        val dialog = AlertDialog.Builder(this)
            .setTitle(getString(R.string.updates_downloading_title, version))
            .setView(progressLayout)
            .setCancelable(false)
            .setNegativeButton(R.string.updates_action_cancel_download) { _, _ ->
                isCancelled = true
                callRef?.cancel()
                announceStatus(getString(R.string.updates_cancelled_announcement))
            }
            .create()

        dialog.show()
        announceStatus(getString(R.string.updates_started_announcement, version))

        lifecycleScope.launch {
            try {
                val apkFile = File(cacheDir, "GeminiAudiobook_update.apk")
                var lastAnnouncedPercent = 0

                withContext(Dispatchers.IO) {
                    val client = OkHttpClient.Builder().build()
                    val req = Request.Builder()
                        .url(downloadUrl)
                        .header("User-Agent", "GeminiAudiobookUpdater")
                        .build()

                    val call = client.newCall(req)
                    callRef = call
                    call.execute().use { resp ->
                        if (!resp.isSuccessful) throw IllegalStateException("HTTP ${resp.code}")
                        val body = resp.body ?: throw IllegalStateException("Empty body")
                        val totalBytes = body.contentLength()
                        val tempFile = File(cacheDir, "GeminiAudiobook_update.tmp")

                        var downloadedBytes = 0L
                        val buffer = ByteArray(8192)

                        body.byteStream().use { input ->
                            FileOutputStream(tempFile).use { output ->
                                while (true) {
                                    if (isCancelled) {
                                        tempFile.delete()
                                        throw CancellationException("Cancelled")
                                    }
                                    val read = input.read(buffer)
                                    if (read == -1) break
                                    output.write(buffer, 0, read)
                                    downloadedBytes += read

                                    if (totalBytes > 0) {
                                        val percent = ((downloadedBytes * 100) / totalBytes).toInt()
                                        val downloadedMB = downloadedBytes / (1024.0 * 1024.0)
                                        val totalMB = totalBytes / (1024.0 * 1024.0)

                                        withContext(Dispatchers.Main) {
                                            progressBar.progress = percent
                                            textProgressInfo.text = String.format(
                                                java.util.Locale.US,
                                                getString(R.string.updates_progress_text_format),
                                                downloadedMB,
                                                totalMB,
                                                percent
                                            )
                                        }

                                        if (percent >= lastAnnouncedPercent + 25 && percent < 100) {
                                            lastAnnouncedPercent = (percent / 25) * 25
                                            withContext(Dispatchers.Main) {
                                                announceStatus(getString(R.string.updates_percent_announcement, lastAnnouncedPercent))
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        if (apkFile.exists()) apkFile.delete()
                        tempFile.renameTo(apkFile)
                    }
                }

                if (!isCancelled) {
                    withContext(Dispatchers.Main) {
                        dialog.dismiss()
                        announceStatus(getString(R.string.update_download_complete))
                        installApkFile(apkFile)
                    }
                }
            } catch (e: CancellationException) {
                withContext(Dispatchers.Main) {
                    dialog.dismiss()
                }
            } catch (e: Exception) {
                Log.e(TAG, "Download update failed: ${e.message}")
                withContext(Dispatchers.Main) {
                    dialog.dismiss()
                    val err = getString(R.string.update_download_failed, e.localizedMessage ?: e.message)
                    announceStatus(err)
                    Toast.makeText(this@MainActivity, err, Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun installApkFile(apkFile: File) {
        if (!apkFile.exists() || apkFile.length() < 1000) {
            Toast.makeText(this, getString(R.string.toast_invalid_update_file), Toast.LENGTH_SHORT).show()
            return
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (!packageManager.canRequestPackageInstalls()) {
                announceStatus(getString(R.string.update_install_perm_msg))
                Toast.makeText(this, getString(R.string.toast_install_perm), Toast.LENGTH_LONG).show()
                val permissionIntent = Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:$packageName")
                )
                startActivity(permissionIntent)
                return
            }
        }

        try {
            val apkUri = FileProvider.getUriForFile(
                this,
                "com.antigravity.audiobook.fileprovider",
                apkFile
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(apkUri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to launch package installer: ${e.message}")
            val err = getString(R.string.status_conversion_error, e.localizedMessage ?: e.message)
            announceStatus(err)
            Toast.makeText(this, err, Toast.LENGTH_LONG).show()
        }
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
            val isIncomplete = (status == "in_progress" || status == "paused" || book.chaptersCount < totalChapters) && totalChapters > 0

            val textTitle = view.findViewById<TextView>(R.id.textBookTitle)
            val textSubtitle = view.findViewById<TextView>(R.id.textBookSubtitle)

            textTitle.text = book.title
            if (isIncomplete) {
                textSubtitle.text = context.getString(R.string.book_subtitle_incomplete, book.chaptersCount, totalChapters)
                view.contentDescription = context.getString(R.string.desc_book_incomplete, book.title, book.chaptersCount, totalChapters)
            } else {
                textSubtitle.text = context.getString(R.string.book_subtitle_complete, book.chaptersCount)
                view.contentDescription = context.getString(R.string.desc_book_complete, book.title, book.chaptersCount)
            }

            view.setOnClickListener {
                if (isIncomplete) {
                    if (book.chaptersCount == 0) {
                        resumeIncompleteBook(book)
                    } else {
                        AlertDialog.Builder(context)
                            .setTitle(book.title)
                            .setMessage(context.getString(R.string.book_incomplete_dialog_msg, book.chaptersCount, totalChapters))
                            .setPositiveButton(R.string.action_resume_conversion) { _, _ ->
                                resumeIncompleteBook(book)
                            }
                            .setNeutralButton(R.string.action_play_done) { _, _ ->
                                playBook(book, chapterIndex = 1)
                            }
                            .setNegativeButton(R.string.action_cancel, null)
                            .show()
                    }
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
