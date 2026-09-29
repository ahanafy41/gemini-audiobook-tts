# Gemini API Voice Design & Custom Voices Specification

Comprehensive technical specification and integration guide for **Voice Design** (`type: "prompted"`), custom voice lifecycle management, and speech synthesis using Google Gemini 3.8 TTS models (`gemini-3.8-flash-tts` and `gemini-3.8-flash-lite-tts`).

---

## 1. Architectural Overview

### 1.1 What is Voice Design?
Voice Design allows developers to synthesize unique, consistent vocal personas from natural language descriptions rather than selecting from a static catalog of prebuilt voices or requiring voice cloning recordings.

Gemini supports two distinct custom voice paradigms:
1. **Voice Design (`type: "prompted"`)**: A novel voice is generated purely from a descriptive prompt (casting brief specifying age, accent, gender, timbre, cadence).
2. **Voice Replication (`type: "replicated"`)**: A voice is cloned from reference audio and explicit consent recordings.

### 1.2 Storage and Lifecycle
- **Persistence (`store=true`)**: For `type: "prompted"`, `store` **must be set to `true`**. Submitting `store: false` for prompted voices returns an `INVALID_ARGUMENT` error.
- **Voice Identifier (`id`)**: Successfully stored voices receive a persistent identifier formatted as `voice_<alphanumeric>` (e.g., `voice_42n103zlznqt`).
- **Time-to-Live (TTL)**: Custom voices have an expiration timestamp (`expire_time`) set exactly 1 year from creation.
- **Project Limits**: Google projects support up to 200 stored custom voices (shared between prompted and replicated types).
- **Instant Auditioning**: Creating a prompted voice immediately returns an output-only `sample_audio` object containing base64-encoded WAV audio reading a test sentence in the designed persona.

### 1.3 Supported Models
- **`gemini-3.8-flash-tts`**: High-fidelity, expressive model optimized for studio narration, nuanced acting, audiobook generation, and character roleplay.
- **`gemini-3.8-flash-lite-tts`**: Cost-efficient, low-latency model optimized for high-volume audiobooks, voice agents, and real-time interaction. It fully supports custom voice IDs created by `gemini-3.8-flash-tts`.

---

## 2. REST API Specification

### Base URL
```
https://generativelanguage.googleapis.com/v1beta
```

### Authentication
Authentication is supplied either via query parameter or HTTP header:
- **Query Parameter**: `?key=YOUR_GEMINI_API_KEY`
- **HTTP Header**: `x-goog-api-key: YOUR_GEMINI_API_KEY`

---

### 2.1 Create Custom Voice (Voice Design)
Creates and persists a new custom vocal persona.

- **Method**: `POST`
- **Endpoint**: `/v1beta/voices`
- **Headers**:
  - `Content-Type: application/json`
  - `x-goog-api-key: <API_KEY>`

#### Request Body Schema
```json
{
  "store": true,
  "voice": {
    "model": "gemini-3.8-flash-tts",
    "type": "prompted",
    "display_name": "Egyptian Historian & Storyteller",
    "prompted": {
      "input": "A wise, passionate Egyptian historian in his late 50s with an authentic, warm Cairene accent, speaking with deep knowledge, measured cadence, and captivating storytelling flair."
    }
  }
}
```

#### Field Definitions
- `store` (boolean, required): Must be `true` for prompted voices.
- `voice.model` (string, required): Base model used to generate the voice persona (e.g., `gemini-3.8-flash-tts`).
- `voice.type` (string, required): Must be `"prompted"`.
- `voice.display_name` (string, required): Human-readable label for identification.
- `voice.prompted.input` (string, required): Natural language casting brief describing vocal traits.

#### Response Body Schema (HTTP 200 OK)
```json
{
  "id": "voice_42n103zlznqt",
  "model": "models/gemini-3.8-flash-tts",
  "type": "prompted",
  "expire_time": "2027-09-28T21:54:20.020144453Z",
  "display_name": "Egyptian Historian & Storyteller",
  "prompted": {
    "input": "A wise, passionate Egyptian historian in his late 50s with an authentic, warm Cairene accent, speaking with deep knowledge, measured cadence, and captivating storytelling flair."
  },
  "sample_audio": {
    "mime_type": "audio/wav",
    "data": "UklGRiq0MwBXQVZFZm10IBAAAAABAAEA..."
  },
  "usage": {
    "total_tokens": 2481,
    "total_input_tokens": 220,
    "total_output_tokens": 2261
  }
}
```

---

### 2.2 List Stored Voices
Lists custom or prebuilt voices available to the project.

