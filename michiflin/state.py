"""Persistent runtime state: settings, queue metadata, AI usage and link registry.

Only metadata is stored. Prompts, answers and downloaded files never are.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from contextlib import contextmanager

from . import config
from .config import CONFIG_DIR, DEFAULTS, LEGACY_STATE_FILE, STATE_FILE
from .util import utc_day

VERSION = 5
LINK_LIMIT = 2000
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

lock = threading.RLock()
data: dict[str, Any] = {
    "version": VERSION,
    "settings": {},
    "jobs": {},
    "usage": {},
    "cooldowns": {},
    "reasons": {},
    "remaining": {},
    "links": {},
    "link_seq": 0,
    "sent": [],
    "flags": {},
    "access": {},
    "apps": {},
    "people": {},
    "prefs": {},
}

# Settings each person keeps for themselves; everything else is shared and changed only by administrators.
PERSONAL = frozenset({
    "language", "video_height", "audio_kbps", "audio_format", "part_mb", "part_format", "auto_send", "batch", "delay",
    "window", "daily_cap_mb", "reader_kb", "reader_images", "reader_links", "capture_device", "capture_quality",
    "notify", "progress", "reactions", "chat_mode", "image_size", "ai_pin",
})
_acting = threading.local()

# Allowed values for each owner setting: a set of choices or an inclusive int range.
SETTING_RULES: dict[str, Any] = {
    "language": {"auto", "es", "en"},
    "video_height": {144, 240, 360, 480, 720, 1080},
    "audio_kbps": {32, 48, 64, 96, 128, 160, 192},
    "audio_format": {"m4a", "mp3", "opus"},
    "part_mb": (1, 20),
    "part_format": {"7z", "zip", "raw"},
    "batch": (0, 200),
    "delay": (0, 3600),
    "auto_send": {True, False},
    "daily_cap_mb": (0, 100000),
    "reader_images": {"off", "low"},
    "reader_kb": (30, 900),
    "reader_links": {"chat", "web"},
    "capture_device": {"mobile", "desktop"},
    "notify": {"minimal", "normal"},
    "progress": {"on", "off"},
    "reactions": {"on", "off", "all"},
    "chat_mode": {"app", "full"},
    "capture_quality": {"normal", "high", "max"},
    "image_size": {512, 768, 1024},
    "ttl_hours": (1, 336),
    "user_jobs": (1, 20),
    "user_daily_mb": (0, 100000),
    "ai_daily": (0, 1000),
    "image_daily": (0, 200),
    "code_daily": (0, 50),
    "ai_reserve": (0, 90),
}


def _valid(key: str, value: Any) -> bool:
    rule = SETTING_RULES.get(key)
    if rule is None:
        return key in {"window", "ai_pin"} and isinstance(value, str)
    if isinstance(rule, tuple):
        return isinstance(value, int) and not isinstance(value, bool) and rule[0] <= value <= rule[1]
    return value in rule


def act_as(address: str) -> None:
    """Personal settings read and written by this thread belong to this person; administrators use the shared ones."""
    address = (address or "").strip().lower()
    _acting.address = "" if address in config.ADMIN_ADDRESSES else address
    _acting.sender = address
    _acting.charged = False


def acting_as() -> str:
    return str(getattr(_acting, "address", ""))


def request_sender() -> str:
    """Address behind the current request, administrators included."""
    return str(getattr(_acting, "sender", ""))


def charge_once() -> bool:
    """True the first time per request: one request spends one unit of a daily allowance."""
    if getattr(_acting, "charged", False):
        return False
    _acting.charged = True
    return True


def uncharge() -> None:
    _acting.charged = False


@contextmanager
def person(address: str):
    previous = acting_as()
    act_as(address)
    try:
        yield
    finally:
        _acting.address = previous


def _shared(key: str) -> Any:
    with lock:
        value = data["settings"].get(key, DEFAULTS.get(key))
    if not _valid(key, value):
        value = DEFAULTS.get(key)
        if not _valid(key, value):
            rule = SETTING_RULES.get(key)
            value = rule[0] if isinstance(rule, tuple) else sorted(rule, key=str)[0] if rule else ""
    return value


def setting(key: str) -> Any:
    address = acting_as()
    if address and key in PERSONAL:
        with lock:
            own = data["prefs"].get(address) or {}
            if key in own and _valid(key, own[key]):
                return own[key]
    return _shared(key)


def can_change(key: str) -> bool:
    return not acting_as() or key in PERSONAL


def own_settings() -> None:
    """Give the acting person their own copy, starting from the current shared values."""
    address = acting_as()
    if not address:
        return
    with lock:
        if address in data["prefs"]:
            return
        data["prefs"][address] = {key: _shared(key) for key in PERSONAL}
    _save_soon()


def reset_own_settings() -> None:
    address = acting_as()
    if address:
        with lock:
            data["prefs"].pop(address, None)
        own_settings()


def forget_person(address: str) -> None:
    with lock:
        data["prefs"].pop((address or "").lower(), None)
    _save_soon()


def set_setting(key: str, value: Any) -> bool:
    if not _valid(key, value) or not can_change(key):
        return False
    address = acting_as()
    with lock:
        if address:
            data["prefs"].setdefault(address, {key: _shared(key) for key in PERSONAL})[key] = value
        else:
            data["settings"][key] = value
    save()
    return True


def save() -> None:
    with lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        now = time.time()
        data["sent"] = [item for item in data["sent"] if now - item[0] < 86400][-2000:]
        _prune_usage()
        temporary = STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(STATE_FILE)


def load() -> bool:
    """Load state. Returns True when a legacy state was migrated (queue discarded)."""
    migrated = False
    with lock:
        if STATE_FILE.is_file():
            try:
                stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(stored, dict) and stored.get("version") == VERSION:
                    for key in data:
                        if key in stored and isinstance(stored[key], type(data[key])):
                            data[key] = stored[key]
            except (OSError, ValueError):
                pass
        if LEGACY_STATE_FILE.exists():
            # The previous format kept an unrecoverable pending queue: drop it entirely.
            try:
                legacy = json.loads(LEGACY_STATE_FILE.read_text(encoding="utf-8"))
                old = legacy.get("settings", {}) if isinstance(legacy, dict) else {}
                if old.get("language") in {"auto", "es", "en"}:
                    data["settings"].setdefault("language", old["language"])
            except (OSError, ValueError, AttributeError):
                pass
            LEGACY_STATE_FILE.unlink(missing_ok=True)
            data["flags"].pop("outbox_purged", None)
            migrated = True
    save()
    return migrated


# ---------------------------------------------------------------------------
# Link registry: short ids make URLs tappable as chat commands (/v_ab).
# ---------------------------------------------------------------------------
def _encode(number: int) -> str:
    text = ""
    while True:
        number, rest = divmod(number, 36)
        text = _ALPHABET[rest] + text
        if not number:
            return text


def link_id(url: str) -> str:
    with lock:
        links: dict[str, Any] = data["links"]
        for key, entry in links.items():
            if entry[0] == url:
                entry[1] = time.time()
                return key
        data["link_seq"] += 1
        key = "k" + _encode(data["link_seq"])
        links[key] = [url, time.time()]
        if len(links) > LINK_LIMIT:
            for old in sorted(links, key=lambda item: links[item][1])[: len(links) - LINK_LIMIT]:
                links.pop(old, None)
    _save_soon()
    return key


_save_timer: threading.Timer | None = None


def _save_soon() -> None:
    """Coalesce frequent small changes into one write."""
    global _save_timer
    with lock:
        if _save_timer is None or not _save_timer.is_alive():
            _save_timer = threading.Timer(3.0, save)
            _save_timer.daemon = True
            _save_timer.start()


def resolve_link(token: str) -> str:
    token = (token or "").strip().lower()
    with lock:
        entry = data["links"].get(token)
    return entry[0] if entry else ""


# ---------------------------------------------------------------------------
# AI usage accounting (per provider/model per UTC day) and cooldowns.
# ---------------------------------------------------------------------------
def _prune_usage() -> None:
    today = utc_day()
    data["usage"] = {day: value for day, value in data["usage"].items() if day >= _days_ago(7)}
    data["usage"].setdefault(today, {})
    now = time.time()
    data["cooldowns"] = {key: until for key, until in data["cooldowns"].items() if until > now}
    data["reasons"] = {key: reason for key, reason in data["reasons"].items() if key in data["cooldowns"]}


def _days_ago(days: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))


def record_usage(key: str, ok: bool, tokens: int = 0) -> None:
    with lock:
        day = data["usage"].setdefault(utc_day(), {})
        entry = day.setdefault(key, [0, 0, 0])
        entry[0] += 1
        entry[1] += 0 if ok else 1
        entry[2] += max(0, int(tokens))
    _save_soon()


def usage_today(key: str) -> int:
    """Successful uses today; failed attempts do not spend the visible quota."""
    with lock:
        entry = data["usage"].get(utc_day(), {}).get(key, [0, 0])
    return max(0, int(entry[0]) - int(entry[1] if len(entry) > 1 else 0))


def usage_report_rows() -> list[tuple[str, int, int, int]]:
    with lock:
        day = data["usage"].get(utc_day(), {})
        return sorted((key, value[0], value[1], value[2]) for key, value in day.items())


def set_cooldown(key: str, seconds: int, reason: str = "") -> None:
    with lock:
        data["cooldowns"][key] = time.time() + max(1, seconds)
        if reason:
            data["reasons"][key] = reason
        else:
            data["reasons"].pop(key, None)
    _save_soon()


def until_utc_midnight() -> int:
    """Seconds until the next daily reset of quotas counted in UTC days."""
    now = time.time()
    return int(86400 - now % 86400) + 60


def cooldown_reason(key: str) -> str:
    with lock:
        return str(data["reasons"].get(key, "")) if cooldown_until(key) else ""


def cooldown_until(key: str) -> float:
    with lock:
        until = float(data["cooldowns"].get(key, 0))
    return until if until > time.time() else 0.0


def set_remaining(key: str, remaining: int, limit: int) -> None:
    with lock:
        data["remaining"][key] = [int(remaining), int(limit), time.time()]


def remaining_for(key: str) -> tuple[int, int] | None:
    with lock:
        entry = data["remaining"].get(key)
    if not entry or time.time() - entry[2] > 6 * 3600:
        return None
    return int(entry[0]), int(entry[1])


def record_sent(size: int, address: str = "") -> None:
    with lock:
        data["sent"].append([time.time(), int(size), address.lower()] if address else [time.time(), int(size)])


def sent_last_day() -> int:
    now = time.time()
    with lock:
        return sum(int(item[1]) for item in data["sent"] if now - item[0] < 86400)


def flag(name: str) -> Any:
    with lock:
        return data["flags"].get(name)


def set_flag(name: str, value: Any) -> None:
    with lock:
        data["flags"][name] = value
    save()
