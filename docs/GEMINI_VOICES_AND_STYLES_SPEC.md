# دليل ومواصفات الأصوات وأساليب الأداء الصوتي في Gemini 3.8 Flash TTS
## (Gemini 3.8 Flash TTS: Voice Roster, Emotional Delivery & Style Prompting Specification)

---

## 1. نظرة عامة والمعمارية الفنية (Architectural Overview)

توفر نماذج **Gemini 3.8 Flash TTS** (وعائلتها المتمثلة في `gemini-3.8-flash-tts` و `gemini-3.8-flash-lite-tts` و `gemini-3.1-flash-tts-preview`) إمكانات توليد صوتي متقدمة وفائقة النقاء للغة العربية واللغات المتعددة. تتميز هذه النماذج بالقدرة على التحكم الدقيق في نبرة الصوت، المشاعر، سرعة الإلقاء، والوقفات الصوتية من خلال التوجيه الأسلوبي والوسوم التعبيرية المضمنة (Acoustic Steering & Inline Tags).

### الفوارق المعمارية وقواعد الاتصال الحاكمة (Critical API Invariants)

1. **حقل `systemInstruction` غير مدعوم في نماذج TTS المتخصصة**:
   - إرسال `systemInstruction` إلى نموذج `gemini-3.8-flash-tts` أو `gemini-3.8-flash-lite-tts` ينتج عنه الخطأ الصريح:
     `HTTP 400: Developer instruction is not enabled for this model`.
   - **البديل المعتمد والمثبت تجريبياً**: يتم توجيه الأداء والأسلوب ونبرة الصوت عبر **بادئات التوجيه الإخراجي (Director Prompts)** في بداية النص داخل حقل `contents[].parts[].text`، مثل:
     `[Style: Authoritative, solemn historical documentary narration, grave baritone]`
2. **الوسوم المضمنة لا تُنطق صوتياً (Zero-Verbalization of Inline Tags)**:
   - أثبتت الاختبارات العملية (المطابقة حرفياً عبر تفريغ صوتي بنموذج `gemini-2.5-flash`) أن النموذج يفسر وسوم التوجيه مثل `[Style: ...]`, `[short pause]`, `<short pause>`, `[gasp]`, `[whispering]` كأوامر صوتية حركية مباشرة، ولا يقرأ هذه الوسوم نصياً على الإطلاق.
3. **سياسة الحصص وحدود المعدل (Quota & Rate Limits)**:
   - **`gemini-3.8-flash-tts` (Free Tier)**: يخضع لحصة يومية قدرها 10 طلبات في اليوم (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`).
   - **`gemini-3.8-flash-lite-tts` (Free Tier)**: يشترك في نفس المحرك الصوتي ونفس قائمة الأصوات الثلاثين ونفس جودة الـ PCM/WAV (24kHz)، ولكنه يخضع لمعدل دقيق قدره **3 طلبات في الدقيقة (3 RPM)** ويتجدد تلقائياً كل 60 ثانية (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`).
   - الاستراتيجية الموصى بها في الكود البرمجي: البدء بنموذج `gemini-3.8-flash-tts`، والتحويل التلقائي الذكي (Fallback) إلى `gemini-3.8-flash-lite-tts` عند نفاد الحصة اليومية، مع مراعاة فاصل زمني ~20-21 ثانية بين كل مقطع صوتي لتفادي خطأ HTTP 429.

---

## 2. جدول وأطلس الأصوات الرسمية الثلاثين (Gemini TTS 30 Prebuilt Voices Roster)

تستند أسماء الأصوات في منظومة Gemini TTS إلى أسماء الأجرام السماوية والنجوم والأساطير الفلكية، وتنقسم نبراتها بين الذكورية والأنثوية بمختلف الطبقات (Bass, Baritone, Tenor, Alto, Mezzo, Soprano).

فيما يلي السجل الكامل والشامل لجميع الأصوات الرسمية الثلاثين:

