# Gemini Audiobook TTS v1.5.3 Release Notes

## New Features & Enhancements

### 1. Active Round-Robin Key Rotation & Strict Per-Key 60s Cycle
- **Eliminated Engine Stall**: Removed the blanket 60-second delay in `AudiobookEngine.kt` that was previously stalling conversion across all keys.
- **Round-Robin Multi-Key Utilization**: When multiple API keys are provided, each new chunk rotates sequentially across available keys with zero delay between ready keys.
- **Strict Per-Key 60s Window Tracking**: The 60-second cooldown is tracked per key starting from request dispatch, guaranteeing zero 429 quota exhaustion hits while maximizing synthesis throughput.

### 2. Full Bilingual Localization (Arabic & English)
- **Multi-Language UI**: Added complete support for both Arabic (`values-ar/strings.xml`) and English (`values/strings.xml`).
- **In-App Language Selector**: Added a language selection button in the Settings tab (العربية / English / System Default).
- **Accessibility Invariant**: Screen reader live announcements (TalkBack & Jieshuo) and button descriptions adapt dynamically to the selected language.

### 3. Build & Parity Details
- Android Version Code: `30`
- Android Version Name: `1.5.3`
- Target SDK: `34` (Android 14)
- Automated signed APK delivery via GitHub Releases
