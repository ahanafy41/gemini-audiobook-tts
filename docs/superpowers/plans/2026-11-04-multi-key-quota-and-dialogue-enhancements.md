# Multi-Key Quota Management, Dialogue Engine & Desktop Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Farid's complete Desktop suite (PR #1) into the repository and port its high-impact innovations—unlimited multi-key quota management, automatic 429 rotation with Pacific midnight reset, inquit dialogue splitting, emotion inference, chapter title vocalization, and .docx/CUE/M3U export—into the Android application.

**Architecture:** The project maintains a dual-wing architecture: a cross-platform Python CLI/Desktop GUI suite in `desktop/` and root Python modules for PC/NVDA, and a native Kotlin/Android app in `android/` for TalkBack and Jieshuo. A new Android domain module `KeyQuotaManager.kt` persists quota states in encrypted/internal app storage (`key_quotas.json`), `GeminiTtsClient.kt` rotates across unlimited keys, `BookParser.kt` extracts .docx and vocalizes chapter titles, `DialogueTurnAnnotator.kt` splits inquit narrative clauses and infers emotions, and `AudioExporter.kt` generates CUE sheets and M3U playlists.

**Tech Stack:** Kotlin (Android SDK 26+, Coroutines, OkHttp3, AndroidX), Python 3.10+ (wxPython, unittest), Gradle (Kotlin DSL), Git.

**Spec:** System design and comparison findings documented in discussion transcript, PR #1 (`farid5006/gemini-audiobook-tts:feat/desktop-app-and-quota-manager`), and Android repository specifications in `project_spec.json`.

## Global Constraints

- **No Broken Builds:** Android build (`./gradlew testDebugUnitTest` and `./gradlew assembleRelease`) must pass 100% on every commit.
- **Accessibility Invariants:** All UI elements in Android and Desktop must provide explicit content descriptions (`android:contentDescription`, `wx.Window.SetName`) for screen readers (TalkBack, Jieshuo, NVDA).
- **Privacy & Secret Protection:** Zero raw API keys committed or logged in plaintext; key IDs are SHA-256 16-character hashes; masked previews only (`AIzaSy...abcd`).
- **No Heavy Dependencies:** .docx parsing on Android must use standard `java.util.zip.ZipInputStream` and XML parsing, avoiding heavy third-party POI libraries.

## Review Focus

1. **429 Rate Limit Burst vs Daily Cap:** Temporary per-minute rate limit (RPM with short retryDelay e.g., 30s) must NOT lock a key until Pacific Midnight if Google only requested a brief backoff; only daily quota exhaustion locks until midnight.
2. **Missing Chapter Title in Audio:** Chapters with non-empty text must prepend the chapter title and `<short pause>` so listeners hear the chapter heading.
3. **Empty or Whitespace-only Keys:** Blank lines or malformed strings pasted into the multi-key list must be filtered out gracefully without causing index errors.
4. **All Keys Exhausted Scenario:** When every key is exhausted, the engine must not crash or loop infinitely; it must raise a clean `QuotaExhaustedException` reporting the exact minutes until the earliest key resets.
5. **Arabic Inquit Sentence Reassembly:** Inquit clauses like `«نعم»، قال بهدوء، «أنا مستعد»` must retain sentence order and assign dialogue to `character` and narrative verb to `narrator` without dropping punctuation.

---

### Task 1: Merge PR #1 (Farid's Desktop Suite & Python Core Engine)

**Files:**
- Modify: `.git` (Merge remote branch `pr-1-farid` into `main`)
- Verify: `test_engine.py`

**Interfaces:**
- Produces: `desktop/` suite, `key_quota_manager.py`, `gemini_tts_client.py`, `book_parser.py`, `smart_chunker.py` in the root repository.

- [ ] **Step 1: Verify PR #1 clean merge status**
Run: `git merge-base main pr-1-farid`
Expected: Outputs common ancestor without conflict warnings.

- [ ] **Step 2: Merge branch `pr-1-farid` into `main`**
Run: `git merge pr-1-farid -m "feat: merge PR #1 desktop GUI suite and universal multi-speaker TTS engine"`