| اسم الصوت (Voice Name) | النوع المقدر (Gender) | طبقة الصوت والرنين (Pitch & Timbre) | الطابع الشخصي (Persona) | أفضل تصنيف للكتب والإنتاج (Best Audiobook Genre) |
| :--- | :--- | :--- | :--- | :--- |
| **Charon** | رجالي | باريتون رخيم عميق (Deep Baritone) | رصين، سلطوي، رسمي، جاد | كتب التاريخ، السير الذاتية، التراث، الوثائقيات الجادة |
| **Kore** | نسائي | ألتو متوازن وقوي (Balanced Alto) | واثقة، واضحة، حاسمة، فصيحة | الروايات الأدبية، التحقيقات الصحفية، الروايات العامة |
| **Fenrir** | رجالي | تينور ديناميكي سريع (Dynamic Tenor) | حماسي، درامي، مشحون، انفعالي | روايات الإثارة والتشويق، مشاهد المعارك، الفانتازيا الحركية |
| **Zephyr** | نسائي | سوبرانو ناعم خفيف (Soft Light Soprano) | هادئة، مضيئة، مريحة، دافئة | قصص ما قبل النوم، التأمل، اليقظة الذهنية، الشعر والخواطر |
| **Puck** | رجالي | تينور مرح مبهج (Upbeat Mid-High Tenor) | مرح، نابض بالحياة، عفوي، ودود | أدب الأطفال والناشئة، الروايات الخفيفة، الحوارات السريعة |
| **Aoede** | نسائي | سوبرانو دافئ انسيابي (Warm Melodious Soprano) | انسيابية، طبيعية، شجية، قريبة | المذكرات الشخصية، أدب الرحلات، الروايات الاجتماعية |
| **Orus** | رجالي | باريتون مستقر راسخ (Stable Grounded Baritone) | حكيم، رزين، مطمئن، متزن | الفلسفة، المقالات العلمية، التنمية الذاتية، الأدب الفكري |
| **Leda** | نسائي | سوبرانو مبهج شبابي (Bright Youthful Soprano) | متفائلة، حيوية، مشرقة | قصص اليافعين، الحكايات الشعبية، المحتوى التعليمي |
| **Achernar** | نسائي | سوبرانو هامس رقيق (Soft Whispery Soprano) | هامسة، وديعة، بالغة الرقة | قصص الاسترخاء العميق، اليوميات الخاصة، النصوص الروحانية |
| **Achird** | رجالي | باريتون ودود محادث (Conversational Baritone) | ودود، اجتماعي، مبتسم النبرة | البودكاست، كتب تطوير الذات، الإرشادات العملية |
| **Algenib** | رجالي | باس خشن أجش (Gravelly Deep Bass) | جهوري، محنك، خشن النبرة | أدب الجريمة (Noir)، مذكرات المحاربين، الرعب والفانتازيا المظلمة |
| **Algieba** | نسائي | ألتو حريري شجي (Silky Smooth Alto) | شجية، إيقاعية، عذبة الإلقاء | الشعر العربي الفصيح، النثر الصوفي، الملاحم التاريخية |
| **Alnilam** | رجالي | باريتون قاطع صارم (Firm Direct Baritone) | عسكري، مباشر، قوي المخارج | التاريخ العسكري، السياسة، التحليلات الجيوسياسية |
| **Autonoe** | نسائي | سوبرانو نابض مشرق (Bright Vivacious Soprano) | حماسية، منطلقة، سريعة البديهة | روايات المغامرات، قصص الخيال العلمي الموجهة للشباب |
| **Callirrhoe** | نسائي | ميزو هادئ مريح (Easy-going Mezzo) | مسترخية، عفوية، غير متكلفة | المقالات اليومية، كتب السفر والترحال، الحكايات العائلية |
| **Despina** | نسائي | ألتو مخملي راقٍ (Smooth Velvety Alto) | أنيقة، فارهة، فصيحة النطق | الأدب الكلاسيكي، تاريخ الفنون، الميثولوجيا القديمة |
| **Enceladus** | رجالي | باريتون دافئ هوائي (Breathy Intimate Baritone) | حالم، ليلي، هامس الإلقاء | جلسات الاسترخاء، التنويم الإيحائي، التأمل الليلي |
| **Erinome** | نسائي | ألتو نقي شديد الوضوح (Crystalline Clear Alto) | دقيقة، موضوعية، أكاديمية النبرة | الموسوعات العلمية، المقررات الجامعية، المراجع التوثيقية |
| **Gacrux** | رجالي | باس شيخوخي وقور (Mature Elder Bass) | حكيم مسن، مهيب، بطيء الإيقاع | دور الحكيم في الروايات، الأساطير الشعبية، الملاحم التراثية |
| **Iapetus** | رجالي | باريتون تحليلي نظيف (Crisp Analytical Baritone) | موضوعي، حيادي، ناصع النبرة | كتب العلوم والتكنولوجيا، التحليلات الاقتصادية |
| **Laomedeia** | نسائي | سوبرانو موسيقي معبر (Musical Expressive Soprano) | نغمية، مرحة، متغيرة الطبقات | حكايات الحيوان الرمزية، الأناشيد الأدبية، قصص الخيال |
| **Pulcherrima** | نسائي | ميزو واثق معاصر (Assertive Forward Mezzo) | قيادية، معاصرة، واثقة الحضور | ريادة الأعمال، قصص الجواسيس والغموض المعاصر |
| **Rasalgethi** | رجالي | باريتون إخباري متزن (Informative Measured Baritone) | وثائقي، منتظم، خبير الإلقاء | الوثائقيات الجغرافية والطبيعية، الروايات الواقعية |
| **Sadachbia** | نسائي | ميزو حيوي شغوف (Lively Curious Mezzo) | شغوفة، فضولية، محفزة للذهن | كتب تبسيط العلوم، استكشاف الفضاء، مغامرات الفتيان |
| **Sadaltager** | رجالي | باريتون أكاديمي عالم (Knowledgeable Scholarly Baritone) | أستاذي، عميق الفهم، متأنٍ | أمهات كتب الفكر، تاريخ العلوم والحضارات، الفلسفة الإسلامية |
| **Schedar** | رجالي | باريتون محايد مستوٍ (Even Balanced Baritone) | حيادي تماماً، غير متحيز | النشرات الإخبارية، محاضر الجلسات، التوثيق القضائي والتاريخي |
| **Sulafat** | نسائي | ميزو دافئ عميق التعاطف (Warm Empathetic Mezzo) | متعاطفة، حنونة، دافئة القلب | الروايات الإنسانية المؤثرة، كتب التعافي النفسي، المذكرات |
| **Umbriel** | رجالي | تينور وديع مسامر (Companionable Casual Tenor) | مريح، مسامر، صديق الجلسة | كتب الذكريات، أدب السمر، المقالات الساخرة الهادفة |
| **Vindemiatrix** | نسائي | ألتو أمومي مطمئن (Gentle Nurturing Alto) | حانية، أمومية، غامرة بالسكينة | قصص الأطفال الهادفة، كتب التربية، قصص النوم الهادئة |
| **Zubenelgenubi** | رجالي | باريتون عصري تلقائي (Casual Contemporary Baritone) | شبابي، واقعي، متحرر من الرسميات | الروايات الواقعية المعاصرة، الحوارات اليومية |

