# تطبيق ومحرك الكتب الصوتية: Gemini Audiobook TTS (Native Android & Termux Engine)

نظام متكامل لتحويل الكتب والمستندات النصية (`.md` و `.txt`) إلى كتب صوتية احترافية مقسمة لفصول باستخدام نموذج جوجل الجديد **Gemini 3.8 Flash TTS** الصادر في سبتمبر 2026، مع مشغل صوتي متوافق 100% مع قارئات الشاشة (TalkBack و Jieshuo).

---

## 🚀 1. التشغيل الفوري المباشر في Termux (CLI Engine)

المحرك جاهز ومختبر ويعمل بالكامل داخل Termux على جهازك الآن:

### أ. فحص جاهزية البيئة:
```bash
python3 /data/data/com.termux/files/home/gemini_audiobook_tts/doctor.py
```

### ب. تشغيل الاختبارات الآلية (13 اختبار):
```bash
python3 /data/data/com.termux/files/home/gemini_audiobook_tts/test_engine.py
```

### ج. تحويل كتاب حقيقي باستخدام مفتاحك:
```bash
python3 /data/data/com.termux/files/home/gemini_audiobook_tts/gemini_audiobook_engine.py \
  --input /مسار/الكتاب.md \
  --output-dir ./my_audiobook \
  --api-key "AIzaSy..." \
  --voice "Kore"
```
*(أو استخدم علم `--mock` لاختبار التقطيع والفصول وتوليد ملفات صوتية تجريبية مجاناً دون الحاجة لمفتاح).*

---

## 📱 2. مشروع تطبيق أندرويد الأصلي (Android Project)

الكود المصدري الكامل لتطبيق أندرويد بلغة **Kotlin** موجود داخل مجلد `android/`:
- **المسار:** `/data/data/com.termux/files/home/gemini_audiobook_tts/android/`

### هيكل مشروع أندرويد:
- `app/src/main/java/com/antigravity/audiobook/domain/SmartTextChunker.kt`: التقطيع الذكي بحد أقصى 8000 حرف.
- `app/src/main/java/com/antigravity/audiobook/domain/MarkdownStripper.kt`: تنظيف الماركداون واستخراج الفصول.
- `app/src/main/java/com/antigravity/audiobook/domain/BookParser.kt`: التحليل التلقائي للفصول العربية والروايات.
- `app/src/main/java/com/antigravity/audiobook/data/GeminiTtsClient.kt`: الاتصال بنموذج `gemini-3.8-flash-tts` عبر OkHttp.
- `app/src/main/java/com/antigravity/audiobook/player/AudiobookPlayerService.kt`: خدمة تشغيل Media3 في الخلفية مع **خفض الصوت التلقائي (Audio Focus Ducking)** عند تحدث TalkBack أو Jieshuo.
- `app/src/main/java/com/antigravity/audiobook/MainActivity.kt`: الواجهة المقتضبة الفخمة، مع أزرار لمس كبيرة (أكبر من 48dp)، وإشعارات حية صوتية (`accessibilityLiveRegion`).
