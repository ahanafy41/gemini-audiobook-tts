# Gemini Audiobook TTS v1.5.5 Release Notes

## Complete Desktop Parity, Smart 429 Handling, and Accessible Live Conversion Dialog

### 1. 100% Desktop Parity for Key Quota & 429 Resilience
- **Smart 429 Error Discrimination**: Differentiated between transient RPM bursts (1 request/min rate limit) and genuine daily quota exhaustion (`GenerateRequestsPerDayPerProjectPerModel`, `QuotaFailure`, or `retryDelay > 120s`).
- **65s Cooldown & Same-Key Retry Buffer**: Instead of prematurely locking API keys until Pacific midnight, the client now cools down for 65 seconds with live countdown reporting and retries up to 2 times on the active key.
- **Proactive Sequential Rotation (100 RPD for 3.8 Flash)**: Tracks daily requests and automatically rotates to the next available key upon reaching 100 requests (or daily cap) for seamless, uninterrupted conversions.
- **Pure Request Payload**: Removed `speechMetadata` injection from single-speaker TTS requests, matching Python desktop's pure payload standard to eliminate voice timbre and dialect drift.

### 2. Intelligent Text Normalization & Sizing for Pasted Text
- **OCR and Clipboard Cleanup**: Ported desktop `normalizeUnformattedText` to strip invisible control characters, rejoin mid-sentence broken lines, and preserve complete Arabic diacritics (tashkeel).
- **Model-Adaptive 8,000-Character Chunker**: Aligned `AudiobookEngine` to use 8,000 characters per chunk (with 8,500 maximum boundary) matching `SmartTextChunker` defaults, preventing premature splitting and reducing request volume.
- **Continuous Novel Segmentation**: Automatically sections long pasted texts (e.g. 13,000+ characters) into balanced, speech-ready chapters with meaningful titles.

### 3. Accessible Live Conversion Progress Dialog
- **Live Visual & Screen Reader Progress**: Added `dialog_conversion_progress.xml` featuring real-time chapter, chunk, and active key metrics.
- **Accurate Countdown Timer**: Displays countdown seconds during 60s pacing intervals and 65s 429 cooldowns with `accessibilityLiveRegion="polite"` for TalkBack and Jieshuo.
- **Background & Cancellation Controls**: Allows users to dismiss the dialog and continue conversion in the background or cancel execution at any time.

### 4. Build, Signing & Parity Details
- Android Version Code: `32`
- Android Version Name: `1.5.5`
- Target SDK: `34` (Android 14)
- Permanent Keystore: Signed exclusively with `permanent.keystore` (valid through 2054)
- Automated Release: Deployed automatically via GitHub Actions upon push to main