- [ ] **Step 3: Fix Shebang line order in `test_engine.py`**
Place `#!/usr/bin/env python3` at line 1 before imports.

- [ ] **Step 4: Run Python test suite**
Run: `python3 -m unittest test_engine.py`
Expected: `Ran 28 tests ... OK`

- [ ] **Step 5: Commit clean merge**
```bash
git add test_engine.py
git commit --amend -m "feat: merge PR #1 desktop GUI suite and universal multi-speaker TTS engine"
```

---

### Task 2: Build `KeyQuotaManager.kt` for Android

**Files:**
- Create: `android/app/src/main/java/com/antigravity/audiobook/data/KeyQuotaManager.kt`
- Create: `android/app/src/test/java/com/antigravity/audiobook/data/KeyQuotaManagerTest.kt`

**Interfaces:**
- Produces:
  ```kotlin
  class KeyQuotaManager(private val storageDir: File) {
      fun computeKeyId(apiKey: String): String
      fun maskKey(apiKey: String): String
      fun getSecondsUntilPacificMidnight(): Long
      fun parseRetryDelay(errorBody: String): Long?
      fun isKeyAvailable(apiKey: String, modelId: String): Boolean
      fun recordSuccess(apiKey: String, modelId: String)
      fun record429Exhaustion(apiKey: String, modelId: String, retryDelaySeconds: Long?, errorMessage: String): Long
      fun findFirstAvailableKeyIndex(apiKeys: List<String>, modelId: String, preferredIndex: Int = 0): Int
      fun getNextAvailableKey(apiKeys: List<String>, currentIndex: Int, modelId: String): Pair<Int, String?>
      fun getEarliestRenewalTime(apiKeys: List<String>, modelId: String): Pair<Long, String>
  }
  ```

- [ ] **Step 1: Write failing unit tests for KeyQuotaManager in Kotlin**
Test key hashing, masked preview, Pacific midnight calculation, JSON/regex `retryDelay` parsing, and quota auto-renewal after timestamp expiration.

- [ ] **Step 2: Run test to verify it fails**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.data.KeyQuotaManagerTest`
Expected: Compilation failure (class not found).

- [ ] **Step 3: Implement `KeyQuotaManager.kt`**
Implement thread-safe JSON file persistence (`key_quotas.json`), Pacific Timezone calculation via `java.time.ZoneId.of("America/Los_Angeles")`, and Google RetryInfo parsing.

- [ ] **Step 4: Run test to verify it passes**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.data.KeyQuotaManagerTest`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**
```bash
git add android/app/src/main/java/com/antigravity/audiobook/data/KeyQuotaManager.kt android/app/src/test/java/com/antigravity/audiobook/data/KeyQuotaManagerTest.kt
git commit -m "feat(android): add persistent KeyQuotaManager with Pacific midnight reset and 429 retry delay"
```

---

### Task 3: Refactor Android `GeminiTtsClient.kt` for Unlimited Multi-Key Rotation

**Files:**
- Modify: `android/app/src/main/java/com/antigravity/audiobook/data/GeminiTtsClient.kt`
- Modify: `android/app/src/test/java/com/antigravity/audiobook/data/GeminiTtsClientTest.kt`

**Interfaces:**
- Consumes: `KeyQuotaManager` from Task 2.
- Produces:
  ```kotlin
  class GeminiTtsClient(
      private val quotaManager: KeyQuotaManager,
      private var apiKeys: List<String>,
      private val modelId: String = "gemini-3.8-flash-tts"
  ) {
      fun getActiveKey(): String
      fun rotateKey(reason: String): String
      fun setApiKeys(keys: List<String>)
  }
  ```

- [ ] **Step 1: Write failing unit test for multi-key rotation and 429 exhaustion**
Verify that on 429 response, `GeminiTtsClient` calls `quotaManager.record429Exhaustion`, switches to the next available key, and continues synthesis without failing the user.