---

## 3. الأنماط الإخراجية الثلاثة المعتمدة للكتب الصوتية العربية (3 Core Production Styles)

### النمط الأول: الوثائقي والتاريخي الرصين (Solemn Historical Documentary)
- **الصوت الموصى به**: `Charon` (البدائل: `Orus`, `Alnilam`, `Sadaltager`).
- **المواصفات الصوتية**: وقار وجدية، نبرة جهورية، مخارج حروف عربية قوية وفخمة، وقفات محسوبة بعد الفواصل والعبارات التاريخية ذات الوزن.
- **توجيه المخرج (Director Prompt)**:
  ```text
  [Style: Authoritative, solemn historical documentary narration, grave baritone, deliberate and measured cadence]
  ```
- **نموذج النص العربي مع الوسوم**:
  ```text
  [Style: Authoritative, solemn historical documentary narration, grave baritone, deliberate and measured cadence]
  في قلبِ القاهرةِ الفاطمية، [short pause] يقفُ الجامعُ الأزهرُ شامخاً منذ أكثرَ من ألفِ عام، شاهداً على تحولاتِ الفكرِ وعراقةِ الحضارةِ الإسلامية.
  ```

---

### النمط الثاني: الرواية الدرامية والتشويق (Dramatic Novel & Suspense)
- **الصوت الموصى به**: `Fenrir` أو `Kore` (البدائل: `Puck`, `Pulcherrima`).
- **المواصفات الصوتية**: إيقاع مشدود، تحولات ديناميكية في نبرة الصوت، التعبير عن حبس الأنفاس والمفاجأة عبر وسم `[gasp]` والوقفات المشحونة بالتوتر.
- **توجيه المخرج (Director Prompt)**:
  ```text
  [Style: Dramatic, cinematic, intense suspense, breathless anticipation and emotional charge]
  ```
