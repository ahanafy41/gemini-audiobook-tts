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

    @Test
    fun testNestedQuotesNotTruncated() {
        val text = "قال المعلم: «اقرأوا في كتاب \"الأيام\" لطه حسين الفصل الأول» وعاد إلى مقعده."
        val turns = annotator.annotateText(text)

        assertEquals(3, turns.size)
        assertEquals("Narrator", turns[0].speaker)
        assertTrue(turns[0].text.contains("قال المعلم"))

        assertEquals("Character", turns[1].speaker)
        assertEquals("اقرأوا في كتاب \"الأيام\" لطه حسين الفصل الأول", turns[1].text)

        assertEquals("Narrator", turns[2].speaker)
        assertTrue(turns[2].text.contains("وعاد إلى مقعده"))
    }

    @Test
    fun testIsolatedSingleWordTermRemainsNarrator() {
        // Book title without inquit should remain narrator voice
        val textBook = "قرأت كتاب «الأغاني» للأصفهاني."
        val turnsBook = annotator.annotateText(textBook)
        assertEquals(1, turnsBook.size)
        assertEquals("Narrator", turnsBook[0].speaker)
        assertEquals("قرأت كتاب «الأغاني» للأصفهاني.", turnsBook[0].text)

        // Nickname without inquit should remain narrator voice
        val textNickname = "كان الصحابي يلقب بـ «الفاروق» رضي الله عنه."
        val turnsNickname = annotator.annotateText(textNickname)
        assertEquals(1, turnsNickname.size)
        assertEquals("Narrator", turnsNickname[0].speaker)
        assertTrue(turnsNickname[0].text.contains("«الفاروق»"))
    }

    @Test
    fun testArabicPrefixedInquitVerbsAttributeCharacterTurns() {
        // Prefixed inquit verb فقال
        val textFaQala = "«نعم» فقال أحمد مبتسماً."
        val turnsFaQala = annotator.annotateText(textFaQala)
        assertEquals(2, turnsFaQala.size)
        assertEquals("Character", turnsFaQala[0].speaker)
        assertEquals("نعم", turnsFaQala[0].text)
        assertEquals("cheerful, warm smiling and joyful tone", turnsFaQala[0].stylePrompt)
        assertEquals("Narrator", turnsFaQala[1].speaker)
        assertEquals("فقال أحمد مبتسماً.", turnsFaQala[1].text)

        // Hal participle قائلاً
        val textQailan = "«حسناً» قائلاً وهو يغادر القاعة."
        val turnsQailan = annotator.annotateText(textQailan)
        assertEquals(2, turnsQailan.size)
        assertEquals("Character", turnsQailan[0].speaker)
        assertEquals("حسناً", turnsQailan[0].text)
        assertEquals("Narrator", turnsQailan[1].speaker)
        assertEquals("قائلاً وهو يغادر القاعة.", turnsQailan[1].text)

        // Prefixed وأردف with calm emotion
        val textArdafa = "«سأعود غداً» وأردف بهدوء."
        val turnsArdafa = annotator.annotateText(textArdafa)
        assertEquals(2, turnsArdafa.size)
        assertEquals("Character", turnsArdafa[0].speaker)
        assertEquals("سأعود غداً", turnsArdafa[0].text)
        assertEquals("calm, composed, steady and reassuring tone", turnsArdafa[0].stylePrompt)
        assertEquals("Narrator", turnsArdafa[1].speaker)
        assertEquals("وأردف بهدوء.", turnsArdafa[1].text)

        // Prefixed فسأل
        val textFaSaala = "«أين الطريق؟» فسأل المسافر."
        val turnsFaSaala = annotator.annotateText(textFaSaala)
        assertEquals(2, turnsFaSaala.size)
        assertEquals("Character", turnsFaSaala[0].speaker)
        assertEquals("أين الطريق؟", turnsFaSaala[0].text)
        assertEquals("Narrator", turnsFaSaala[1].speaker)
        assertEquals("فسأل المسافر.", turnsFaSaala[1].text)
    }

    @Test
    fun testDashedDialogueLinesParsing() {
        val text = """
            — أين وضعت المفاتيح؟ — سأل أحمد بهدوء
            — إنها هنا على الطاولة.
        """.trimIndent()
        val turns = annotator.annotateText(text)

        assertEquals(3, turns.size)
        assertEquals("Character", turns[0].speaker)
        assertEquals("أين وضعت المفاتيح؟", turns[0].text)
        assertEquals("calm, composed, steady and reassuring tone", turns[0].stylePrompt)

        assertEquals("Narrator", turns[1].speaker)
        assertEquals("سأل أحمد بهدوء", turns[1].text)

        assertEquals("Character", turns[2].speaker)
        assertEquals("إنها هنا على الطاولة.", turns[2].text)
    }

    @Test
    fun testDashedDialogueInterleavedWithNarrative() {
        val text = """
            دخل القائد الغرفة ونظر إلى جنوده.
            — هل أنتم مستعدون للمعركة؟
            صاح أحدهم بحماس:
            — نحن جاهزون دائماً!
        """.trimIndent()
        val turns = annotator.annotateText(text)

        assertEquals(4, turns.size)
        assertEquals("Narrator", turns[0].speaker)
        assertTrue(turns[0].text.contains("دخل القائد"))

        assertEquals("Character", turns[1].speaker)
        assertEquals("هل أنتم مستعدون للمعركة؟", turns[1].text)

        assertEquals("Narrator", turns[2].speaker)
        assertTrue(turns[2].text.contains("صاح أحدهم"))

        assertEquals("Character", turns[3].speaker)
        assertEquals("نحن جاهزون دائماً!", turns[3].text)
    }

    @Test
    fun testSingleWordConversationalPunctuationBecomesDialogue() {
        val text = "«نعم؟»"
        val turns = annotator.annotateText(text)
        assertEquals(1, turns.size)
        assertEquals("Character", turns[0].speaker)
        assertEquals("نعم؟", turns[0].text)
    }

    @Test
    fun testMultiWordQuoteWithoutInquitBecomesDialogue() {
        val text = "«سنلتقي غداً في الصباح الباكر»"
        val turns = annotator.annotateText(text)
        assertEquals(1, turns.size)
        assertEquals("Character", turns[0].speaker)
        assertEquals("سنلتقي غداً في الصباح الباكر", turns[0].text)
    }

    @Test
    fun testEastAsianBracketsAreAlwaysDialogue() {
        val text = "「こんにちは」"
        val turns = annotator.annotateText(text)
        assertEquals(1, turns.size)
        assertEquals("Character", turns[0].speaker)
        assertEquals("こんにちは", turns[0].text)
    }

    @Test
    fun testInquitSplittingWithLeadingAndTrailingQuotes() {
        val text = "«لا يمكنك الذهاب»، قال أحمد بصوت خافت، «الطقس عاصف جداً»."
        val turns = annotator.annotateText(text)

        assertEquals(3, turns.size)
        assertEquals("Character", turns[0].speaker)
        assertEquals("لا يمكنك الذهاب", turns[0].text)
        assertEquals("whispered urgently, quiet hushed tone", turns[0].stylePrompt)

        assertEquals("Narrator", turns[1].speaker)
        assertTrue(turns[1].text.contains("قال أحمد"))

        assertEquals("Character", turns[2].speaker)
        assertEquals("الطقس عاصف جداً", turns[2].text)
        assertEquals("whispered urgently, quiet hushed tone", turns[2].stylePrompt)
    }

    @Test
    fun testSummarizeText() {
        val dialogueText = "قال أحمد: «مرحباً بكم جميعاً» ثم انصرف."
        val summary = annotator.summarizeText(dialogueText)
        assertTrue(summary.contains("حوار ثنائي"))

        val narrationText = "هذا نص سردي خالص بدون أي حوار أو شخصيات."
        val summaryNarr = annotator.summarizeText(narrationText)
        assertTrue(summaryNarr.contains("نص فردي"))
    }
}
