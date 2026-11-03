#!/usr/bin/env python3
"""
Gemini TTS Client for Gemini Audiobook TTS.
Handles communication with the Gemini 3.8 Flash TTS REST API via standard library
(urllib.request & json), parses speech metadata, handles audio decoding,
and crafts valid WAV headers for raw PCM output.
"""

import base64
import json
import logging
import math
import os
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("GeminiTtsClient")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


PREBUILT_VOICES: List[Dict[str, str]] = [
    {"name": "Kore", "gender": "أنثى", "style_ar": "صوت حازم وواضح، مثالي للسرد الروائي والكتب المعرفية"},
    {"name": "Puck", "gender": "ذكر", "style_ar": "صوت حيوي ومشرق، مناسب للقصص المشوقة والحوارات الشابة"},
    {"name": "Charon", "gender": "ذكر", "style_ar": "صوت عميق ورصين، مثالي للكتب التاريخية والوثائقية"},
    {"name": "Fenrir", "gender": "ذكر", "style_ar": "صوت قوي وحماسي، مناسب للملاحم والمشاهد الدرامية"},
    {"name": "Aoede", "gender": "أنثى", "style_ar": "صوت عذب ومنساب، رائع للأدب والشعر والروايات الوجدانية"},
    {"name": "Zephyr", "gender": "أنثى", "style_ar": "صوت مشرق ولطيف، مناسب للكتب التعليمية والقصص الخفيفة"},
    {"name": "Leda", "gender": "أنثى", "style_ar": "صوت شاب وودود، مناسب للقصص الاجتماعية واليوميات"},
    {"name": "Orus", "gender": "ذكر", "style_ar": "صوت متزن وواثق، ممتاز للكتب الفكرية والفلسفية"},
    {"name": "Callirrhoe", "gender": "أنثى", "style_ar": "صوت هادئ ومريح، مناسب للتأمل وتطوير الذات"},
    {"name": "Autonoe", "gender": "أنثى", "style_ar": "صوت ناضج ومعبر، مثالي للسرد الأدبي الرصين"},
    {"name": "Enceladus", "gender": "ذكر", "style_ar": "صوت هامس ودافئ، مناسب للأجواء الغامضة والهادئة"},
    {"name": "Iapetus", "gender": "ذكر", "style_ar": "صوت جهوري وواضح، مناسب للخطب والنصوص التراثية"},
    {"name": "Umbriel", "gender": "ذكر", "style_ar": "صوت هادئ ومتأنٍ، مناسب للتحليلات العلمية المبسطة"},
    {"name": "Algieba", "gender": "ذكر", "style_ar": "صوت سلس وطبيعي، مريح للاستماع الطويل"},
    {"name": "Despina", "gender": "أنثى", "style_ar": "صوت دافئ وناعم، مناسب للروايات العائلية"},
    {"name": "Erinome", "gender": "أنثى", "style_ar": "صوت دقيق وواضح المخارج، ممتاز للنصوص التعليمية"},
    {"name": "Algenib", "gender": "ذكر", "style_ar": "صوت رخيم ذو طابع كلاسيكي، مناسب للأدب العربي"},
    {"name": "Rasalgethi", "gender": "ذكر", "style_ar": "صوت إخباري وثائقي، مثالي للكتب السياسية والاقتصادية"},
    {"name": "Laomedeia", "gender": "أنثى", "style_ar": "صوت متفائل وحيوي، مناسب لكتب السير الذاتية الملهمة"},
    {"name": "Achernar", "gender": "أنثى", "style_ar": "صوت رقيق وهادئ، مناسب للقصص الروحانية والوجدانية"},
    {"name": "Alnilam", "gender": "ذكر", "style_ar": "صوت حازم ومتماسك، مناسب للكتب القانونية والإدارية"},
    {"name": "Schedar", "gender": "ذكر", "style_ar": "صوت متوازن وطبيعي، مناسب لمختلف أنواع الكتب العامة"},
    {"name": "Gacrux", "gender": "أنثى", "style_ar": "صوت ناضج ووقور، مناسب للكتب التاريخية والسرد الكلاسيكي"},
    {"name": "Pulcherrima", "gender": "أنثى", "style_ar": "صوت واضح ومعبر، يبرز تفاصيل الحوارات بوضوح"},
    {"name": "Achird", "gender": "ذكر", "style_ar": "صوت ودود وقريب من المستمع، مناسب للمقالات والحكايات"},
    {"name": "Zubenelgenubi", "gender": "ذكر", "style_ar": "صوت عميق وهادئ، مناسب للروايات الفلسفية"},
    {"name": "Vindemiatrix", "gender": "أنثى", "style_ar": "صوت لطيف ومتأنٍ، مريح جداً للكتب الطويلة"},
    {"name": "Sadachbia", "gender": "ذكر", "style_ar": "صوت نشط ومتحمس، مناسب لكتب المغامرات والخيال العلمي"},
    {"name": "Sadaltager", "gender": "ذكر", "style_ar": "صوت حكيم وواسع المعرفة، مثالي للموسوعات والشروح"},
    {"name": "Sulafat", "gender": "أنثى", "style_ar": "صوت دافئ ومطمئن، ممتاز للقراءة الليلية الهادئة"},
]

STYLE_PRESETS: Dict[str, str] = {
    "طبيعي": "",
    "إذاعي": "professional radio broadcaster, resonant, articulate and engaging tone",
    "وثائقي رصين": "authoritative documentary narrator, calm, objective and steady pacing",
    "درامي": "dramatic theatrical storyteller, expressive emotional depth and dynamic pacing",
    "تأمل وهدوء": "calm, soothing, gentle meditative voice with slow, relaxing delivery",
}

MODEL_DAILY_LIMITS: Dict[str, int] = {
    "gemini-3.8-flash-tts": 100,
    "gemini-3.8-flash-lite-tts": 100,
    "gemini-3.1-flash-tts-preview": 10,
    "gemini-2.5-flash-preview-tts": 10,
    "gemini-2.5-pro-preview-tts": 10,
}


class QuotaExhaustedError(RuntimeError):
    """Raised when all provided API keys have exhausted their quota for the selected model."""


