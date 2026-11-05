package com.antigravity.audiobook.domain

import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.FileOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class BookParserTest {

    @Rule
    @JvmField
    val tempFolder = TemporaryFolder()

    private lateinit var parser: BookParser

    @Before
    fun setUp() {
        parser = BookParser()
    }

    private fun createSampleDocx(file: File, documentXmlContent: String) {
        ZipOutputStream(FileOutputStream(file)).use { zos ->
            val entry = ZipEntry("word/document.xml")
            zos.putNextEntry(entry)
            val bytes = documentXmlContent.toByteArray(Charsets.UTF_8)
            zos.write(bytes, 0, bytes.size)
            zos.closeEntry()
        }
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

    @Test
    fun testMarkdownChapterParsingIncludesTitleAndShortPause() {
        val markdown = """
            # الفصل الأول: بداية الرحلة
            انطلقت السفينة في عرض البحر الهادئ.
            
            ## الفصل الثاني: العاصفة
            وفجأة تلبدت السماء بالغيوم السوداء.
            
            # الفصل الثالث: الجزيرة المهجورة
            
            # الفصل الرابع: شاطئ الأمان
            وصل الناجون أخيراً بعد رحلة شاقة.
        """.trimIndent()

        val parsed = parser.parseContent(markdown, "رواية المغامرة")
        assertEquals(4, parsed.chapters.size)

        val ch1 = parsed.chapters[0]
        assertEquals("الفصل الأول: بداية الرحلة", ch1.chapterTitle)
        assertTrue(
            "Markdown Chapter 1 must prepend title and short pause",
            ch1.text.startsWith("الفصل الأول: بداية الرحلة. <short pause>\n\n")
        )
        assertTrue(ch1.text.contains("انطلقت السفينة في عرض البحر الهادئ."))

        val ch2 = parsed.chapters[1]
        assertEquals("الفصل الثاني: العاصفة", ch2.chapterTitle)
        assertTrue(
            "Markdown Chapter 2 must prepend title and short pause",
            ch2.text.startsWith("الفصل الثاني: العاصفة. <short pause>\n\n")
        )
        assertTrue(ch2.text.contains("وفجأة تلبدت السماء بالغيوم السوداء."))

        // Chapter 3 has empty body -> text should just be title without pause suffix
        val ch3 = parsed.chapters[2]
        assertEquals("الفصل الثالث: الجزيرة المهجورة", ch3.chapterTitle)
        assertEquals("الفصل الثالث: الجزيرة المهجورة", ch3.text)

        val ch4 = parsed.chapters[3]
        assertEquals("الفصل الرابع: شاطئ الأمان", ch4.chapterTitle)
        assertTrue(
            "Markdown Chapter 4 must prepend title and short pause",
            ch4.text.startsWith("الفصل الرابع: شاطئ الأمان. <short pause>\n\n")
        )
        assertTrue(ch4.text.contains("وصل الناجون أخيراً بعد رحلة شاقة."))
    }

    @Test
    fun testDocxStreamingParserPreservesSpacesAndExtractsParagraphs() {
        val docxFile = tempFolder.newFile("sample_book.docx")
        val xmlContent = """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:body>
                    <w:p>
                        <w:r><w:t>المقدمة العامة للكتاب</w:t></w:r>
                    </w:p>
                    <w:p>
                        <w:r><w:t>الجزء الأول من الجملة</w:t></w:r>
                        <w:r><w:t xml:space="preserve"> مع الحفاظ الكامل على المسافات </w:t></w:r>
                        <w:r><w:t>والجزء الثاني.</w:t></w:r>
                        <w:br/>
                        <w:r><w:t>وهذا سطر جديد بعد فاصل أسطر.</w:t></w:r>
                        <w:tab/>
                        <w:r><w:t>وهنا نص بعد علامة الجدولة.</w:t></w:r>
                    </w:p>
                    <w:p>
                        <w:pPr>
                            <w:pStyle w:val="Heading1"/>
                        </w:pPr>
                        <w:r><w:t>الفصل الأول: تاريخ الحضارات</w:t></w:r>
                    </w:p>
                    <w:p>
                        <w:r><w:t>شهدت العصور القديمة ازدهاراً منقطع النظير.</w:t></w:r>
                    </w:p>
                </w:body>
            </w:document>
        """.trimIndent()

        createSampleDocx(docxFile, xmlContent)

        val extracted = parser.extractDocxText(docxFile)
        assertTrue("Extracted text must contain intro paragraph", extracted.contains("المقدمة العامة للكتاب"))
        assertTrue("Must preserve whitespace when xml:space=preserve", extracted.contains("الجزء الأول من الجملة مع الحفاظ الكامل على المسافات والجزء الثاني."))
        assertTrue("Must handle <w:br/> as line break", extracted.contains("والجزء الثاني.\nوهذا سطر جديد بعد فاصل أسطر."))
        assertTrue("Must handle <w:tab/> as space/tab", extracted.contains("وهذا سطر جديد بعد فاصل أسطر. وهنا نص بعد علامة الجدولة."))
        assertTrue("Heading style should be detected with prefix", extracted.contains("# الفصل الأول: تاريخ الحضارات"))
        assertTrue("Following paragraph should be present", extracted.contains("شهدت العصور القديمة ازدهاراً منقطع النظير."))

        val parsedBook = parser.parseFile(docxFile, "كتاب الحضارات")
        assertTrue(parsedBook.chapters.isNotEmpty())
        assertEquals("كتاب الحضارات", parsedBook.title)
    }

    @Test
    fun testDocxCorruptedOrEmptyThrowsExceptionAndNeverReadsBinary() {
        // 1. Corrupted binary file (invalid zip bytes)
        val corruptedFile = tempFolder.newFile("corrupted.docx")
        corruptedFile.writeBytes(byteArrayOf(0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x08, 0x00, 0xFF.toByte(), 0xEE.toByte(), 0x00, 0x12))

        try {
            parser.readFileSafe(corruptedFile)
            fail("readFileSafe must throw IllegalArgumentException on corrupted docx rather than reading binary bytes")
        } catch (e: IllegalArgumentException) {
            assertTrue("Exception message should indicate docx error", e.message?.contains("وورد") == true || e.message?.contains("docx") == true)
        }

        // 2. Valid zip but missing word/document.xml
        val missingDocXml = tempFolder.newFile("missing_entry.docx")
        ZipOutputStream(FileOutputStream(missingDocXml)).use { zos ->
            val entry = ZipEntry("unrelated.txt")
            zos.putNextEntry(entry)
            zos.write("Some unrelated file".toByteArray(Charsets.UTF_8))
            zos.closeEntry()
        }

        try {
            parser.readFileSafe(missingDocXml)
            fail("readFileSafe must throw IllegalArgumentException when word/document.xml is missing")
        } catch (e: IllegalArgumentException) {
            assertTrue("Exception message should indicate docx missing entry", e.message?.contains("word/document.xml") == true || e.message?.contains("docx") == true)
        }

        // 3. Valid docx archive with empty body
        val emptyDocx = tempFolder.newFile("empty_body.docx")
        createSampleDocx(emptyDocx, """
            <?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:body>
                </w:body>
            </w:document>
        """.trimIndent())

        try {
            parser.readFileSafe(emptyDocx)
            fail("readFileSafe must throw IllegalArgumentException when docx has no readable text")
        } catch (e: IllegalArgumentException) {
            assertTrue("Exception message should indicate empty docx", e.message?.contains("فارغ") == true)
        }
    }
}
