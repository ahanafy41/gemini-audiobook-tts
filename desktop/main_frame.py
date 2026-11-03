#!/usr/bin/env python3
"""
NVDA-Accessible Main Window (MainFrame) for Gemini Audiobook Desktop.
Implements a modern, professional, bilingual (English default + Arabic) Hub & Panel interface:
- Top Hub Navigation Bar with 4 large toggle buttons (height >= 44px): Library, Player, Voices, Settings.
- Central Content Host: Opens chosen panel on click, toggles off to clean empty state on second click.
- 100% NVDA Screen Reader accessibility:
  - Dynamic state announcements (e.g., 'Library panel - open' / 'لوحة المكتبة - مفتوحة').
  - Immediate focus delegation to the first interactive element upon opening any panel.
  - Context-aware keyboard shortcuts active exclusively when the relevant panel is open.
- All background thread UI updates are marshaled exclusively via wx.CallAfter.
"""

import ctypes
import json
import logging
import sys
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import wx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from book_parser import BookParser, ParsedBook
from doctor import EnvironmentDoctor
from gemini_tts_client import GeminiTtsClient, DialogueTurnAnnotator
from player_service import AudiobookPlayerService

import desktop.i18n as i18n
from desktop.i18n import (
    APP_NAME,
    MODEL_CHOICES,
    PREBUILT_VOICES_CATALOG,
    STYLE_PRESETS,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    format_voice_choice,
    get_model_labels,
    normalize_lang,
    tr,
)
from desktop.settings_manager import (
    SUPPORTED_MODELS,
    SettingsManager,
)
from desktop.worker import (
    SynthesisWorker,
    atomic_write_bytes,
    detect_dialogue_and_emotions,
    get_adaptive_chunk_limit,
    merge_and_normalize_wav_files,
    sanitize_book_folder_name,
)

logger = logging.getLogger("DesktopMainFrame")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# Ensure required translation keys exist in i18n.TRANSLATIONS for both English and Arabic
_EXTRA_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "app_title": "Gemini Audiobook",
        "btn_start_convert": "&Start Conversion",
        "btn_resume_convert": "&Resume Conversion",
        "btn_converting_busy": "Synthesizing...",
        "btn_testing_api_busy": "Testing Connection...",
        "status_stats": "Mode: {mode} | Characters: {chars} | Chapters: {chapters} | Estimated Requests: {chunks}",
        "msg_export_blocked_title": "Conversion in Progress",
        "msg_export_blocked_running": (
            "Audio conversion is still in progress. Please wait until all chapters finish "
            "converting before exporting the complete WAV file."
        ),
        "menu_file_start_convert": "&Start Conversion\tF5",
        "menu_file_pause_cancel": "Pa&use / Cancel\tEsc",
        "menu_playback_play_pause_space": "&Play / Pause\tSpace",
        "menu_playback_rewind_15": "&Rewind 15s",
        "menu_playback_forward_30": "&Forward 30s",
        "menu_playback_prev_pgup": "Pre&vious Chapter\tPgUp",
        "menu_playback_next_pgdn": "&Next Chapter\tPgDn",
        "menu_voices_audition_narrator": "Audition &Narrator Voice",
        "menu_voices_audition_character": "Audition &Character Voice",
        "menu_voices_sync_menu": "&Sync Voices",
        "menu_tools_test_api": "&Test API Connection\tCtrl+T",
        "menu_tools_diagnostics": "System &Diagnostics",
        "menu_tools_updates": "Check for &Updates",
        "btn_rewind_15": "-15 Seconds",
        "acc_rewind_15": "Rewind 15 seconds",
        "btn_forward_30": "+30 Seconds",
        "acc_forward_30": "Forward 30 seconds",
        "dlg_conversion_complete_merged": (
            "{message}\n\nComplete Merged Audiobook:\n{merged_path}"
        ),
        "player_select_chapter_first": "Please select a chapter from the list first.",
        "nav_library": "Library",
        "nav_player": "Player",
        "nav_voices": "Voices",
        "nav_settings": "Settings",
        "nav_state_open": "open",
        "nav_state_closed": "closed",
        "nav_accessible_pattern": "{name} panel - {state}",
        "content_host_accessible_name": "Main Content Area",
        "acc_bottom_status_panel": "Global synthesis status bar",
        "status_book_restored_with_progress": "Restored book: '{title}' ({completed}/{total} chapters, {chunks} parts saved). Ready to resume.",
        "status_idle_ready": "Ready - Awaiting conversion.",
        "shortcut_focus_status": "Focus Status Bar\tF4",
    },
    "ar": {
        "app_title": "Gemini Audiobook",
        "btn_start_convert": "&بدء التحويل",
        "btn_resume_convert": "ا&ستئناف التحويل",
        "btn_converting_busy": "جارِ توليد الصوت...",
        "btn_testing_api_busy": "جارِ فحص الاتصال...",
        "status_stats": "النمط: {mode} | الأحرف: {chars} | الفصول: {chapters} | الطلبات المتوقعة: {chunks}",
        "msg_export_blocked_title": "التحويل قيد التنفيذ",
        "msg_export_blocked_running": (
            "عملية التحويل الصوتي لا تزال جارية. يرجى الانتظار حتى اكتمال جميع الفصول "
            "قبل تصدير ملف WAV الكامل."
        ),
        "menu_file_start_convert": "&بدء التحويل\tF5",
        "menu_file_pause_cancel": "إي&قاف مؤقت / إلغاء\tEsc",
        "menu_playback_play_pause_space": "&تشغيل / إيقاف مؤقت\tSpace",
        "menu_playback_rewind_15": "تأ&خير 15 ثانية",
        "menu_playback_forward_30": "تق&ديم 30 ثانية",
        "menu_playback_prev_pgup": "الفصل ال&سابق\tPgUp",
        "menu_playback_next_pgdn": "الفصل ال&تالي\tPgDn",
        "menu_voices_audition_narrator": "معاينة صوت ال&راوي",
        "menu_voices_audition_character": "معاينة صوت ال&شخصية",
        "menu_voices_sync_menu": "&مزامنة الأصوات",
        "menu_tools_test_api": "&فحص اتصال API\tCtrl+T",
        "menu_tools_diagnostics": "&فحص جاهزية النظام",
        "menu_tools_updates": "فحص ال&تحديثات",
        "btn_rewind_15": "تأخير 15 ثانية",
        "acc_rewind_15": "تأخير التشغيل 15 ثانية",
        "btn_forward_30": "تقديم 30 ثانية",
        "acc_forward_30": "تقديم التشغيل 30 ثانية",
        "dlg_conversion_complete_merged": (
            "{message}\n\nملف الكتاب الصوتي الكامل المدمج:\n{merged_path}"
        ),
        "player_select_chapter_first": "يرجى اختيار فصل من القائمة أولاً.",
        "nav_library": "المكتبة",
        "nav_player": "المشغل",
        "nav_voices": "الأصوات",
        "nav_settings": "الإعدادات",
        "nav_state_open": "مفتوحة",
        "nav_state_closed": "مغلقة",
        "nav_accessible_pattern": "لوحة {name} - {state}",
        "content_host_accessible_name": "منطقة المحتوى الرئيسية",
        "acc_bottom_status_panel": "شريط حالة التحويل الصوتي العام",
        "status_book_restored_with_progress": "تم استرجاع كتاب: '{title}' (محفوظ {completed} من {total} فصول، و{chunks} مقطع). جاهز للاستئناف.",
        "status_idle_ready": "جاهز - في انتظار بدء التحويل.",
        "shortcut_focus_status": "التركيز على شريط الحالة\tF4",
    },
}

for _lang_code, _entries in _EXTRA_TRANSLATIONS.items():
    _target_dict = TRANSLATIONS.setdefault(_lang_code, {})
    for _k, _v in _entries.items():
        _target_dict.setdefault(_k, _v)


def get_style_choices(lang: str = "en") -> List[str]:
    """Returns localized delivery style labels via desktop.i18n."""
    if hasattr(i18n, "get_style_choices"):
        return i18n.get_style_choices(lang)  # type: ignore
    return i18n.get_style_labels(lang)


def read_book_file_with_docx_fallback(file_path: Path) -> str:
    """
    Reads .txt, .md, or .docx files safely. Uses python-docx if installed,
    or standard library zipfile + xml.etree.ElementTree for .docx extraction.
    """
    if file_path.suffix.lower() == ".docx":
        try:
            import docx  # type: ignore

            doc = docx.Document(str(file_path))
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
            return "\n\n".join(paragraphs)
        except Exception:
            with zipfile.ZipFile(str(file_path), "r") as zf:
                xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            ns_p = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
            ns_t = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            extracted_paras: List[str] = []
            for p_elem in root.iter(ns_p):
                runs = [t_elem.text for t_elem in p_elem.iter(ns_t) if t_elem.text]
                joined = "".join(runs).strip()
                if joined:
                    extracted_paras.append(joined)
            return "\n\n".join(extracted_paras)

    return BookParser.read_file_safe(file_path)


class WindowsMciAudioPlayer:
    """
    Native Windows Multimedia Control Interface (winmm.dll MCI) audio player
    supporting WAV playback, pause, resume, millisecond seeking, and speed scaling,
    with automatic fallback to AudiobookPlayerService on non-Windows platforms.
    """

    ALIAS = "gemini_audiobook_mci"

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self.is_windows = sys.platform.startswith("win") and hasattr(ctypes, "windll")
        self.fallback_player = AudiobookPlayerService(state_dir=state_dir)
        self.current_file: Optional[str] = None
        self.is_Loaded = False
        self.is_playing = False
        self.is_paused = False
        self.speed_factor = 1000
        self._sim_position_ms = 0
        self._sim_duration_ms = 0

    def _mci_send(self, command: str) -> Tuple[int, str]:
        if not self.is_windows:
            return (0, "")
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(command, buf, 255, 0)
        if err != 0:
            err_buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.winmm.mciGetErrorStringW(err, err_buf, 255)
            logger.debug("MCI command '%s' returned %d: %s", command, err, err_buf.value)
        return (err, buf.value.strip())

    def open_and_play(self, file_path: str, start_ms: int = 0, speed_str: str = "1.0x") -> bool:
        target = Path(file_path)
        if not target.is_file():
            return False

        self.stop()
        self.current_file = str(target.resolve())

        # Convert to short path for MCI compatibility with Arabic/Unicode paths
        if self.is_windows:
            try:
                buf_size = ctypes.windll.kernel32.GetShortPathNameW(self.current_file, None, 0)
                if buf_size > 0:
                    short_buf = ctypes.create_unicode_buffer(buf_size)
                    if ctypes.windll.kernel32.GetShortPathNameW(self.current_file, short_buf, buf_size):
                        self.current_file = short_buf.value
            except Exception:
                pass  # Fall back to original path if GetShortPathNameW fails

        if not self.is_windows:
            ok = self.fallback_player.play(self.current_file)
            self.is_Loaded = ok
            self.is_playing = ok
            self.is_paused = False
            self._sim_position_ms = start_ms
            self._sim_duration_ms = max(1000, int(target.stat().st_size / 48))
            return ok

        err, _ = self._mci_send(f'open "{self.current_file}" type mpegvideo alias {self.ALIAS}')
        if err != 0:
            err, _ = self._mci_send(f'open "{self.current_file}" type waveaudio alias {self.ALIAS}')
            if err != 0:
                return False

        self._mci_send(f"set {self.ALIAS} time format milliseconds")
        self.is_Loaded = True
        self.set_speed(speed_str)

        play_cmd = f"play {self.ALIAS} from {max(0, int(start_ms))}"
        err, _ = self._mci_send(play_cmd)
        if err != 0:
            err, _ = self._mci_send(f"play {self.ALIAS}")

        self.is_playing = err == 0
        self.is_paused = False
        return self.is_playing

    def toggle_play_pause(self) -> str:
        if not self.is_Loaded:
            return "stopped"
        if self.is_playing and not self.is_paused:
            if self.is_windows:
                self._mci_send(f"pause {self.ALIAS}")
            else:
                self.fallback_player.pause()
            self.is_paused = True
            self.is_playing = False
            return "paused"
        else:
            if self.is_windows:
                err, _ = self._mci_send(f"resume {self.ALIAS}")
                if err != 0:
                    pos = self.get_position_ms()
                    self._mci_send(f"play {self.ALIAS} from {pos}")
            else:
                self.fallback_player.resume()
            self.is_paused = False
            self.is_playing = True
            return "playing"

    def seek_relative(self, delta_ms: int) -> int:
        if not self.is_Loaded:
            return 0
        cur = self.get_position_ms()
        total = self.get_length_ms()
        target = max(0, cur + delta_ms)
        if total > 0:
            target = min(total, target)

        if self.is_windows:
            if self.is_playing:
                self._mci_send(f"play {self.ALIAS} from {target}")
            else:
                self._mci_send(f"seek {self.ALIAS} to {target}")
        else:
            self._sim_position_ms = target
        return target

    def set_speed(self, speed_str: str) -> None:
        clean = speed_str.lower().replace("x", "").strip()
        try:
            ratio = float(clean)
        except ValueError:
            ratio = 1.0
        self.speed_factor = max(500, min(2500, int(round(ratio * 1000))))
        if self.is_windows and self.is_Loaded:
            self._mci_send(f"set {self.ALIAS} speed {self.speed_factor}")

    def get_position_ms(self) -> int:
        if not self.is_Loaded:
            return 0
        if self.is_windows:
            err, val = self._mci_send(f"status {self.ALIAS} position")
            if err == 0 and val.isdigit():
                return int(val)
            return 0
        return self._sim_position_ms

    def get_length_ms(self) -> int:
        if not self.is_Loaded:
            return 0
        if self.is_windows:
            err, val = self._mci_send(f"status {self.ALIAS} length")
            if err == 0 and val.isdigit():
                return int(val)
            return 0
        return self._sim_duration_ms

    def get_mode(self) -> str:
        if not self.is_Loaded:
            return "stopped"
        if self.is_windows:
            err, val = self._mci_send(f"status {self.ALIAS} mode")
            if err == 0 and val:
                return val.lower()
        return "playing" if self.is_playing else ("paused" if self.is_paused else "stopped")

    def stop(self) -> None:
        if self.is_windows:
            self._mci_send(f"stop {self.ALIAS}")
            self._mci_send(f"close {self.ALIAS}")
        else:
            self.fallback_player.stop()
        self.is_Loaded = False
        self.is_playing = False
        self.is_paused = False



class NavButtonAccessible(wx.Accessible):
    """
    Ensures primary navigation buttons report as real push buttons (Role: PUSHBUTTON, not Checkbox)
    with dynamic pressed/not-pressed accessibility states for NVDA and screen readers,
    without duplicate text suffixes.
    """

    def __init__(self, win: wx.Window, is_active_callback, get_name_callback, lang_callback=None) -> None:
        super().__init__(win)
        self.is_active = is_active_callback
        self.get_name = get_name_callback

    def GetRole(self, childId: int):
        return (wx.ACC_OK, wx.ROLE_SYSTEM_PUSHBUTTON)

    def GetState(self, childId: int):
        state = wx.ACC_STATE_SYSTEM_FOCUSABLE
        if self.is_active():
            state |= wx.ACC_STATE_SYSTEM_PRESSED
        return (wx.ACC_OK, state)

    def GetName(self, childId: int):
        return (wx.ACC_OK, self.get_name())