- **نموذج النص العربي مع الوسوم**:
  ```text
  [Style: Dramatic, cinematic, intense suspense, breathless anticipation and emotional charge]
  دقّت ساعةُ منتصفِ الليل! [gasp] التفتَ حاملاً السراج، فرأى ظلاً طويلاً يتحركُ بخفةٍ نحو البابِ المغلق، <short pause> وحبس أنفاسَه مترقباً المجهول.
  ```

---

### النمط الثالث: الهدوء والتأمل والقصص الليلية (Calm Sleep & Meditation)
- **الصوت الموصى به**: `Zephyr` (البدائل: `Achernar`, `Aoede`, `Enceladus`, `Vindemiatrix`).
- **المواصفات الصوتية**: نبرة هامسة هادئة، هواء خفيف مع الصوت، إيقاع شديد التمهل، يساعد على خفض النشاط الذهني والاستسلام للاسترخاء التام.
- **توجيه المخرج (Director Prompt)**:
  ```text
  [Style: Whispering, gentle bedtime story, deeply relaxing, slow peaceful pacing]
  ```
- **نموذج النص العربي مع الوسوم**:
  ```text
  [Style: Whispering, gentle bedtime story, deeply relaxing, slow peaceful pacing]
  أغمض عينيكَ بهدوءٍ وسكينة... [short pause] اترك همومَ النهارِ تتلاشى بعيداً خلفَ الأفق، واستسلم لدفءِ الليلِ وهدوءِ الراحةِ التامة.
  ```

---

## 4. قائمة الوسوم التعبيرية المدعومة وكيفية توظيفها (Supported Inline Tags)

تتيح عائلة Gemini 3.8 Flash TTS إدراج وسوم داخلية لتوجيه الأداء الصوتي اللحظي:

1. **وسوم الوقفات (Pause Tags)**:
   - `[short pause]` أو `<short pause>`: وقفة صامتة تتراوح بين 0.5 إلى 0.8 ثانية. مثالية بعد العبارات التمهيدية أو الانتقال بين الفقرات.
   - الفواصل العادية `,` والنقاط `.` وعلامات التعجب `!` تؤثر أيضاً تأثيراً مباشراً على إيقاع الإلقاء وتنفس المعلق الصوتي.
2. **وسوم المشاعر والانفعالات الحركية (Emotional & Physiological Tags)**:
   - `[gasp]`: شهقة مفاجئة أو سحب هواء سريع يعبر عن الرعب أو الصدمة.
   - `[whispering]` أو `[whispers]`: تحويل العبارة اللاحقة إلى همس حقيقي ناصع.
   - `[sighs]`: زفرة تنهد تدل على التعب أو الراحة أو الحزن.
   - `[excitedly]`: رفع الطبقة وزيادة السرعة تعبيراً عن الحماس.
   - `[clears throat]`: تنحنح تمهيدي يعطي واقعية بشرية كاملة للأداء.

> [!IMPORTANT]
> **قاعدة التنسيق**: افصل الوسوم دائماً بمسافات واضحة عن الكلمات العربية المحيطة، وتجنب وضع وسمين متتاليين مباشرة بدون كلمات أو علامات ترقيم بينهما.

---

## 5. أمثلة برمجية كاملة (Python & cURL Examples)

### مثال 1: استدعاء cURL مباشر

