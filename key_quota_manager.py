#!/usr/bin/env python3
"""
Key Quota Manager for Gemini Audiobook TTS.
Maintains persistent per-key and per-model quota tracking in `key_quotas.json`.

Features:
- Per-key and per-model daily quota tracking (e.g., 100 RPD for Gemini 3.8, 10 RPD for legacy models).
- Automatic parsing of Google 429 RetryInfo / retryDelay and error text.
- Smart calculation of seconds until next Pacific Time midnight (Google API daily quota reset).
- Automatic renewal when `resets_at` timestamp passes.
- Instant skipping of exhausted keys on startup and rotation.
- Safe atomic JSON persistence (tempfile + os.replace) and thread-safe locking.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("KeyQuotaManager")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# Known Free Tier daily request limits per model per project
MODEL_DAILY_CAPS: Dict[str, int] = {
    "gemini-3.8-flash-tts": 100,
    "gemini-2.5-flash-preview-tts": 10,
    "gemini-3.1-flash-tts-preview": 10,
    "gemini-2.5-pro-preview-tts": 10,
}
DEFAULT_MODEL_DAILY_CAP = 10


def get_model_daily_cap(model_id: str) -> int:
    """Returns the daily request cap for the given model ID."""
    for known_model, cap in MODEL_DAILY_CAPS.items():
        if known_model in model_id:
            return cap
    return DEFAULT_MODEL_DAILY_CAP


def compute_key_id(api_key: str) -> str:
    """Computes a secure, consistent 16-character SHA-256 hash for an API key."""
    clean = api_key.strip()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def mask_key(api_key: str) -> str:
    """Returns a masked preview of an API key for safe logging (e.g. 'AIzaSy...abcd')."""
    clean = api_key.strip()
    if len(clean) > 10:
        return f"{clean[:6]}...{clean[-4:]}"
    return "***"


def get_seconds_until_pacific_midnight() -> int:
    """
    Computes seconds remaining until next midnight in US Pacific Time (UTC-8 / UTC-7),
    which is when Google Gemini daily quotas reset.
    """
    now_utc = datetime.now(timezone.utc)
    try:
        import zoneinfo
        tz_pacific = zoneinfo.ZoneInfo("America/Los_Angeles")
        now_pacific = now_utc.astimezone(tz_pacific)
    except Exception:
        tz_pacific = timezone(timedelta(hours=-8))
        now_pacific = now_utc.astimezone(tz_pacific)

    tomorrow_pacific = (now_pacific + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    seconds_left = int((tomorrow_pacific - now_pacific).total_seconds())
    return max(60, seconds_left)


def parse_retry_delay_from_error(error_body: str) -> Optional[int]:
    """
    Extracts retryDelay in seconds from Google API error response body.
    Supports both structured RetryInfo JSON and text regex patterns.
    """
    if not error_body:
        return None

    # 1. Try structured JSON error details
    try:
        data = json.loads(error_body)
        error_details = data.get("error", {}).get("details", [])
        for detail in error_details:
            if "RetryInfo" in detail.get("@type", ""):
                raw_delay = str(detail.get("retryDelay", "")).strip()
                if raw_delay.endswith("s"):
                    return int(float(raw_delay[:-1]))
    except Exception:
        pass

    # 2. Try regex for "retry in Xh Ym Zs" or "Xm Ys" or "Xs"
    hms_match = re.search(r"(\d+)\s*h(?:ours?)?\s*(\d+)\s*m(?:in(?:utes?)?)?\s*(\d+)\s*s(?:ec(?:onds?)?)?", error_body, re.IGNORECASE)
    if hms_match:
        h, m, s = int(hms_match.group(1)), int(hms_match.group(2)), int(hms_match.group(3))
        return h * 3600 + m * 60 + s

    ms_match = re.search(r"(\d+)\s*m(?:in(?:utes?)?)?\s*(\d+)\s*s(?:ec(?:onds?)?)?", error_body, re.IGNORECASE)
    if ms_match:
        m, s = int(ms_match.group(1)), int(ms_match.group(2))
        return m * 60 + s

    s_match = re.search(r"retry\s+(?:in|after)\s+(\d+)\s*s(?:ec(?:onds?)?)?", error_body, re.IGNORECASE)
    if s_match:
        return int(s_match.group(1))

    return None


class KeyQuotaManager:
    """
    Thread-safe persistent manager for tracking per-key and per-model quotas in key_quotas.json.
    """

    DEFAULT_FILENAME = "key_quotas.json"

    def __init__(self, storage_path: Optional[Union[str, Path]] = None) -> None:
        if storage_path is not None:
            self.storage_path = Path(storage_path).resolve()
        else:
            base_dir = Path(__file__).resolve().parent
            self.storage_path = base_dir / self.DEFAULT_FILENAME

        import threading
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = {
            "version": 1,
            "last_updated": int(time.time()),
            "keys": {},
        }
        self.load()

    def load(self) -> None:
        """Loads quota records from key_quotas.json if it exists."""
        with self._lock:
            if not self.storage_path.is_file() or self.storage_path.stat().st_size == 0:
                return
            try:
                content = self.storage_path.read_text(encoding="utf-8")
                self._data = json.loads(content)
            except Exception as exc:
                logger.warning("Could not read key_quotas.json: %s. Starting with fresh state.", exc)
                self._data = {"version": 1, "last_updated": int(time.time()), "keys": {}}

    def save(self) -> None:
        """Atomically saves quota records to key_quotas.json."""
        with self._lock:
            self._data["last_updated"] = int(time.time())
            parent = self.storage_path.parent
            parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)

            # Atomic write via temporary file
            tf = tempfile.NamedTemporaryFile("w", dir=str(parent), delete=False, encoding="utf-8")
            try:
                tf.write(payload)
                tf.flush()
                os.fsync(tf.fileno())
                tf.close()
                os.replace(tf.name, str(self.storage_path))
            except Exception as exc:
                if os.path.exists(tf.name):
                    try:
                        os.unlink(tf.name)
                    except OSError:
                        pass
                logger.error("Failed to atomic-write key_quotas.json: %s", exc)

    def _get_model_record(self, api_key: str, model_id: str, create: bool = True) -> Optional[Dict[str, Any]]:
        """Internal helper to retrieve or initialize a model quota record for a key."""
        clean_key = api_key.strip()
        if not clean_key:
            return None

        key_id = compute_key_id(clean_key)
        keys_dict: Dict[str, Any] = self._data.setdefault("keys", {})

        if key_id not in keys_dict:
            if not create:
                return None
            keys_dict[key_id] = {
                "key_preview": mask_key(clean_key),
                "created_at": int(time.time()),
                "models": {},
            }

        models_dict: Dict[str, Any] = keys_dict[key_id].setdefault("models", {})
        if model_id not in models_dict:
            if not create:
                return None
            models_dict[model_id] = {
                "status": "AVAILABLE",
                "requests_today": 0,
                "daily_cap": get_model_daily_cap(model_id),
                "resets_at": 0,
                "resets_at_iso": None,
                "last_success_at": 0,
                "last_429_at": 0,
                "last_error": "",
            }

        return models_dict[model_id]

    def is_key_available(self, api_key: str, model_id: str) -> bool:
        """
        Checks whether the given API key is currently available for `model_id`.
        If a previous exhaustion has passed its `resets_at` time, automatically resets
        the status to AVAILABLE and returns True.
        """
        clean_key = api_key.strip()
        if not clean_key:
            return False

        rec = self._get_model_record(clean_key, model_id, create=False)
        if rec is None:
            return True  # Fresh key never used before

        now = int(time.time())
        resets_at = rec.get("resets_at", 0)

        # Check if quota renewal time has arrived
        if rec.get("status") == "EXHAUSTED":
            if resets_at > 0 and now >= resets_at:
                logger.info(
                    "Quota renewed for key %s on model %s (resets_at timestamp passed).",
                    mask_key(clean_key),
                    model_id,
                )
                rec["status"] = "AVAILABLE"
                rec["requests_today"] = 0
                rec["resets_at"] = 0
                rec["resets_at_iso"] = None
                self.save()
                return True
            return False

        # Status is AVAILABLE: verify requests_today against daily cap
        daily_cap = rec.get("daily_cap", get_model_daily_cap(model_id))
        if rec.get("requests_today", 0) >= daily_cap:
            return False

        return True

    def get_key_status_info(self, api_key: str, model_id: str) -> Dict[str, Any]:
        """Returns detailed status information for a key and model."""
        clean_key = api_key.strip()
        rec = self._get_model_record(clean_key, model_id, create=True)
        now = int(time.time())
        resets_at = rec.get("resets_at", 0)

        is_avail = self.is_key_available(clean_key, model_id)
        remaining_seconds = max(0, resets_at - now) if resets_at > 0 else 0

        return {
            "key_preview": mask_key(clean_key),
            "key_id": compute_key_id(clean_key),
            "model_id": model_id,
            "available": is_avail,
            "status": "AVAILABLE" if is_avail else "EXHAUSTED",
            "requests_today": rec.get("requests_today", 0),
            "daily_cap": rec.get("daily_cap", get_model_daily_cap(model_id)),
            "resets_at": resets_at,
            "resets_at_iso": rec.get("resets_at_iso"),
            "seconds_until_reset": remaining_seconds,
            "last_error": rec.get("last_error", ""),
        }

    def record_success(self, api_key: str, model_id: str) -> None:
        """Records a successful API request on `api_key` for `model_id`."""
        clean_key = api_key.strip()
        if not clean_key:
            return

        rec = self._get_model_record(clean_key, model_id, create=True)
        rec["requests_today"] = rec.get("requests_today", 0) + 1
        rec["last_success_at"] = int(time.time())
        rec["status"] = "AVAILABLE"

        daily_cap = rec.get("daily_cap", get_model_daily_cap(model_id))
        if rec["requests_today"] >= daily_cap:
            # Reached full daily limit
            now = int(time.time())
            delay_sec = get_seconds_until_pacific_midnight()
            resets_at = now + delay_sec
            rec["status"] = "EXHAUSTED"
            rec["resets_at"] = resets_at
            rec["resets_at_iso"] = datetime.fromtimestamp(resets_at, tz=timezone.utc).isoformat()
            logger.info(
                "Key %s reached full daily limit (%d requests) on %s. Scheduled reset in %ds.",
                mask_key(clean_key),
                daily_cap,
                model_id,
                delay_sec,
            )

        self.save()

    def record_429_exhaustion(
        self,
        api_key: str,
        model_id: str,
        retry_delay_seconds: Optional[int] = None,
        error_message: str = "",
    ) -> int:
        """
        Records HTTP 429 quota exhaustion for `api_key` on `model_id`.
        Sets status to EXHAUSTED and calculates `resets_at`.
        Returns `resets_at` Unix timestamp.
        """
        clean_key = api_key.strip()
        if not clean_key:
            return 0

        now = int(time.time())
        if retry_delay_seconds is not None:
            delay = retry_delay_seconds
        else:
            delay = get_seconds_until_pacific_midnight()

        resets_at = now + delay
        resets_iso = datetime.fromtimestamp(resets_at, tz=timezone.utc).isoformat()

        rec = self._get_model_record(clean_key, model_id, create=True)
        rec["status"] = "EXHAUSTED"
        rec["daily_cap"] = get_model_daily_cap(model_id)
        rec["requests_today"] = rec["daily_cap"]  # Mark as fully consumed
        rec["resets_at"] = resets_at
        rec["resets_at_iso"] = resets_iso
        rec["last_429_at"] = now
        rec["last_error"] = error_message[:300] if error_message else "429 RESOURCE_EXHAUSTED"

        self.save()
        logger.info(
            "Recorded 429 exhaustion for key %s on model %s. Resets at %s (%ds remaining).",
            mask_key(clean_key),
            model_id,
            resets_iso,
            delay,
        )
        return resets_at

    def find_first_available_key_index(
        self,
        api_keys: List[str],
        model_id: str,
        preferred_index: int = 0,
    ) -> int:
        """
        Finds the first available key index from `api_keys` for `model_id`.
        Prioritizes `preferred_index` if available; otherwise scans from 0 to len(api_keys)-1.
        If all keys are exhausted, returns the index of the key that will reset earliest.
        """
        if not api_keys:
            return 0

        # 1. Check preferred index
        if 0 <= preferred_index < len(api_keys):
            if self.is_key_available(api_keys[preferred_index], model_id):
                return preferred_index

        # 2. Find first available key
        for idx, k in enumerate(api_keys):
            if self.is_key_available(k, model_id):
                return idx

        # 3. If all keys exhausted, find key resetting earliest
        best_idx = 0
        earliest_reset = float("inf")
        now = int(time.time())
        for idx, k in enumerate(api_keys):
            rec = self._get_model_record(k, model_id, create=False)
            if rec:
                r_at = rec.get("resets_at", 0)
                if r_at > 0 and r_at < earliest_reset:
                    earliest_reset = r_at
                    best_idx = idx

        return best_idx

    def get_next_available_key(
        self,
        api_keys: List[str],
        current_index: int,
        model_id: str,
    ) -> Tuple[int, Optional[str]]:
        """
        Advances from `current_index + 1` looking for the next available API key.
        Returns `(next_index, next_key)` or `(-1, None)` if all remaining keys are exhausted.
        """
        total = len(api_keys)
        for idx in range(current_index + 1, total):
            if self.is_key_available(api_keys[idx], model_id):
                return idx, api_keys[idx]

        return -1, None

    def get_earliest_renewal_time(
        self,
        api_keys: List[str],
        model_id: str,
    ) -> Tuple[int, Optional[str]]:
        """
        Returns `(remaining_seconds, human_readable_time)` for the key that will renew earliest.
        """
        now = int(time.time())
        earliest_timestamp = float("inf")

        for k in api_keys:
            rec = self._get_model_record(k, model_id, create=False)
            if rec:
                r_at = rec.get("resets_at", 0)
                if r_at > now and r_at < earliest_timestamp:
                    earliest_timestamp = r_at

        if earliest_timestamp == float("inf"):
            return 0, None

        remaining = int(earliest_timestamp - now)
        hours = remaining // 3600
        mins = (remaining % 3600) // 60
        secs = remaining % 60
        if hours > 0:
            time_str = f"{hours} ساعة و{mins} دقيقة"
        elif mins > 0:
            time_str = f"{mins} دقيقة و{secs} ثانية"
        else:
            time_str = f"{secs} ثانية"

        return remaining, time_str
