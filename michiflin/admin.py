"""Access control and owner tools: allowlist, contact attempts, alerts, recent log lines, restart."""
from __future__ import annotations

import collections
import logging
import os
import threading
import time
from typing import Any

import requests

from . import chat, config, names, state
from .util import local_time, tr

log = logging.getLogger("michiflin")
_recent: collections.deque[str] = collections.deque(maxlen=60)
_activity: dict[str, float] = {}
ALERT_GAP = 6 * 3600


class _Buffer(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            _recent.append(f"{time.strftime('%H:%M', time.localtime(record.created))} {record.levelname[0]} {record.getMessage()[:220]}")


def install_log_buffer() -> None:
    logging.getLogger("michiflin").addHandler(_Buffer())


def _access() -> dict[str, Any]:
    with state.lock:
        access = state.data.setdefault("access", {})
        access.setdefault("allowed", [])
        access.setdefault("blocked", [])
        access.setdefault("attempts", {})
        access.setdefault("alerts", True)
        return access


def is_admin(address: str) -> bool:
    return address.lower() in config.ADMIN_ADDRESSES


def is_allowed(address: str) -> bool:
    address = address.lower()
    return is_admin(address) or address in config.ALLOWED_SENDERS or address in _access()["allowed"]


def is_blocked(address: str) -> bool:
    return address.lower() in _access()["blocked"]


def seen(address: str) -> None:
    _activity[address.lower()] = time.time()


def record_attempt(address: str, text: str) -> bool:
    """Log a message from an unknown contact; True when the admins should be alerted now."""
    address = address.lower() or "?"
    now = time.time()
    with state.lock:
        attempts = _access()["attempts"]
        entry = attempts.setdefault(address, {"count": 0, "first": now, "last": 0.0, "alerted": 0.0, "sample": ""})
        entry["count"] += 1
        entry["last"] = now
        entry["sample"] = (text or "")[:80]
        alert = bool(_access()["alerts"]) and now - float(entry.get("alerted") or 0) > ALERT_GAP
        if alert:
            entry["alerted"] = now
        if len(attempts) > 200:
            for stale in sorted(attempts, key=lambda key: attempts[key]["last"])[:50]:
                attempts.pop(stale, None)
    state.save()
    return alert


def alert_admins(message: str) -> None:
    """Send a notice to every admin chat the bot already knows."""
    for chat_id in admin_chats():
        chat.text(chat_id, message)


def alert_text(address: str, text: str) -> str:
    locale = "en" if state.setting("language") == "en" else "es"
    sample = (text or "").replace("\n", " ")[:80]
    allow = names.cmd(locale, "admin", "allow")
    return tr(locale, f"🛡️ Contacto ajeno bloqueado: {address}\n«{sample}»\nPara darle acceso: {allow} {address}",
              f"🛡️ Unknown contact blocked: {address}\n«{sample}»\nTo grant access: {allow} {address}")


def block_unknown(address: str, contact_id: int = 0) -> None:
    address = address.lower()
    if not address or is_allowed(address):
        return
    with state.lock:
        blocked = _access()["blocked"]
        if address not in blocked:
            blocked.append(address)
    _set_blocked_contact(address, True, contact_id)
    state.save()


def admin_chats() -> list[int]:
    found = []
    if not chat.ready():
        return found
    for address in config.ADMIN_ADDRESSES:
        try:
            contact = chat.rpc().lookup_contact_id_by_addr(chat.account(), address)
            if contact:
                chat_id = chat.rpc().get_chat_id_by_contact_id(chat.account(), contact)
                if chat_id:
                    found.append(int(chat_id))
        except Exception:
            continue
    return found


def grant(address: str) -> bool:
    address = address.strip().lower()
    if "@" not in address:
        return False
    with state.lock:
        access = _access()
        if address not in access["allowed"]:
            access["allowed"].append(address)
        if address in access["blocked"]:
            access["blocked"].remove(address)
        access["attempts"].pop(address, None)
    _set_blocked_contact(address, False)
    state.save()
    return True


def revoke(address: str, block: bool = False) -> bool:
    address = address.strip().lower()
    if "@" not in address or is_admin(address):
        return False
    with state.lock:
        access = _access()
        if address in access["allowed"]:
            access["allowed"].remove(address)
        if block and address not in access["blocked"]:
            access["blocked"].append(address)
    state.forget_person(address)
    if block:
        _set_blocked_contact(address, True)
    state.save()
    return True


def set_alerts(enabled: bool) -> None:
    with state.lock:
        _access()["alerts"] = enabled
    state.save()


def _set_blocked_contact(address: str, blocked: bool, contact_id: int = 0) -> None:
    """Block or unblock in the core; address lookups skip blocked contacts, so unblocking scans that list."""
    if not chat.ready():
        return
    try:
        rpc, account = chat.rpc(), chat.account()
        if blocked:
            contact_id = contact_id or int(rpc.lookup_contact_id_by_addr(account, address) or 0)
            if contact_id:
                rpc.block_contact(account, contact_id)
            return
        for contact in rpc.get_blocked_contacts(account):
            if str(contact.address).lower() == address:
                rpc.unblock_contact(account, contact.id)
    except Exception as exc:
        log.warning("contact block change failed: %s", exc)


def overview(locale: str) -> str:
    access = _access()
    now = time.time()
    users = sorted(config.ALLOWED_SENDERS | set(access["allowed"]))
    lines = [tr(locale, "🛡️ Administración", "🛡️ Administration"), ""]
    lines.append(tr(locale, "Usuarios con acceso:", "Users with access:"))
    for address in users:
        role = tr(locale, "admin", "admin") if is_admin(address) else tr(locale, "usuario", "user")
        last = _activity.get(address)
        when = tr(locale, f"activo hace {_ago(now - last, locale)}", f"active {_ago(now - last, locale)} ago") if last else tr(locale, "sin actividad en esta sesión", "no activity this session")
        lines.append(f"• {_mask(address)} · {role} · {when}")
    attempts = access["attempts"]
    lines += ["", tr(locale, f"Intentos de contacto ajenos: {len(attempts)}", f"Foreign contact attempts: {len(attempts)}")]
    for address, entry in sorted(attempts.items(), key=lambda item: -item[1]["last"])[:8]:
        lines.append(f"• {address} · {entry['count']}× · {local_time(entry['last'], '%d/%m %H:%M')}")
    if access["blocked"]:
        lines += ["", tr(locale, f"Bloqueados: {len(access['blocked'])}", f"Blocked: {len(access['blocked'])}")]
    lines += ["", tr(locale, f"Alertas de contactos ajenos: {'sí' if access['alerts'] else 'no'}", f"Foreign contact alerts: {'yes' if access['alerts'] else 'no'}")]
    run = os.getenv("GITHUB_RUN_ID", "")
    if run:
        lines.append(tr(locale, f"Sesión del servidor: {run}", f"Server session: {run}"))
    return "\n".join(lines)


def snapshot() -> dict[str, Any]:
    """Structured administration view for the mini app."""
    access = _access()
    users = sorted(config.ALLOWED_SENDERS | set(access["allowed"]))
    return {
        "users": [{"address": address, "admin": is_admin(address), "last": _activity.get(address, 0.0)} for address in users],
        "attempts": [{"address": address, "count": entry["count"], "last": entry["last"], "sample": entry.get("sample", "")}
                     for address, entry in sorted(access["attempts"].items(), key=lambda item: -item[1]["last"])[:30]],
        "blocked": list(access["blocked"]), "alerts": bool(access["alerts"]), "logs": list(_recent)[-40:],
        "session": os.getenv("GITHUB_RUN_ID", ""),
    }


def recent_logs(locale: str) -> str:
    if not _recent:
        return tr(locale, "📜 Sin advertencias ni errores en esta sesión.", "📜 No warnings or errors this session.")
    return tr(locale, "📜 Últimas advertencias y errores", "📜 Latest warnings and errors") + "\n\n" + "\n".join(list(_recent)[-25:])


def restart(locale: str) -> str:
    """Queue a fresh server session, then stop this one after the state is saved."""
    repository, token = os.getenv("GITHUB_REPOSITORY", ""), config.MICHIFLIN_GITHUB_TOKEN
    if not repository or not token:
        return tr(locale, "⚠️ El reinicio remoto necesita el token de GitHub del bot.", "⚠️ Remote restart needs the bot's GitHub token.")
    try:
        response = requests.post(f"https://api.github.com/repos/{repository}/actions/workflows/michiflin.yml/dispatches",
                                 json={"ref": os.getenv("GITHUB_REF_NAME", "main")}, timeout=20,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    except requests.RequestException:
        return tr(locale, "⚠️ No pude contactar con GitHub.", "⚠️ Could not reach GitHub.")
    if response.status_code != 204:
        return tr(locale, f"⚠️ GitHub rechazó el reinicio ({response.status_code}).", f"⚠️ GitHub refused the restart ({response.status_code}).")

    def stop() -> None:
        time.sleep(20)
        state.save()
        os._exit(0)

    threading.Thread(target=stop, name="restart", daemon=True).start()
    return tr(locale, "🔄 Reiniciando: vuelvo en unos 3 minutos.", "🔄 Restarting: back in about 3 minutes.")


def _mask(address: str) -> str:
    user, _, domain = address.partition("@")
    return f"{user[:3]}…@{domain}" if len(user) > 3 else address


def _ago(seconds: float, locale: str) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h"
