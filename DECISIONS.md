# Engineering Decisions Log (DECISIONS.md)

## ADR-001: Per-Key 60s Cycle Pacing and Active Round-Robin Rotation

### Context
In version 1.5.2, a global blanket 60-second delay was added to `AudiobookEngine.kt` between every chunk. While this prevented 429 errors on a single free-tier key (which has a 1 RPM limit), it crippled multi-key performance: converting with 5 API keys still took 60 seconds per chunk because the entire engine stalled for a minute after every request, ignoring other ready keys.

### Decision
1. **Decouple Engine Pacing from Key Rate Limits**:
   - Remove the blanket 60s pause from `AudiobookEngine.kt`.
   - Maintain a lightweight 1-second pacing delay between chunks for system breathing and GC.
2. **Strict Per-Key 60s Window Tracking**:
   - In `GeminiTtsClient.kt`, record the start timestamp of each request for the specific API key used: `keyLastRequestTime[key] = System.currentTimeMillis()`.
   - When a key is selected for synthesis, enforce pacing: if fewer than 60 seconds have elapsed since its previous request began, wait only the remaining duration for that specific key.
3. **Active Round-Robin Key Rotation**:
   - On each synthesis call, rotate to the next available API key in round-robin sequence.
   - If multiple keys are provided (e.g., 3 keys), each key can execute immediately if its individual 60-second cooldown has elapsed.
   - If all keys are in cooldown, the client selects the key with the shortest remaining wait time and waits only that remainder, guaranteeing zero 429 quota exhaustion.

---

## ADR-002: Android Bilingual Support (Arabic & English Localization)

### Context
The Android application previously had only Arabic string resources in `res/values/strings.xml`, and several UI elements, dialog messages, and TalkBack live region announcements in `MainActivity.kt` were hardcoded in Arabic. Users who use English or want an English UI/TTS experience were unable to switch languages.

### Decision
1. **Resource Segregation**:
   - Move Arabic string definitions to `res/values-ar/strings.xml`.
   - Provide standard English definitions in `res/values/strings.xml` (default Android fallback).
   - Extract hardcoded strings in `MainActivity.kt` into named string resources (`@string/...`).
2. **In-App Language Selection**:
   - Add a language selection preference in the Settings tab (العربية / English / الافتراضي للنظام).
   - Persist user choice in `SharedPreferences`.
   - Apply locale dynamically via `AppCompatDelegate.setApplicationLocales` and `ContextWrapper` configuration to ensure TalkBack/Jieshuo accessibility announcements update immediately.