class DialogueTurnAnnotator:
    """
    Analyzes narrative Arabic/English text to split into 2-speaker turns (Speaker1: Narrator, Speaker2: Character)
    according to Google's official Gemini 3.8 Flash TTS Multi-Speaker specification.
    Supports two standard formats:
    1. Script / Podcast Format (أحمد: مرحباً / سارة: أهلاً بك):
       Detects speaker names at start of lines and buffers continuous turns cleanly.
    2. Novel / Quotation Format:
       Distinguishes authentic dialogue sentences from isolated narrative quoted terms (e.g., nicknames or single words)
       and automatically infers emotional speechMetadata.style from Arabic narrative context cues.
    """

    INLINE_ARABIC_TAGS: List[Tuple[str, str]] = [
        ("تنهيدة", "<sigh>"),
        ("يتنهد", "<sigh>"),
        ("تتنهد", "<sigh>"),
        ("ضحكة", "<laugh>"),
        ("يضحك", "<laugh>"),
        ("تضحك", "<laugh>"),
        ("شهقة", "<gasp>"),
        ("يشهق", "<gasp>"),
        ("تشهق", "<gasp>"),
        ("وقفة قصيرة", "<short pause>"),
        ("صمت قصير", "<short pause>"),
        ("وقفة طويلة", "<long pause>"),
        ("صمت طويل", "<long pause>"),
    ]

    EMOTION_CUE_RULES: List[Tuple[re.Pattern[str], str]] = [
        (
            re.compile(r"(همس|بهمس|بصوت خافت|بصوت منخفض|همست|يهمس|تسرّ|بسرية)"),
            "whispered urgently, quiet hushed tone",
        ),
        (
            re.compile(r"(صرخ|بغضب|صاح|هتف|بانفعال|بحدة|صرخت|صاحت|غاضب|بصوت عال)"),
            "shouting with anger, intense and forceful delivery",
        ),
        (
            re.compile(r"(بحزن|ببكاء|بأسى|بألم|دموع|بكى|بكت|حزين|متأثراً|بصوت متهدج)"),
            "sad, emotional, tearful and trembling voice",
        ),
        (
            re.compile(r"(مبتسماً|بفرح|بسعادة|ضاحكاً|بابتسامة|مبتهجاً|فرحاً|بمرح)"),
            "cheerful, warm smiling and joyful tone",
        ),
        (
            re.compile(r"(بدهشة|بخوف|بذهول|برعب|مذعوراً|متفاجئاً|بارتباك|مرتجفاً)"),
            "gasping, fearful and surprised tone",
        ),
        (
            re.compile(r"(بهدوء|بسكينة|برزانة|بوَقار|بثقة|بصوت هادئ|بحكمة)"),
            "calm, composed, steady and reassuring tone",
        ),
    ]

    DIALOGUE_VERBS = {
        # Arabic
        "قال", "قالت", "يقول", "تقول", "سأل", "سألت", "يسأل", "تسأل",
        "أجاب", "أجابت", "يجيب", "تجيب", "صاح", "صاحت", "يصيح", "تصيح",
        "هتف", "هتفت", "يهتف", "تهتف", "همس", "همست", "يهمس", "تهمس",
        "تمتم", "تمتمت", "غمغم", "غمغمت", "رد", "ردت", "يرد", "ترد",
        "أردف", "أردفت", "تابع", "تابعت", "قاطع", "قاطعت", "أضاف", "أضافت",
        # English
        "said", "says", "asked", "asks", "replied", "replies", "answered", "answers",
        "shouted", "whispered", "cried", "exclaimed", "muttered", "added", "continued",
        # French
        "dit", "disait", "demanda", "répondit", "repondit", "s'écria", "chuchota", "ajouta",
        # Spanish
        "dijo", "decía", "decia", "preguntó", "pregunto", "respondió", "respondio", "exclamó", "susurró", "añadió",
        # German
        "sagte", "fragte", "antwortete", "rief", "flüsterte", "erwiderte",
        # Russian
        "сказал", "сказала", "спросил", "спросила", "ответил", "ответила",
    }

    QUOTE_PATTERN = re.compile(r"([«“\"„「『][^»”\"“」』]+[»”\"“」』])")
    SCRIPT_LINE_REGEX = re.compile(r"^\s*([^:\r\n]{1,30})\s*[:：]\s*(.+)$")
    EXPLICIT_SPEAKER_LINE = re.compile(
        r"^\s*(الراوي|السارد|المتحدث\s*1|المتحدث\s*2|Speaker\s*1|Speaker\s*2|شخصية|الحوار)\s*[:：]\s*(.+)$",
        re.IGNORECASE,
    )

    @classmethod
    def replace_inline_expressive_tags(cls, text: str) -> str:
        """Converts parenthetical Arabic expressive descriptions like (تنهيدة) into official TTS tags."""
        result = text
        for ar_word, en_tag in cls.INLINE_ARABIC_TAGS:
            pattern = re.compile(rf"[\(\[\{{]\s*{re.escape(ar_word)}\s*[\)\]\}}]")
            result = pattern.sub(f" {en_tag} ", result)
        return re.sub(r"[ \t]{2,}", " ", result).strip()

    @classmethod
    def infer_style_from_context(cls, context_text: str, default_style: str = "expressive character dialogue") -> str:
        """Infers English speechMetadata.style from preceding Arabic narrative cues."""
        if not context_text:
            return default_style
        recent_window = context_text[-220:]
        for pattern, style_desc in cls.EMOTION_CUE_RULES:
            if pattern.search(recent_window):
                return style_desc
        return default_style

    @classmethod
    def is_dialogue_quote(cls, quote_content: str, preceding_text: str, following_text: str, quote_raw: str = "") -> bool:
        """
        Determines whether a quoted string represents authentic spoken dialogue or an isolated quoted term.
        Supports universal international conventions including East Asian brackets and conversational punctuation.
        """
        content = quote_content.strip()
        if not content:
            return False

        # East Asian dialogue quotation brackets 「...」 and 『...』 are strictly dialogue
        if quote_raw.startswith(("「", "『")) or content.startswith(("「", "『")):
            return True

        # Dialogue sentences with question/exclamation or conversational punctuation
        if any(p in content for p in ["?", "؟", "!", "！", "？"]):
            return True

        words = content.split()
        if len(words) >= 3 or len(content) >= 15:
            return True

        prec_tail = preceding_text.strip()[-30:] if preceding_text else ""
        if prec_tail.endswith((":", "：", "—", "-", "–")):
            return True

        prec_words = [w.strip('،,.:-—«»"“”„「」') for w in prec_tail.split()]
        if any(w.lower() in cls.DIALOGUE_VERBS for w in prec_words[-3:]):
            return True

        foll_head = following_text.strip()[:30] if following_text else ""
        foll_words = [w.strip('،,.:-—«»"“”„「」') for w in foll_head.split()]
        if any(w.lower() in cls.DIALOGUE_VERBS for w in foll_words[:3]):
            return True

        return False

    @classmethod
    def parse_script_format(
        cls,
        text: str,
        narrator_style: str = "natural audiobook narrator, clear pronunciation",
        character_default_style: str = "expressive character dialogue",
    ) -> List[Dict[str, str]]:
        """
        Parses script/podcast lines formatted as 'Speaker: Content' according to Google's official multi-speaker specs.
        Buffers consecutive lines from the same speaker into coherent turns.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        detected_speakers: List[str] = []
        for line in lines:
            m = cls.SCRIPT_LINE_REGEX.match(line)
            if m:
                spk = m.group(1).strip()
                if spk and not any(s.lower() == spk.lower() for s in detected_speakers):
                    detected_speakers.append(spk)

        if len(detected_speakers) < 2:
            return []

        spk1_alias = detected_speakers[0]
        spk2_alias = detected_speakers[1] if len(detected_speakers) > 1 else None

        raw_turns: List[Dict[str, str]] = []
        current_speaker = "Speaker1"
        current_buffer: List[str] = []

        for line in lines:
            m = cls.SCRIPT_LINE_REGEX.match(line)
            if m:
                spk_name = m.group(1).strip()
                content = m.group(2).strip()

                if spk_name.lower() == spk1_alias.lower():
                    target_spk = "Speaker1"
                elif spk2_alias and spk_name.lower() == spk2_alias.lower():
                    target_spk = "Speaker2"
                elif any(k in spk_name.lower() for k in ["راوي", "narrator", "speaker1", "سارد", "متحدث 1"]):
                    target_spk = "Speaker1"
                else:
                    target_spk = "Speaker2"

                if current_buffer:
                    if target_spk != current_speaker:
                        raw_turns.append({
                            "speaker": current_speaker,
                            "text": " ".join(current_buffer),
                            "style": narrator_style if current_speaker == "Speaker1" else character_default_style,
                        })
                        current_buffer = []
                        current_speaker = target_spk
                else:
                    current_speaker = target_spk

                current_buffer.append(content)
            else:
                current_buffer.append(line)

        if current_buffer:
            raw_turns.append({
                "speaker": current_speaker,
                "text": " ".join(current_buffer),
                "style": narrator_style if current_speaker == "Speaker1" else character_default_style,
            })

        return raw_turns

    @classmethod
    def parse_quotation_format(
        cls,
        text: str,
        narrator_style: str = "natural audiobook narrator, clear pronunciation",
        character_default_style: str = "expressive character dialogue",
    ) -> List[Dict[str, str]]:
        """
        Parses novel format by separating dialogue quotes from narrative text.
        Preserves isolated quoted terms inside narrative turns for Speaker1.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        raw_turns: List[Dict[str, str]] = []
        last_narrator_context = ""

        for line in lines:
            matches = list(cls.QUOTE_PATTERN.finditer(line))
            if not matches:
                raw_turns.append({
                    "speaker": "Speaker1",
                    "text": line,
                    "style": narrator_style,
                })
                last_narrator_context = line
                continue

            last_idx = 0
            for m in matches:
                start, end = m.span()
                quote_raw = m.group(1)
                clean_quote = quote_raw.strip("«»\"“”„「『」』").strip()

                if start > last_idx:
                    narr = line[last_idx:start].strip()
                    if narr:
                        raw_turns.append({
                            "speaker": "Speaker1",
                            "text": narr,
                            "style": narrator_style,
                        })
                        last_narrator_context = narr

                prec = line[:start]
                foll = line[end:]
                if cls.is_dialogue_quote(clean_quote, prec, foll, quote_raw=quote_raw):
                    inferred_style = cls.infer_style_from_context(
                        last_narrator_context, default_style=character_default_style
                    )
                    raw_turns.append({
                        "speaker": "Speaker2",
                        "text": clean_quote,
                        "style": inferred_style,
                    })
                else:
                    # Isolated phrase or term inside narrative - preserve for narrator
                    raw_turns.append({
                        "speaker": "Speaker1",
                        "text": quote_raw,
                        "style": narrator_style,
                    })
                    last_narrator_context = quote_raw

                last_idx = end

            if last_idx < len(line):
                tail = line[last_idx:].strip()
                if tail:
                    raw_turns.append({
                        "speaker": "Speaker1",
                        "text": tail,
                        "style": narrator_style,
                    })
                    last_narrator_context = tail

        # Merge adjacent turns from the same speaker to ensure fluent, unbroken speech delivery
        merged: List[Dict[str, str]] = []
        for t in raw_turns:
            txt = t["text"].strip()
            if not txt:
                continue
            if merged and merged[-1]["speaker"] == t["speaker"]:
                merged[-1]["text"] += " " + txt
            else:
                merged.append({
                    "speaker": t["speaker"],
                    "text": txt,
                    "style": t.get("style", narrator_style if t["speaker"] == "Speaker1" else character_default_style),
                })

        return merged

    @classmethod
    def parse_dashed_dialogue_format(
        cls,
        text: str,
        narrator_style: str = "natural audiobook narrator, clear pronunciation",
        character_default_style: str = "expressive character dialogue",
    ) -> List[Dict[str, str]]:
        """
        Universal structural dialogue parser for literary works across all languages (Arabic, French, English, Russian, Spanish, etc.)
        where spoken dialogue turns start with typographical dashes (- / — / – / ـ).
        Structurally separates character speech from intervening/trailing narrator inquits regardless of language.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        has_dashes = any(re.match(r"^[-—–ـ]\s*", ln) for ln in lines)
        if not has_dashes:
            return []

        raw_turns: List[Dict[str, str]] = []
        last_narrator_context = ""

        for line in lines:
            m_dash = re.match(r"^[-—–ـ]\s*(.+)$", line)
            if m_dash:
                content_line = m_dash.group(1).strip()
                # Split on internal dashes separating speech and narrator inquit
                parts = re.split(r"\s+[-—–ـ]\s+", content_line)
                if len(parts) == 1:
                    inferred_style = cls.infer_style_from_context(last_narrator_context, character_default_style)
                    raw_turns.append({"speaker": "Speaker2", "text": content_line, "style": inferred_style})
                elif len(parts) == 2:
                    p1, p2 = parts[0].strip(), parts[1].strip()
                    first_word = p2.split()[0].lower().strip('،,.:-—«»"“”„「」') if p2.split() else ""
                    is_inquit = (first_word in cls.DIALOGUE_VERBS) or (first_word and first_word[0].islower())
                    if is_inquit:
                        inferred_style = cls.infer_style_from_context(last_narrator_context, character_default_style)
                        raw_turns.append({"speaker": "Speaker2", "text": p1, "style": inferred_style})
                        raw_turns.append({"speaker": "Speaker1", "text": p2, "style": narrator_style})
                        last_narrator_context = p2
                    else:
                        inferred_style = cls.infer_style_from_context(last_narrator_context, character_default_style)
                        raw_turns.append({"speaker": "Speaker2", "text": content_line, "style": inferred_style})
                else:
                    # 3 or more parts: e.g. - Dialogue 1 - inquit - Dialogue 2
                    for idx, seg in enumerate(parts):
                        seg_clean = seg.strip()
                        if not seg_clean:
                            continue
                        if idx % 2 == 0:
                            inferred_style = cls.infer_style_from_context(last_narrator_context, character_default_style)
                            raw_turns.append({"speaker": "Speaker2", "text": seg_clean, "style": inferred_style})
                        else:
                            raw_turns.append({"speaker": "Speaker1", "text": seg_clean, "style": narrator_style})
                            last_narrator_context = seg_clean
            else:
                raw_turns.append({"speaker": "Speaker1", "text": line, "style": narrator_style})
                last_narrator_context = line

        # Merge adjacent turns from the same speaker
        merged: List[Dict[str, str]] = []
        for t in raw_turns:
            txt = t["text"].strip()
            if not txt:
                continue
            if merged and merged[-1]["speaker"] == t["speaker"]:
                merged[-1]["text"] += " " + txt
            else:
                merged.append({
                    "speaker": t["speaker"],
                    "text": txt,
                    "style": t.get("style", narrator_style if t["speaker"] == "Speaker1" else character_default_style),
                })
        return merged

    @classmethod
    def extract_turns(
        cls,
        text: str,
        narrator_style: str = "natural audiobook narrator, clear pronunciation",
        character_default_style: str = "expressive character dialogue",
    ) -> List[Dict[str, str]]:
        """
        Splits text into a list of turn dicts:
        [{"speaker": "Speaker1"|"Speaker2", "text": "...", "style": "..."}]
        Prioritizes script format; falls back to quotation format, then single-speaker narrator.
        """
        processed_text = cls.replace_inline_expressive_tags(text)
        if not processed_text.strip():
            return []

        script_turns = cls.parse_script_format(
            processed_text,
            narrator_style=narrator_style,
            character_default_style=character_default_style,
        )
        if len(script_turns) >= 2:
            return script_turns

        dashed_turns = cls.parse_dashed_dialogue_format(
            processed_text,
            narrator_style=narrator_style,
            character_default_style=character_default_style,
        )
        if any(t["speaker"] == "Speaker2" for t in dashed_turns):
            return dashed_turns

        quote_turns = cls.parse_quotation_format(
            processed_text,
            narrator_style=narrator_style,
            character_default_style=character_default_style,
        )
        if any(t["speaker"] == "Speaker2" for t in quote_turns):
            return quote_turns

        return [{
            "speaker": "Speaker1",
            "text": processed_text.strip(),
            "style": narrator_style,
        }]


class GeminiTtsClient:
    """
    Client for synthesizing speech via Google's Gemini TTS models (gemini-3.8-flash-tts, etc.).
    Requires no third-party dependencies, leveraging pure Python standard libraries.
    """

    DEFAULT_MODEL_ID = "gemini-3.8-flash-tts"
    BASE_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    VOICES_API_URL = "https://generativelanguage.googleapis.com/v1beta/voices"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_keys: Optional[List[str]] = None,
        model_id: str = DEFAULT_MODEL_ID,
        custom_endpoint: Optional[str] = None,
        max_retries: int = 3,
        mock_mode: bool = False,
        pacing_seconds: Optional[float] = None,
        max_429_retries_per_key: int = 2,
        retry_429_wait_seconds: float = 65.0,
        on_all_keys_exhausted: Optional[Callable[[str, int], Optional[str]]] = None,
        on_pacing_wait: Optional[Callable[[ float], None]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        raw_keys: List[str] = []
        if api_keys:
            for k in api_keys:
                for sub_k in re.split(r"[\r\n,;]+", str(k)):
                    cleaned = sub_k.strip()
                    if cleaned and cleaned not in raw_keys:
                        raw_keys.append(cleaned)
        if api_key:
            for sub_k in re.split(r"[\r\n,;]+", str(api_key)):
                cleaned = sub_k.strip()
                if cleaned and cleaned not in raw_keys:
                    raw_keys.append(cleaned)
        if not raw_keys:
            env_key = os.getenv("GEMINI_API_KEY", "").strip()
            for sub_k in re.split(r"[\r\n,;]+", env_key):
                cleaned = sub_k.strip()
                if cleaned and cleaned not in raw_keys:
                    raw_keys.append(cleaned)

        self.api_keys: List[str] = raw_keys
        self.current_key_index: int = 0
        self.api_key: str = self.api_keys[0] if self.api_keys else ""
        self.model_id: str = model_id or self.DEFAULT_MODEL_ID
        self.custom_endpoint: Optional[str] = custom_endpoint
        self.max_retries: int = max_retries
        self.mock_mode: bool = bool(mock_mode or (len(self.api_keys) == 0))

        if pacing_seconds is None:
            self.pacing_seconds: float = 0.0 if self.mock_mode else 60.0
        else:
            self.pacing_seconds = max(0.0, float(pacing_seconds))

        self.max_429_retries_per_key: int = max(0, int(max_429_retries_per_key))
        self.retry_429_wait_seconds: float = max(0.0, float(retry_429_wait_seconds))
        self.on_all_keys_exhausted = on_all_keys_exhausted
        self.on_pacing_wait = on_pacing_wait
        self._sleep: Callable[[float], None] = sleep_fn or time.sleep

        self.key_usage_counts: Dict[int, int] = {i: 0 for i in range(len(self.api_keys))}
        self.exhausted_key_indices: set[int] = set()
        self._last_request_timestamp: Optional[float] = None

        if self.mock_mode:
            logger.info("GeminiTtsClient initialized in MOCK mode (synthetic audio generation).")
        else:
            logger.info(
                "GeminiTtsClient initialized for model %s with %d API key(s) (daily cap per key: %d).",
                self.model_id,
                len(self.api_keys),
                self.get_model_daily_limit(self.model_id),
            )

    @classmethod
    def get_model_daily_limit(cls, model_id: str) -> int:
        """Returns the known daily free-tier request cap for the specified model."""
        if model_id in MODEL_DAILY_LIMITS:
            return MODEL_DAILY_LIMITS[model_id]
        if "3.8" in model_id:
            return 100
        return 10

    @classmethod
    def get_prebuilt_voices(cls) -> List[Dict[str, str]]:
        """Returns the verified catalog of 30 Gemini TTS prebuilt voices."""
        return [dict(v) for v in PREBUILT_VOICES]

    @classmethod
    def get_style_presets(cls) -> Dict[str, str]:
        """Returns the 5 Arabic narrative delivery style presets."""
        return dict(STYLE_PRESETS)

    @classmethod
    def resolve_style_instruction(cls, style_or_preset: str) -> str:
        """Resolves an Arabic preset name or custom style description to an instruction string."""
        cleaned = (style_or_preset or "").strip()
        if not cleaned or cleaned.lower() in ("natural", "default", "طبيعي"):
            return ""
        return STYLE_PRESETS.get(cleaned, cleaned)

    def get_active_api_key(self) -> str:
        """Returns the currently active API key."""
        if not self.api_keys:
            return ""
        self.current_key_index = min(self.current_key_index, len(self.api_keys) - 1)
        self.api_key = self.api_keys[self.current_key_index]
        return self.api_key

    def _rotate_to_next_key(self, reason: str) -> bool:
        """
        Marks the current key as exhausted for the active model and rotates to the next available key.
        Returns True if a fresh key is available, or False if all keys are exhausted.
        """
        if not self.api_keys:
            return False
        self.exhausted_key_indices.add(self.current_key_index)
        logger.warning(
            "Rotating away from API key #%d (%s). Exhausted keys: %d/%d.",
            self.current_key_index + 1,
            reason,
            len(self.exhausted_key_indices),
            len(self.api_keys),
        )
        for idx in range(len(self.api_keys)):
            if idx not in self.exhausted_key_indices:
                self.current_key_index = idx
                self.api_key = self.api_keys[idx]
                logger.info("Switched active API key to key #%d.", idx + 1)
                return True
        return False

    def _enforce_pacing(self) -> None:
        """Enforces the mandatory interval (default 60s) between consecutive real API calls."""
        if self.mock_mode or self.pacing_seconds <= 0.0:
            return
        now = time.monotonic()
        if self._last_request_timestamp is not None:
            elapsed = now - self._last_request_timestamp
            remaining = self.pacing_seconds - elapsed
            if remaining > 0:
                logger.info("Rate-limit pacing: waiting %.1f seconds before next API request...", remaining)
                if self.on_pacing_wait:
                    self.on_pacing_wait(remaining)
                self._sleep(remaining)
        self._last_request_timestamp = time.monotonic()

    @staticmethod
    def create_wav_header(
        pcm_data: bytes,
        sample_rate: int = 24000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> bytes:
        """
        Creates a standard 44-byte RIFF/WAVE header for linear PCM audio data.
        """
        byte_rate = sample_rate * channels * (bits_per_sample // 8)
        block_align = channels * (bits_per_sample // 8)
        data_size = len(pcm_data)
        file_size = 36 + data_size

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            file_size,
            b"WAVE",
            b"fmt ",
            16,               # Subchunk1Size for PCM
            1,                # AudioFormat 1 = Linear PCM
            channels,         # NumChannels
            sample_rate,      # SampleRate
            byte_rate,        # ByteRate
            block_align,      # BlockAlign
            bits_per_sample,  # BitsPerSample
            b"data",
            data_size,
        )
        return header + pcm_data

    @staticmethod
    def generate_synthetic_wav(
        duration_seconds: float = 1.0,
        frequency_hz: float = 440.0,
        sample_rate: int = 24000,
    ) -> bytes:
        """
        Generates a valid, playable synthetic sine-wave WAV file.
        Used for offline testing, dry-runs, and diagnostic self-checks.
        """
        total_samples = int(duration_seconds * sample_rate)
        amplitude = 12000
        pcm_chunks = []

        for i in range(total_samples):
            envelope = math.sin(math.pi * i / max(1, total_samples))
            sample_val = int(
                amplitude * envelope * math.sin(2.0 * math.pi * frequency_hz * (i / sample_rate))
            )
            pcm_chunks.append(struct.pack("<h", max(-32768, min(32767, sample_val))))

        raw_pcm = b"".join(pcm_chunks)
        return GeminiTtsClient.create_wav_header(raw_pcm, sample_rate=sample_rate)

    def _build_payload(
        self,
        text: str,
        voice_name: str,
        style: str = "",
    ) -> Dict[str, Any]:
        """
        Constructs the official Gemini generateContent JSON request payload for TTS.
        Keeps parts[0].text pure without English style prefixes to prevent dialect/accent drift.
        """
        resolved_style = self.resolve_style_instruction(style)
        processed_text = DialogueTurnAnnotator.replace_inline_expressive_tags(text)

        is_custom_voice = voice_name.startswith("voice_") or voice_name.startswith("voices/")
        clean_voice_id = voice_name.replace("voices/", "")
        if is_custom_voice:
            voice_config: Dict[str, Any] = {"customVoiceConfig": {"voiceId": clean_voice_id}}
        else:
            voice_config = {
                "prebuiltVoiceConfig": {
                    "voiceName": voice_name
                }
            }

        final_text = f"{resolved_style}\n\n{processed_text}" if (resolved_style and resolved_style.strip()) else processed_text
        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {"text": final_text}
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": voice_config
                },
            },
        }
        return payload

    def _build_multi_speaker_payload(
        self,
        turns: List[Dict[str, str]],
        speaker1_voice: str = "Charon",
        speaker2_voice: str = "Kore",
    ) -> Dict[str, Any]:
        """
        Constructs the official 2-speaker multiSpeakerVoiceConfig payload for dramatic dialogue.
        """
        dialogue_lines: List[str] = []
        turn_metadata: List[Dict[str, str]] = []

        for turn in turns:
            spk = turn.get("speaker", "Speaker1")
            txt = turn.get("text", "").strip()
            sty = turn.get("style", "natural narrator")
            if not txt:
                continue
            dialogue_lines.append(f"{spk} ({sty}): {txt}")
            turn_metadata.append({
                "speaker": spk,
                "style": sty,
                "text": txt,
            })

        full_script = "\n".join(dialogue_lines)

        return {
            "contents": [
                {
                    "parts": [
                        {"text": full_script}
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "multiSpeakerVoiceConfig": {
                        "speakerVoiceConfigs": [
                            {
                                "speaker": "Speaker1",
                                "voiceConfig": {
                                    "prebuiltVoiceConfig": {"voiceName": speaker1_voice}
                                },
                            },
                            {
                                "speaker": "Speaker2",
                                "voiceConfig": {
                                    "prebuiltVoiceConfig": {"voiceName": speaker2_voice}
                                },
                            },
                        ]
                    }
                },
            },
        }

    def _extract_audio_bytes(self, response_data: Dict[str, Any]) -> bytes:
        """
        Extracts and Base64-decodes audio bytes from diverse Google API response schemas.
        """
        # Format 1: Direct audioContent field (Google Cloud / TTS standard)
        if "audioContent" in response_data and response_data["audioContent"]:
            return base64.b64decode(response_data["audioContent"])

        # Format 2: Direct audio field
        if "audio" in response_data and response_data["audio"]:
            return base64.b64decode(response_data["audio"])

        # Format 3: Gemini contents / candidates payload
        candidates = response_data.get("candidates", [])
        if candidates and isinstance(candidates, list):
            first_candidate = candidates[0]
            content = first_candidate.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                if "inlineData" in part and "data" in part["inlineData"]:
                    return base64.b64decode(part["inlineData"]["data"])
                if "audioData" in part and "data" in part["audioData"]:
                    return base64.b64decode(part["audioData"]["data"])

        # Format 4: Fallback output field
        if "output" in response_data and isinstance(response_data["output"], str):
            try:
                return base64.b64decode(response_data["output"])
            except Exception:
                pass

        raise ValueError(f"Unable to locate Base64 audio in response payload: {list(response_data.keys())}")

    def _execute_tts_request(self, payload: Dict[str, Any], char_count: int) -> bytes:
        """
        Executes a TTS request with strict 60s pacing, smart 2-retry 65s buffer on HTTP 429,
        proactive daily cap rotation (100 for 3.8 / 10 for legacy), and strict model commitment.
        """
        daily_cap = self.get_model_daily_limit(self.model_id)

        while True:
            # Check if current key already reached its proactive daily limit
            current_usage = self.key_usage_counts.get(self.current_key_index, 0)
            if current_usage >= daily_cap:
                rotated = self._rotate_to_next_key(
                    f"proactive daily cap reached ({current_usage}/{daily_cap}) for model {self.model_id}"
                )
                if not rotated:
                    return self._handle_all_keys_exhausted(payload, char_count)

            active_key = self.get_active_api_key()
            endpoint = self.custom_endpoint
            if not endpoint:
                endpoint = f"{self.BASE_API_URL}/{self.model_id}:generateContent?key={active_key}"

            post_data = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "GeminiAudiobookEngine/2.0",
            }

            retries_429 = 0
            transient_retries = 0

            while True:
                self._enforce_pacing()
                req = urllib.request.Request(endpoint, data=post_data, headers=headers, method="POST")
                try:
                    logger.info(
                        "Sending Gemini TTS request [model=%s, key=#%d (%d/%d used), chars=%d]...",
                        self.model_id,
                        self.current_key_index + 1,
                        self.key_usage_counts.get(self.current_key_index, 0) + 1,
                        daily_cap,
                        char_count,
                    )
                    with urllib.request.urlopen(req, timeout=90) as response:
                        raw_response = response.read().decode("utf-8")
                        json_resp = json.loads(raw_response)
                        decoded_bytes = self._extract_audio_bytes(json_resp)

                        # Increment usage counter for active key
                        self.key_usage_counts[self.current_key_index] = (
                            self.key_usage_counts.get(self.current_key_index, 0) + 1
                        )

                        # Rotate immediately if key just hit the daily cap so next request uses fresh key
                        if self.key_usage_counts[self.current_key_index] >= daily_cap and len(self.api_keys) > 1:
                            logger.info(
                                "API key #%d reached daily limit (%d/%d). Pre-rotating for subsequent requests.",
                                self.current_key_index + 1,
                                self.key_usage_counts[self.current_key_index],
                                daily_cap,
                            )
                            self._rotate_to_next_key(f"reached {daily_cap} requests")

                        if decoded_bytes.startswith(b"RIFF"):
                            return decoded_bytes
                        return self.create_wav_header(decoded_bytes, sample_rate=24000)

                except urllib.error.HTTPError as err:
                    error_body = ""
                    try:
                        error_body = err.read().decode("utf-8", errors="ignore")
                    except Exception:
                        pass

                    logger.warning(
                        "HTTP Error %d on key #%d: %s | Body: %s",
                        err.code,
                        self.current_key_index + 1,
                        err.reason,
                        error_body[:300],
                    )

                    if err.code == 429 or "RESOURCE_EXHAUSTED" in error_body:
                        used_so_far = self.key_usage_counts.get(self.current_key_index, 0)
                        if used_so_far < daily_cap and retries_429 < self.max_429_retries_per_key:
                            retries_429 += 1
                            logger.warning(
                                "HTTP 429 received on key #%d before daily cap (%d/%d). "
                                "Waiting %.1fs before retry %d/%d on same key...",
                                self.current_key_index + 1,
                                used_so_far,
                                daily_cap,
                                self.retry_429_wait_seconds,
                                retries_429,
                                self.max_429_retries_per_key,
                            )
                            if self.on_pacing_wait:
                                self.on_pacing_wait(self.retry_429_wait_seconds)
                            self._sleep(self.retry_429_wait_seconds)
                            self._last_request_timestamp = time.monotonic()
                            continue

                        # Persistent 429 after retries or cap reached -> rotate to next key
                        rotated = self._rotate_to_next_key(
                            f"persistent HTTP 429 after {retries_429} retries"
                        )
                        if rotated:
                            break  # Break inner loop to use the new key in outer loop
                        return self._handle_all_keys_exhausted(payload, char_count)

                    if err.code in (500, 502, 503, 504) and transient_retries < self.max_retries:
                        transient_retries += 1
                        backoff = transient_retries * 2.5
                        self._sleep(backoff)
                        continue

                    raise RuntimeError(
                        f"[GeminiTtsClient] فشل طلب تحويل النص إلى صوت عبر النموذج '{self.model_id}' "
                        f"(HTTP {err.code}: {err.reason}). السبب التفصيلي: {error_body[:200]}. "
                        f"الإجراء المقترح: تحقق من صلاحية مفتاح API أو اتصال الإنترنت ثم أعد المحاولة."
                    ) from err

                except Exception as exc:
                    if isinstance(exc, (QuotaExhaustedError, RuntimeError)):
                        raise
                    transient_retries += 1
                    logger.warning(
                        "Network exception on attempt %d/%d: %s",
                        transient_retries,
                        self.max_retries,
                        str(exc),
                    )
                    if transient_retries >= self.max_retries:
                        raise RuntimeError(
                            f"[GeminiTtsClient] تعذر الاتصال بخادم Gemini TTS بعد {self.max_retries} محاولات. "
                            f"السبب: {str(exc)}. الإجراء المقترح: تحقق من اتصال الشبكة أو جرب لاحقاً."
                        ) from exc
                    self._sleep(transient_retries * 2.0)

    def _handle_all_keys_exhausted(self, payload: Dict[str, Any], char_count: int) -> bytes:
        """
        Invoked when all configured API keys are exhausted for the user-selected model.
        Never switches models silently! Calls on_all_keys_exhausted callback if provided,
        otherwise raises QuotaExhaustedError so the caller/UI can prompt the user and save progress.
        """
        total_keys = len(self.api_keys)
        if self.on_all_keys_exhausted is not None:
            chosen_model = self.on_all_keys_exhausted(self.model_id, total_keys)
            if chosen_model and chosen_model != self.model_id:
                logger.info(
                    "User explicitly authorized model switch from '%s' to '%s'. Resetting key counters.",
                    self.model_id,
                    chosen_model,
                )
                self.model_id = chosen_model
                self.current_key_index = 0
                self.exhausted_key_indices.clear()
                self.key_usage_counts = {i: 0 for i in range(len(self.api_keys))}
                return self._execute_tts_request(payload, char_count)

        raise QuotaExhaustedError(
            f"[GeminiTtsClient] نفدت الحصة اليومية لجميع مفاتيح API المتاحة ({total_keys} مفتاح) "
            f"على النموذج المختار '{self.model_id}'. تم حفظ التقدم بأمان؛ يمكنك إضافة مفاتيح جديدة "
            f"أو الانتظار حتى تجديد الحصة اليومية أو اختيار نموذج آخر يدوياً."
        )

    def synthesize(
        self,
        text: str,
        voice_name: str = "Kore",
        style: str = "",
    ) -> bytes:
        """
        Synthesizes the given text to playable WAV audio bytes.
        """
        clean_text = text.strip()
        if not clean_text:
            return self.generate_synthetic_wav(duration_seconds=0.1)

        if self.mock_mode:
            logger.info("Synthesizing mock audio for text segment (%d chars)...", len(clean_text))
            simulated_duration = max(0.5, min(10.0, len(clean_text) / 15.0))
            return self.generate_synthetic_wav(duration_seconds=simulated_duration)

        payload = self._build_payload(clean_text, voice_name=voice_name, style=style)
        return self._execute_tts_request(payload, char_count=len(clean_text))

    def synthesize_multi_speaker(
        self,
        text: str,
        speaker1_voice: str = "Charon",
        speaker2_voice: str = "Kore",
        narrator_style: str = "natural audiobook narrator, clear pronunciation",
        character_default_style: str = "expressive character dialogue",
    ) -> bytes:
        """
        Synthesizes dramatic 2-speaker audio (Speaker1: Narrator, Speaker2: Character)
        with automatic emotional style inference from Arabic narrative cues.
        """
        clean_text = text.strip()
        if not clean_text:
            return self.generate_synthetic_wav(duration_seconds=0.1)

        turns = DialogueTurnAnnotator.extract_turns(
            clean_text,
            narrator_style=self.resolve_style_instruction(narrator_style),
            character_default_style=character_default_style,
        )

        if self.mock_mode:
            logger.info(
                "Synthesizing mock multi-speaker audio (%d turns, %d chars)...",
                len(turns),
                len(clean_text),
            )
            simulated_duration = max(0.5, min(10.0, len(clean_text) / 15.0))
            return self.generate_synthetic_wav(duration_seconds=simulated_duration)

        payload = self._build_multi_speaker_payload(
            turns=turns,
            speaker1_voice=speaker1_voice,
            speaker2_voice=speaker2_voice,
        )
        return self._execute_tts_request(payload, char_count=len(clean_text))

    def list_custom_voices(self) -> List[Dict[str, Any]]:
        """
        Fetches custom voices from the official Google /v1beta/voices endpoint.
        Returns list of custom voice dicts: [{'id': ..., 'name': ..., 'type': 'prompted'|'replicated', 'description': ...}].
        """
        api_key = self.get_active_api_key()
        if not api_key:
            return []

        url = f"{self.VOICES_API_URL}?key={api_key}"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "x-goog-api-key": api_key,
                    "User-Agent": "GeminiAudiobookEngine/2.0",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                voices_raw = data.get("voices", [])
                result = []
                for v in voices_raw:
                    vid = v.get("id") or v.get("name", "").replace("voices/", "")
                    if not vid:
                        continue
                    disp = v.get("displayName") or v.get("display_name") or vid
                    v_type = v.get("type", "prompted")
                    prompt_obj = v.get("prompted", {})
                    prompt_desc = prompt_obj.get("input", "") if isinstance(prompt_obj, dict) else ""
                    if v_type == "replicated" or "replicated" in v:
                        v_type = "replicated"
                        desc = "صوت مستنسخ بالذكاء الاصطناعي (Replicated Voice)"
                    else:
                        v_type = "prompted"
                        desc = prompt_desc or f"صوت مصمم: {disp}"

                    result.append({
                        "id": vid,
                        "name": disp,
                        "gender": "مخصص",
                        "gender_ar": "مخصص",
                        "gender_en": "Custom",
                        "type": v_type,
                        "style_ar": desc,
                        "trait_ar": desc,
                        "trait_en": desc,
                    })
                return result
        except Exception as exc:
            logger.warning("Listing custom voices from v1beta/voices failed: %s", str(exc))
            return []

    def create_prompted_voice(
        self,
        voice_name: str,
        prompt_description: str,
        model_id: str = "gemini-3.8-flash-tts",
    ) -> Tuple[str, Optional[bytes]]:
        """
        Designs and stores a new custom voice from text description using official Google Gemini API (Free Tier compatible).
        Endpoint: POST /v1beta/voices?key=$apiKey
        Returns: (voice_id, sample_audio_bytes)
        """
        clean_name = voice_name.strip()
        clean_prompt = prompt_description.strip()
        if not clean_name or not clean_prompt:
            raise ValueError(
                "[VoiceStudio] فشل إنشاء الصوت: اسم الصوت والوصف مطلوبان. "
                "الإجراء: أدخل اسماً للصوت ووصفاً دقيقاً للنبرة والطبقة."
            )

        api_key = self.get_active_api_key()
        if not api_key:
            raise ValueError("مفتاح API غير متوفر. يرجى إضافة مفتاح API في الإعدادات.")

        clean_model = model_id.replace("models/", "")
        url = f"{self.VOICES_API_URL}?key={api_key}"
        payload = {
            "store": True,
            "voice": {
                "model": clean_model,
                "type": "prompted",
                "display_name": clean_name,
                "prompted": {
                    "input": clean_prompt,
                },
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                "User-Agent": "GeminiAudiobookEngine/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8")
                res_json = json.loads(body)
                vid = res_json.get("id") or res_json.get("name", "").replace("voices/", "")
                if not vid and "voice" in res_json:
                    v_obj = res_json["voice"]
                    vid = v_obj.get("id") or v_obj.get("name", "").replace("voices/", "")

                if not vid:
                    raise RuntimeError(f"لم يُرجع الخادم معرف الصوت (Voice ID). الاستجابة: {body}")

                sample_b64 = ""
                sample_obj = res_json.get("sample_audio") or res_json.get("sampleAudio")
                if isinstance(sample_obj, dict):
                    sample_b64 = sample_obj.get("data", "")
                elif isinstance(sample_obj, str):
                    sample_b64 = sample_obj

                sample_bytes = None
                if sample_b64:
                    raw = base64.b64decode(sample_b64)
                    if raw[:4] == b"RIFF":
                        sample_bytes = raw
                    else:
                        sample_bytes = self.create_wav_header(raw, sample_rate=24000)

                return vid, sample_bytes
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"فشل تصميم الصوت ({err.code}): {err_body}") from err

    def create_replicated_voice(
        self,
        voice_name: str,
        reference_audio_bytes: bytes,
        consent_audio_bytes: bytes,
        model_id: str = "gemini-3.8-flash-tts",
    ) -> Tuple[str, Optional[bytes]]:
        """
        Creates and stores a replicated voice from reference speech and consent audio using official Google API.
        Requires a Paid Gemini API key (Google Cloud Pay-as-you-go).
        Endpoint: POST /v1beta/voices?key=$apiKey
        Returns: (voice_id, sample_audio_bytes)
        """
        clean_name = voice_name.strip()
        if not clean_name:
            raise ValueError("اسم الصوت المستنسخ مطلوب.")
        if not reference_audio_bytes or len(reference_audio_bytes) < 44:
            raise ValueError("عينة الصوت المرجعية غير صالحة أو فارغة.")
        if not consent_audio_bytes or len(consent_audio_bytes) < 44:
            raise ValueError("عينة الإقرار القانوني الصوتي غير صالحة أو فارغة.")

        api_key = self.get_active_api_key()
        if not api_key:
            raise ValueError("مفتاح API غير متوفر.")

        ref_b64 = base64.b64encode(reference_audio_bytes).decode("ascii")
        consent_b64 = base64.b64encode(consent_audio_bytes).decode("ascii")

        clean_model = model_id.replace("models/", "")
        url = f"{self.VOICES_API_URL}?key={api_key}"
        payload = {
            "store": True,
            "voice": {
                "model": clean_model,
                "type": "replicated",
                "display_name": clean_name,
                "replicated": {
                    "source_audio": {
                        "mime_type": "audio/wav",
                        "data": ref_b64,
                    },
                    "consent_audio": {
                        "mime_type": "audio/wav",
                        "data": consent_b64,
                    },
                },
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                "User-Agent": "GeminiAudiobookEngine/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
                res_json = json.loads(body)
                vid = res_json.get("id") or res_json.get("name", "").replace("voices/", "")
                if not vid and "voice" in res_json:
                    v_obj = res_json["voice"]
                    vid = v_obj.get("id") or v_obj.get("name", "").replace("voices/", "")

                if not vid:
                    raise RuntimeError(f"لم يُرجع الخادم معرف الصوت المستنسخ. الاستجابة: {body}")

                sample_b64 = ""
                sample_obj = res_json.get("sample_audio") or res_json.get("sampleAudio")
                if isinstance(sample_obj, dict):
                    sample_b64 = sample_obj.get("data", "")
                elif isinstance(sample_obj, str):
                    sample_b64 = sample_obj

                sample_bytes = None
                if sample_b64:
                    raw = base64.b64decode(sample_b64)
                    if raw[:4] == b"RIFF":
                        sample_bytes = raw
                    else:
                        sample_bytes = self.create_wav_header(raw, sample_rate=24000)

                return vid, sample_bytes
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            err_lower = err_body.lower()
            if err.code == 403 or "billing" in err_lower or "quota" in err_lower or "paid" in err_lower:
                raise RuntimeError(
                    "ميزة استنساخ الصوت تتطلب حساباً مفعلاً في Google Cloud (Pay-as-you-go / Paid API Key). "
                    "الحصة المجانية لا تدعم استنساخ الصوت حالياً."
                ) from err
            elif "consent" in err_lower or "match" in err_lower:
                raise RuntimeError(
                    "فشل التحقق من الموافقة: يرجى التأكد من تسجيل عبارة الإقرار الإنجليزية بدقة وبصوت نفس المتحدث."
                ) from err
            elif "duration" in err_lower or "short" in err_lower:
                raise RuntimeError(
                    "عينة الصوت قصيرة جداً؛ يرجى تسجيل عينة صوتية لا تقل مدتها عن 10 ثوانٍ."
                ) from err
            else:
                raise RuntimeError(f"فشل استنساخ الصوت ({err.code}): {err_body}") from err

    @staticmethod
    def atomic_save_audio(file_path: Union[str, Path], audio_bytes: bytes) -> None:
        """
        Saves audio bytes atomically to disk using tempfile.NamedTemporaryFile and os.replace.
        """
        import tempfile
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(target.parent),
                prefix=f".{target.stem}_",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write(audio_bytes)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, str(target))
            logger.info("Saved audio file atomically to: %s (%d bytes)", target, len(audio_bytes))
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise


