# Gemini Audiobook TTS v1.5.4 Release Notes

## Complete English Localization & Notification Polish

### 1. 100% Bilingual Parity across All UI Components
- **Zero Hardcoded Arabic in Layouts**: Replaced all hardcoded strings in `dialog_paste_text.xml`, `dialog_voice_replication.xml`, `activity_main.xml`, and `item_book.xml` with standard resource identifiers (`@string/...`).
- **Naturalized English Terminology**: Completely overhauled English strings to remove awkward phrasing and ensure clear, professional UI text throughout the application.
- **Dynamic Voice Profiles & Styles**: Voice profiles (`VoiceProfile.kt`) and narration styles (`VoiceStylePreset.kt`) now feature authentic English titles and descriptions alongside Arabic, switching dynamically based on user locale.

### 2. Foreground Service & Notification Localization
- **System Notification Channels**: Localized notification channel names and descriptions in `AudiobookPlayerService.kt`.
- **System Share Sheets & Choosers**: Localized system chooser dialogs in `AudioExporter.kt`.
- **Screen Reader Announcements (TalkBack & Jieshuo)**: All `announceStatus` calls, dialog titles, buttons, and progress announcements fully adhere to the active locale without mixing languages.

### 3. XML Standards & Safety Verification
- **Ampersand XML Entity Escaping**: Fixed all raw ampersands in `res/values/strings.xml` and `res/values-ar/strings.xml` with valid `&amp;` entities.
- **Python Verification Test Suite**: Verified 28/28 tests passing (`python3 test_engine.py`).
- **Permanent Keystore Verification**: Keystore `android/keystore/permanent.keystore` verified and intact through 2054.

### 4. Build & Parity Details
- Android Version Code: `31`
- Android Version Name: `1.5.4`
- Target SDK: `34` (Android 14)
- Release Automation: Triggered via GitHub Actions on main push