```bash
curl -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash-lite-tts:generateContent?key=${GEMINI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {
        "parts": [
          {
            "text": "[Style: Authoritative, solemn historical documentary narration]\nفي عام ستمائة وواحد وأربعين للميلاد، [short pause] دخل الفاتح عمرو بن العاص أرض مصر."
          }
        ]
      }
    ],
    "generationConfig": {
      "responseModalities": ["AUDIO"],
      "speechConfig": {
        "voiceConfig": {
          "prebuiltVoiceConfig": {
            "voiceName": "Charon"
          }
        }
      }
    }
  }' | jq -r '.candidates[0].content.parts[0].inlineData.data' | base64 -d > documentary_sample.wav
```

---

### مثال 2: كود بايثون متكامل مع معالجة الرأس وترويسة WAV (Python Production Snippet)

```python
#!/usr/bin/env python3
"""
Standard Library Gemini 3.8 Flash TTS Client with Model Cascading.
"""
import base64
import json
import os
import struct
import urllib.request
from pathlib import Path

def craft_wav_header(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Builds a compliant 44-byte RIFF/WAVE header for linear PCM data."""
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = len(pcm_data)
    file_size = 36 + data_size
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", file_size, b"WAVE", b"fmt ",
        16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size
    )
    return header + pcm_data

def synthesize_arabic_speech(
    text: str,
    voice_name: str = "Charon",
    api_key: str = None,
    output_path: str = "output.wav"
) -> str:
    key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is required.")

    # Intelligent Model Hierarchy
    models = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview"]
    
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name
                    }
                }
            }
        }
    }
    
    post_data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "GeminiAudiobookClient/1.0"}

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                part = data["candidates"][0]["content"]["parts"][0]
                b64_audio = part["inlineData"]["data"]
                raw_bytes = base64.b64decode(b64_audio)
                
                wav_bytes = raw_bytes if raw_bytes.startswith(b"RIFF") else craft_wav_header(raw_bytes, 24000)
                
                out_file = Path(output_path)
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_bytes(wav_bytes)
                print(f"Synthesized successfully with {model} ({len(wav_bytes)} bytes) -> {out_file}")
                return str(out_file.resolve())
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="ignore")
            # If rate limited / quota exhausted on primary model, fallback automatically
            if err.code == 429:
                print(f"Model {model} 429 limit reached. Falling back to next model...")
                continue
            raise RuntimeError(f"HTTP {err.code}: {err_body}")

    raise RuntimeError("All Gemini TTS models were exhausted.")

if __name__ == "__main__":
    arabic_quote = (
        "[Style: Authoritative, solemn historical documentary narration]\n"
        "في قلبِ القاهرةِ الفاطمية، [short pause] يقفُ الجامعُ الأزهرُ شامخاً منذ أكثر من ألفِ عام."
    )
    synthesize_arabic_speech(arabic_quote, voice_name="Charon", output_path="sample_charon.wav")
```

---

## 6. توصيات التشكيل وضبط النص العربي للكتب الصوتية (Arabic Diacritization Best Practices)

1. **تشكيل أواخر الكلمات والكلمات الملتبسة**:
   - نموذج Gemini 3.8 Flash TTS يفهم سياق الكلمات العربية بدقة متقدمة للغاية، ولكنه يلتزم التزاماً تاماً بالحركات الإعرابية (التشكيل) إن وجدت.
   - يُنصح بتشكيل بنية الكلمات المتشابهة (مثل: عَمْر وعُمَر، فُتِحَت وفَتَحَت، تَمَّ ويَتِمُّ) لمنع أي التباس نطقي.
2. **نطق الأرقام والتواريخ والسنوات**:
   - يُفضل كتابة الأرقام التاريخية حروفاً باللغة العربية (مثال: "في عام ستمائة وواحد وأربعين للميلاد" بدلاً من "في عام 641 م") لضمان إعراب العدد والمعدود بدقة لغوية تراثية مثالية.
3. **طول الفقرة والمقطع (Chunk Size)**:
   - أنسب حجم للمقطع الصوتي هو ما بين 150 إلى 300 حرف (جملة أو جملتان متكاملتان)، حيث يعطي النموذج أفضل تلوين صوتي واستقرار في الإيقاع دون أي استعجال أو بطء مفاجئ.