- **Method**: `GET`
- **Endpoint**: `/v1beta/voices`
- **Query Parameters**:
  - `type` (optional): Filter by voice type (`prompted`, `replicated`, or `prebuilt`).
  - `language_code` (optional): Filter by language (e.g., `ar-EG`, `en-US`).
  - `page_size` (optional): Maximum items to return per page.
  - `page_token` (optional): Pagination token from previous response.

#### Example Request
```
GET /v1beta/voices?type=prompted&key=YOUR_API_KEY
```

#### Response Body Schema
```json
{
  "voices": [
    {
      "id": "voice_42n103zlznqt",
      "model": "models/gemini-3.8-flash-tts",
      "type": "prompted",
      "expire_time": "2027-09-28T21:54:20.020144453Z",
      "display_name": "Egyptian Historian & Storyteller",
      "prompted": {
        "input": "A wise, passionate Egyptian historian..."
      }
    }
  ],
  "next_page_token": "..."
}
```

---

### 2.3 Get Voice Details
Fetches full metadata and the audition sample audio for an existing voice ID.

- **Method**: `GET`
- **Endpoint**: `/v1beta/voices/{voice_id}`

#### Example Request
```
GET /v1beta/voices/voice_42n103zlznqt?key=YOUR_API_KEY
```

#### Response Body Schema
Returns the complete Voice object including `sample_audio` with `mime_type` and base64 audio payload.

---

### 2.4 Delete Stored Voice
Removes a stored voice from the project.

- **Method**: `DELETE`
- **Endpoint**: `/v1beta/voices/{voice_id}`

#### Response Body Schema
```json
{}
```

---

### 2.5 Speech Synthesis with Custom Voice
Synthesizes arbitrary text using the custom voice ID via the `generateContent` endpoint.

- **Method**: `POST`
- **Endpoint**: `/v1beta/models/{model_id}:generateContent`
  - Supported `model_id`: `gemini-3.8-flash-lite-tts` or `gemini-3.8-flash-tts`
- **Headers**:
  - `Content-Type: application/json`
  - `x-goog-api-key: <API_KEY>`

#### Request Body Schema
```json
{
  "contents": [
    {
      "parts": [
        {
          "text": "أهلاً بكم في رحلتنا التاريخية عبر شوارع القاهرة المعز."
        }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "voice": "voice_42n103zlznqt"
      }
    }
  }
}
```

> **Key Syntax Note**: Unlike prebuilt voices which nest under `voiceConfig.prebuiltVoiceConfig.voiceName`, custom voices pass the `voice_<id>` string directly into `voiceConfig.voice`.

#### Response Body Schema (HTTP 200 OK)
```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "inlineData": {
              "mimeType": "audio/wav",
              "data": "UklGRvLDBwBXQVZFZm10IBAAAAABAAEA..."
            }
          }
        ],
        "role": "model"
      },
      "finishReason": "STOP"
    }
  ]
}
```

---

## 3. Voice Prompt Engineering Guide

When crafting prompts for Voice Design, treat the prompt as a **casting brief for a voice actor** rather than a keyword tag cloud.

### 3.1 Core Persona Dimensions

1. **Archetype & Role**:
   - Instead of generic adjectives ("friendly", "good"), specify role-grounded archetypes: *court chronicler, documentary narrator, lively podcast host, veteran professor, bedside storyteller*.
2. **Age & Gender**:
   - Ground vocal weight and resonance: *late 50s male, 30s female, elderly grandmother*.
3. **Accent & Regional Dialect**:
   - Be specific about geography and register: *authentic Cairene Egyptian Arabic, formal Modern Standard Arabic (Fusha) with classical cadence, warm northern English accent*.
4. **Timbre & Vocal Texture**:
   - Describe acoustic texture: *warm resonance, velvety, slight gravelly rasp, crisp articulation, baritone depth*.
5. **Cadence & Baseline Delivery**:
   - Define rhythm: *unhurried and measured, brisk and inquisitive, steady rhythmic pacing*.

### 3.2 Invariant vs. Situational Guidance
- **Permanent Persona (Voice Design Prompt)**:
  - Define traits that remain unchanged across books or chapters: age, gender, accent, vocal timber, baseline cadence.
- **Situational Tone (`speech_metadata.style` or Inline Tags)**:
  - Use runtime styles for per-paragraph emotional shifts: `"whispered with urgency"`, `"joyful and celebratory"`.
  - Use inline vocal tags inside dialogue: `<sigh>`, `<laugh>`, `<pause>`, `<gasp>`.

### 3.3 Production Prompt Templates

#### Egyptian Historical Narrator (Male)
```
"A wise, passionate Egyptian historian in his late 50s with an authentic, warm Cairene accent, speaking with deep knowledge, measured cadence, and captivating storytelling flair."
```

