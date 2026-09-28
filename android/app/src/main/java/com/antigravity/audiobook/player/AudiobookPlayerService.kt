package com.antigravity.audiobook.player

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.annotation.OptIn
import androidx.core.app.NotificationCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import com.antigravity.audiobook.MainActivity

/**
 * Background Audiobook Player Service based on Jetpack Media3.
 * Enforces Audio Focus with automatic ducking/pause for TalkBack and Jieshuo screen readers.
 * Persists playback bookmarks automatically across sessions.
 */
class AudiobookPlayerService : MediaSessionService(), Player.Listener {

    companion object {
        private const val TAG = "AudiobookPlayerService"
        const val CHANNEL_ID = "audiobook_playback_channel"
        const val NOTIFICATION_ID = 1001
        private const val PREFS_NAME = "audiobook_bookmarks"
        private const val KEY_BOOK_TITLE = "last_book_title"
        private const val KEY_CHAPTER_INDEX = "last_chapter_index"
        private const val KEY_POSITION_MS = "last_position_ms"

        const val ACTION_PLAY_CHAPTER = "com.antigravity.audiobook.ACTION_PLAY_CHAPTER"
        const val EXTRA_AUDIO_PATH = "extra_audio_path"
        const val EXTRA_BOOK_TITLE = "extra_book_title"
        const val EXTRA_CHAPTER_TITLE = "extra_chapter_title"
        const val EXTRA_CHAPTER_INDEX = "extra_chapter_index"
    }

    private var player: ExoPlayer? = null
    private var mediaSession: MediaSession? = null
    private lateinit var prefs: SharedPreferences

    private var currentBookTitle: String = ""
    private var currentChapterTitle: String = ""
    private var currentChapterIndex: Int = 1

    @OptIn(UnstableApi::class)
    override fun onCreate() {
        super.onCreate()
        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        createNotificationChannel()

        // Speech-optimized audio attributes with automatic AudioFocus ducking for screen readers
        val audioAttributes = AudioAttributes.Builder()
            .setContentType(C.AUDIO_CONTENT_TYPE_SPEECH)
            .setUsage(C.USAGE_MEDIA)
            .build()

        player = ExoPlayer.Builder(this)
            .setAudioAttributes(audioAttributes, true) // true = handleAudioFocus automatically
            .setHandleAudioBecomingNoisy(true) // pause when headphones disconnected
            .build()
            .apply {
                addListener(this@AudiobookPlayerService)
            }

        val sessionActivityPendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        mediaSession = MediaSession.Builder(this, player!!)
            .setSessionActivity(sessionActivityPendingIntent)
            .build()

        Log.i(TAG, "AudiobookPlayerService initialized with Media3 and AudioFocus.")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent == null) return START_STICKY

        val action = intent.action
        if (action == ACTION_PLAY_CHAPTER) {
            val audioPath = intent.getStringExtra(EXTRA_AUDIO_PATH) ?: ""
            currentBookTitle = intent.getStringExtra(EXTRA_BOOK_TITLE) ?: "كتاب صوتي"
            currentChapterTitle = intent.getStringExtra(EXTRA_CHAPTER_TITLE) ?: "فصل"
            currentChapterIndex = intent.getIntExtra(EXTRA_CHAPTER_INDEX, 1)

            if (audioPath.isNotEmpty()) {
                playAudioFile(audioPath)
            }
        }

        return START_STICKY
    }

    private fun playAudioFile(path: String) {
        val p = player ?: return
        val mediaItem = MediaItem.fromUri(path)
        p.setMediaItem(mediaItem)

        // Restore saved position if same book and chapter
        val lastTitle = prefs.getString(KEY_BOOK_TITLE, "")
        val lastIdx = prefs.getInt(KEY_CHAPTER_INDEX, -1)
        val lastPos = prefs.getLong(KEY_POSITION_MS, 0L)

        val seekPos = if (lastTitle == currentBookTitle && lastIdx == currentChapterIndex && lastPos > 0) {
            lastPos
        } else {
            0L
        }

        p.prepare()
        if (seekPos > 0) {
            p.seekTo(seekPos)
            Log.i(TAG, "Restored bookmark for '$currentBookTitle' at $seekPos ms.")
        }
        p.play()

        updateForegroundNotification(isPlaying = true)
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? {
        return mediaSession
    }

    override fun onIsPlayingChanged(isPlaying: Boolean) {
        updateForegroundNotification(isPlaying)
        if (!isPlaying) {
            saveCurrentBookmark()
        }
    }

    override fun onPlaybackStateChanged(playbackState: Int) {
        if (playbackState == Player.STATE_ENDED) {
            saveBookmark(0L) // Reset position for this chapter
        }
    }

    private fun saveCurrentBookmark() {
        val currentPos = player?.currentPosition ?: 0L
        saveBookmark(currentPos)
    }

    private fun saveBookmark(pos: Long) {
        if (currentBookTitle.isNotBlank()) {
            prefs.edit()
                .putString(KEY_BOOK_TITLE, currentBookTitle)
                .putInt(KEY_CHAPTER_INDEX, currentChapterIndex)
                .putLong(KEY_POSITION_MS, pos)
                .apply()
            Log.i(TAG, "Saved bookmark: $currentBookTitle (Ch $currentChapterIndex) at $pos ms.")
        }
    }

    private fun updateForegroundNotification(isPlaying: Boolean) {
        val contentIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(currentBookTitle)
            .setContentText(currentChapterTitle)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentIntent(contentIntent)
            .setOngoing(isPlaying)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

        startForeground(NOTIFICATION_ID, notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "تشغيل الكتب الصوتية",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "إشعارات التحكم في مشغل الكتاب الصوتي بالخلفية"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        saveCurrentBookmark()
        mediaSession?.run {
            player.release()
            release()
            mediaSession = null
        }
        player = null
        super.onDestroy()
        Log.i(TAG, "AudiobookPlayerService destroyed.")
    }
}
