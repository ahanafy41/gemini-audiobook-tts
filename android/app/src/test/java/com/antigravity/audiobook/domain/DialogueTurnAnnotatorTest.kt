package com.antigravity.audiobook.domain

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class DialogueTurnAnnotatorTest {

    private lateinit var annotator: DialogueTurnAnnotator

    @Before
    fun setUp() {
        annotator = DialogueTurnAnnotator("Narrator", "Character")
    }

    @Test
    fun testDialogueQuotationSeparation() {
        val text = "نظر القائد إلى جنوده ثم قال: «استعدوا للمعركة القادمة بكل شجاعة» وعاد إلى خيمته."
        val turns = annotator.annotateText(text)

        assertEquals(3, turns.size)
        assertEquals("Narrator", turns[0].speaker)
        assertTrue(turns[0].text.contains("نظر القائد"))

        assertEquals("Character", turns[1].speaker)
        assertEquals("استعدوا للمعركة القادمة بكل شجاعة", turns[1].text)

        assertEquals("Narrator", turns[2].speaker)
        assertTrue(turns[2].text.contains("وعاد إلى خيمته"))
    }

    @Test
    fun testEmotionStyleInference() {
        val text = "اقترب منه وهمس بصوت خافت: «السر محفوظ في الخزنة القديمة»."
        val turns = annotator.annotateText(text)

        assertEquals(2, turns.size)
        val characterTurn = turns[1]
        assertEquals("Character", characterTurn.speaker)
        assertEquals("whispered urgently, quiet hushed tone", characterTurn.stylePrompt)
    }

    @Test
    fun testScriptFormatParsing() {
        val script = """
            أحمد: مرحباً كيف حالك اليوم؟
            سارة: بخير والحمد لله، وأنت؟
        """.trimIndent()

        val turns = annotator.annotateText(script)
        assertEquals(2, turns.size)
        assertEquals("Narrator", turns[0].speaker)
        assertEquals("Character", turns[1].speaker)
    }
}
