# Goldfish Annotated Review Report

**Target:** `/data/data/com.termux/files/home/gemini_audiobook_tts/docs/superpowers/plans/2026-11-04-multi-key-quota-and-dialogue-enhancements.md` (`full file`)

## Prioritized Findings & Resolution Summary

### [Issue 1] [egm-zoom-out / egm-design] - Severity: Blocker
* **Affected Scope:** `KeyQuotaManager.kt` (`getNextAvailableKey`)
* **Discrepancy Description:** No-wrap index search bug. Rotating from the last index terminated at `apiKeys.size` without wrapping to index 0, falsely reporting all keys exhausted.
* **Resolution Category:** **PROPOSE FIX** (Applied & Verified in commit `ae1770d`)
* **Action Taken:** Replaced linear slicing with modulo circular indexing: `for (i in 1 until apiKeys.size) { val idx = (currentIndex + i) % apiKeys.size; ... }`.

### [Issue 2] [egm-design] - Severity: Blocker
* **Affected Scope:** `KeyQuotaManager.kt` (`record429Exhaustion`)
* **Discrepancy Description:** Transient 429 bursts without explicit `retryDelay` defaulted to 24-hour Pacific Midnight lockout instead of short backoff.
* **Resolution Category:** **PROPOSE FIX** (Applied & Verified in commit `ae1770d`)
* **Action Taken:** Differentiated between transient RPM bursts (defaults to 60 seconds) and confirmed daily quota exhaustion (`RESOURCE_EXHAUSTED` / `quota`), locking to Pacific midnight only on the latter. Removed artificial client-side `MODEL_DAILY_CAPS = 100` to support paid accounts.

### [Issue 3] [egm-codebase-details] - Severity: Blocker
* **Affected Scope:** `MarkdownStripper.kt` (`extractChapters`)
* **Discrepancy Description:** Markdown chapters omitted chapter titles from spoken text on Android, violating Review Focus #2.
* **Resolution Category:** **PROPOSE FIX** (Applied & Verified in commit `62dc274`)
* **Action Taken:** Prepend `$title. <short pause>\n\n$cleanedBody` to `spokenText` in `MarkdownStripper.kt`, establishing exact parity with plain-text chapters and Python desktop engine.

### [Issue 4] [egm-design / egm-zoom-out] - Severity: Blocker
* **Affected Scope:** `BookParser.kt` (`extractDocxText`)
* **Discrepancy Description:** DOM-based parsing of `word/document.xml` caused high memory usage and Out-Of-Memory (OOM) risks on large books, while collapsing inter-word spaces.
* **Resolution Category:** **PROPOSE FIX** (Applied & Verified in commit `62dc274`)
* **Action Taken:** Replaced DOM builder with $O(1)$ memory streaming `XmlPullParser` handling `xml:space="preserve"`, `<w:p>`, `<w:br/>`, `<w:tab/>`, and `<w:t>`, strictly guarding against binary ZIP reading.

### [Issue 5] [egm-codebase-details / egm-design] - Severity: Major
* **Affected Scope:** `DialogueTurnAnnotator.kt` (`quoteRegex`, `DIALOGUE_VERBS`)
* **Discrepancy Description:** Generic negated quote classes caused collision and truncation in nested quotes; `DIALOGUE_VERBS` was dead code, classifying single quoted book titles or terms as character dialogue.
* **Resolution Category:** **PROPOSE FIX** (Applied & Verified in commit `a8d23f0`)
* **Action Taken:** Switched to paired quotation regex matching, activated `isDialogueQuote` to retain single-word terms in narrator voice, expanded Arabic inquit verb morphology (`فقال`, `قائلاً`, `متسائلاً`), and added dashed novel dialogue support.

---

## Final Status: ALL FINDINGS RESOLVED (0 Blockers, 0 Open Deficiencies)
All approved repairs have been integrated, verified by tests, and committed to git branch `main`.