#### Classical Islamic Scholar / Fusha Narrator (Male)
```
"A distinguished classical scholar in his early 60s speaking pristine Modern Standard Arabic with impeccable grammatical precision, authoritative baritone timbre, and deliberate, reverent cadence."
```

#### Warm Arab Educator & Mentor (Female)
```
"A warm, articulate educator in her late 30s with a melodic and clear Egyptian accent, speaking with encouraging patience, bright articulation, and engaging vocal energy."
```

---

## 4. Complete Code Implementations

### 4.1 Pure Python Client (Standard Library)

```python
import base64
import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
API_KEY = "YOUR_GEMINI_API_KEY"

def design_voice(display_name: str, casting_prompt: str) -> dict:
    """Designs and stores a custom voice persona."""
    url = f"{BASE_URL}/voices?key={urllib.parse.quote(API_KEY)}"
    payload = {
        "store": True,
        "voice": {
            "model": "gemini-3.8-flash-tts",
            "type": "prompted",
            "display_name": display_name,
            "prompted": {
                "input": casting_prompt
            }
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def synthesize_text(text: str, voice_id: str, output_file: str, model: str = "gemini-3.8-flash-lite-tts"):
    """Synthesizes text using a custom voice ID."""
    url = f"{BASE_URL}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(API_KEY)}"
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "voice": voice_id
                }
            }
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    
    b64_data = res["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    audio_bytes = base64.b64decode(b64_data)
    Path(output_file).write_bytes(audio_bytes)
    print(f"Saved {len(audio_bytes)} bytes of WAV audio to {output_file}")

# Example Workflow
if __name__ == "__main__":
    # 1. Design Voice
    voice = design_voice(
        display_name="Cairene Storyteller",
        casting_prompt="A warm, engaging Egyptian narrator in his 40s speaking natural Cairene Arabic."
    )
    voice_id = voice["id"]
    print(f"Created Voice ID: {voice_id}")

    # 2. Synthesize
    synthesize_text(
        text="القاهرة مدينة الألف مئذنة، حكاياتها لا تنتهي عبر التاريخ.",
        voice_id=voice_id,
        output_file="story.wav"
    )
```

---

### 4.2 cURL Reference

#### Create Prompted Voice
```bash
curl "https://generativelanguage.googleapis.com/v1beta/voices" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{
    "store": true,
    "voice": {
      "model": "gemini-3.8-flash-tts",
      "type": "prompted",
      "display_name": "Egyptian Historian",
      "prompted": {
        "input": "A wise Egyptian historian in his late 50s with a warm Cairene accent."
      }
    }
  }'
```

#### List Stored Prompted Voices
```bash
curl "https://generativelanguage.googleapis.com/v1beta/voices?type=prompted" \
  -H "x-goog-api-key: $GEMINI_API_KEY"
```

#### Synthesize Speech with Voice ID
```bash
curl "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-lite-tts:generateContent" \
  -H "x-goog-api-key: $GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -X POST \
  -d '{
    "contents": [{
      "parts": [{ "text": "مرحباً بكم في التاريخ." }]
    }],
    "generationConfig": {
      "responseModalities": ["AUDIO"],
      "speechConfig": {
        "voiceConfig": {
          "voice": "voice_42n103zlznqt"
        }
      }
    }
  }'
```

---

## 5. Live Operational & Diagnostic Findings

During empirical verification on the live Gemini API environment, the following operational characteristics were established:

1. **Endpoint Status**: The `/v1beta/voices` endpoint is fully live and functional. Voice creation, listing, retrieval, and synthesis were verified end-to-end.
2. **Quota Tiering**:
   - `gemini-3.8-flash-tts`: Subject to a Free Tier daily quota limit (10 requests/day per project). Quota exhaustion returns HTTP 429 (`RESOURCE_EXHAUSTED`, `GenerateRequestsPerDayPerProjectPerModel-FreeTier`).
   - `gemini-3.8-flash-lite-tts`: Features distinct and more generous rate limits. It flawlessly synthesizes speech using voice IDs created by `gemini-3.8-flash-tts`.
3. **Verified Custom Voice in Project**:
   - **Voice ID**: `voice_42n103zlznqt`
   - **Display Name**: `Test Egyptian Historian`
   - **Model**: `models/gemini-3.8-flash-tts`
   - **Expiry Date**: `2027-09-28T21:54:20Z` (1 year TTL)
   - **Audition Sample**: 3,396,786 bytes (audio/wav)
   - **Synthesized Output**: Verified 267,186 bytes output file generated at `output_sample/custom_egyptian_voice.wav`.