- [ ] **Step 2: Run test to verify it fails**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.data.GeminiTtsClientTest`
Expected: Compilation failure or assertion failure on single-key API.

- [ ] **Step 3: Implement multi-key rotation and quota integration in `GeminiTtsClient.kt`**
Update network execution loop to handle 429 by extracting `retryDelay`, recording exhaustion in `KeyQuotaManager`, and switching active key.

- [ ] **Step 4: Run tests to verify it passes**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.data.GeminiTtsClientTest`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add android/app/src/main/java/com/antigravity/audiobook/data/GeminiTtsClient.kt android/app/src/test/java/com/antigravity/audiobook/data/GeminiTtsClientTest.kt
git commit -m "feat(android): support unlimited API keys with automatic 429 rotation and quota tracking"
```

---

### Task 4: Fix Chapter Title Vocalization & Expand Patterns in `BookParser.kt`

**Files:**
- Modify: `android/app/src/main/java/com/antigravity/audiobook/domain/BookParser.kt`
- Modify: `android/app/src/test/java/com/antigravity/audiobook/domain/BookParserTest.kt`

**Interfaces:**
- Produces:
  ```kotlin
  class BookParser(private val continuousChapterSize: Int = 7500) {
      fun parseFile(file: File, explicitTitle: String? = null): ParsedBook
      fun parseContent(content: String, title: String = "بدون اسم", filePath: String = ""): ParsedBook
      fun extractDocxText(file: File): String
  }
  ```

- [ ] **Step 1: Write failing unit test for chapter title vocalization and .docx parsing**
Test:
1. `chapter.text` must start with `"${chapter.chapterTitle}. <short pause>\n\n"` when text is present.
2. Numbered chapters like `1. البداية` and keywords `المطلب`, `الكتاب`, `مدخل` are recognized.
3. Sample .docx file text extracted cleanly using `ZipInputStream`.

- [ ] **Step 2: Run test to verify it fails**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.domain.BookParserTest`
Expected: FAIL on missing title prefix and missing .docx parser.

- [ ] **Step 3: Implement title vocalization, expanded regex patterns, and zero-dependency .docx extractor**
In `BookParser.kt`:
1. Prepend `"${title_clean}. <short pause>\n\n$cleanBody"` to spoken text.
2. Add regex patterns for `المطلب`, `الكتاب`, `مدخل`, `الخاتمة`, and `^[0-9]+[.:–—\-]`.
3. Implement `extractDocxText` using `ZipInputStream` to read `word/document.xml`.

- [ ] **Step 4: Run test to verify it passes**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.domain.BookParserTest`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add android/app/src/main/java/com/antigravity/audiobook/domain/BookParser.kt android/app/src/test/java/com/antigravity/audiobook/domain/BookParserTest.kt
git commit -m "fix(android): vocalize chapter titles in speech, expand Arabic patterns, and add docx support"
```

---

### Task 5: Upgrade `DialogueTurnAnnotator.kt` (Inquit Verbs & Emotion Inference)

**Files:**
- Modify: `android/app/src/main/java/com/antigravity/audiobook/domain/DialogueTurnAnnotator.kt`
- Modify: `android/app/src/test/java/com/antigravity/audiobook/domain/DialogueTurnAnnotatorTest.kt`

**Interfaces:**
- Produces:
  ```kotlin
  data class DialogueTurn(
      val speaker: String,
      val text: String,
      val stylePrompt: String = ""
  )
  class DialogueTurnAnnotator(
      private val narratorSpeakerName: String = "Narrator",
      private val characterSpeakerName: String = "Character"
  ) {
      fun annotateText(rawText: String, inferEmotions: Boolean = true): List<DialogueTurn>
  }
  ```

- [ ] **Step 1: Write failing unit test for inquit splitting and emotion style inference**
Test:
1. Dialogue interrupted by inquit verb `«لا يمكنك الذهاب»، قال أحمد بصوت خافت، «الطقس عاصف»` splits into 3 turns: Character -> Narrator -> Character.
2. Emotion cue `بصوت خافت` infers style `whispered urgently, quiet hushed tone`.

