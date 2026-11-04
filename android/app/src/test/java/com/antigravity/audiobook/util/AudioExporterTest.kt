package com.antigravity.audiobook.util

import org.junit.Assert.*
import org.junit.Test

class AudioExporterTest {

    @Test
    fun testGenerateCueSheet() {
        val chapters = listOf(
            ChapterAudioMeta(1, "المقدمة", 120000L), // 2 mins
            ChapterAudioMeta(2, "الفصل الأول", 300000L) // 5 mins
        )

        val cue = AudioExporter.generateCueSheet("تاريخ مصر", chapters, "full_book.wav")

        assertTrue(cue.contains("TITLE \"تاريخ مصر\""))
        assertTrue(cue.contains("FILE \"full_book.wav\" WAVE"))
        assertTrue(cue.contains("TRACK 01 AUDIO"))
        assertTrue(cue.contains("TITLE \"المقدمة\""))
        assertTrue(cue.contains("INDEX 01 00:00:00"))

        assertTrue(cue.contains("TRACK 02 AUDIO"))
        assertTrue(cue.contains("TITLE \"الفصل الأول\""))
        // Track 2 starts around 02:00:30 (with 400ms padding)
        assertTrue(cue.contains("INDEX 01 02:00"))
    }

    @Test
    fun testGenerateM3uPlaylist() {
        val chapters = listOf(
            ChapterAudioMeta(1, "الفصل الأول", 150000L, "chapters/chapter_001.wav"),
            ChapterAudioMeta(2, "الفصل الثاني", 180000L, "chapters/chapter_002.wav")
        )

        val m3u = AudioExporter.generateM3uPlaylist("رواية ملحمية", chapters)

        assertTrue(m3u.startsWith("#EXTM3U\n#PLAYLIST:رواية ملحمية"))
        assertTrue(m3u.contains("#EXTINF:150,الفصل الأول\nchapters/chapter_001.wav"))
        assertTrue(m3u.contains("#EXTINF:180,الفصل الثاني\nchapters/chapter_002.wav"))
    }
}
