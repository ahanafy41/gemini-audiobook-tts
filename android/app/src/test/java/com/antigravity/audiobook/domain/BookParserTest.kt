package com.antigravity.audiobook.domain

import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class BookParserTest {

    private lateinit var parser: BookParser

    @Before
    fun setUp() {
        parser = BookParser()
    }

    @Test
    fun testSpokenChapterTitlePrepend() {
        val content = """
            الفصل الأول: فجر التاريخ
            كانت الأيام الأولى مفعمة بالنشاط والعمل.
            
            الفصل الثاني: بناء الأهرامات
            استمر البناء سنوات طويلة وشهد إنجازات حضارية عظمى.
        """.trimIndent()

        val parsed = parser.parseContent(content, "تاريخ مصر")
        assertEquals(2, parsed.chapters.size)

        val ch1 = parsed.chapters[0]
        assertTrue("Chapter 1 text should begin with title and short pause", ch1.text.startsWith("الفصل الأول: فجر التاريخ. <short pause>\n\n"))
        assertTrue("Chapter 1 text should contain body", ch1.text.contains("كانت الأيام الأولى"))

        val ch2 = parsed.chapters[1]
        assertTrue("Chapter 2 text should begin with title and short pause", ch2.text.startsWith("الفصل الثاني: بناء الأهرامات. <short pause>\n\n"))
    }

    @Test
    fun testExpandedChapterPatterns() {
        val content = """
            المبحث الأول: الإطار النظري
            هنا يبدأ المبحث الأول.
            
            المطلب الثاني: الدراسات السابقة
            هنا تفاصيل المطلب الثاني.
            
            1. النتائج والتوصيات
            هنا الفصل المرقم بالأرقام.
        """.trimIndent()

        val parsed = parser.parseContent(content, "بحث علمي")
        assertEquals(3, parsed.chapters.size)
        assertTrue(parsed.chapters[0].chapterTitle.contains("المبحث الأول"))
        assertTrue(parsed.chapters[1].chapterTitle.contains("المطلب الثاني"))
        assertTrue(parsed.chapters[2].chapterTitle.contains("1. النتائج"))
    }
}
