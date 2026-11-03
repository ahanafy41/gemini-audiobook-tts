# Gemini Audiobook TTS

[![Platform](https://img.shields.io/badge/Platform-Android%208.0%2B-green.svg)](https://android.com)
[![Language](https://img.shields.io/badge/Language-Kotlin%20100%25-purple.svg)](https://kotlinlang.org)
[![API Level](https://img.shields.io/badge/Target%20SDK-34%20(Android%2014)-blue.svg)](https://developer.android.com)
[![Accessibility](https://img.shields.io/badge/Accessibility-TalkBack%20%26%20Jieshuo%20(CSR)-orange.svg)](#accessibility--screen-reader-first-design)
[![Latest Release](https://img.shields.io/badge/Release-v1.2.1-success.svg)](https://github.com/ahanafy41/gemini-audiobook-tts/releases)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

A high-performance, standalone native Android application that converts plain text documents (`.txt`), Markdown files (`.md`), and digital books into studio-grade audiobooks segmented into chapters. Powered by Google's state-of-the-art **Gemini 3.8 Flash TTS** neural engine, and engineered from the ground up with a strict **Screen Reader First** accessibility architecture for visually impaired and blind users.

---

## 🚀 Key Highlights

- **100% Standalone Native Android**: Built in Kotlin with Jetpack components and OkHttp. Zero third-party dependencies, zero terminal requirements, no background daemon setups. Install the APK and start listening immediately.
- **Screen Reader First (TalkBack & Jieshuo / CSR)**: Fully accessible UI complying with WCAG 2.2 Level AAA standards, featuring large touch targets, live auditory announcements, and automatic **Audio Focus Ducking** during playback.
- **Gemini 3.8 Flash Neural Speech**: Direct integration with Google's latest multimodal speech models (`gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts`).
- **30 Prebuilt Voices & 4 Narrative Styles**: Select from 30 astronomical and mythological voices with customizable delivery styles (Documentary, Dramatic, Broadcast, Natural).
- **Multi-Speaker Dialogue Engine**: Native parsing for scripts and podcast formats (`Speaker1: / Speaker2:` or `Narrator: / Character:`) compatible with Google AI Studio, as well as classic quotation marks (`«...»` and `"..."`).
- **Human Voice Replication**: In-app vocal sampling (10–30s) and mandatory consent voice verification to clone and apply real voices to your books.
- **AI Voice Design**: Describe any custom vocal persona in natural language to generate unique acoustic identities.
- **Quick "Paste & Convert"**: Instant one-tap conversion of clipboard text into accessible audio tracks with live character counting.
- **Background Player with Media3 / ExoPlayer**: Foreground playback service with lock screen controls, playback speed adjustment, and position tracking.
- **Export & Share**: Automatically exports synthesized chapters to the public `Download/Audiobooks/` directory and supports one-tap file sharing.
- **Seamless In-App OTA Updates**: Built-in update checker that downloads and installs new releases directly from GitHub Releases with a permanent signing keystore.

---

## ♿ Accessibility & Screen Reader First Design

Gemini Audiobook TTS was architected specifically with blind and visually impaired users in mind, rigorously tested with **Google TalkBack** and the **Jieshuo (Commentary Screen Reader / CSR)** Chinese screen reader:

1. **Intelligent Audio Focus Ducking**:
   - The application manages Android's `AudioFocusRequest`. When a screen reader speaks or an accessibility gesture is triggered, the audiobook automatically ducks (lowers volume to 20%) or pauses, ensuring screen reader feedback is never muffled or drowned out.
2. **Concise Spoken Labels & Zero Clutter**:
   - All UI buttons, sliders, and navigation tabs are labeled with clear, functional descriptions. Visual-only decorations, redundant prefixes, and bracketed English acronyms were eliminated to keep spoken verbosity minimal.
3. **Live Region Auditory Feedback (`accessibilityLiveRegion`)**:
   - Real-time synthesis progress, chapter transitions, character counts, and network statuses are broadcast instantly to the screen reader without requiring manual swiping or screen exploration.
4. **Accessible Touch Targets**:
   - Every interactive element exceeds the minimum 48dp accessibility guideline, ensuring effortless gesture navigation and touch targeting.
5. **Strict File Picker Filtering**:
   - File choosers enforce strict MIME-type and extension filtering (`.txt` and `.md`), preventing accidental selection of unsupported formats, with immediate auditory error announcements if an invalid file is selected.

---

## 📥 Download & Installation

You can download the pre-compiled, digitally signed release APK directly from GitHub:

- **Download APK**: [Latest Release (v1.2.1)](https://github.com/ahanafy41/gemini-audiobook-tts/releases/latest)
- **Minimum Requirements**: Android 8.0 (API level 26) or higher.
- **Architecture**: Universal APK (`arm64-v8a`, `armeabi-v7a`, `x86_64`).
- **API Key**: Requires a free or paid Google Gemini API key from [Google AI Studio](https://aistudio.google.com/).

---

## 🛠️ How It Works (App Architecture)

The app is built upon clean architecture principles in pure Kotlin:

```text
android/app/src/main/java/com/antigravity/audiobook/
├── MainActivity.kt               # Material 3 Bottom Navigation UI (Library, Player, Studio, Settings)
├── data/
│   ├── GeminiTtsClient.kt        # Direct OkHttp client for Gemini 3.8 Flash TTS REST API
│   └── LocalTtsEngine.kt         # Fallback engine & voice management
├── domain/
│   ├── BookParser.kt             # Automated chapter heading detector (Arabic & English patterns)
│   ├── MarkdownStripper.kt       # Cleans Markdown syntax and unpronounceable formatting tokens
│   ├── SmartTextChunker.kt       # Context-aware text segmentation (up to 8,000 chars per chunk)
│   ├── DialogueTurnAnnotator.kt  # Turns script dialogues into Google multi-speaker JSON payloads
│   ├── MultiSpeakerConfig.kt     # Multi-speaker assignment (Narrator vs Characters)
│   ├── VoiceProfile.kt           # Roster of 30 official Google prebuilt neural voices
│   └── VoiceStylePreset.kt       # Delivery styles (Documentary, Dramatic, Radio, Natural)
├── engine/
│   └── AudiobookEngine.kt        # Orchestrates parsing, synthesis, caching, and progress tracking
├── player/
│   └── AudiobookPlayerService.kt # Media3 / ExoPlayer background service with Audio Focus Ducking
└── util/
    ├── AudioExporter.kt          # Automatic export to Android Download/Audiobooks directory
    └── AudioRecorderHelper.kt    # In-app PCM/WAV recorder for voice replication & consent
```

### Synthesis Pipeline

1. **Ingestion & Chapter Extraction**: The input `.txt` or `.md` file is parsed by `BookParser` and `MarkdownStripper` to identify structural headings (`#`, `##`, `الفصل`, `الباب`, `Chapter`).
2. **Context-Aware Chunking**: `SmartTextChunker` divides long chapters into phonetic segments (up to 7,500 characters) preserving sentence boundaries and punctuation.
3. **Neural Synthesis**: `GeminiTtsClient` transmits structured requests containing voice parameters, style directors, and multi-speaker annotations to Google's endpoints via OkHttp.
4. **WAV Assembly**: Returned linear PCM audio (24,000 Hz, 16-bit mono) is augmented with standard 44-byte RIFF headers in-memory via `ByteBuffer`.
5. **Atomic Saving & Export**: Audio files are saved atomically to app storage and automatically mirrored to `Download/Audiobooks/<Book_Title>/`.
6. **Playback & Tracking**: `AudiobookPlayerService` queues chapters in a playlist, preserving position and chapter bookmarks across sessions.

---

## 📖 User Guide

### 1. Initial Setup
1. Launch the app and navigate to the **Settings** tab.
2. Enter your Google Gemini API Key.
3. Choose your default model (`gemini-3.8-flash-tts` recommended for maximum fidelity, or `gemini-3.8-flash-lite-tts` for high volume).

### 2. Converting a Book
1. Open the **Library** tab.
2. Tap **Select File** and pick any `.txt` or `.md` book on your device.
3. Tap **Start Conversion**. You will hear live voice progress updates.
4. Once completed, your audiobook appears in the Library, ready for immediate listening or sharing.

### 3. Converting Copied Text (Paste & Convert)
1. In the **Library** tab, tap **Paste Text**.
2. Tap **Paste from Clipboard** to automatically fetch your copied text.
3. The app will announce character count and whether the text is single-narrator or a dialogue script.
4. Tap **Convert**. The audio will generate and start playing instantly.

### 4. Multi-Speaker Stories & Scripts
1. Format your text as a dialogue script:
   ```text
   Narrator: The morning sun broke through the heavy clouds.
   Character: We must leave before the storm returns!
   Narrator: She replied with determination in her eyes.
   ```
   *(Arabic script names like `الراوي:` and `البطل:` or quotes `«...»` / `"..."` are also supported).*
2. In **Voice Studio**, enable **Multi-Speaker Dialogue**.
3. Choose a voice for the Narrator and a distinct voice for the Characters.
4. Convert as normal—the engine will synthesize both voices seamlessly in one audio stream.

### 5. Cloning a Human Voice (Voice Replication)
1. In **Voice Studio**, tap **Replicate Voice**.
2. Record or pick a 10–30 second clean sample of the speaker's voice.
3. Read and record the mandatory consent affirmation prompt displayed on screen.
4. Tap **Submit Replication**. Your newly replicated voice will appear in your voice list tagged with `[Replicated]` and can be assigned as narrator or character.

---

## 🏗️ Building from Source

To compile the Android app locally:

### Prerequisites
- Android Studio Hedgehog (2023.1.1) or newer
- JDK 17
- Android SDK 34 (Build Tools 34.0.0)

### Build Commands
```bash
# Clone the repository
git clone https://github.com/ahanafy41/gemini-audiobook-tts.git
cd gemini-audiobook-tts/android

# Build Debug APK
./gradlew assembleDebug

# Output APK path:
# android/app/build/outputs/apk/debug/app-debug.apk
```

### Automated CI/CD
Every commit pushed to the `main` branch automatically triggers GitHub Actions (`.github/workflows/build_apk.yml`), compiling and signing the APK with the repository's permanent keystore, and creating an automatic release.

## ❓ Frequently Asked Questions (FAQ)

### What is Gemini Audiobook TTS?
Gemini Audiobook TTS is a free, open-source native Android application that converts plain text documents (`.txt`) and Markdown books (`.md`) into chapter-segmented audiobooks using Google's neural speech model, **Gemini 3.8 Flash TTS**.

### Is Gemini Audiobook TTS fully compatible with TalkBack and Jieshuo?
Yes, 100%. The app is engineered from the ground up for blind and visually impaired users. It implements automatic **Audio Focus Ducking** (lowering audiobook volume when TalkBack or Jieshuo speaks), accessible 48dp+ touch targets, and real-time auditory notifications (`accessibilityLiveRegion`).

### How does the Multi-Speaker Dialogue feature work?
The app automatically detects dialogue scripts formatted for Google AI Studio (`Speaker1: / Speaker2:` or `Narrator: / Character:`) as well as classic quotation marks (`«...»` and `"..."`). It routes dialogue turns to separate prebuilt neural voices in a single seamless audio stream.

### Can I replicate my own voice or design unique vocal personas?
Yes! You can record a short 10–30 second audio sample with a vocal consent verification to replicate your voice, or describe any acoustic persona in natural language via the AI Voice Design tool.

### Does listening to generated audiobooks require an active internet connection?
No. Once chapters are synthesized, they are saved locally to your device and mirrored to `Download/Audiobooks/`. You can listen, pause, adjust speed, and navigate chapters completely offline using the built-in Media3 / ExoPlayer service.

### Where can I get a Google Gemini API Key?
You can generate a free API key at [Google AI Studio](https://aistudio.google.com/). The free tier includes access to both `gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts`.

### How do I update to new releases?
The app features built-in Over-The-Air (OTA) updates. Simply navigate to Settings and tap **Check for Updates** to download and install the latest APK directly from GitHub without losing any data.

---

## 📜 Changelog

For a comprehensive historical record of all versions, bug fixes, and feature additions, see [CHANGELOG.md](file:///data/data/com.termux/files/home/gemini_audiobook_tts/CHANGELOG.md).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