class MainFrame(wx.Frame):
    """
    NVDA-Accessible 4-Tab Main Application Window for Gemini Audiobook.
    """

    ID_MENU_OPEN_BOOK = wx.NewIdRef()
    ID_MENU_PASTE_TEXT = wx.NewIdRef()
    ID_MENU_START_SYNTH = wx.NewIdRef()
    ID_MENU_PAUSE_CANCEL = wx.NewIdRef()
    ID_MENU_EXPORT_WAV = wx.NewIdRef()
    ID_MENU_EXIT = wx.NewIdRef()

    ID_MENU_PLAY_PAUSE = wx.NewIdRef()
    ID_MENU_REWIND_15 = wx.NewIdRef()
    ID_MENU_FORWARD_30 = wx.NewIdRef()
    ID_MENU_PREV_CHAPTER = wx.NewIdRef()
    ID_MENU_NEXT_CHAPTER = wx.NewIdRef()
    ID_MENU_SAVE_BOOKMARK = wx.NewIdRef()

    ID_MENU_AUDITION_NARRATOR = wx.NewIdRef()
    ID_MENU_AUDITION_CHARACTER = wx.NewIdRef()
    ID_MENU_SYNC_VOICES = wx.NewIdRef()

    ID_MENU_TEST_API = wx.NewIdRef()
    ID_MENU_DOCTOR = wx.NewIdRef()
    ID_MENU_UPDATES = wx.NewIdRef()

    ID_MENU_LANG_EN = wx.NewIdRef()
    ID_MENU_LANG_AR = wx.NewIdRef()
    ID_FOCUS_STATUS = wx.NewIdRef()

    # Legacy accelerator IDs preserved for backward compatibility
    ID_ACCEL_OPEN_BOOK = ID_MENU_OPEN_BOOK
    ID_ACCEL_PASTE_TEXT = ID_MENU_PASTE_TEXT
    ID_ACCEL_START_SYNTH = ID_MENU_START_SYNTH
    ID_ACCEL_PLAY_PAUSE = ID_MENU_PLAY_PAUSE

    SPEED_CHOICES = ["0.75x", "1.0x", "1.25x", "1.5x", "1.75x", "2.0x"]
    LANGUAGE_CODES = ["en", "ar"]

    GITHUB_RELEASES_LATEST_URL = (
        "https://api.github.com/repos/ahanafy41/gemini-audiobook-tts/releases/latest"
    )

    def __init__(self, settings_manager: Optional[SettingsManager] = None) -> None:
        self.settings_mgr = settings_manager or SettingsManager()
        self.lang: str = normalize_lang(str(self.settings_mgr.get("language", "en")))
        self._sanitize_legacy_settings()

        super().__init__(
            parent=None,
            id=wx.ID_ANY,
            title=tr("app_title", self.lang),
            size=(1020, 760),
        )
        self.SetName(tr("main_window_accessible_name", self.lang))
        self.parser = BookParser()
        self.parsed_book: Optional[ParsedBook] = None
        self.worker: Optional[SynthesisWorker] = None
        self.last_book_output_dir: Optional[Path] = None
        self.audio_player = WindowsMciAudioPlayer()
        self.playable_chapters: List[Dict[str, Any]] = []
        self.current_playing_index: int = -1
        self._active_panel: Optional[str] = None
        self.library_books: List[Dict[str, Any]] = []
        self.active_playing_book_dir: Optional[Path] = None
        self.active_playing_book_title: str = ""
        self.selected_ref_audio_path: str = ""
        self.selected_consent_audio_path: str = ""
        self.last_designed_sample_path: str = ""

        self.main_panel = wx.Panel(self)
        self.main_panel.SetName(tr("main_panel_accessible_name", self.lang))
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # 1. Top Hub Navigation Row: 4 Primary Push Buttons (Library & Player, Editor Studio, Voices, Settings)
        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_nav_library = wx.Button(self.main_panel, label=tr("nav_library", self.lang))
        self.btn_nav_editor = wx.Button(self.main_panel, label=tr("nav_editor", self.lang))
        self.btn_nav_voices = wx.Button(self.main_panel, label=tr("nav_voices", self.lang))
        self.btn_nav_settings = wx.Button(self.main_panel, label=tr("nav_settings", self.lang))

        nav_font = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)

        self._nav_buttons: Dict[str, wx.Button] = {
            "library": self.btn_nav_library,
            "editor": self.btn_nav_editor,
            "voices": self.btn_nav_voices,
            "settings": self.btn_nav_settings,
        }

        for key, btn in self._nav_buttons.items():
            btn.SetMinSize(wx.Size(-1, 48))
            btn.SetFont(nav_font)
            btn.SetAccessible(
                NavButtonAccessible(
                    btn,
                    lambda k=key: self._active_panel == k,
                    lambda k=key: tr(f"nav_{k}", self.lang),
                    lambda: self.lang,
                )
            )
            nav_sizer.Add(btn, 1, wx.EXPAND | wx.ALL, 4)

        main_sizer.Add(nav_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 4)

        # 2. Central Content Host
        self.content_panel = wx.Panel(self.main_panel)
        self.content_panel.SetName(tr("content_host_accessible_name", self.lang))
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)

        # 3. Permanent Bottom Status Panel (always visible across all tabs and empty state)
        self.bottom_status_panel = wx.Panel(self.main_panel)
        self.bottom_status_panel.SetName(tr("acc_bottom_status_panel", self.lang))
        bottom_sizer = wx.BoxSizer(wx.VERTICAL)

        self.lbl_progress = wx.StaticText(self.bottom_status_panel, label=tr("lbl_progress", self.lang))
        self.gauge_progress = wx.Gauge(
            self.bottom_status_panel,
            range=100,
            style=wx.GA_HORIZONTAL | wx.GA_SMOOTH,
        )
        self.gauge_progress.SetName(tr("acc_progress", self.lang))
        bottom_sizer.Add(self.lbl_progress, 0, wx.LEFT | wx.RIGHT | wx.TOP, 2)
        bottom_sizer.Add(self.gauge_progress, 0, wx.EXPAND | wx.ALL, 2)

        status_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_synthesis_status = wx.StaticText(
            self.bottom_status_panel,
            label=tr("lbl_synthesis_status", self.lang),
        )
        self.txt_synthesis_status = wx.TextCtrl(
            self.bottom_status_panel,
            value=tr("status_idle_ready", self.lang),
            style=wx.TE_READONLY,
        )
        self.txt_synthesis_status.SetName(tr("acc_synthesis_status", self.lang))
        self.txt_synthesis_status.SetMinSize(wx.Size(-1, 32))

        status_row.Add(self.lbl_synthesis_status, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        status_row.Add(self.txt_synthesis_status, 1, wx.EXPAND, 0)
        bottom_sizer.Add(status_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        self.bottom_status_panel.SetSizer(bottom_sizer)

        self.tab_library = wx.Panel(self.content_panel)
        self.tab_library.SetName(tr("tab_library_acc", self.lang))

        self.tab_editor = wx.Panel(self.content_panel)
        self.tab_editor.SetName(tr("tab_editor_acc", self.lang))

        self.tab_voices = wx.Panel(self.content_panel)
        self.tab_voices.SetName(tr("tab_voices_acc", self.lang))

        self.tab_settings = wx.Panel(self.content_panel)
        self.tab_settings.SetName(tr("tab_settings_acc", self.lang))

        self._build_tab_library()
        self._build_tab_editor()
        self._build_tab_voices()
        self._build_tab_settings()

        self._panels: Dict[str, wx.Panel] = {
            "library": self.tab_library,
            "editor": self.tab_editor,
            "voices": self.tab_voices,
            "settings": self.tab_settings,
        }

        # Initially, all 4 panels are hidden (content host is completely empty)
        for panel in self._panels.values():
            self.content_sizer.Add(panel, 1, wx.EXPAND)
            panel.Hide()

        self.content_panel.SetSizer(self.content_sizer)
        main_sizer.Add(self.content_panel, 1, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(self.bottom_status_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.main_panel.SetSizer(main_sizer)

        # Bind Hub Navigation Events (Primary Push Buttons with Toggle Semantics)
        self.btn_nav_library.Bind(wx.EVT_BUTTON, lambda evt: self._toggle_panel("library"))
        self.btn_nav_editor.Bind(wx.EVT_BUTTON, lambda evt: self._toggle_panel("editor"))
        self.btn_nav_voices.Bind(wx.EVT_BUTTON, lambda evt: self._toggle_panel("voices"))
        self.btn_nav_settings.Bind(wx.EVT_BUTTON, lambda evt: self._toggle_panel("settings"))

        self._bind_command_events()
        self._update_nav_button_accessible_names()
        self._update_context_shortcuts()
        self._setup_player_timer()
        self.Bind(wx.EVT_CLOSE, self._on_close_window)

        self._refresh_voice_choices()
        self._refresh_playable_chapters()
        self._update_live_text_analysis()
        self._auto_restore_last_book_session()
        self.Centre()

    def _sanitize_legacy_settings(self) -> None:
        """
        Ensures language defaults cleanly to 'en' and cleans any legacy English
        style_prompt when Natural style (index 0) is active to prevent dialect drift.
        """
        changed = False
        if not self.settings_mgr.get("language"):
            self.settings_mgr.set("language", "en", auto_save=False)
            changed = True

        style_idx = int(self.settings_mgr.get("style_index", 0) or 0)
        current_prompt = str(self.settings_mgr.get("style_prompt", "") or "")
        valid_prompts = {s["prompt"] for s in STYLE_PRESETS}
        if style_idx == 0 or current_prompt not in valid_prompts or "Authoritative documentary" in current_prompt:
            if style_idx == 0 or "Authoritative documentary" in current_prompt:
                self.settings_mgr.set("style_index", 0, auto_save=False)
                self.settings_mgr.set("style_label", STYLE_PRESETS[0]["label"], auto_save=False)
                self.settings_mgr.set("style_prompt", "", auto_save=False)
                changed = True

        if changed:
            try:
                self.settings_mgr.save()
            except Exception:
                pass

    def _check_and_update_resume_state(self, book_title: str) -> None:
        """
        Inspects output directory for existing progress.json for this book title
        and updates btn_start_resume to 'Resume Conversion' ONLY if an incomplete
        conversion is actually in progress.
        If the book is completed, or if there is no text in the editor, or no progress,
        it resets to 'Start Conversion'.
        """
        if not hasattr(self, "btn_start_resume"):
            return

        if self.worker is not None and self.worker.is_alive():
            if self.worker.is_paused():
                resume_lbl = tr("btn_resume_convert", self.lang)
                self.btn_start_resume.SetLabel(resume_lbl)
                self.btn_start_resume.SetName(resume_lbl)
            else:
                busy_lbl = tr("btn_converting_busy", self.lang)
                self.btn_start_resume.SetLabel(busy_lbl)
                self.btn_start_resume.SetName(busy_lbl)
            return

        start_lbl = tr("btn_start_convert", self.lang)
        editor_text = self.txt_book_editor.GetValue().strip() if hasattr(self, "txt_book_editor") else ""
        if not editor_text:
            self.btn_start_resume.SetLabel(start_lbl)
            self.btn_start_resume.SetName(start_lbl)
            return

        safe_title = sanitize_book_folder_name(book_title)
        if not safe_title:
            self.btn_start_resume.SetLabel(start_lbl)
            self.btn_start_resume.SetName(start_lbl)
            return

        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir) if hasattr(self, "txt_output_dir") else Path(self.settings_mgr.default_output_dir)
        book_dir = base_out / safe_title
        manifest_file = book_dir / "book_manifest.json"
        prog_file = book_dir / "progress.json"

        # If book is already completed, it's not resumable; treat as fresh start
        is_completed = False
        if manifest_file.is_file():
            try:
                mdata = json.loads(manifest_file.read_text(encoding="utf-8"))
                m_total = mdata.get("total_chapters", 0)
                m_done = len(mdata.get("chapters", []))
                m_status = mdata.get("status", "")
                if m_status == "completed" or (m_total > 0 and m_done >= m_total):
                    is_completed = True
            except Exception:
                pass

        if is_completed:
            self.btn_start_resume.SetLabel(start_lbl)
            self.btn_start_resume.SetName(start_lbl)
            return

        if prog_file.is_file():
            try:
                data = json.loads(prog_file.read_text(encoding="utf-8"))
                comp_chunks = len(data.get("completed_chunks", {}))
                comp_chapters = len(data.get("completed_chapters", {}))
                tot_chapters = (
                    len(self.parsed_book.chapters)
                    if self.parsed_book and self.parsed_book.chapters
                    else (data.get("total_chapters") or 0)
                )
                if (comp_chunks > 0 or comp_chapters > 0) and (tot_chapters == 0 or comp_chapters < tot_chapters):
                    resume_lbl = tr("btn_resume_convert", self.lang)
                    self.btn_start_resume.SetLabel(resume_lbl)
                    self.btn_start_resume.SetName(resume_lbl)
                    msg = tr(
                        "status_book_restored_with_progress",
                        self.lang,
                        title=book_title,
                        completed=comp_chapters,
                        chunks=comp_chunks,
                        total=tot_chapters,
                    )
                    self.txt_synthesis_status.SetValue(msg)
                    return
            except Exception as exc:
                logger.warning("Error reading progress for resume state: %s", exc)

        self.btn_start_resume.SetLabel(start_lbl)
        self.btn_start_resume.SetName(start_lbl)

    def _auto_restore_last_book_session(self) -> None:
        """
        Scans library books. If the last book was completed, does NOT load it into the conversion editor;
        instead, stays cleanly on the Library panel. If incomplete, offers resumption.
        """
        self._refresh_library_books()

        last_book = str(self.settings_mgr.get("last_opened_book", "")).strip()
        if not last_book:
            self._toggle_panel("library")
            return
        book_path = Path(last_book)
        if not book_path.is_file():
            self._toggle_panel("library")
            return

        book_title = book_path.stem.replace("_", " ").strip() or tr("default_book_title", self.lang)
        safe_title = sanitize_book_folder_name(book_title)
        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir) if hasattr(self, "txt_output_dir") else Path(self.settings_mgr.default_output_dir)
        book_dir = base_out / safe_title
        manifest_p = book_dir / "book_manifest.json"

        is_completed = False
        if manifest_p.is_file():
            try:
                data = json.loads(manifest_p.read_text(encoding="utf-8"))
                total = data.get("total_chapters", 0)
                done = len(data.get("chapters", []))
                status = data.get("status", "")
                if status == "completed" or (total > 0 and done >= total):
                    is_completed = True
            except Exception:
                pass

        if is_completed:
            logger.info("Last book '%s' is completed. Defaulting cleanly to Library view.", book_title)
            self._toggle_panel("library")
            return

        try:
            raw_content = read_book_file_with_docx_fallback(book_path)
            if not raw_content.strip():
                self._toggle_panel("library")
                return
            self.txt_book_title.SetValue(book_title)
            self.txt_book_editor.SetValue(raw_content)
            self._parse_and_populate_chapters(raw_content, book_title, str(book_path.resolve()))
            self._check_and_update_resume_state(book_title)
            if hasattr(self, "panel_converter_studio"):
                self.panel_converter_studio.Show()
                self.btn_toggle_converter.SetValue(True)
                self.tab_library.Layout()
            self._toggle_panel("library")
            logger.info("Auto-restored last incomplete book session: %s", book_title)
        except Exception as exc:
            logger.warning("Auto-restoring last book '%s' failed: %s", last_book, exc)
            self._toggle_panel("library")

    # ------------------------------------------------------------------
    # Hub & Panel Navigation & Context Methods
    # ------------------------------------------------------------------
    def _get_first_focus_control(self, panel_key: str) -> Optional[wx.Window]:
        if panel_key == "library":
            return getattr(self, "lst_library_books", None)
        elif panel_key == "editor":
            return getattr(self, "btn_open_book", None)
        elif panel_key == "voices":
            return getattr(self, "choice_primary_voice", None)
        elif panel_key == "settings":
            return getattr(self, "choice_language", None)
        return None

    def _toggle_panel(self, target_panel: str) -> None:
        if self._active_panel == target_panel:
            # Re-clicking the active button toggles it off -> empty state
            self._panels[target_panel].Hide()
            self._active_panel = None
        else:
            # Show chosen panel, hide all others
            for key, panel in self._panels.items():
                if key == target_panel:
                    panel.Show()
                else:
                    panel.Hide()
            self._active_panel = target_panel

        self._update_nav_button_accessible_names()
        self._update_context_shortcuts()

        self.content_panel.Layout()
        self.main_panel.Layout()
        self.Layout()

        if self._active_panel is not None:
            first_ctrl = self._get_first_focus_control(self._active_panel)
            if first_ctrl:
                wx.CallAfter(first_ctrl.SetFocus)

    def _update_nav_button_accessible_names(self) -> None:
        nav_keys = ["library", "editor", "voices", "settings"]
        for key in nav_keys:
            if key not in self._nav_buttons:
                continue
            btn = self._nav_buttons[key]
            clean_name = tr(f"nav_{key}", self.lang)
            btn.SetName(clean_name)
            btn.SetLabel(clean_name)
            try:
                wx.Accessible.NotifyEvent(wx.ACC_EVENT_OBJECT_STATECHANGE, btn, wx.OBJID_CLIENT, 0)
                wx.Accessible.NotifyEvent(wx.ACC_EVENT_OBJECT_NAMECHANGE, btn, wx.OBJID_CLIENT, 0)
            except Exception:
                pass

    def _update_context_shortcuts(self) -> None:
        entries: List[Tuple[int, int, int]] = [
            (wx.ACCEL_NORMAL, wx.WXK_F4, self.ID_FOCUS_STATUS.GetId()),
        ]
        if self._active_panel == "editor":
            entries.extend([
                (wx.ACCEL_CTRL, ord("O"), self.ID_MENU_OPEN_BOOK.GetId()),
                (wx.ACCEL_ALT, ord("O"), self.ID_MENU_OPEN_BOOK.GetId()),
                (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("V"), self.ID_MENU_PASTE_TEXT.GetId()),
                (wx.ACCEL_ALT, ord("V"), self.ID_MENU_PASTE_TEXT.GetId()),
                (wx.ACCEL_NORMAL, wx.WXK_F5, self.ID_MENU_START_SYNTH.GetId()),
                (wx.ACCEL_ALT, ord("S"), self.ID_MENU_START_SYNTH.GetId()),
                (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, self.ID_MENU_PAUSE_CANCEL.GetId()),
                (wx.ACCEL_CTRL, ord("E"), self.ID_MENU_EXPORT_WAV.GetId()),
            ])
        elif self._active_panel == "player":
            entries.extend([
                (wx.ACCEL_ALT, ord("P"), self.ID_MENU_PLAY_PAUSE.GetId()),
                (wx.ACCEL_NORMAL, wx.WXK_PAGEUP, self.ID_MENU_PREV_CHAPTER.GetId()),
                (wx.ACCEL_NORMAL, wx.WXK_PAGEDOWN, self.ID_MENU_NEXT_CHAPTER.GetId()),
                (wx.ACCEL_CTRL, ord("B"), self.ID_MENU_SAVE_BOOKMARK.GetId()),
            ])
        elif self._active_panel == "settings":
            entries.extend([
                (wx.ACCEL_CTRL, ord("T"), self.ID_MENU_TEST_API.GetId()),
            ])

        self.SetAcceleratorTable(wx.AcceleratorTable(entries))

    def _bind_command_events(self) -> None:
        self.Bind(wx.EVT_MENU, lambda evt: self.txt_synthesis_status.SetFocus(), id=self.ID_FOCUS_STATUS.GetId())
        self.Bind(wx.EVT_MENU, self._on_open_book_file, id=self.ID_MENU_OPEN_BOOK.GetId())
        self.Bind(wx.EVT_MENU, self._on_paste_from_clipboard, id=self.ID_MENU_PASTE_TEXT.GetId())
        self.Bind(wx.EVT_MENU, self._on_start_or_resume_synthesis, id=self.ID_MENU_START_SYNTH.GetId())
        self.Bind(wx.EVT_MENU, self._on_pause_or_cancel_synthesis, id=self.ID_MENU_PAUSE_CANCEL.GetId())
        self.Bind(wx.EVT_MENU, self._on_export_merged_wav, id=self.ID_MENU_EXPORT_WAV.GetId())
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), id=self.ID_MENU_EXIT.GetId())

        self.Bind(wx.EVT_MENU, self._on_player_play_pause, id=self.ID_MENU_PLAY_PAUSE.GetId())
        self.Bind(wx.EVT_MENU, lambda evt: self._on_player_seek(-15000), id=self.ID_MENU_REWIND_15.GetId())
        self.Bind(wx.EVT_MENU, lambda evt: self._on_player_seek(30000), id=self.ID_MENU_FORWARD_30.GetId())
        self.Bind(wx.EVT_MENU, lambda evt: self._on_player_change_chapter(-1), id=self.ID_MENU_PREV_CHAPTER.GetId())
        self.Bind(wx.EVT_MENU, lambda evt: self._on_player_change_chapter(1), id=self.ID_MENU_NEXT_CHAPTER.GetId())
        self.Bind(wx.EVT_MENU, self._on_save_bookmark_clicked, id=self.ID_MENU_SAVE_BOOKMARK.GetId())

        self.Bind(wx.EVT_MENU, self._on_sync_custom_voices, id=self.ID_MENU_SYNC_VOICES.GetId())

        self.Bind(wx.EVT_MENU, self._on_verify_api_keys, id=self.ID_MENU_TEST_API.GetId())
        self.Bind(wx.EVT_MENU, self._on_run_system_doctor, id=self.ID_MENU_DOCTOR.GetId())
        self.Bind(wx.EVT_MENU, self._on_check_github_updates, id=self.ID_MENU_UPDATES.GetId())

        self.Bind(wx.EVT_MENU, lambda evt: self._apply_language("en"), id=self.ID_MENU_LANG_EN.GetId())
        self.Bind(wx.EVT_MENU, lambda evt: self._apply_language("ar"), id=self.ID_MENU_LANG_AR.GetId())

    # ------------------------------------------------------------------
    # Dynamic Language Switching (_apply_language)
    # ------------------------------------------------------------------
    def _apply_language(self, lang: str) -> None:
        self.lang = normalize_lang(lang)
        self.settings_mgr.set("language", self.lang)

        # Update Window and Panel Titles/Names
        self.SetTitle(tr("app_title", self.lang))
        self.SetName(tr("main_window_accessible_name", self.lang))
        self.main_panel.SetName(tr("main_panel_accessible_name", self.lang))
        self.content_panel.SetName(tr("content_host_accessible_name", self.lang))

        self.tab_library.SetName(tr("tab_library_acc", self.lang))
        if hasattr(self, "tab_editor"):
            self.tab_editor.SetName(tr("tab_editor_acc", self.lang))
        self.tab_player.SetName(tr("tab_player_acc", self.lang))
        self.tab_voices.SetName(tr("tab_voices_acc", self.lang))
        self.tab_settings.SetName(tr("tab_settings_acc", self.lang))

        # Update Hub Navigation Buttons and Accessible Names
        self._update_nav_button_accessible_names()

        # Tab 1 Labels & Controls
        self.lbl_open_book.SetLabel(tr("lbl_open_book", self.lang))
        self.btn_open_book.SetLabel(tr("btn_open_book", self.lang))
        self.btn_open_book.SetName(tr("acc_open_book", self.lang))

        self.lbl_paste_clipboard.SetLabel(tr("lbl_paste_clipboard", self.lang))
        self.btn_paste_clipboard.SetLabel(tr("btn_paste_clipboard", self.lang))
        self.btn_paste_clipboard.SetName(tr("acc_paste_clipboard", self.lang))

        self.lbl_dialogue_tpl.SetLabel(tr("lbl_dialogue_tpl", self.lang))
        self.btn_insert_dialogue_tpl.SetLabel(tr("btn_dialogue_tpl", self.lang))
        self.btn_insert_dialogue_tpl.SetName(tr("acc_dialogue_tpl", self.lang))

        for tag_info in self._expressive_tag_controls:
            tag_info["lbl"].SetLabel(tr(tag_info["lbl_key"], self.lang))
            tag_info["btn"].SetLabel(tr(tag_info["btn_key"], self.lang))
            tag_info["btn"].SetName(tr(tag_info["acc_key"], self.lang))

        self.lbl_book_title.SetLabel(tr("lbl_book_title", self.lang))
        self.txt_book_title.SetName(tr("acc_book_title", self.lang))

        self.lbl_live_detector_caption.SetLabel(tr("lbl_live_detector", self.lang))
        self.txt_live_detector.SetName(tr("acc_live_detector", self.lang))

        self.lbl_book_editor.SetLabel(tr("lbl_book_editor", self.lang))
        self.txt_book_editor.SetName(tr("acc_book_editor", self.lang))

        self.lbl_detected_chapters.SetLabel(tr("lbl_detected_chapters", self.lang))
        self.lst_detected_chapters.SetName(tr("acc_detected_chapters", self.lang))

        self.lbl_start_synthesis.SetLabel(tr("lbl_start_synthesis", self.lang))
        if self.worker is not None and self.worker.is_alive():
            if self.worker.is_paused():
                self.btn_start_resume.SetLabel(tr("btn_resume_convert", self.lang))
                self.btn_start_resume.SetName(tr("btn_resume_convert", self.lang))
            else:
                self.btn_start_resume.SetLabel(tr("btn_converting_busy", self.lang))
                self.btn_start_resume.SetName(tr("btn_converting_busy", self.lang))
        else:
            self.btn_start_resume.SetLabel(tr("btn_start_convert", self.lang))
            self.btn_start_resume.SetName(tr("btn_start_convert", self.lang))

        self.lbl_pause_cancel.SetLabel(tr("lbl_pause_cancel", self.lang))
        self.btn_pause_cancel.SetLabel(tr("btn_pause_cancel", self.lang))
        self.btn_pause_cancel.SetName(tr("acc_pause_cancel", self.lang))

        self.lbl_export_merged.SetLabel(tr("lbl_export_merged", self.lang))
        self.btn_export_wav.SetLabel(tr("btn_export_merged", self.lang))
        self.btn_export_wav.SetName(tr("acc_export_merged", self.lang))

        self.lbl_progress.SetLabel(tr("lbl_progress", self.lang))
        self.gauge_progress.SetName(tr("acc_progress", self.lang))

        self.lbl_synthesis_status.SetLabel(tr("lbl_synthesis_status", self.lang))
        self.txt_synthesis_status.SetName(tr("acc_synthesis_status", self.lang))

        # Tab 2 Labels & Controls
        self.lbl_refresh_player.SetLabel(tr("lbl_refresh_player", self.lang))
        self.btn_refresh_player_list.SetLabel(tr("btn_refresh_player", self.lang))
        self.btn_refresh_player_list.SetName(tr("acc_refresh_player", self.lang))

        self.lbl_player_chapters.SetLabel(tr("lbl_player_chapters", self.lang))
        self.lst_player_chapters.SetName(tr("acc_player_chapters", self.lang))

        self.lbl_play_pause.SetLabel(tr("lbl_play_pause", self.lang))
        self.btn_play_pause.SetLabel(tr("btn_play_pause", self.lang))
        self.btn_play_pause.SetName(tr("acc_play_pause", self.lang))

        self.lbl_rewind_15.SetLabel(tr("lbl_rewind_10", self.lang))
        self.btn_rewind_15.SetLabel(tr("btn_rewind_15", self.lang))
        self.btn_rewind_15.SetName(tr("acc_rewind_15", self.lang))

        self.lbl_forward_30.SetLabel(tr("lbl_forward_10", self.lang))
        self.btn_forward_30.SetLabel(tr("btn_forward_30", self.lang))
        self.btn_forward_30.SetName(tr("acc_forward_30", self.lang))

        self.lbl_prev_chapter.SetLabel(tr("lbl_prev_chapter", self.lang))
        self.btn_prev_chapter.SetLabel(tr("btn_prev_chapter", self.lang))
        self.btn_prev_chapter.SetName(tr("acc_prev_chapter", self.lang))

        self.lbl_next_chapter.SetLabel(tr("lbl_next_chapter", self.lang))
        self.btn_next_chapter.SetLabel(tr("btn_next_chapter", self.lang))
        self.btn_next_chapter.SetName(tr("acc_next_chapter", self.lang))

        self.lbl_save_bookmark.SetLabel(tr("lbl_save_bookmark", self.lang))
        self.btn_save_bookmark.SetLabel(tr("btn_save_bookmark", self.lang))
        self.btn_save_bookmark.SetName(tr("acc_save_bookmark", self.lang))

        self.lbl_playback_speed.SetLabel(tr("lbl_playback_speed", self.lang))
        self.choice_playback_speed.SetName(tr("acc_playback_speed", self.lang))

        self.lbl_player_status.SetLabel(tr("lbl_player_status", self.lang))
        self.txt_player_time_status.SetName(tr("acc_player_status", self.lang))

        # Tab 3 Labels & Controls
        self.lbl_primary_voice.SetLabel(tr("lbl_primary_voice", self.lang))
        self.choice_primary_voice.SetName(tr("acc_primary_voice", self.lang))


        self.lbl_primary_voice_desc.SetLabel(tr("lbl_primary_voice_desc", self.lang))
        self.txt_primary_voice_desc.SetName(tr("acc_primary_voice_desc", self.lang))

        self.lbl_style_preset.SetLabel(tr("lbl_style_preset", self.lang))
        self.choice_style_preset.SetName(tr("acc_style_preset", self.lang))
        cur_style_sel = max(0, self.choice_style_preset.GetSelection())
        self.choice_style_preset.SetItems(get_style_choices(self.lang))
        self.choice_style_preset.SetSelection(min(cur_style_sel, len(STYLE_PRESETS) - 1))

        self.lbl_multi_speaker.SetLabel(tr("lbl_multi_speaker", self.lang))
        self.chk_multi_speaker.SetLabel(tr("chk_multi_speaker", self.lang))
        self.chk_multi_speaker.SetName(tr("acc_multi_speaker", self.lang))

        self.lbl_auto_emotion.SetLabel(tr("lbl_auto_emotion", self.lang))
        self.chk_auto_emotion.SetLabel(tr("chk_auto_emotion", self.lang))
        self.chk_auto_emotion.SetName(tr("acc_auto_emotion", self.lang))

        self.lbl_secondary_voice.SetLabel(tr("lbl_secondary_voice", self.lang))
        self.choice_secondary_voice.SetName(tr("acc_secondary_voice", self.lang))


        self.lbl_custom_voice_name.SetLabel(tr("lbl_custom_voice_name", self.lang))
        self.txt_custom_voice_name.SetName(tr("acc_custom_voice_name", self.lang))

        self.lbl_custom_voice_prompt.SetLabel(tr("lbl_custom_voice_prompt", self.lang))
        self.txt_custom_voice_prompt.SetName(tr("acc_custom_voice_prompt", self.lang))

        self.lbl_design_voice.SetLabel(tr("lbl_design_voice", self.lang))
        self.btn_design_voice.SetLabel(tr("btn_design_voice", self.lang))
        self.btn_design_voice.SetName(tr("acc_design_voice", self.lang))

        self.lbl_replication_info.SetLabel(tr("lbl_replication_info", self.lang))
        self.txt_replication_tier_info.SetName(tr("acc_replication_info", self.lang))

        self.lbl_replicate_wav.SetLabel(tr("lbl_replicate_wav", self.lang))
        self.btn_replicate_voice_wav.SetLabel(tr("btn_replicate_wav", self.lang))
        self.btn_replicate_voice_wav.SetName(tr("acc_replicate_wav", self.lang))

        self.lbl_sync_voices.SetLabel(tr("lbl_sync_voices", self.lang))
        self.btn_sync_custom_voices.SetLabel(tr("btn_sync_voices", self.lang))
        self.btn_sync_custom_voices.SetName(tr("acc_sync_voices", self.lang))

        # Tab 4 Labels & Controls
        self.lbl_language.SetLabel(tr("lbl_language", self.lang))
        self.choice_language.SetName(tr("acc_language", self.lang))
        lang_sel_idx = 1 if self.lang == "ar" else 0
        if self.choice_language.GetSelection() != lang_sel_idx:
            self.choice_language.SetSelection(lang_sel_idx)

        self.lbl_api_keys.SetLabel(tr("lbl_api_keys", self.lang))
        self.txt_api_keys.SetName(tr("acc_api_keys", self.lang))

        self.lbl_add_key_clip.SetLabel(tr("lbl_add_key_clip", self.lang))
        self.btn_add_key_clipboard.SetLabel(tr("btn_add_key_clip", self.lang))
        self.btn_add_key_clipboard.SetName(tr("acc_add_key_clip", self.lang))

        self.lbl_test_keys.SetLabel(tr("lbl_test_keys", self.lang))
        if self.btn_test_keys.IsEnabled():
            self.btn_test_keys.SetLabel(tr("btn_test_keys", self.lang))
            self.btn_test_keys.SetName(tr("acc_test_keys", self.lang))

        self.lbl_model.SetLabel(tr("lbl_model", self.lang))
        self.choice_model.SetName(tr("acc_model", self.lang))
        cur_model_sel = max(0, self.choice_model.GetSelection())
        self.choice_model.SetItems(get_model_labels(self.lang))
        self.choice_model.SetSelection(min(cur_model_sel, len(MODEL_CHOICES) - 1))

        self.lbl_pacing.SetLabel(tr("lbl_pacing", self.lang))
        self.txt_pacing_seconds.SetName(tr("acc_pacing", self.lang))

        self.lbl_output_dir.SetLabel(tr("lbl_output_dir", self.lang))
        self.txt_output_dir.SetName(tr("acc_output_dir", self.lang))

        self.lbl_browse_output.SetLabel(tr("lbl_browse_output", self.lang))
        self.btn_browse_output_dir.SetLabel(tr("btn_browse_output", self.lang))
        self.btn_browse_output_dir.SetName(tr("acc_browse_output", self.lang))

        if hasattr(self, "lbl_merge_indexing") and hasattr(self, "choice_merge_indexing"):
            self.lbl_merge_indexing.SetLabel(tr("lbl_merge_indexing", self.lang))
            self.choice_merge_indexing.SetName(tr("acc_merge_indexing", self.lang))
            cur_merge_sel = max(0, self.choice_merge_indexing.GetSelection())
            self.choice_merge_indexing.SetItems([
                tr("choice_merge_with_cue", self.lang),
                tr("choice_merge_plain", self.lang),
            ])
            self.choice_merge_indexing.SetSelection(min(cur_merge_sel, 1))

        self.lbl_save_settings.SetLabel(tr("lbl_save_settings", self.lang))
        self.btn_save_settings.SetLabel(tr("btn_save_settings", self.lang))
        self.btn_save_settings.SetName(tr("acc_save_settings", self.lang))

        self.lbl_run_doctor.SetLabel(tr("lbl_run_doctor", self.lang))
        self.btn_run_doctor.SetLabel(tr("btn_run_doctor", self.lang))
        self.btn_run_doctor.SetName(tr("acc_run_doctor", self.lang))

        self.lbl_check_updates.SetLabel(tr("lbl_check_updates", self.lang))
        self.btn_check_updates.SetLabel(tr("btn_check_updates", self.lang))
        self.btn_check_updates.SetName(tr("acc_check_updates", self.lang))

        self.lbl_settings_report.SetLabel(tr("lbl_settings_report", self.lang))
        self.txt_settings_report.SetName(tr("acc_settings_report", self.lang))

        self._refresh_voice_choices()
        self._update_live_text_analysis()
        self.content_panel.Layout()
        self.main_panel.Layout()
        self.Layout()

    # ------------------------------------------------------------------
    # Accessible Control Builders (Strict StaticText + SetName Contract)
    # ------------------------------------------------------------------
    @staticmethod
    def _add_labeled_button_pair(
        parent: wx.Window,
        sizer: wx.Sizer,
        caption: str,
        button_label: str,
        accessible_name: str,
        handler: Callable[[wx.CommandEvent], None],
    ) -> Tuple[wx.StaticText, wx.Button]:
        lbl = wx.StaticText(parent, label=caption)
        btn = wx.Button(parent, label=button_label)
        btn.SetName(accessible_name)
        btn.Bind(wx.EVT_BUTTON, handler)

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(lbl, 0, wx.BOTTOM, 2)
        box.Add(btn, 0, wx.EXPAND, 0)
        sizer.Add(box, 0, wx.ALL, 4)
        return lbl, btn

    @staticmethod
    def _add_labeled_textctrl_pair(
        parent: wx.Window,
        sizer: wx.Sizer,
        caption: str,
        accessible_name: str,
        initial_value: str = "",
        style: int = 0,
        proportion: int = 0,
    ) -> Tuple[wx.StaticText, wx.TextCtrl]:
        lbl = wx.StaticText(parent, label=caption)
        txt = wx.TextCtrl(parent, value=initial_value, style=style)
        txt.SetName(accessible_name)

        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        sizer.Add(txt, proportion, wx.EXPAND | wx.ALL, 4)
        return lbl, txt

    @staticmethod
    def _add_labeled_choice_pair(
        parent: wx.Window,
        sizer: wx.Sizer,
        caption: str,
        accessible_name: str,
        choices: List[str],
        initial_index: int = 0,
        handler: Optional[Callable[[wx.CommandEvent], None]] = None,
    ) -> Tuple[wx.StaticText, wx.Choice]:
        lbl = wx.StaticText(parent, label=caption)
        ch = wx.Choice(parent, choices=choices)
        ch.SetName(accessible_name)
        if choices:
            ch.SetSelection(max(0, min(len(choices) - 1, initial_index)))
        if handler is not None:
            ch.Bind(wx.EVT_CHOICE, handler)

        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        sizer.Add(ch, 0, wx.EXPAND | wx.ALL, 4)
        return lbl, ch

    @staticmethod
    def _add_labeled_checkbox_pair(
        parent: wx.Window,
        sizer: wx.Sizer,
        caption: str,
        checkbox_label: str,
        accessible_name: str,
        initial_value: bool = False,
        handler: Optional[Callable[[wx.CommandEvent], None]] = None,
    ) -> Tuple[wx.StaticText, wx.CheckBox]:
        lbl = wx.StaticText(parent, label=caption)
        chk = wx.CheckBox(parent, label=checkbox_label)
        chk.SetName(accessible_name)
        chk.SetValue(bool(initial_value))
        if handler is not None:
            chk.Bind(wx.EVT_CHECKBOX, handler)

        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        sizer.Add(chk, 0, wx.ALL, 4)
        return lbl, chk

    @staticmethod
    def _add_labeled_listbox_pair(
        parent: wx.Window,
        sizer: wx.Sizer,
        caption: str,
        accessible_name: str,
        proportion: int = 1,
        handler: Optional[Callable[[wx.CommandEvent], None]] = None,
    ) -> Tuple[wx.StaticText, wx.ListBox]:
        lbl = wx.StaticText(parent, label=caption)
        lb = wx.ListBox(parent, choices=[], style=wx.LB_SINGLE)
        lb.SetName(accessible_name)
        if handler is not None:
            lb.Bind(wx.EVT_LISTBOX, handler)

        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        sizer.Add(lb, proportion, wx.EXPAND | wx.ALL, 4)
        return lbl, lb

    @staticmethod
    def _add_labeled_gauge_pair(
        parent: wx.Window,
        sizer: wx.Sizer,
        caption: str,
        accessible_name: str,
        max_range: int = 100,
    ) -> Tuple[wx.StaticText, wx.Gauge]:
        lbl = wx.StaticText(parent, label=caption)
        gauge = wx.Gauge(parent, range=max_range, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        gauge.SetName(accessible_name)

        sizer.Add(lbl, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        sizer.Add(gauge, 0, wx.EXPAND | wx.ALL, 4)
        return lbl, gauge

    # ------------------------------------------------------------------
    # Tab 1: Library & Integrated Audio Player
    # ------------------------------------------------------------------
    def _build_tab_library(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 1. Library Shelf Actions
        lib_tool_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_refresh_library = wx.Button(
            self.tab_library,
            label=tr("btn_refresh_library", self.lang),
        )
        self.btn_refresh_library.SetName(tr("acc_refresh_library", self.lang))
        self.btn_refresh_library.Bind(wx.EVT_BUTTON, lambda evt: self._refresh_library_books())
        lib_tool_row.Add(self.btn_refresh_library, 0, wx.ALL, 3)

        self.btn_open_library_folder = wx.Button(
            self.tab_library,
            label=tr("btn_open_book_folder", self.lang),
        )
        self.btn_open_library_folder.SetName(tr("acc_open_book_folder", self.lang))
        self.btn_open_library_folder.Bind(wx.EVT_BUTTON, self._on_open_library_folder)
        lib_tool_row.Add(self.btn_open_library_folder, 0, wx.ALL, 3)

        self.btn_resume_in_editor = wx.Button(
            self.tab_library,
            label=tr("btn_resume_in_editor", self.lang),
        )
        self.btn_resume_in_editor.SetName(tr("acc_resume_in_editor", self.lang))
        self.btn_resume_in_editor.Bind(wx.EVT_BUTTON, self._on_resume_selected_book)
        lib_tool_row.Add(self.btn_resume_in_editor, 0, wx.ALL, 3)

        self.btn_delete_book = wx.Button(
            self.tab_library,
            label=tr("btn_delete_book", self.lang),
        )
        self.btn_delete_book.SetName(tr("acc_delete_book", self.lang))
        self.btn_delete_book.Bind(wx.EVT_BUTTON, self._on_delete_selected_book)
        lib_tool_row.Add(self.btn_delete_book, 0, wx.ALL, 3)

        sizer.Add(lib_tool_row, 0, wx.EXPAND | wx.ALL, 2)

        # Books list
        self.lbl_library_books = wx.StaticText(
            self.tab_library,
            label=tr("lbl_library_books", self.lang),
        )
        sizer.Add(self.lbl_library_books, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)

        self.lst_library_books = wx.ListBox(
            self.tab_library,
            style=wx.LB_SINGLE | wx.LB_HSCROLL,
            size=(-1, 140),
        )
        self.lst_library_books.SetName(tr("acc_library_books", self.lang))
        self.lst_library_books.Bind(wx.EVT_LISTBOX, self._on_library_book_selected)
        self.lst_library_books.Bind(wx.EVT_LISTBOX_DCLICK, self._on_play_selected_book)
        sizer.Add(self.lst_library_books, 0, wx.EXPAND | wx.ALL, 4)

        # 2. Integrated Player Controls Section
        self.lbl_player_chapters, self.lst_player_chapters = self._add_labeled_listbox_pair(
            self.tab_library,
            sizer,
            tr("lbl_player_chapters", self.lang),
            tr("acc_player_chapters", self.lang),
            proportion=1,
            handler=self._on_player_chapter_selected,
        )
        self.lst_player_chapters.Bind(wx.EVT_KEY_DOWN, self._on_player_list_keydown)
        self.lst_player_chapters.Bind(wx.EVT_LISTBOX_DCLICK, self._on_player_chapter_selected)

        # Transport controls row
        transport_row = wx.WrapSizer(wx.HORIZONTAL)
        self.lbl_play_pause, self.btn_play_pause = self._add_labeled_button_pair(
            self.tab_library,
            transport_row,
            tr("lbl_play_pause", self.lang),
            tr("btn_play_pause", self.lang),
            tr("acc_play_pause", self.lang),
            self._on_player_play_pause,
        )
        self.lbl_rewind_15, self.btn_rewind_15 = self._add_labeled_button_pair(
            self.tab_library,
            transport_row,
            tr("lbl_rewind_10", self.lang),
            tr("btn_rewind_15", self.lang),
            tr("acc_rewind_15", self.lang),
            lambda evt: self._on_player_seek(-15000),
        )
        self.btn_rewind_10 = self.btn_rewind_15

        self.lbl_forward_30, self.btn_forward_30 = self._add_labeled_button_pair(
            self.tab_library,
            transport_row,
            tr("lbl_forward_10", self.lang),
            tr("btn_forward_30", self.lang),
            tr("acc_forward_30", self.lang),
            lambda evt: self._on_player_seek(30000),
        )
        self.btn_forward_10 = self.btn_forward_30

        self.lbl_prev_chapter, self.btn_prev_chapter = self._add_labeled_button_pair(
            self.tab_library,
            transport_row,
            tr("lbl_prev_chapter", self.lang),
            tr("btn_prev_chapter", self.lang),
            tr("acc_prev_chapter", self.lang),
            lambda evt: self._on_player_change_chapter(-1),
        )
        self.lbl_next_chapter, self.btn_next_chapter = self._add_labeled_button_pair(
            self.tab_library,
            transport_row,
            tr("lbl_next_chapter", self.lang),
            tr("btn_next_chapter", self.lang),
            tr("acc_next_chapter", self.lang),
            lambda evt: self._on_player_change_chapter(1),
        )
        self.lbl_save_bookmark, self.btn_save_bookmark = self._add_labeled_button_pair(
            self.tab_library,
            transport_row,
            tr("lbl_save_bookmark", self.lang),
            tr("btn_save_bookmark", self.lang),
            tr("acc_save_bookmark", self.lang),
            self._on_save_bookmark_clicked,
        )
        sizer.Add(transport_row, 0, wx.EXPAND, 0)

        # Speed choice & Elapsed/Total Time
        speed_time_row = wx.BoxSizer(wx.HORIZONTAL)
        speed_col = wx.BoxSizer(wx.VERTICAL)
        saved_speed = str(self.settings_mgr.get("playback_speed", "1.0x"))
        speed_idx = self.SPEED_CHOICES.index(saved_speed) if saved_speed in self.SPEED_CHOICES else 1
        self.lbl_playback_speed, self.choice_playback_speed = self._add_labeled_choice_pair(
            self.tab_library,
            speed_col,
            tr("lbl_playback_speed", self.lang),
            tr("acc_playback_speed", self.lang),
            choices=self.SPEED_CHOICES,
            initial_index=speed_idx,
            handler=self._on_playback_speed_changed,
        )
        speed_time_row.Add(speed_col, 1, wx.EXPAND, 0)

        time_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_player_status, self.txt_player_time_status = self._add_labeled_textctrl_pair(
            self.tab_library,
            time_col,
            tr("lbl_player_status", self.lang),
            tr("acc_player_status", self.lang),
            initial_value=tr("player_status_default", self.lang),
            style=wx.TE_READONLY,
        )
        speed_time_row.Add(time_col, 2, wx.EXPAND, 0)
        sizer.Add(speed_time_row, 0, wx.EXPAND, 0)

        self.tab_library.SetSizer(sizer)

    # ------------------------------------------------------------------
    # Tab 2: Book Creation & Synthesis Studio
    # ------------------------------------------------------------------
    def _build_tab_editor(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Row 1: Ingest actions
        ingest_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_open_book, self.btn_open_book = self._add_labeled_button_pair(
            self.tab_editor,
            ingest_row,
            tr("lbl_open_book", self.lang),
            tr("btn_open_book", self.lang),
            tr("acc_open_book", self.lang),
            self._on_open_book_file,
        )
        self.lbl_paste_clipboard, self.btn_paste_clipboard = self._add_labeled_button_pair(
            self.tab_editor,
            ingest_row,
            tr("lbl_paste_clipboard", self.lang),
            tr("btn_paste_clipboard", self.lang),
            tr("acc_paste_clipboard", self.lang),
            self._on_paste_from_clipboard,
        )
        self.lbl_dialogue_tpl, self.btn_insert_dialogue_tpl = self._add_labeled_button_pair(
            self.tab_editor,
            ingest_row,
            tr("lbl_dialogue_tpl", self.lang),
            tr("btn_dialogue_tpl", self.lang),
            tr("acc_dialogue_tpl", self.lang),
            self._on_insert_dialogue_template,
        )
        sizer.Add(ingest_row, 0, wx.EXPAND, 0)

        # Row 2: Expressive tags
        tags_row = wx.WrapSizer(wx.HORIZONTAL)
        expressive_tags = [
            ("lbl_tag_sigh", "btn_tag_sigh", "acc_tag_sigh", "<sigh>"),
            ("lbl_tag_laugh", "btn_tag_laugh", "acc_tag_laugh", "<laugh>"),
            ("lbl_tag_gasp", "btn_tag_gasp", "acc_tag_gasp", "<gasp>"),
            ("lbl_tag_whisper", "btn_tag_whisper", "acc_tag_whisper", "<whispering>"),
            ("lbl_tag_short_pause", "btn_tag_short_pause", "acc_tag_short_pause", "<short pause>"),
            ("lbl_tag_long_pause", "btn_tag_long_pause", "acc_tag_long_pause", "<long pause>"),
        ]
        self._expressive_tag_controls: List[Dict[str, Any]] = []
        for lbl_key, btn_key, acc_key, tag_token in expressive_tags:
            t_lbl, t_btn = self._add_labeled_button_pair(
                self.tab_editor,
                tags_row,
                tr(lbl_key, self.lang),
                tr(btn_key, self.lang),
                tr(acc_key, self.lang),
                lambda evt, t=tag_token: self._insert_tag_into_editor(t),
            )
            self._expressive_tag_controls.append(
                {
                    "lbl": t_lbl,
                    "btn": t_btn,
                    "lbl_key": lbl_key,
                    "btn_key": btn_key,
                    "acc_key": acc_key,
                }
            )
        sizer.Add(tags_row, 0, wx.EXPAND, 0)

        # Row 3: Book Title & Detector
        meta_row = wx.BoxSizer(wx.HORIZONTAL)
        col_title = wx.BoxSizer(wx.VERTICAL)
        self.lbl_book_title, self.txt_book_title = self._add_labeled_textctrl_pair(
            self.tab_editor,
            col_title,
            tr("lbl_book_title", self.lang),
            tr("acc_book_title", self.lang),
            initial_value=tr("default_book_title", self.lang),
        )
        meta_row.Add(col_title, 1, wx.EXPAND, 0)

        col_detector = wx.BoxSizer(wx.VERTICAL)
        self.lbl_live_detector_caption, self.txt_live_detector = self._add_labeled_textctrl_pair(
            self.tab_editor,
            col_detector,
            tr("lbl_live_detector", self.lang),
            tr("acc_live_detector", self.lang),
            initial_value=tr("default_live_detector", self.lang),
            style=wx.TE_READONLY,
        )
        self.lbl_text_stats = wx.StaticText(
            self.tab_editor,
            label=tr("default_live_detector", self.lang),
        )
        self.lbl_text_stats.SetName(tr("acc_live_detector", self.lang))
        col_detector.Add(self.lbl_text_stats, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        meta_row.Add(col_detector, 2, wx.EXPAND, 0)
        sizer.Add(meta_row, 0, wx.EXPAND, 0)

        # Row 4: Split Editor & Detected Chapters
        content_row = wx.BoxSizer(wx.HORIZONTAL)
        editor_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_book_editor, self.txt_book_editor = self._add_labeled_textctrl_pair(
            self.tab_editor,
            editor_col,
            tr("lbl_book_editor", self.lang),
            tr("acc_book_editor", self.lang),
            initial_value="",
            style=wx.TE_MULTILINE,
            proportion=1,
        )
        self.txt_book_editor.Bind(wx.EVT_TEXT, self._on_editor_text_changed)
        content_row.Add(editor_col, 2, wx.EXPAND, 0)

        chapters_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_detected_chapters, self.lst_detected_chapters = self._add_labeled_listbox_pair(
            self.tab_editor,
            chapters_col,
            tr("lbl_detected_chapters", self.lang),
            tr("acc_detected_chapters", self.lang),
            proportion=1,
            handler=self._on_detected_chapter_selected,
        )
        content_row.Add(chapters_col, 1, wx.EXPAND, 0)
        sizer.Add(content_row, 1, wx.EXPAND, 0)

        # Row 5: Control buttons
        synth_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_start_synthesis, self.btn_start_resume = self._add_labeled_button_pair(
            self.tab_editor,
            synth_btn_row,
            tr("lbl_start_synthesis", self.lang),
            tr("btn_start_convert", self.lang),
            tr("btn_start_convert", self.lang),
            self._on_start_or_resume_synthesis,
        )
        self.btn_start_synthesis = self.btn_start_resume

        self.lbl_pause_cancel, self.btn_pause_cancel = self._add_labeled_button_pair(
            self.tab_editor,
            synth_btn_row,
            tr("lbl_pause_cancel", self.lang),
            tr("btn_pause_cancel", self.lang),
            tr("acc_pause_cancel", self.lang),
            self._on_pause_or_cancel_synthesis,
        )
        self.btn_pause_cancel.Disable()

        self.lbl_export_merged, self.btn_export_wav = self._add_labeled_button_pair(
            self.tab_editor,
            synth_btn_row,
            tr("lbl_export_merged", self.lang),
            tr("btn_export_merged", self.lang),
            tr("acc_export_merged", self.lang),
            self._on_export_merged_wav,
        )
        self.btn_export_merged_wav = self.btn_export_wav
        sizer.Add(synth_btn_row, 0, wx.EXPAND, 0)

        self.tab_editor.SetSizer(sizer)

    # ------------------------------------------------------------------
    # Tab 3: Voice Studio
    # ------------------------------------------------------------------
    def _build_tab_voices(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Primary voice selection & description
        self.lbl_primary_voice, self.choice_primary_voice = self._add_labeled_choice_pair(
            self.tab_voices,
            sizer,
            tr("lbl_primary_voice", self.lang),
            tr("acc_primary_voice", self.lang),
            choices=[],
            initial_index=0,
            handler=self._on_primary_voice_changed,
        )

        self.lbl_primary_voice_desc, self.txt_primary_voice_desc = self._add_labeled_textctrl_pair(
            self.tab_voices,
            sizer,
            tr("lbl_primary_voice_desc", self.lang),
            tr("acc_primary_voice_desc", self.lang),
            initial_value="",
            style=wx.TE_READONLY,
        )

        # Delivery Style Preset
        style_labels = get_style_choices(self.lang)
        saved_style_idx = int(self.settings_mgr.get("style_index", 0))
        self.lbl_style_preset, self.choice_style_preset = self._add_labeled_choice_pair(
            self.tab_voices,
            sizer,
            tr("lbl_style_preset", self.lang),
            tr("acc_style_preset", self.lang),
            choices=style_labels,
            initial_index=saved_style_idx,
            handler=self._on_style_preset_changed,
        )

        # Two-Speaker Dramatic Dialogue Section
        dialogue_row = wx.BoxSizer(wx.HORIZONTAL)
        chk_col1 = wx.BoxSizer(wx.VERTICAL)
        self.lbl_multi_speaker, self.chk_multi_speaker = self._add_labeled_checkbox_pair(
            self.tab_voices,
            chk_col1,
            tr("lbl_multi_speaker", self.lang),
            tr("chk_multi_speaker", self.lang),
            tr("acc_multi_speaker", self.lang),
            initial_value=bool(self.settings_mgr.get("multi_speaker_enabled", False)),
            handler=self._on_dialogue_settings_changed,
        )
        dialogue_row.Add(chk_col1, 1, wx.EXPAND, 0)

        chk_col2 = wx.BoxSizer(wx.VERTICAL)
        self.lbl_auto_emotion, self.chk_auto_emotion = self._add_labeled_checkbox_pair(
            self.tab_voices,
            chk_col2,
            tr("lbl_auto_emotion", self.lang),
            tr("chk_auto_emotion", self.lang),
            tr("acc_auto_emotion", self.lang),
            initial_value=bool(self.settings_mgr.get("auto_emotion_inference", False)),
            handler=self._on_dialogue_settings_changed,
        )
        dialogue_row.Add(chk_col2, 1, wx.EXPAND, 0)
        sizer.Add(dialogue_row, 0, wx.EXPAND, 0)

        self.lbl_secondary_voice, self.choice_secondary_voice = self._add_labeled_choice_pair(
            self.tab_voices,
            sizer,
            tr("lbl_secondary_voice", self.lang),
            tr("acc_secondary_voice", self.lang),
            choices=[],
            initial_index=1,
            handler=self._on_secondary_voice_changed,
        )

        # -----------------------------------------------------------------
        # Advanced Voice Studio Tool Dropdown (Clean, unsprawled UI)
        # -----------------------------------------------------------------
        tool_choices = [
            tr("voice_tool_none", self.lang),
            tr("voice_tool_design", self.lang),
            tr("voice_tool_replicate", self.lang),
        ]
        self.lbl_advanced_voice_tool, self.choice_advanced_voice_tool = self._add_labeled_choice_pair(
            self.tab_voices,
            sizer,
            tr("lbl_advanced_voice_tool", self.lang),
            tr("acc_advanced_voice_tool", self.lang),
            choices=tool_choices,
            initial_index=0,
            handler=self._on_advanced_voice_tool_changed,
        )

        # Container for Voice Design (starts hidden)
        self.panel_voice_design = wx.Panel(self.tab_voices)
        design_box = wx.StaticBox(self.panel_voice_design, label=tr("group_voice_design", self.lang))
        design_sizer = wx.StaticBoxSizer(design_box, wx.VERTICAL)

        d_row1 = wx.BoxSizer(wx.HORIZONTAL)
        d_name_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_design_voice_name, self.txt_design_voice_name = self._add_labeled_textctrl_pair(
            design_box,
            d_name_col,
            tr("lbl_design_voice_name", self.lang),
            tr("acc_design_voice_name", self.lang),
            initial_value="",
        )
        d_row1.Add(d_name_col, 1, wx.EXPAND, 0)

        d_prompt_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_design_voice_prompt, self.txt_design_voice_prompt = self._add_labeled_textctrl_pair(
            design_box,
            d_prompt_col,
            tr("lbl_design_voice_prompt", self.lang),
            tr("acc_design_voice_prompt", self.lang),
            initial_value=tr("default_design_voice_prompt", self.lang),
        )
        d_row1.Add(d_prompt_col, 2, wx.EXPAND, 0)
        design_sizer.Add(d_row1, 0, wx.EXPAND | wx.ALL, 3)

        d_btns_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_design_voice = wx.Button(
            design_box,
            label=tr("btn_create_designed_voice", self.lang),
        )
        self.btn_design_voice.SetName(tr("acc_create_designed_voice", self.lang))
        self.btn_design_voice.Bind(wx.EVT_BUTTON, self._on_design_custom_voice)
        d_btns_row.Add(self.btn_design_voice, 0, wx.ALL, 3)

        self.btn_audition_designed_voice = wx.Button(
            design_box,
            label=tr("btn_audition_designed_voice", self.lang),
        )
        self.btn_audition_designed_voice.SetName(tr("acc_audition_designed_voice", self.lang))
        self.btn_audition_designed_voice.Bind(wx.EVT_BUTTON, self._on_audition_designed_voice)
        self.btn_audition_designed_voice.Disable()
        d_btns_row.Add(self.btn_audition_designed_voice, 0, wx.ALL, 3)

        design_sizer.Add(d_btns_row, 0, wx.EXPAND | wx.ALL, 3)
        self.panel_voice_design.SetSizer(design_sizer)
        sizer.Add(self.panel_voice_design, 0, wx.EXPAND | wx.ALL, 4)
        self.panel_voice_design.Hide()

        # Container for Voice Replication (starts hidden)
        self.panel_voice_replication = wx.Panel(self.tab_voices)
        rep_box = wx.StaticBox(self.panel_voice_replication, label=tr("group_voice_replication", self.lang))
        rep_sizer = wx.StaticBoxSizer(rep_box, wx.VERTICAL)

        self.txt_replication_notice = wx.TextCtrl(
            rep_box,
            value=tr("paid_tier_notice", self.lang),
            style=wx.TE_READONLY | wx.TE_MULTILINE,
            size=(-1, 45),
        )
        self.txt_replication_notice.SetName(tr("paid_tier_notice", self.lang))
        rep_sizer.Add(self.txt_replication_notice, 0, wx.EXPAND | wx.ALL, 3)

        r_name_row = wx.BoxSizer(wx.HORIZONTAL)
        r_name_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_replicate_voice_name, self.txt_replicate_voice_name = self._add_labeled_textctrl_pair(
            rep_box,
            r_name_col,
            tr("lbl_replicate_voice_name", self.lang),
            tr("acc_replicate_voice_name", self.lang),
            initial_value="",
        )
        r_name_row.Add(r_name_col, 1, wx.EXPAND, 0)
        rep_sizer.Add(r_name_row, 0, wx.EXPAND | wx.ALL, 3)

        r_files_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_pick_ref_audio = wx.Button(
            rep_box,
            label=tr("btn_pick_ref_audio", self.lang),
        )
        self.btn_pick_ref_audio.SetName(tr("acc_pick_ref_audio", self.lang))
        self.btn_pick_ref_audio.Bind(wx.EVT_BUTTON, self._on_pick_ref_audio)
        r_files_row.Add(self.btn_pick_ref_audio, 0, wx.ALL, 3)

        self.txt_ref_audio_status = wx.TextCtrl(
            rep_box,
            value="لم يتم اختيار ملف",
            style=wx.TE_READONLY,
            size=(-1, 28),
        )
        self.txt_ref_audio_status.SetName(tr("lbl_ref_audio_file", self.lang))
        r_files_row.Add(self.txt_ref_audio_status, 1, wx.EXPAND | wx.ALL, 3)
        rep_sizer.Add(r_files_row, 0, wx.EXPAND | wx.ALL, 2)

        consent_box_row = wx.BoxSizer(wx.HORIZONTAL)
        self.txt_legal_consent_text = wx.TextCtrl(
            rep_box,
            value=tr("legal_consent_phrase", self.lang),
            style=wx.TE_READONLY,
            size=(-1, 28),
        )
        self.txt_legal_consent_text.SetName(tr("lbl_legal_consent_text", self.lang))
        consent_box_row.Add(self.txt_legal_consent_text, 1, wx.EXPAND | wx.ALL, 3)

        self.btn_copy_consent = wx.Button(
            rep_box,
            label=tr("btn_copy_consent_text", self.lang),
        )
        self.btn_copy_consent.SetName(tr("acc_copy_consent_text", self.lang))
        self.btn_copy_consent.Bind(wx.EVT_BUTTON, self._on_copy_consent_phrase)
        consent_box_row.Add(self.btn_copy_consent, 0, wx.ALL, 3)
        rep_sizer.Add(consent_box_row, 0, wx.EXPAND | wx.ALL, 2)

        r_consent_audio_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_pick_consent_audio = wx.Button(
            rep_box,
            label=tr("btn_pick_consent_audio", self.lang),
        )
        self.btn_pick_consent_audio.SetName(tr("acc_pick_consent_audio", self.lang))
        self.btn_pick_consent_audio.Bind(wx.EVT_BUTTON, self._on_pick_consent_audio)
        r_consent_audio_row.Add(self.btn_pick_consent_audio, 0, wx.ALL, 3)

        self.txt_consent_audio_status = wx.TextCtrl(
            rep_box,
            value="لم يتم اختيار ملف",
            style=wx.TE_READONLY,
            size=(-1, 28),
        )
        self.txt_consent_audio_status.SetName(tr("lbl_consent_audio_file", self.lang))
        r_consent_audio_row.Add(self.txt_consent_audio_status, 1, wx.EXPAND | wx.ALL, 3)
        rep_sizer.Add(r_consent_audio_row, 0, wx.EXPAND | wx.ALL, 2)

        rep_btns_row = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_replicate_voice = wx.Button(
            rep_box,
            label=tr("btn_start_replication", self.lang),
        )
        self.btn_replicate_voice.SetName(tr("acc_start_replication", self.lang))
        self.btn_replicate_voice.Bind(wx.EVT_BUTTON, self._on_start_voice_replication)
        self.btn_start_replication = self.btn_replicate_voice
        rep_btns_row.Add(self.btn_replicate_voice, 0, wx.ALL, 3)

        rep_sizer.Add(rep_btns_row, 0, wx.EXPAND | wx.ALL, 3)
        self.panel_voice_replication.SetSizer(rep_sizer)
        sizer.Add(self.panel_voice_replication, 0, wx.EXPAND | wx.ALL, 4)
        self.panel_voice_replication.Hide()

        self.tab_voices.SetSizer(sizer)

    # ------------------------------------------------------------------
    # Tab 4: Settings
    # ------------------------------------------------------------------
    def _build_tab_settings(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Interface Language Selection
        lang_choices = [SUPPORTED_LANGUAGES["en"], SUPPORTED_LANGUAGES["ar"]]
        initial_lang_idx = 1 if self.lang == "ar" else 0
        self.lbl_language, self.choice_language = self._add_labeled_choice_pair(
            self.tab_settings,
            sizer,
            tr("lbl_language", self.lang),
            tr("acc_language", self.lang),
            choices=lang_choices,
            initial_index=initial_lang_idx,
            handler=self._on_language_choice_changed,
        )

        existing_keys = "\n".join(self.settings_mgr.get_api_keys())
        self.lbl_api_keys, self.txt_api_keys = self._add_labeled_textctrl_pair(
            self.tab_settings,
            sizer,
            tr("lbl_api_keys", self.lang),
            tr("acc_api_keys", self.lang),
            initial_value=existing_keys,
            style=wx.TE_MULTILINE,
            proportion=1,
        )

        key_btns_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_add_key_clip, self.btn_add_key_clipboard = self._add_labeled_button_pair(
            self.tab_settings,
            key_btns_row,
            tr("lbl_add_key_clip", self.lang),
            tr("btn_add_key_clip", self.lang),
            tr("acc_add_key_clip", self.lang),
            self._on_add_api_key_from_clipboard,
        )
        self.lbl_test_keys, self.btn_test_keys = self._add_labeled_button_pair(
            self.tab_settings,
            key_btns_row,
            tr("lbl_test_keys", self.lang),
            tr("btn_test_keys", self.lang),
            tr("acc_test_keys", self.lang),
            self._on_verify_api_keys,
        )
        self.btn_verify_keys = self.btn_test_keys
        sizer.Add(key_btns_row, 0, wx.EXPAND, 0)

        # Model Selection (clean labels via get_model_labels) & Pacing Interval
        model_pacing_row = wx.BoxSizer(wx.HORIZONTAL)
        model_col = wx.BoxSizer(wx.VERTICAL)
        model_labels = get_model_labels(self.lang)
        current_model_id = str(self.settings_mgr.get("model_id", "gemini-3.8-flash-tts"))
        model_idx = next(
            (i for i, m in enumerate(MODEL_CHOICES) if m["id"] == current_model_id),
            0,
        )
        self.lbl_model, self.choice_model = self._add_labeled_choice_pair(
            self.tab_settings,
            model_col,
            tr("lbl_model", self.lang),
            tr("acc_model", self.lang),
            choices=model_labels,
            initial_index=model_idx,
            handler=self._on_model_selection_changed,
        )
        model_pacing_row.Add(model_col, 2, wx.EXPAND, 0)

        pacing_col = wx.BoxSizer(wx.VERTICAL)
        pacing_val = str(self.settings_mgr.get("pacing_seconds", 60.0))
        self.lbl_pacing, self.txt_pacing_seconds = self._add_labeled_textctrl_pair(
            self.tab_settings,
            pacing_col,
            tr("lbl_pacing", self.lang),
            tr("acc_pacing", self.lang),
            initial_value=pacing_val,
        )
        model_pacing_row.Add(pacing_col, 1, wx.EXPAND, 0)
        sizer.Add(model_pacing_row, 0, wx.EXPAND, 0)

        # Output folder selection
        out_row = wx.BoxSizer(wx.HORIZONTAL)
        out_col = wx.BoxSizer(wx.VERTICAL)
        self.lbl_output_dir, self.txt_output_dir = self._add_labeled_textctrl_pair(
            self.tab_settings,
            out_col,
            tr("lbl_output_dir", self.lang),
            tr("acc_output_dir", self.lang),
            initial_value=str(self.settings_mgr.get("output_dir", "")),
        )
        out_row.Add(out_col, 2, wx.EXPAND, 0)

        self.lbl_browse_output, self.btn_browse_output_dir = self._add_labeled_button_pair(
            self.tab_settings,
            out_row,
            tr("lbl_browse_output", self.lang),
            tr("btn_browse_output", self.lang),
            tr("acc_browse_output", self.lang),
            self._on_browse_output_dir,
        )
        sizer.Add(out_row, 0, wx.EXPAND, 0)

        # Merged audio format and chapter indexing mode (.cue)
        merge_idx_row = wx.BoxSizer(wx.VERTICAL)
        merge_choices = [
            tr("choice_merge_with_cue", self.lang),
            tr("choice_merge_plain", self.lang),
        ]
        merge_init_idx = 0 if self.settings_mgr.get("merge_with_cue", True) else 1
        self.lbl_merge_indexing, self.choice_merge_indexing = self._add_labeled_choice_pair(
            self.tab_settings,
            merge_idx_row,
            tr("lbl_merge_indexing", self.lang),
            tr("acc_merge_indexing", self.lang),
            choices=merge_choices,
            initial_index=merge_init_idx,
        )
        sizer.Add(merge_idx_row, 0, wx.EXPAND, 0)

        # Save, System Doctor, and GitHub Update Check
        diag_row = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_save_settings, self.btn_save_settings = self._add_labeled_button_pair(
            self.tab_settings,
            diag_row,
            tr("lbl_save_settings", self.lang),
            tr("btn_save_settings", self.lang),
            tr("acc_save_settings", self.lang),
            self._on_save_settings_clicked,
        )
        self.lbl_run_doctor, self.btn_run_doctor = self._add_labeled_button_pair(
            self.tab_settings,
            diag_row,
            tr("lbl_run_doctor", self.lang),
            tr("btn_run_doctor", self.lang),
            tr("acc_run_doctor", self.lang),
            self._on_run_system_doctor,
        )
        self.lbl_check_updates, self.btn_check_updates = self._add_labeled_button_pair(
            self.tab_settings,
            diag_row,
            tr("lbl_check_updates", self.lang),
            tr("btn_check_updates", self.lang),
            tr("acc_check_updates", self.lang),
            self._on_check_github_updates,
        )
        sizer.Add(diag_row, 0, wx.EXPAND, 0)

        self.lbl_settings_report, self.txt_settings_report = self._add_labeled_textctrl_pair(
            self.tab_settings,
            sizer,
            tr("lbl_settings_report", self.lang),
            tr("acc_settings_report", self.lang),
            initial_value=tr("settings_ready", self.lang),
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            proportion=1,
        )

        self.tab_settings.SetSizer(sizer)

    def _on_language_choice_changed(self, event: wx.CommandEvent) -> None:
        sel = self.choice_language.GetSelection()
        target_lang = "ar" if sel == 1 else "en"
        if target_lang != self.lang:
            self._apply_language(target_lang)

    # ------------------------------------------------------------------
    # Keyboard Shortcuts & Timers
    # ------------------------------------------------------------------

    def _on_player_list_keydown(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_SPACE:
            sel = self.lst_player_chapters.GetSelection()
            if sel != wx.NOT_FOUND:
                self._on_player_play_pause(event)
            # Do NOT call Skip() here — consume Space to prevent button activation
        else:
            event.Skip()

    def _setup_player_timer(self) -> None:
        self.player_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_player_timer_tick, self.player_timer)
        self.player_timer.Start(500)

    @staticmethod
    def _format_ms(ms: int) -> str:
        total_sec = max(0, int(ms) // 1000)
        mins = total_sec // 60
        secs = total_sec % 60
        if mins >= 60:
            hrs = mins // 60
            mins = mins % 60
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _on_player_timer_tick(self, event: wx.TimerEvent) -> None:
        if not self.audio_player.is_Loaded:
            return
        pos_ms = self.audio_player.get_position_ms()
        len_ms = self.audio_player.get_length_ms()
        mode = self.audio_player.get_mode()

        if mode == "playing":
            state_lbl = tr("player_playing", self.lang)
        elif mode == "paused":
            state_lbl = tr("player_paused", self.lang)
        else:
            state_lbl = tr("player_stopped", self.lang)

        speed_str = self.choice_playback_speed.GetStringSelection() or "1.0x"
        status_str = tr(
            "player_status_fmt",
            self.lang,
            state=state_lbl,
            elapsed=self._format_ms(pos_ms),
            total=self._format_ms(len_ms),
            speed=speed_str,
        )
        if self.txt_player_time_status.GetValue() != status_str:
            self.txt_player_time_status.SetValue(status_str)

        # Auto-save bookmark every 5 seconds while playing
        if mode == "playing" and (pos_ms // 1000) % 5 == 0 and self.current_playing_index >= 0:
            if self.current_playing_index < len(self.playable_chapters):
                ch = self.playable_chapters[self.current_playing_index]
                book_id = str(self._resolve_active_book_output_dir())
                self.settings_mgr.save_bookmark(
                    book_id=book_id,
                    chapter_file=ch.get("path", ""),
                    chapter_index=self.current_playing_index,
                    position_ms=pos_ms,
                    speed=speed_str,
                )

    # ------------------------------------------------------------------
    # Tab 1 Handlers (Library & Conversion)
    # ------------------------------------------------------------------
    def _on_open_book_file(self, event: wx.Event) -> None:
        with wx.FileDialog(
            self,
            message=tr("dlg_open_book_title", self.lang),
            wildcard=tr("dlg_open_book_wildcard", self.lang),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            chosen_path = Path(dlg.GetPath())

        try:
            raw_content = read_book_file_with_docx_fallback(chosen_path)
            book_title = chosen_path.stem.replace("_", " ").strip() or tr("default_book_title", self.lang)
            self.txt_book_title.SetValue(book_title)
            self.settings_mgr.set("last_opened_book", str(chosen_path.resolve()))
            self.txt_book_editor.SetValue(raw_content)
            self._parse_and_populate_chapters(raw_content, book_title, str(chosen_path.resolve()))
            self._check_and_update_resume_state(book_title)
        except Exception as exc:
            wx.MessageBox(
                tr("dlg_open_book_error", self.lang, error=str(exc)),
                tr("dlg_error_title", self.lang),
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def _on_paste_from_clipboard(self, event: wx.Event) -> None:
        if wx.TheClipboard.Open():
            try:
                data_obj = wx.TextDataObject()
                if wx.TheClipboard.GetData(data_obj):
                    pasted = data_obj.GetText()
                    if pasted.strip():
                        self.txt_book_editor.SetValue(pasted)
                        title = self.txt_book_title.GetValue().strip() or tr("default_book_title", self.lang)
                        self._parse_and_populate_chapters(pasted, title, "")
                        self._check_and_update_resume_state(title)
            finally:
                wx.TheClipboard.Close()

    def _on_insert_dialogue_template(self, event: wx.Event) -> None:
        template = (
            "الراوي: كان الليل هادئاً في المكتبة القديمة، حين اقترب المسافر من الطاولة الخشبية. <short pause>\n"
            "الشخصية: بهمس وبصوت خافت: هل هذا هو المخطوط الذي بحثنا عنه طويلاً؟\n"
            "الراوي: ابتسم الحكيم بهدوء وأشار إلى الصفحات المذهبة. <short pause>\n"
            "الشخصية: بفرح ومبتسماً: الحمد لله، لقد وجدنا المعرفة التي كنا ننشدها!\n"
        )
        current = self.txt_book_editor.GetValue()
        new_text = f"{current.rstrip()}\n\n{template}" if current.strip() else template
        self.txt_book_editor.SetValue(new_text)
        self.chk_multi_speaker.SetValue(True)
        self.settings_mgr.set("multi_speaker_enabled", True)
        self._update_live_text_analysis()

    def _insert_tag_into_editor(self, tag: str) -> None:
        insertion_point = self.txt_book_editor.GetInsertionPoint()
        self.txt_book_editor.WriteText(f" {tag} ")
        self.txt_book_editor.SetFocus()
        self.txt_book_editor.SetInsertionPoint(insertion_point + len(tag) + 2)

    def _parse_and_populate_chapters(self, text: str, title: str, file_path: str) -> None:
        self.parsed_book = self.parser.parse_content(text, filename=title, file_path=file_path)
        self.lst_detected_chapters.Clear()
        for idx, ch in enumerate(self.parsed_book.chapters, start=1):
            self.lst_detected_chapters.Append(
                tr("chapter_item_fmt", self.lang, index=idx, title=ch.chapter_title, chars=len(ch.text))
            )
        self._update_live_text_analysis()

    def _on_detected_chapter_selected(self, event: wx.CommandEvent) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        sel = self.lst_detected_chapters.GetSelection()
        if sel == wx.NOT_FOUND or not self.parsed_book:
            return
        if 0 <= sel < len(self.parsed_book.chapters):
            ch = self.parsed_book.chapters[sel]
            clean_title = (ch.chapter_title or "").split("\n")[0].strip()[:40]
            self.txt_synthesis_status.SetValue(
                tr("chapter_selected_status", self.lang, title=clean_title, chars=len(ch.text))
            )

    def _on_editor_text_changed(self, event: wx.CommandEvent) -> None:
        self._update_live_text_analysis()
        if hasattr(self, "btn_start_resume"):
            title = self.txt_book_title.GetValue().strip() if hasattr(self, "txt_book_title") else ""
            self._check_and_update_resume_state(title)

    def _update_live_text_analysis(self) -> None:
        text = self.txt_book_editor.GetValue()
        char_count = len(text)
        analysis = detect_dialogue_and_emotions(text)
        model_id = self._get_selected_model_id()
        chunk_limit = get_adaptive_chunk_limit(model_id)
        expected_chunks = max(1, (char_count + chunk_limit - 1) // chunk_limit) if char_count > 0 else 0
        chapters_count = (
            len(self.parsed_book.chapters)
            if self.parsed_book and self.parsed_book.chapters
            else (1 if char_count > 0 else 0)
        )

        mode_str = (
            tr("detector_dialogue", self.lang, turns=analysis["dialogue_turns"])
            if analysis["is_dialogue"]
            else tr("detector_single", self.lang)
        )
        summary = tr(
            "status_stats",
            self.lang,
            chars=char_count,
            chapters=chapters_count,
            chunks=expected_chunks,
            mode=mode_str,
        )
        self.lbl_text_stats.SetLabel(summary)
        self.txt_live_detector.SetValue(summary)

    def _get_selected_model_id(self) -> str:
        sel = self.choice_model.GetSelection()
        if 0 <= sel < len(MODEL_CHOICES):
            return str(MODEL_CHOICES[sel]["id"])
        return str(self.settings_mgr.get("model_id", "gemini-3.8-flash-tts"))

    def _get_selected_model_label(self) -> str:
        sel = self.choice_model.GetSelection()
        labels = get_model_labels(self.lang)
        if 0 <= sel < len(labels):
            return labels[sel]
        return MODEL_CHOICES[0]["label"]

    def _collect_and_save_current_settings(self) -> Dict[str, Any]:
        raw_keys_lines = self.txt_api_keys.GetValue().splitlines()
        keys = self.settings_mgr.set_api_keys(raw_keys_lines, auto_save=False)

        model_id = self._get_selected_model_id()
        self.settings_mgr.set("model_id", model_id, auto_save=False)

        try:
            pacing = max(1.0, float(self.txt_pacing_seconds.GetValue().strip()))
        except ValueError:
            pacing = 60.0
            self.txt_pacing_seconds.SetValue("60.0")
        self.settings_mgr.set("pacing_seconds", pacing, auto_save=False)

        out_dir = self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir
        self.settings_mgr.set("output_dir", out_dir, auto_save=False)

        style_sel = max(0, self.choice_style_preset.GetSelection())
        style_obj = STYLE_PRESETS[min(style_sel, len(STYLE_PRESETS) - 1)]
        style_prompt = "" if style_sel == 0 else style_obj["prompt"]
        self.settings_mgr.set("style_index", style_sel, auto_save=False)
        self.settings_mgr.set("style_label", style_obj["label"], auto_save=False)
        self.settings_mgr.set("style_prompt", style_prompt, auto_save=False)

        self.settings_mgr.set("multi_speaker_enabled", self.chk_multi_speaker.GetValue(), auto_save=False)
        self.settings_mgr.set("auto_emotion_inference", self.chk_auto_emotion.GetValue(), auto_save=False)

        merge_with_cue = True
        if hasattr(self, "choice_merge_indexing"):
            merge_with_cue = (self.choice_merge_indexing.GetSelection() == 0)
            self.settings_mgr.set("merge_with_cue", merge_with_cue, auto_save=False)

        self.settings_mgr.set("language", self.lang, auto_save=False)

        self.settings_mgr.save()
        return {
            "api_keys": keys,
            "model_id": model_id,
            "pacing_seconds": pacing,
            "output_dir": out_dir,
            "voice_name": str(self.settings_mgr.get("voice_name", "Charon")),
            "speaker2_voice": str(self.settings_mgr.get("speaker2_voice", "Kore")),
            "style_prompt": style_prompt,
            "multi_speaker": self.chk_multi_speaker.GetValue(),
            "auto_emotion": self.chk_auto_emotion.GetValue(),
            "merge_with_cue": merge_with_cue,
        }

    def _on_start_or_resume_synthesis(self, event: wx.Event) -> None:
        if self.worker is not None and self.worker.is_alive():
            if self.worker.is_paused():
                self.worker.resume()
                busy_lbl = tr("btn_converting_busy", self.lang)
                self.btn_start_resume.SetLabel(busy_lbl)
                self.btn_start_resume.SetName(busy_lbl)
                self.btn_start_resume.Disable()
                self.btn_pause_cancel.Enable()
                self.btn_export_wav.Disable()
                self.txt_synthesis_status.SetValue(tr("status_resumed", self.lang))
                wx.Bell()
                self.txt_synthesis_status.SetFocus()
            else:
                self.txt_synthesis_status.SetValue(tr("status_already_running", self.lang))
            return

        text = self.txt_book_editor.GetValue().strip()
        if not text:
            wx.MessageBox(
                tr("dlg_no_text_msg", self.lang),
                tr("dlg_no_text_title", self.lang),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        cfg = self._collect_and_save_current_settings()
        title = self.txt_book_title.GetValue().strip() or tr("default_book_title", self.lang)
        self._parse_and_populate_chapters(
            text,
            title,
            str(self.settings_mgr.get("last_opened_book", "")),
        )

        # Immediately update button states and announce start to NVDA
        busy_lbl = tr("btn_converting_busy", self.lang)
        self.btn_start_resume.SetLabel(busy_lbl)
        self.btn_start_resume.SetName(busy_lbl)
        self.btn_start_resume.Disable()
        self.btn_pause_cancel.Enable()
        self.btn_export_wav.Disable()

        model_display = self._get_selected_model_label()
        self.txt_synthesis_status.SetValue(
            tr("status_started", self.lang, model=model_display, voice=cfg["voice_name"])
        )
        wx.Bell()
        self.txt_synthesis_status.SetFocus()

        self.worker = SynthesisWorker(
            book_text=text,
            book_title=title,
            output_dir=cfg["output_dir"],
            api_keys=cfg["api_keys"],
            model_id=cfg["model_id"],
            voice_name=cfg["voice_name"],
            style_prompt=cfg["style_prompt"],
            multi_speaker=cfg["multi_speaker"],
            speaker2_voice=cfg["speaker2_voice"],
            auto_emotion=cfg["auto_emotion"],
            pacing_seconds=cfg["pacing_seconds"],
            source_file_path=str(self.settings_mgr.get("last_opened_book", "")),
            mock_mode=(len(cfg["api_keys"]) == 0),
            merge_with_cue=bool(cfg.get("merge_with_cue", True)),
            on_progress=self._on_worker_progress,
            on_countdown=self._on_worker_countdown,
            on_key_rotated=self._on_worker_key_rotated,
            on_chapter_ready=self._on_worker_chapter_ready,
            on_ask_legacy_fallback=self._on_worker_ask_legacy_fallback,
            on_finished=self._on_worker_finished,
        )
        self.last_book_output_dir = self.worker.output_dir
        self.worker.start()

    def _on_pause_or_cancel_synthesis(self, event: wx.Event) -> None:
        if self.worker is None or not self.worker.is_alive():
            self.txt_synthesis_status.SetValue(tr("status_no_active_conversion", self.lang))
            return

        if not self.worker.is_paused():
            self.worker.pause()
            res = wx.MessageBox(
                tr("dlg_pause_cancel_msg", self.lang),
                tr("dlg_pause_cancel_title", self.lang),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                self,
            )
            if res == wx.YES:
                self.worker.cancel()
                start_lbl = tr("btn_start_convert", self.lang)
                self.btn_start_resume.SetLabel(start_lbl)
                self.btn_start_resume.SetName(start_lbl)
                self.btn_start_resume.Enable()
                self.btn_pause_cancel.Disable()
                self.btn_export_wav.Enable()
                self.txt_synthesis_status.SetValue(tr("status_cancelling", self.lang))
            else:
                resume_lbl = tr("btn_resume_convert", self.lang)
                self.btn_start_resume.SetLabel(resume_lbl)
                self.btn_start_resume.SetName(resume_lbl)
                self.btn_start_resume.Enable()
                self.txt_synthesis_status.SetValue(tr("status_paused", self.lang))
        else:
            self.worker.cancel()
            start_lbl = tr("btn_start_convert", self.lang)
            self.btn_start_resume.SetLabel(start_lbl)
            self.btn_start_resume.SetName(start_lbl)
            self.btn_start_resume.Enable()
            self.btn_pause_cancel.Disable()
            self.btn_export_wav.Enable()
            self.txt_synthesis_status.SetValue(tr("status_cancelled", self.lang))

    def _resolve_active_book_output_dir(self) -> Path:
        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir)
        if self.last_book_output_dir is not None and self.last_book_output_dir.is_dir():
            return self.last_book_output_dir
        if self.worker is not None and self.worker.output_dir.is_dir():
            return self.worker.output_dir
        safe_title = sanitize_book_folder_name(self.txt_book_title.GetValue().strip())
        candidate = base_out / safe_title
        if candidate.is_dir():
            return candidate
        return base_out

    def _on_export_merged_wav(self, event: wx.Event) -> None:
        if self.worker is not None and self.worker.is_alive():
            wx.MessageBox(
                tr("msg_export_blocked_running", self.lang),
                tr("msg_export_blocked_title", self.lang),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir)
        book_dir = self._resolve_active_book_output_dir()

        candidate_dirs = [book_dir]
        if base_out not in candidate_dirs:
            candidate_dirs.append(base_out)

        complete_wavs: List[Path] = []
        wav_files: List[Path] = []
        for d in candidate_dirs:
            if not d.is_dir():
                continue
            found_complete = sorted(d.glob("*_complete.wav"))
            if found_complete and not complete_wavs:
                complete_wavs = [p for p in found_complete if p.is_file() and p.stat().st_size > 44]
            ch_dir = d / "chapters"
            if ch_dir.is_dir() and not wav_files:
                wav_files = [p for p in sorted(ch_dir.glob("*.wav")) if p.is_file() and p.stat().st_size > 44]
            if not wav_files:
                raw_dir = d / "raw_chunks"
                if raw_dir.is_dir():
                    wav_files = [p for p in sorted(raw_dir.glob("*.wav")) if p.is_file() and p.stat().st_size > 44]

        if not complete_wavs and not wav_files:
            wx.MessageBox(
                tr("dlg_no_audio_msg", self.lang),
                tr("dlg_no_audio_title", self.lang),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        safe_title = sanitize_book_folder_name(self.txt_book_title.GetValue().strip() or "audiobook")
        default_name = f"{safe_title}_complete.wav"
        with wx.FileDialog(
            self,
            message=tr("dlg_export_wav_title", self.lang),
            defaultDir=str(book_dir if book_dir.is_dir() else base_out),
            defaultFile=default_name,
            wildcard=tr("dlg_export_wav_wildcard", self.lang),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            dest_path = Path(dlg.GetPath())

        try:
            if wav_files:
                dur_ms = merge_and_normalize_wav_files(wav_files, dest_path, normalize=True)
            else:
                src_complete = complete_wavs[0]
                raw_bytes = src_complete.read_bytes()
                atomic_write_bytes(dest_path, raw_bytes)
                dur_ms = max(1000, int(( max(0, len(raw_bytes) - 44) / 48000.0) * 1000))

            msg = tr(
                "dlg_export_done_msg",
                self.lang,
                path=str(dest_path),
                duration=self._format_ms(dur_ms),
            )
            self.txt_synthesis_status.SetValue(msg.replace("\n", " | "))
            wx.MessageBox(
                msg,
                tr("dlg_export_done_title", self.lang),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
        except Exception as exc:
            wx.MessageBox(
                tr("dlg_export_error_msg", self.lang, error=str(exc)),
                tr("dlg_export_error_title", self.lang),
                wx.OK | wx.ICON_ERROR,
                self,
            )

    # ------------------------------------------------------------------
    # Worker UI Callbacks (Invoked via wx.CallAfter)
    # ------------------------------------------------------------------
    def _on_worker_progress(
        self,
        ch_idx: int,
        total_chapters: int,
        chunk_idx: int,
        total_chunks: int,
        percent: float,
        message: str,
    ) -> None:
        try:
            if not self:
                return
        except Exception:
            return
        self.gauge_progress.SetValue(max(0, min(100, int(round(percent)))))
        self.txt_synthesis_status.SetValue(message)

    def _on_worker_countdown(
        self,
        remaining_seconds: int,
        reason_ar: str,
        active_key_num: int,
        total_keys: int,
    ) -> None:
        try:
            if not self:
                return
        except Exception:
            return
        if remaining_seconds > 0:
            self.txt_synthesis_status.SetValue(
                tr(
                    "status_countdown",
                    self.lang,
                    reason=reason_ar,
                    seconds=remaining_seconds,
                    key_num=active_key_num,
                    total_keys=total_keys,
                )
            )
        else:
            self.txt_synthesis_status.SetValue(
                tr(
                    "status_key_active",
                    self.lang,
                    reason=reason_ar,
                    key_num=active_key_num,
                    total_keys=total_keys,
                )
            )

    def _on_worker_key_rotated(self, new_key_num: int, total_keys: int, message: str) -> None:
        try:
            if not self:
                return
        except Exception:
            return
        self.txt_synthesis_status.SetValue(message)

    def _on_worker_chapter_ready(self, chapter_record: Dict[str, Any]) -> None:
        try:
            if not self:
                return
        except Exception:
            return
        if self.worker is not None:
            self.last_book_output_dir = self.worker.output_dir
        self._refresh_playable_chapters()

    def _on_worker_ask_legacy_fallback(
        self,
        current_model: str,
        alternative_model: str,
        decision_callback: Callable[[bool], None],
    ) -> None:
        try:
            if not self:
                decision_callback(False)
                return
        except Exception:
            decision_callback(False)
            return
        prompt_text = tr(
            "dlg_legacy_fallback_msg",
            self.lang,
            current_model=current_model,
            alt_model=alternative_model,
        )
        res = wx.MessageBox(
            prompt_text,
            tr("dlg_legacy_fallback_title", self.lang),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        decision_callback(res == wx.YES)

    def _on_worker_finished(
        self,
        success: bool,
        message: str,
        manifest_data: Optional[Dict[str, Any]],
    ) -> None:
        try:
            if not self:
                return
        except Exception:
            return
        self.btn_start_resume.Enable()
        self.btn_pause_cancel.Disable()
        self.btn_export_wav.Enable()

        title = self.txt_book_title.GetValue().strip() or tr("default_book_title", self.lang)
        if not success:
            self._check_and_update_resume_state(title)
        else:
            start_lbl = tr("btn_start_convert", self.lang)
            self.btn_start_resume.SetLabel(start_lbl)
            self.btn_start_resume.SetName(start_lbl)

        if isinstance(manifest_data, dict) and manifest_data.get("output_dir"):
            self.last_book_output_dir = Path(str(manifest_data["output_dir"]))
        elif self.worker is not None:
            self.last_book_output_dir = self.worker.output_dir

        self.txt_synthesis_status.SetValue(message)
        self._refresh_playable_chapters()

        if success:
            self.gauge_progress.SetValue(100)
            merged_path = ""
            if isinstance(manifest_data, dict):
                merged_path = str(manifest_data.get("merged_audio_path", "") or "")
            dialog_msg = message
            if merged_path and merged_path not in message:
                dialog_msg = tr(
                    "dlg_conversion_complete_merged",
                    self.lang,
                    message=message,
                    merged_path=merged_path,
                )
            wx.MessageBox(
                dialog_msg,
                tr("dlg_conversion_done_title", self.lang),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
        else:
            wx.MessageBox(
                message,
                tr("dlg_conversion_notice_title", self.lang),
                wx.OK | wx.ICON_WARNING,
                self,
            )

    # ------------------------------------------------------------------
    # Tab 2 Handlers (Audio Player)
    # ------------------------------------------------------------------
    def _refresh_playable_chapters(self) -> None:
        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir)
        active_book_dir = self._resolve_active_book_output_dir()

        search_dirs: List[Path] = []
        for cand in (active_book_dir, base_out):
            if cand not in search_dirs:
                search_dirs.append(cand)

        items: List[Dict[str, Any]] = []
        for out_dir in search_dirs:
            manifest_path = out_dir / "book_manifest.json"
            chapters_dir = out_dir / "chapters"

            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    for ch in manifest.get("chapters", []):
                        rel_path = ch.get("audio_file", "")
                        abs_p = out_dir / rel_path
                        if abs_p.is_file():
                            items.append(
                                {
                                    "title": ch.get("title", abs_p.stem),
                                    "path": str(abs_p.resolve()),
                                    "duration_sec": ch.get("duration_seconds", 0),
                                }
                            )
                except Exception:
                    pass

            if not items and chapters_dir.is_dir():
                for wav_p in sorted(chapters_dir.glob("*.wav")):
                    dur_sec = max(1, int(wav_p.stat().st_size // 48000))
                    items.append(
                        {
                            "title": wav_p.stem,
                            "path": str(wav_p.resolve()),
                            "duration_sec": dur_sec,
                        }
                    )
            if items:
                break

        self.playable_chapters = items
        self.lst_player_chapters.Clear()
        for idx, item in enumerate(self.playable_chapters, start=1):
            dur_str = self._format_ms(int(item["duration_sec"]) * 1000)
            self.lst_player_chapters.Append(f"{idx}. {item['title']} ({dur_str})")

        # Restore saved bookmark selection if present
        book_id = str(self._resolve_active_book_output_dir())
        bm = self.settings_mgr.get_bookmark(book_id)
        if bm and self.playable_chapters:
            idx = int(bm.get("chapter_index", 0))
            if 0 <= idx < len(self.playable_chapters):
                self.lst_player_chapters.SetSelection(idx)
                self.current_playing_index = idx

    def _on_player_chapter_selected(self, event: wx.CommandEvent) -> None:
        sel = self.lst_player_chapters.GetSelection()
        if sel != wx.NOT_FOUND:
            self.current_playing_index = sel
            self._play_chapter_at_index(sel)

    def _on_player_play_pause(self, event: wx.Event) -> None:
        if self._active_panel not in ("library", "player"):
            return
        if not self.playable_chapters:
            self._refresh_playable_chapters()
        if not self.playable_chapters:
            self.txt_player_time_status.SetValue(tr("player_no_chapters", self.lang))
            return

        sel = self.lst_player_chapters.GetSelection()
        if sel == wx.NOT_FOUND:
            self.txt_player_time_status.SetValue(tr("player_select_chapter_first", self.lang))
            return

        target_chapter = self.playable_chapters[sel]
        target_path = target_chapter["path"]
        speed_str = self.choice_playback_speed.GetStringSelection() or "1.0x"

        if self.audio_player.is_Loaded and self.audio_player.current_file == target_path:
            mode_state = self.audio_player.toggle_play_pause()
            state_lbl = (
                tr("player_playing", self.lang)
                if mode_state == "playing"
                else (tr("player_paused", self.lang) if mode_state == "paused" else tr("player_stopped", self.lang))
            )
            pos_ms = self.audio_player.get_position_ms()
            len_ms = self.audio_player.get_length_ms()
            self.txt_player_time_status.SetValue(
                tr(
                    "player_status_short_fmt",
                    self.lang,
                    state=state_lbl,
                    elapsed=self._format_ms(pos_ms),
                    total=self._format_ms(len_ms),
                )
            )
            return

        # Check if bookmark exists for this chapter
        start_ms = 0
        book_id = str(self._resolve_active_book_output_dir())
        bm = self.settings_mgr.get_bookmark(book_id)
        if bm and bm.get("chapter_file") == target_path:
            start_ms = int(bm.get("position_ms", 0))

        self.current_playing_index = sel
        ok = self.audio_player.open_and_play(target_path, start_ms=start_ms, speed_str=speed_str)
        if ok:
            self.txt_player_time_status.SetValue(
                tr(
                    "player_now_playing",
                    self.lang,
                    title=target_chapter["title"],
                    pos=self._format_ms(start_ms),
                )
            )
        else:
            self.txt_player_time_status.SetValue(
                tr("player_open_failed", self.lang, path=target_path)
            )

    def _on_player_seek(self, delta_ms: int) -> None:
        if self._active_panel not in ("library", "player"):
            return
        if not self.audio_player.is_Loaded:
            return
        new_pos = self.audio_player.seek_relative(delta_ms)
        len_ms = self.audio_player.get_length_ms()
        self.txt_player_time_status.SetValue(
            tr(
                "player_seek_fmt",
                self.lang,
                pos=self._format_ms(new_pos),
                total=self._format_ms(len_ms),
            )
        )

    def _on_player_change_chapter(self, step: int) -> None:
        if self._active_panel not in ("library", "player"):
            return
        if not self.playable_chapters:
            return
        new_idx = max(0, min(len(self.playable_chapters) - 1, self.current_playing_index + step))
        self.lst_player_chapters.SetSelection(new_idx)
        self.current_playing_index = new_idx
        self.audio_player.stop()
        self._on_player_play_pause(wx.CommandEvent())

    def _on_playback_speed_changed(self, event: wx.CommandEvent) -> None:
        speed_str = self.choice_playback_speed.GetStringSelection() or "1.0x"
        self.settings_mgr.set("playback_speed", speed_str)
        self.audio_player.set_speed(speed_str)

    def _on_save_bookmark_clicked(self, event: wx.CommandEvent) -> None:
        if self._active_panel not in ("library", "player"):
            return
        if self.current_playing_index < 0 or self.current_playing_index >= len(self.playable_chapters):
            self.txt_player_time_status.SetValue(tr("player_select_first", self.lang))
            return
        ch = self.playable_chapters[self.current_playing_index]
        pos_ms = self.audio_player.get_position_ms()
        speed_str = self.choice_playback_speed.GetStringSelection() or "1.0x"
        book_id = str(self._resolve_active_book_output_dir())
        self.settings_mgr.save_bookmark(
            book_id=book_id,
            chapter_file=ch["path"],
            chapter_index=self.current_playing_index,
            position_ms=pos_ms,
            speed=speed_str,
        )
        self.txt_player_time_status.SetValue(
            tr(
                "player_bookmark_saved",
                self.lang,
                title=ch["title"],
                pos=self._format_ms(pos_ms),
            )
        )

    # ------------------------------------------------------------------
    # Tab 3 Handlers (Voice Studio)
    # ------------------------------------------------------------------
    def _get_combined_voices_list(self) -> List[Dict[str, str]]:
        voices = [dict(v) for v in PREBUILT_VOICES_CATALOG]
        for custom in self.settings_mgr.get("custom_voices", []):
            if isinstance(custom, dict) and custom.get("name"):
                voices.append(
                    {
                        "name": str(custom["name"]),
                        "gender": str(custom.get("gender", "Custom")),
                        "gender_en": str(custom.get("gender_en", "Custom")),
                        "gender_ar": str(custom.get("gender_ar", "مخصص")),
                        "trait_en": str(custom.get("trait_en", custom.get("style_ar", "Custom"))),
                        "trait_ar": str(custom.get("trait_ar", custom.get("style_ar", "مخصص"))),
                        "style_ar": str(custom.get("style_ar", "مخصص")),
                    }
                )
        return voices

    def _refresh_voice_choices(self) -> None:
        all_voices = self._get_combined_voices_list()
        labels = [format_voice_choice(v, self.lang) for v in all_voices]

        saved_v1 = str(self.settings_mgr.get("voice_name", "Charon"))
        saved_v2 = str(self.settings_mgr.get("speaker2_voice", "Kore"))

        idx1 = next((i for i, v in enumerate(all_voices) if v["name"] == saved_v1), 0)
        idx2 = next((i for i, v in enumerate(all_voices) if v["name"] == saved_v2), 1)

        self.choice_primary_voice.SetItems(labels)
        self.choice_primary_voice.SetSelection(idx1)

        self.choice_secondary_voice.SetItems(labels)
        self.choice_secondary_voice.SetSelection(idx2)

        if 0 <= idx1 < len(all_voices):
            self.txt_primary_voice_desc.SetValue(format_voice_choice(all_voices[idx1], self.lang))

    def _on_primary_voice_changed(self, event: wx.CommandEvent) -> None:
        all_voices = self._get_combined_voices_list()
        sel = self.choice_primary_voice.GetSelection()
        if 0 <= sel < len(all_voices):
            v_info = all_voices[sel]
            self.settings_mgr.set("voice_name", v_info["name"])
            self.txt_primary_voice_desc.SetValue(format_voice_choice(v_info, self.lang))

    def _on_secondary_voice_changed(self, event: wx.CommandEvent) -> None:
        all_voices = self._get_combined_voices_list()
        sel = self.choice_secondary_voice.GetSelection()
        if 0 <= sel < len(all_voices):
            v_info = all_voices[sel]
            self.settings_mgr.set("speaker2_voice", v_info["name"])

    def _on_style_preset_changed(self, event: wx.CommandEvent) -> None:
        sel = self.choice_style_preset.GetSelection()
        if 0 <= sel < len(STYLE_PRESETS):
            prompt_val = "" if sel == 0 else STYLE_PRESETS[sel]["prompt"]
            self.settings_mgr.set("style_index", sel, auto_save=False)
            self.settings_mgr.set("style_label", STYLE_PRESETS[sel]["label"], auto_save=False)
            self.settings_mgr.set("style_prompt", prompt_val, auto_save=True)

    def _on_dialogue_settings_changed(self, event: wx.CommandEvent) -> None:
        self.settings_mgr.set("multi_speaker_enabled", self.chk_multi_speaker.GetValue(), auto_save=False)
        self.settings_mgr.set("auto_emotion_inference", self.chk_auto_emotion.GetValue(), auto_save=True)

    # -# ------------------------------------------------------------------
    # Library Helper Methods
    # ------------------------------------------------------------------
    def _on_toggle_converter_studio(self, event: wx.CommandEvent) -> None:
        show = self.btn_toggle_converter.GetValue()
        self.panel_converter_studio.Show(show)
        self.tab_library.Layout()

    def _on_open_library_folder(self, event: wx.CommandEvent) -> None:
        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir) if hasattr(self, "txt_output_dir") else Path(self.settings_mgr.default_output_dir)
        base_out.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(base_out))
        except Exception as exc:
            logger.warning("Opening library folder failed: %s", exc)

    def _refresh_library_books(self) -> None:
        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir) if hasattr(self, "txt_output_dir") else Path(self.settings_mgr.default_output_dir)
        books = []
        if base_out.is_dir():
            for item in sorted(base_out.iterdir()):
                if not item.is_dir():
                    continue
                manifest_p = item / "book_manifest.json"
                prog_p = item / "progress.json"
                chapters_dir = item / "chapters"

                if manifest_p.is_file() or prog_p.is_file() or chapters_dir.is_dir():
                    title = item.name.replace("_", " ")
                    total_ch = 0
                    done_ch = 0
                    status = "in_progress"

                    if manifest_p.is_file():
                        try:
                            data = json.loads(manifest_p.read_text(encoding="utf-8"))
                            title = data.get("title", title)
                            total_ch = data.get("total_chapters", 0)
                            chapters = data.get("chapters", [])
                            done_ch = len(chapters)
                            status = data.get("status", "completed" if done_ch >= total_ch and total_ch > 0 else "in_progress")
                        except Exception:
                            pass

                    if total_ch == 0 and chapters_dir.is_dir():
                        wavs = list(chapters_dir.glob("*.wav"))
                        done_ch = len(wavs)
                        total_ch = done_ch
                        status = "completed" if done_ch > 0 else "in_progress"

                    books.append({
                        "title": title,
                        "folder": str(item.resolve()),
                        "done_chapters": done_ch,
                        "total_chapters": total_ch,
                        "status": status,
                    })

        self.library_books = books
        if hasattr(self, "lst_library_books"):
            self.lst_library_books.Clear()
            for idx, b in enumerate(self.library_books, start=1):
                st_text = "مكتمل" if b["status"] == "completed" else "قيد التحويل"
                self.lst_library_books.Append(
                    f"{idx}. «{b['title']}» - {b['done_chapters']}/{b['total_chapters']} فصول ({st_text})"
                )
            if self.library_books:
                self.lst_library_books.SetSelection(0)

    def _on_library_book_selected(self, event: wx.CommandEvent) -> None:
        if not hasattr(self, "lst_library_books"):
            return
        sel = self.lst_library_books.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self.library_books):
            return
        book = self.library_books[sel]
        book_dir = Path(book["folder"])
        self._load_book_into_player(book_dir, book["title"])

    def _on_play_selected_book(self, event: wx.Event) -> None:
        if not hasattr(self, "lst_library_books"):
            return
        sel = self.lst_library_books.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self.library_books):
            return
        book = self.library_books[sel]
        book_dir = Path(book["folder"])
        self._load_book_into_player(book_dir, book["title"])
        if len(self.playable_chapters) > 0:
            self._play_chapter_at_index(0)

    def _load_book_into_player(self, book_dir: Path, book_title: str) -> None:
        self.active_playing_book_dir = book_dir
        self.active_playing_book_title = book_title
        manifest_p = book_dir / "book_manifest.json"
        chapters_dir = book_dir / "chapters"
        items = []

        if manifest_p.is_file():
            try:
                manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
                for ch in manifest.get("chapters", []):
                    rel_p = ch.get("audio_file", "")
                    abs_p = book_dir / rel_p
                    if abs_p.is_file():
                        items.append({
                            "title": ch.get("title", abs_p.stem),
                            "path": str(abs_p.resolve()),
                            "duration_sec": ch.get("duration_seconds", 0),
                        })
            except Exception as exc:
                logger.warning("Failed to parse manifest: %s", exc)

        if not items and chapters_dir.is_dir():
            for wav_p in sorted(chapters_dir.glob("*.wav")):
                dur_sec = max(1, int(wav_p.stat().st_size // 48000))
                items.append({
                    "title": wav_p.stem,
                    "path": str(wav_p.resolve()),
                    "duration_sec": dur_sec,
                })

        self.playable_chapters = items
        self.lst_player_chapters.Clear()
        for idx, item in enumerate(self.playable_chapters, start=1):
            dur_str = self._format_ms(int(item["duration_sec"]) * 1000)
            self.lst_player_chapters.Append(f"{idx}. {item['title']} ({dur_str})")

        if self.playable_chapters:
            self.lst_player_chapters.SetSelection(0)
            self.current_playing_index = 0

    def _on_add_book_file(self, event: wx.CommandEvent) -> None:
        wildcard = "All Supported Files (*.txt;*.md;*.epub;*.docx)|*.txt;*.md;*.epub;*.docx|Text Files (*.txt)|*.txt|Markdown Files (*.md)|*.md|EPUB Files (*.epub)|*.epub|Word Documents (*.docx)|*.docx"
        with wx.FileDialog(self, tr("btn_add_book", self.lang), wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                chosen_path = Path(dlg.GetPath())
                try:
                    content = read_book_file_with_docx_fallback(chosen_path)
                    title = chosen_path.stem.replace("_", " ").strip() or tr("default_book_title", self.lang)
                    self._open_paste_text_dialog(initial_title=title, initial_text=content, source_file=chosen_path)
                except Exception as exc:
                    wx.MessageBox(f"فشل قراءة الملف: {exc}", "خطأ", wx.OK | wx.ICON_ERROR, self)

    def _on_paste_text_clicked(self, event: wx.CommandEvent) -> None:
        self._open_paste_text_dialog()

    def _open_paste_text_dialog(self, initial_title: str = "", initial_text: str = "", source_file: Optional[Path] = None) -> None:
        dlg = PasteTextDialog(self, initial_title=initial_title, initial_text=initial_text)
        if dlg.ShowModal() == wx.ID_OK:
            title = dlg.txt_title.GetValue().strip() or tr("default_book_title", self.lang)
            content = dlg.txt_content.GetValue().strip()
            if not content:
                wx.MessageBox("يرجى إدخال أو لصق نص للتحويل", "تنبيه", wx.OK | wx.ICON_WARNING, self)
                dlg.Destroy()
                return

            self._start_synthesis_for_content(title, content, source_file=source_file)
        dlg.Destroy()

    def _start_synthesis_for_content(self, title: str, content: str, source_file: Optional[Path] = None) -> None:
        safe_title = sanitize_book_folder_name(title)
        base_out = Path(self.txt_output_dir.GetValue().strip() or self.settings_mgr.default_output_dir) if hasattr(self, "txt_output_dir") else Path(self.settings_mgr.default_output_dir)
        book_output_dir = base_out / safe_title
        book_output_dir.mkdir(parents=True, exist_ok=True)

        if not source_file:
            source_file = book_output_dir / f"{safe_title}.txt"
            source_file.write_text(content, encoding="utf-8")

        self.last_book_output_dir = book_output_dir
        self.settings_mgr.set("last_opened_book", str(source_file.resolve()))

        # Parse book into chapters
        parsed_book = self.parser.parse_text(content, book_title=title, source_path=str(source_file.resolve()))
        self.parsed_book = parsed_book

        # Announce and start worker
        self.txt_synthesis_status.SetValue(f"بدء تحويل كتاب '{title}' إلى فصول صوتية...")
        self.gauge_progress.SetValue(0)

        # Worker invocation
        pacing = float(self.settings_mgr.get("pacing_seconds", 60.0))
        keys = self._get_api_keys()
        primary_voice = self.choice_primary_voice.GetStringSelection() if hasattr(self, "choice_primary_voice") else "Charon"
        style_idx = self.choice_style_preset.GetSelection() if hasattr(self, "choice_style_preset") else 0
        multi_enabled = self.chk_multi_speaker.GetValue() if hasattr(self, "chk_multi_speaker") else False
        secondary_voice = self.choice_secondary_voice.GetStringSelection() if hasattr(self, "choice_secondary_voice") else "Kore"
        model_id = str(self.settings_mgr.get("model_id", "gemini-3.8-flash-tts"))

        self.worker = SynthesisWorker(
            book=parsed_book,
            output_dir=book_output_dir,
            api_keys=keys,
            primary_voice=primary_voice,
            pacing_interval_sec=pacing,
            style_index=style_idx,
            custom_instructions="",
            multi_speaker=multi_enabled,
            secondary_voice=secondary_voice,
            model_id=model_id,
            on_progress=self._on_worker_progress,
            on_chapter_done=self._on_worker_chapter_done,
            on_complete=self._on_worker_complete,
            on_error=self._on_worker_error,
            on_log=self._on_worker_log,
        )
        self.worker.start()
        wx.MessageBox(
            f"بدأ تحويل كتاب '{title}' في الخلفية بنجاح! يمكنك متابعة التقدم من شريط الحالة أدناه.",
            "بدء التحويل",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
        self._refresh_library_books()

    def _on_resume_selected_book(self, event: wx.CommandEvent) -> None:
        if not hasattr(self, "lst_library_books"):
            return
        sel = self.lst_library_books.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self.library_books):
            return
        book = self.library_books[sel]
        book_title = book["title"]
        book_dir = Path(book["folder"])

        manifest_p = book_dir / "book_manifest.json"
        is_completed = False
        source_path = ""
        if manifest_p.is_file():
            try:
                mdata = json.loads(manifest_p.read_text(encoding="utf-8"))
                total = mdata.get("total_chapters", 0)
                done = len(mdata.get("chapters", []))
                status = mdata.get("status", "")
                if status == "completed" or (total > 0 and done >= total):
                    is_completed = True
                source_path = str(mdata.get("source_file_path", "") or "")
            except Exception:
                pass

        if is_completed:
            msg = (
                f"الكتاب '{book_title}' مكتمل بالفعل بنسبة 100% وموجود في مشغل المكتبة للاستماع والملاحة."
                if self.lang == "ar"
                else f"Book '{book_title}' is already 100% completed and ready in the library player."
            )
            wx.MessageBox(msg, tr("dlg_info_title", self.lang), wx.OK | wx.ICON_INFORMATION, self)
            return

        content = ""
        for txt_f in sorted(book_dir.glob("*.txt")):
            try:
                c = txt_f.read_text(encoding="utf-8")
                if c.strip():
                    content = c
                    break
            except Exception:
                pass

        if not content and source_path and Path(source_path).is_file():
            try:
                content = read_book_file_with_docx_fallback(Path(source_path))
            except Exception:
                pass

        self.txt_book_title.SetValue(book_title)
        if content:
            self.txt_book_editor.SetValue(content)
            self._parse_and_populate_chapters(content, book_title, str(book_dir))
        self._check_and_update_resume_state(book_title)
        self._toggle_panel("editor")

    def _on_delete_selected_book(self, event: wx.CommandEvent) -> None:
        if not hasattr(self, "lst_library_books"):
            return
        sel = self.lst_library_books.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self.library_books):
            return
        book = self.library_books[sel]
        res = wx.MessageBox(
            tr("dlg_delete_book_msg", self.lang, title=book["title"]),
            tr("dlg_delete_book_title", self.lang),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if res == wx.YES:
            import shutil
            try:
                shutil.rmtree(book["folder"])
                self._refresh_library_books()
            except Exception as exc:
                wx.MessageBox(f"فشل حذف مجلد الكتاب: {exc}", "خطأ", wx.OK | wx.ICON_ERROR, self)

    # ------------------------------------------------------------------
    # Voice Design & Replication Handlers (Official Google API)
    # ------------------------------------------------------------------
    def _on_advanced_voice_tool_changed(self, event: wx.CommandEvent) -> None:
        idx = self.choice_advanced_voice_tool.GetSelection()
        if idx == 1:
            self.panel_voice_design.Show(True)
            self.panel_voice_replication.Show(False)
        elif idx == 2:
            self.panel_voice_design.Show(False)
            self.panel_voice_replication.Show(True)
        else:
            self.panel_voice_design.Show(False)
            self.panel_voice_replication.Show(False)
        self.tab_voices.Layout()
        self.content_panel.Layout()

    def _on_design_custom_voice(self, event: wx.CommandEvent) -> None:
        v_name = self.txt_design_voice_name.GetValue().strip()
        v_prompt = self.txt_design_voice_prompt.GetValue().strip()
        if not v_name or not v_prompt:
            wx.MessageBox(
                tr("dlg_incomplete_voice_msg", self.lang),
                tr("dlg_incomplete_voice_title", self.lang),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        self.btn_design_voice.Disable()
        self.txt_synthesis_status.SetValue("جاري تصميم الصوت عبر Google Gemini API...")

        def run():
            try:
                vid, sample_bytes = self.tts_client.create_prompted_voice(v_name, v_prompt, model_id=self.model_id)
                sample_path = ""
                if sample_bytes:
                    preview_dir = Path(self.settings_mgr.default_output_dir) / "previews"
                    preview_dir.mkdir(parents=True, exist_ok=True)
                    sample_file = preview_dir / f"{vid}_sample.wav"
                    sample_file.write_bytes(sample_bytes)
                    sample_path = str(sample_file.resolve())

                custom_list = list(self.settings_mgr.get("custom_voices", []))
                custom_list.append({
                    "id": vid,
                    "name": v_name,
                    "gender": "مخصص",
                    "gender_ar": "مخصص",
                    "gender_en": "Custom",
                    "trait_ar": v_prompt,
                    "trait_en": v_prompt,
                    "style_ar": v_prompt,
                    "sample_path": sample_path,
                    "type": "prompted",
                })
                self.settings_mgr.set("custom_voices", custom_list)

                def on_done():
                    self.btn_design_voice.Enable()
                    self.txt_synthesis_status.SetValue(f"تم إنشاء الصوت: {v_name}")
                    self.last_designed_sample_path = sample_path
                    if sample_path:
                        self.btn_audition_designed_voice.Enable()
                    self._refresh_voice_choices()
                    wx.MessageBox(
                        tr("voice_design_success_msg", self.lang, name=v_name, id=vid),
                        tr("voice_design_success_title", self.lang),
                        wx.OK | wx.ICON_INFORMATION,
                        self,
                    )
                wx.CallAfter(on_done)
            except Exception as exc:
                def on_err():
                    self.btn_design_voice.Enable()
                    self.txt_synthesis_status.SetValue("فشل تصميم الصوت")
                    wx.MessageBox(f"فشل تصميم الصوت: {exc}", "خطأ", wx.OK | wx.ICON_ERROR, self)
                wx.CallAfter(on_err)

        threading.Thread(target=run, daemon=True).start()

    def _on_audition_designed_voice(self, event: wx.CommandEvent) -> None:
        path = getattr(self, "last_designed_sample_path", "")
        if path and Path(path).is_file():
            self.audio_player.play_file(path)

    def _on_pick_ref_audio(self, event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            message="اختر ملف عينة الصوت المرجعية (WAV)",
            wildcard="ملفات الصوت (*.wav)|*.wav",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.selected_ref_audio_path = dlg.GetPath()
                self.txt_ref_audio_status.SetValue(Path(self.selected_ref_audio_path).name)

    def _on_copy_consent_phrase(self, event: wx.CommandEvent) -> None:
        phrase = tr("legal_consent_phrase", self.lang)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(phrase))
            wx.TheClipboard.Close()
            wx.MessageBox("تم نسخ عبارة الإقرار القانوني الإنجليزية إلى الحافظة بنجاح.", "تم النسخ", wx.OK | wx.ICON_INFORMATION, self)

    def _on_pick_consent_audio(self, event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self,
            message="اختر ملف تسجيل الإقرار القانوني (WAV)",
            wildcard="ملفات الصوت (*.wav)|*.wav",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.selected_consent_audio_path = dlg.GetPath()
                self.txt_consent_audio_status.SetValue(Path(self.selected_consent_audio_path).name)

    def _on_start_voice_replication(self, event: wx.CommandEvent) -> None:
        name = self.txt_replicate_voice_name.GetValue().strip()
        ref_p = getattr(self, "selected_ref_audio_path", "")
        consent_p = getattr(self, "selected_consent_audio_path", "")

        if not name:
            wx.MessageBox("يرجى إدخال اسم للصوت المستنسخ.", "تنبيه", wx.OK | wx.ICON_WARNING, self)
            return
        if not ref_p or not Path(ref_p).is_file():
            wx.MessageBox("يرجى اختيار ملف عينة الصوت المرجعية (WAV).", "تنبيه", wx.OK | wx.ICON_WARNING, self)
            return
        if not consent_p or not Path(consent_p).is_file():
            wx.MessageBox("يرجى اختيار ملف تسجيل الإقرار القانوني الصوتي (WAV).", "تنبيه", wx.OK | wx.ICON_WARNING, self)
            return

        self.btn_start_replication.Disable()
        self.txt_synthesis_status.SetValue("جاري إرسال عينات استنساخ الصوت إلى Google...")

        def run():
            try:
                ref_bytes = Path(ref_p).read_bytes()
                consent_bytes = Path(consent_p).read_bytes()
                vid, sample_bytes = self.tts_client.create_replicated_voice(
                    name, ref_bytes, consent_bytes, model_id=self.model_id
                )
                sample_path = ""
                if sample_bytes:
                    preview_dir = Path(self.settings_mgr.default_output_dir) / "previews"
                    preview_dir.mkdir(parents=True, exist_ok=True)
                    sample_file = preview_dir / f"{vid}_sample.wav"
                    sample_file.write_bytes(sample_bytes)
                    sample_path = str(sample_file.resolve())

                custom_list = list(self.settings_mgr.get("custom_voices", []))
                custom_list.append({
                    "id": vid,
                    "name": name,
                    "gender": "مستنسخ",
                    "gender_ar": "مستنسخ",
                    "gender_en": "Cloned",
                    "trait_ar": "صوت مستنسخ بالذكاء الاصطناعي",
                    "trait_en": "Replicated Voice",
                    "style_ar": "صوت مستنسخ بالذكاء الاصطناعي",
                    "sample_path": sample_path,
                    "type": "replicated",
                })
                self.settings_mgr.set("custom_voices", custom_list)

                def on_done():
                    self.btn_start_replication.Enable()
                    self.txt_synthesis_status.SetValue(f"تم استنساخ الصوت: {name}")
                    self._refresh_voice_choices()
                    wx.MessageBox(
                        tr("voice_replication_success_msg", self.lang, name=name, id=vid),
                        tr("voice_replication_success_title", self.lang),
                        wx.OK | wx.ICON_INFORMATION,
                        self,
                    )
                wx.CallAfter(on_done)
            except Exception as exc:
                def on_err():
                    self.btn_start_replication.Enable()
                    self.txt_synthesis_status.SetValue("فشل استنساخ الصوت")
                    wx.MessageBox(str(exc), "خطأ في استنساخ الصوت", wx.OK | wx.ICON_ERROR, self)
                wx.CallAfter(on_err)

        threading.Thread(target=run, daemon=True).start()

    def _on_sync_custom_voices(self, event: wx.CommandEvent) -> None:
        self.btn_sync_custom_voices.Disable()
        self.txt_synthesis_status.SetValue("جاري مزامنة الأصوات مع حساب Google...")

        def run():
            try:
                remote_voices = self.tts_client.list_custom_voices()
                custom_list = list(self.settings_mgr.get("custom_voices", []))
                known_ids = {v.get("id") for v in custom_list}

                new_count = 0
                for rv in remote_voices:
                    if rv.get("id") and rv["id"] not in known_ids:
                        custom_list.append(rv)
                        known_ids.add(rv["id"])
                        new_count += 1

                self.settings_mgr.set("custom_voices", custom_list)

                def on_done():
                    self.btn_sync_custom_voices.Enable()
                    self.txt_synthesis_status.SetValue("اكتملت مزامنة الأصوات")
                    self._refresh_voice_choices()
                    wx.MessageBox(
                        f"تمت مزامنة الأصوات بنجاح. تم العثور على {len(remote_voices)} صوتاً سحابياً ({new_count} صوتاً جديداً).",
                        "مزامنة الأصوات",
                        wx.OK | wx.ICON_INFORMATION,
                        self,
                    )
                wx.CallAfter(on_done)
            except Exception as exc:
                def on_err():
                    self.btn_sync_custom_voices.Enable()
                    self.txt_synthesis_status.SetValue("فشل مزامنة الأصوات")
                    wx.MessageBox(f"فشل مزامنة الأصوات: {exc}", "خطأ", wx.OK | wx.ICON_ERROR, self)
                wx.CallAfter(on_err)

        threading.Thread(target=run, daemon=True).start()

    def _on_add_api_key_from_clipboard(self, event: wx.CommandEvent) -> None:
        clip_text = ""
        if wx.TheClipboard.Open():
            data = wx.TextDataObject()
            if wx.TheClipboard.GetData(data):
                clip_text = data.GetText().strip()
            wx.TheClipboard.Close()

        if not clip_text:
            wx.MessageBox("الحافظة فارغة؛ انسخ مفتاح Gemini API أولاً.", "تنبيه", wx.OK | wx.ICON_WARNING, self)
            return

        current_text = self.txt_api_keys.GetValue().strip()
        lines = [ln.strip() for ln in current_text.splitlines() if ln.strip()]
        if clip_text not in lines:
            lines.append(clip_text)
            self.txt_api_keys.SetValue("\n".join(lines))
            self.settings_mgr.set_api_keys(lines)
            wx.MessageBox("تمت إضافة مفتاح API بنجاح وحفظه.", "نجاح", wx.OK | wx.ICON_INFORMATION, self)
        else:
            wx.MessageBox("المفتاح موجود بالفعل في القائمة.", "ملاحظة", wx.OK | wx.ICON_INFORMATION, self)

    def _on_verify_api_keys(self, event: wx.CommandEvent) -> None:
        keys = [ln.strip() for ln in self.txt_api_keys.GetValue().splitlines() if ln.strip()]
        if not keys:
            wx.MessageBox("لا توجد مفاتيح في القائمة لفحصها.", "تنبيه", wx.OK | wx.ICON_WARNING, self)
            return

        self.btn_test_keys.Disable()
        self.txt_synthesis_status.SetValue("جاري فحص مفاتيح API...")

        def run_test():
            valid_count = 0
            for k in keys:
                client = GeminiTtsClient(api_key=k, mock_mode=False)
                try:
                    voices = client.list_custom_voices()
                    if voices is not None:
                        valid_count += 1
                except Exception:
                    pass

            def finish():
                self.btn_test_keys.Enable()
                msg = f"تم فحص {len(keys)} مفتاحاً. صالحة: {valid_count}"
                self.txt_synthesis_status.SetValue(msg)
                wx.MessageBox(msg, "فحص مفاتيح API", wx.OK | wx.ICON_INFORMATION, self)

            wx.CallAfter(finish)

        threading.Thread(target=run_test, daemon=True).start()

    def _on_model_selection_changed(self, event: wx.CommandEvent) -> None:
        idx = self.choice_model.GetSelection()
        if 0 <= idx < len(MODEL_CHOICES):
            self.model_id = MODEL_CHOICES[idx]["id"]
            self.settings_mgr.set("model_id", self.model_id)

    def _on_browse_output_dir(self, event: wx.CommandEvent) -> None:
        default_dir = self.txt_output_dir.GetValue().strip() or str(self.settings_mgr.get("output_dir", ""))
        with wx.DirDialog(self, tr("lbl_output_dir", self.lang), defaultPath=default_dir, style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                selected_path = dlg.GetPath()
                self.txt_output_dir.SetValue(selected_path)
                self.settings_mgr.set("output_dir", selected_path)

    def _on_save_settings_clicked(self, event: wx.CommandEvent) -> None:
        self.btn_save_settings.Disable()
        try:
            cfg = self._collect_and_save_current_settings()
            msg = tr(
                "settings_saved_msg",
                self.lang,
                keys=len(cfg["api_keys"]),
                model=self._get_selected_model_label(),
                pacing=cfg["pacing_seconds"],
                output_dir=cfg["output_dir"],
            )
            self.txt_settings_report.SetValue(msg)
        finally:
            self.btn_save_settings.Enable()

        wx.MessageBox(
            msg,
            tr("btn_save_settings", self.lang),
            wx.OK | wx.ICON_INFORMATION,
            self,
        )

    def _on_run_system_doctor(self, event: wx.CommandEvent) -> None:
        self.btn_run_doctor.Disable()
        self.txt_settings_report.SetValue(tr("settings_doctor_running", self.lang))

        def finish_doctor(report_text: str, healthy: bool) -> None:
            self.btn_run_doctor.Enable()
            self.txt_settings_report.SetValue(report_text)
            wx.MessageBox(
                report_text,
                tr("btn_run_doctor", self.lang),
                wx.OK | (wx.ICON_INFORMATION if healthy else wx.ICON_WARNING),
                self,
            )

        def doctor_worker() -> None:
            doc = EnvironmentDoctor()
            healthy = doc.run_all()
            header = (
                tr("settings_doctor_header_ok", self.lang)
                if healthy
                else tr("settings_doctor_header_warn", self.lang)
            )
            lines = [header]
            for k, (passed, msg) in doc.report.items():
                state_lbl = (
                    tr("settings_doctor_item_ok", self.lang)
                    if passed
                    else tr("settings_doctor_item_warn", self.lang)
                )
                lines.append(f"- [{state_lbl}] {k}: {msg}")
            wx.CallAfter(finish_doctor, "\n".join(lines), healthy)

        threading.Thread(target=doctor_worker, daemon=True).start()

    def _on_check_github_updates(self, event: wx.CommandEvent) -> None:
        self.btn_check_updates.Disable()
        self.txt_settings_report.SetValue(tr("settings_checking_updates", self.lang))

        def finish_updates(report_text: str) -> None:
            self.btn_check_updates.Enable()
            self.txt_settings_report.SetValue(report_text)
            wx.MessageBox(
                report_text,
                tr("btn_check_updates", self.lang),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )

        def update_worker() -> None:
            try:
                req = urllib.request.Request(
                    self.GITHUB_RELEASES_LATEST_URL,
                    headers={"User-Agent": "GeminiAudiobookDesktop/2.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                tag = data.get("tag_name", "v2.0.0")
                msg = tr("settings_up_to_date", self.lang, tag=tag)
                wx.CallAfter(finish_updates, msg)
            except Exception:
                msg = tr("settings_up_to_date_offline", self.lang)
                wx.CallAfter(finish_updates, msg)

        threading.Thread(target=update_worker, daemon=True).start()

    def _on_close_window(self, event: wx.CloseEvent) -> None:
        try:
            self.player_timer.Stop()
        except Exception:
            pass
        try:
            self.audio_player.stop()
        except Exception:
            pass
        if self.worker is not None and self.worker.is_alive():
            self.worker.cancel()
        event.Skip()