- [ ] **Step 2: Run test to verify it fails**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.domain.DialogueTurnAnnotatorTest`
Expected: FAIL.

- [ ] **Step 3: Implement inquit splitting and emotion rules in `DialogueTurnAnnotator.kt`**
Port Farid's multilingual inquit verbs table and narrative emotion regex rules into Kotlin.

- [ ] **Step 4: Run test to verify it passes**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.domain.DialogueTurnAnnotatorTest`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add android/app/src/main/java/com/antigravity/audiobook/domain/DialogueTurnAnnotator.kt android/app/src/test/java/com/antigravity/audiobook/domain/DialogueTurnAnnotatorTest.kt
git commit -m "feat(android): add inquit dialogue splitting and narrative emotion inference to DialogueTurnAnnotator"
```

---

### Task 6: Add CUE Sheet and M3U Playlist Generation in `AudioExporter.kt`

**Files:**
- Modify: `android/app/src/main/java/com/antigravity/audiobook/util/AudioExporter.kt`
- Modify: `android/app/src/main/java/com/antigravity/audiobook/engine/AudiobookEngine.kt`
- Create: `android/app/src/test/java/com/antigravity/audiobook/util/AudioExporterTest.kt`

**Interfaces:**
- Produces:
  ```kotlin
  object AudioExporter {
      fun generateCueSheet(bookTitle: String, chapters: List<ChapterAudioMeta>, unifiedWavFileName: String): String
      fun generateM3uPlaylist(bookTitle: String, chapters: List<ChapterAudioMeta>): String
  }
  ```

- [ ] **Step 1: Write failing unit test for CUE and M3U generation**
Verify CUE sheet tracks timing (INDEX 01 mm:ss:ff) and M3U tags (`#EXTM3U`, `#EXTINF`).

- [ ] **Step 2: Run test to verify it fails**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.util.AudioExporterTest`
Expected: FAIL.

- [ ] **Step 3: Implement CUE and M3U exporters in `AudioExporter.kt` and invoke in `AudiobookEngine.kt`**
Generate `playlist.m3u` and `book.cue` alongside `full_book.wav`.

- [ ] **Step 4: Run test to verify it passes**
Run: `./gradlew testDebugUnitTest --tests com.antigravity.audiobook.util.AudioExporterTest`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add android/app/src/main/java/com/antigravity/audiobook/util/AudioExporter.kt android/app/src/main/java/com/antigravity/audiobook/engine/AudiobookEngine.kt android/app/src/test/java/com/antigravity/audiobook/util/AudioExporterTest.kt
git commit -m "feat(android): generate CUE sheet and M3U playlist alongside unified audiobook"
```

---

### Task 7: Accessible Multi-Key Android UI in `MainActivity.kt`

**Files:**
- Modify: `android/app/src/main/res/layout/dialog_settings.xml` (or `activity_main.xml`)
- Modify: `android/app/src/main/java/com/antigravity/audiobook/MainActivity.kt`

**Interfaces:**
- Connects UI events to `KeyQuotaManager` and `GeminiTtsClient`.

- [ ] **Step 1: Update settings layout to multiline API keys field with accessible buttons**
Add Multiline `EditText` for API keys, `btnPasteClipboardKey`, and `btnVerifyKeys` with high contrast and explicit `contentDescription`.

- [ ] **Step 2: Wire `MainActivity.kt` to save multi-key list and announce quota statuses**
Announce live status to TalkBack/Jieshuo: `"تم حفظ X مفاتيح: Y متاح، Z مستنفد"`.

- [ ] **Step 3: Run full Android build & verification**
Run: `./gradlew assembleDebug`
Expected: BUILD SUCCESSFUL.

- [ ] **Step 4: Commit**
```bash
git add android/app/src/main/res/ android/app/src/main/java/com/antigravity/audiobook/MainActivity.kt
git commit -m "feat(android): accessible multi-key settings dialog with clipboard paste and quota reporting"
```
