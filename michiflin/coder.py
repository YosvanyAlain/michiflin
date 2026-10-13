"""Programador: a coding agent on free models that writes, runs and fixes a small project in an isolated sandbox.

It is separate from the extractive Agent: it uses the AI models (the "code" role, or one model chosen by the user).
Commands run as nobody, without network, secrets or access to the bot's files, with CPU, memory and time limits.
"""
from __future__ import annotations

import base64
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import ai, config, progress
from .util import tr

MAX_STEPS = 7
MAX_FILES = 40
MAX_FILE = 120_000
MAX_TOTAL = 400_000
MAX_BINARY = 60_000
RUN_TIMEOUT = 25
RUNS_PER_STEP = 4
OUTPUT_MAX = 2500
TIME_BUDGET = 780  # seconds; the app operation is cut at 900
ANSWER_TOKENS = 5000
ROOT = Path(tempfile.gettempdir()) / "michiflin-code"
SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".pytest_cache", ".mypy_cache", "venv", ".venv"}
BLOCK = re.compile(r"<<<\s*(FILE|RUN|DONE|DELETE)\b[ \t]*([^\n>]*?)\s*>>>[ \t]*\n?(.*?)\n?[ \t]*<<<\s*END\s*>>>", re.S | re.I)
FENCE = re.compile(r"^\s*```[\w.+-]*\n(.*?)\n```\s*$", re.S)

_busy = threading.Semaphore(1)
_isolation: bool | None = None


class CoderError(Exception):
    pass


# ---------------------------------------------------------------------------
# Sandbox.
# ---------------------------------------------------------------------------
def _tool_path() -> str:
    folders = [os.path.dirname(sys.executable)]
    node = shutil.which("node")
    if node:
        folders.append(os.path.dirname(os.path.realpath(node)))
    folders += ["/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dict.fromkeys(folders))


def _wrap(command: str) -> list[str]:
    """Run one shell command as nobody in fresh network, PID and mount namespaces with resource limits."""
    return [
        "sudo", "-n", "timeout", "-k", "3", str(RUN_TIMEOUT),
        "unshare", "--net", "--pid", "--fork", "--kill-child", "--mount-proc", "--",
        "setpriv", "--reuid=65534", "--regid=65534", "--clear-groups", "--",
        "env", "-i", f"PATH={_tool_path()}", "HOME=/tmp", "LANG=C.UTF-8", "PYTHONDONTWRITEBYTECODE=1", "PYTHONIOENCODING=utf-8",
        "prlimit", "--cpu=20", "--as=2147483648", "--fsize=20971520", "--nproc=256", "--",
        "bash", "-c", "umask 000; " + command,
    ]


def isolation() -> bool:
    """True when commands can run fully isolated; without it the agent only writes files."""
    global _isolation
    if _isolation is None:
        _isolation = False
        if config.CODE_RUN and all(shutil.which(tool) for tool in ("sudo", "unshare", "setpriv", "prlimit", "timeout")):
            try:
                probe = subprocess.run(_wrap("id -u"), capture_output=True, text=True, timeout=20, cwd=tempfile.gettempdir())
                _isolation = probe.returncode == 0 and probe.stdout.strip() == "65534"
            except (OSError, subprocess.SubprocessError):
                _isolation = False
    return _isolation


def _lock_private() -> None:
    """Keep the bot's own folders unreadable for the sandbox user."""
    for folder in {config.CONFIG_DIR, config.JOB_ROOT, config.TEMP_ROOT, Path.home()}:
        try:
            path = Path(folder)
            if path.is_dir() and path.stat().st_uid == os.getuid():
                path.chmod(0o700)
        except OSError:
            continue


def _remove(folder: Path) -> None:
    if not folder.exists():
        return
    if isolation():
        subprocess.run(["sudo", "-n", "rm", "-rf", "--", str(folder)], capture_output=True, timeout=30)
    shutil.rmtree(folder, ignore_errors=True)


def _run(folder: Path, command: str) -> tuple[int, str]:
    try:
        done = subprocess.run(_wrap(command), cwd=folder, capture_output=True, timeout=RUN_TIMEOUT + 10)
        output = (done.stdout + done.stderr).decode("utf-8", "replace")
        code = done.returncode
    except subprocess.TimeoutExpired:
        output, code = "", 124
    if code in {124, 137}:
        output += f"\n[stopped: {RUN_TIMEOUT} s or CPU limit reached]"
    if len(output) > OUTPUT_MAX:
        output = output[:OUTPUT_MAX // 2] + "\n[…]\n" + output[-OUTPUT_MAX // 2:]
    return code, output.strip()


# ---------------------------------------------------------------------------
# Project files.
# ---------------------------------------------------------------------------
def safe_path(raw: str) -> str:
    path = raw.strip().strip("`'\"").replace("\\", "/") if raw else ""
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("/"):
        return ""
    path = re.sub(r"/{2,}", "/", path)
    parts = [part for part in path.split("/") if part]
    if not parts or len(path) > 140 or any(part in {".", ".."} or part.startswith("~") for part in parts):
        return ""
    if not all(re.fullmatch(r"[\w.\- ]{1,80}", part) for part in parts):
        return ""
    return "/".join(parts)


def _unfence(content: str) -> str:
    match = FENCE.match(content)
    if match:
        return match.group(1)
    lines = content.split("\n")
    if lines and re.fullmatch(r"\s*```[\w.+-]*\s*", lines[0]):
        lines = lines[1:]
    if lines and re.fullmatch(r"\s*```\s*", lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines)


def write_files(folder: Path, files: list[dict[str, Any]]) -> None:
    for item in files[:MAX_FILES]:
        path = safe_path(str(item.get("path", "")))
        if not path:
            continue
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if "b64" in item:
            try:
                target.write_bytes(base64.b64decode(str(item["b64"]), validate=True)[:MAX_BINARY])
            except (ValueError, TypeError):
                continue
        else:
            target.write_text(str(item.get("text", ""))[:MAX_FILE], encoding="utf-8")
    _open_up(folder)


def _open_up(folder: Path) -> None:
    for path in [folder, *folder.rglob("*")]:
        try:
            if path.stat().st_uid == os.getuid():
                path.chmod(0o777 if path.is_dir() else 0o666)
        except OSError:
            continue


def read_files(folder: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    total = 0
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if not path.is_file() or path.is_symlink() or any(part in SKIP_DIRS for part in relative.parts) or path.suffix == ".pyc":
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if total + len(data) > MAX_TOTAL or len(found) >= MAX_FILES:
            break
        try:
            text = data.decode("utf-8")
            if len(data) > MAX_FILE or "\x00" in text:
                raise UnicodeDecodeError("utf-8", data, 0, 1, "binary")
            found.append({"path": relative.as_posix(), "text": text})
        except UnicodeDecodeError:
            if len(data) > MAX_BINARY:
                continue
            found.append({"path": relative.as_posix(), "b64": base64.b64encode(data).decode()})
        total += len(data)
    return found


def project_name(files: list[dict[str, Any]]) -> str:
    """Human name of a project: manifest name, else the page title, else empty."""
    texts = {item["path"]: item.get("text", "") for item in files}
    found = re.search(r'^\s*name\s*=\s*"([^"\n]{1,60})"', texts.get("manifest.toml", ""), re.M)
    if not found:
        found = re.search(r"<title>\s*([^<\n]{1,60}?)\s*</title>", texts.get("index.html", ""), re.I)
    return found.group(1).strip() if found else ""


def tree(files: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {item['path']} ({len(item.get('text', '')) or len(item.get('b64', '')) * 3 // 4} bytes)" for item in files) or "(empty)"


# ---------------------------------------------------------------------------
# Agent loop.
# ---------------------------------------------------------------------------
def parse(text: str) -> list[tuple[str, str, str]]:
    return [(kind.upper(), arg.strip(), body) for kind, arg, body in BLOCK.findall(text or "")]


def _versions() -> str:
    found = [f"Python {sys.version.split()[0]}"]
    node = shutil.which("node")
    if node:
        try:
            found.append("Node " + subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip().lstrip("v"))
        except (OSError, subprocess.SubprocessError):
            pass
    return ", ".join(found) + ", bash"


def system_prompt(locale: str, can_run: bool) -> str:
    language = "Spanish" if locale == "es" else "English"
    run_block = ("<<<RUN>>>\nshell commands, already inside the project folder: use relative paths, never cd elsewhere (25 s, no network)\n<<<END>>>\n" if can_run else "")
    verify = ("- Verify your work: run the program or quick tests (python3 -m unittest, node file.js, node --check for web scripts). "
              "When a command fails, fix the code and run again.\n- Finish with DONE only when the code works.\n"
              if can_run else "- Commands cannot run here, so re-read your code carefully before DONE.\n")
    return (
        "You are Programador, a careful senior software engineer working as an autonomous coding agent.\n"
        f"Workspace: a project folder on Linux with {_versions()}. There is no internet: you cannot install packages "
        "(no pip or npm install), so use only the standard library and built-in modules. Web pages must be self-contained "
        "(inline CSS and JS, no CDNs).\n"
        "Reply ONLY with action blocks, nothing else:\n"
        "<<<FILE relative/path.ext>>>\ncomplete file content\n<<<END>>>\n"
        + run_block +
        "<<<DELETE relative/path.ext>>>\n<<<END>>>\n"
        f"<<<DONE>>>\nsummary for the user in {language}: what you built and how to use or run it (2 to 6 short lines)\n<<<END>>>\n"
        "Rules:\n"
        "- First decide what the user wants. If the message is a question or a chat (for example 'do you know how to make X?', "
        "'what is Y?', 'can you explain Z?') and does not clearly ask you to build or change something, do NOT write files or run "
        "anything: reply only with a DONE block that answers briefly and asks what they would like you to build.\n"
        "- Always write whole files; never use placeholders or '...'.\n"
        "- Web pages: plain HTML, CSS and JS that open from index.html; keep element ids in the HTML and the JS identical. "
        "An automatic web check reports ids and local links that do not match, so do not write fake-DOM tests.\n"
        "- Delta Chat mini apps (webxdc, .xdc): when the user asks for a mini app, put index.html at the project root, load "
        "<script src=\"webxdc.js\"></script> before your own scripts (the messenger provides that file: never write it) and "
        "use window.webxdc for shared state: selfAddr, selfName, sendUpdate({payload: data}, \"\") and "
        "setUpdateListener(function (update) {...}, 0), which also replays every earlier update. Mini apps have no internet. "
        "Add manifest.toml with one line: name = \"Short app name\". The app packages the project as an .xdc file, so never write "
        "zip files or packaging scripts.\n"
        "- Keep the project small and clear (at most 12 files); add a short README.md when there is more than one file.\n"
        f"- Write user-facing text, comments and the README in {language} unless the user asks otherwise.\n"
        + verify
    )


PLACEHOLDER = re.compile(r"^\W*(\(?\s*\d+\s+lines?\s+written\s*\)?|\.\.\.|…|unchanged|same as before|\[wrote [^\]]*\])\W*$", re.I)


def _compact(text: str) -> str:
    """Older turns keep a note of each action but not the file bodies (and no action syntax the model could copy)."""
    def note(match: re.Match) -> str:
        kind, arg, body = match.group(1).upper(), match.group(2).strip(), match.group(3)
        if kind == "FILE":
            return f"[wrote {arg}: {body.count(chr(10)) + 1} lines]"
        if kind == "RUN":
            return f"[ran: {body.strip()[:200]}]"
        return f"[{kind.lower()} {arg}]".strip()
    return BLOCK.sub(note, text)[:4000]


ASKING = re.compile(r"^\W*(sabes|sabrías|sabrias|conoces|qué es|que es|qué son|que son|cómo funciona|como funciona|explícame|explicame|"
                    r"por qué|por que|do you know|what is|what's|what are|how does|explain|why)\b", re.I)
ORDER = re.compile(r"\b(hazme|haz una?|créame|creame|crea una?|construye|prográmame|programame|genera una?|escribe una?|"
                   r"make me|build me|create me|write me)\b|^\W*(make|build|create|write|add|change|fix)\b", re.I)
POLITE = re.compile(r"^\W*(puedes|podrías|podrias|me haces|me creas|me programas|me puedes|can you|could you|would you|please|por favor)\b", re.I)
BUILD = re.compile(r"\b(hacer|crear|construir|programar|generar|escribir|desarrollar|añadir|agregar|cambiar|arreglar|corregir|"
                   r"make|build|create|write|generate|develop|add|change|fix)\b", re.I)


def looks_like_question(text: str) -> bool:
    """A question without a direct order ('do you know how to make a mini app?') is answered, not built."""
    text = text.strip()
    if len(text) > 400 or ORDER.search(text) or POLITE.search(text):
        return False
    return bool(ASKING.search(text)) or (text.endswith("?") and not BUILD.search(text))


def run(request: str, files: list[dict[str, Any]], locale: str, model_key: str = "") -> dict[str, Any]:
    if not _busy.acquire(timeout=5):
        raise CoderError(tr(locale, "Programador ya está trabajando en otro proyecto. Prueba en unos minutos.",
                            "Programador is already working on another project. Try again in a few minutes."))
    try:
        return _run_project(request, files, locale, model_key)
    finally:
        _busy.release()


def _ask(messages: list[dict[str, Any]], model_key: str, sticky: str) -> ai.AIResult:
    if model_key:
        return ai.complete_exact(messages, model_key, max_tokens=ANSWER_TOKENS, raw=True)
    if sticky:
        result = ai.complete_exact(messages, sticky, max_tokens=ANSWER_TOKENS, raw=True)
        if result.ok:
            return result
    return ai.complete(messages, "code", max_attempts=6, max_tokens=ANSWER_TOKENS, raw=True)


ID_DEFINED = re.compile(r"""\bid\s*=\s*["'`]([\w-]+)|\.id\s*=\s*["'`]([\w-]+)|setAttribute\(\s*["']id["']\s*,\s*["'`]([\w-]+)""")
ID_USED = re.compile(r"""getElementById\(\s*["'`]([\w-]+)["'`]\s*\)|querySelector(?:All)?\(\s*["'`]#([\w-]+)["'`]\s*\)""")
LOCAL_REF = re.compile(r"""<(?:script[^>]+src|link[^>]+href)\s*=\s*["']([^"':?#]+\.(?:m?js|css))["']""", re.I)


def web_check(files: list[dict[str, Any]]) -> list[str]:
    """Catch the classic text-only mistakes of web projects: JS ids missing from the HTML and broken local links."""
    texts = {item["path"]: item["text"] for item in files if "text" in item}
    pages = {path: text for path, text in texts.items() if path.lower().endswith((".html", ".htm"))}
    if not pages:
        return []
    scripts = {path: text for path, text in texts.items() if path.endswith((".js", ".mjs"))
               and not re.search(r"(^|[/._-])(tests?|spec)([/._-]|$)", path.lower())}
    for text in pages.values():
        for index, inline in enumerate(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", text, re.S | re.I)):
            scripts[f"inline script {index + 1}"] = inline
    defined = {name for text in [*pages.values(), *scripts.values()] for match in ID_DEFINED.findall(text) for name in match if name}
    problems = []
    for path, text in scripts.items():
        for name in sorted({name for match in ID_USED.findall(text) for name in match if name} - defined):
            problems.append(f"{path} looks up #{name}, but no element has id=\"{name}\"")
    for path, text in pages.items():
        base = posixpath.dirname(path)
        for ref in LOCAL_REF.findall(text):
            target = posixpath.normpath(posixpath.join(base, ref.removeprefix("./")))
            if not ref.startswith(("http", "//")) and target not in texts and target != "webxdc.js":
                problems.append(f"{path} links {ref}, but that file does not exist")
    return problems


def _wrap_up(messages: list[dict[str, Any]], model_key: str, sticky: str) -> str:
    """Out of rounds: ask only for the closing summary of what exists now."""
    final = messages + [{"role": "user", "content": "No rounds left. Do not write or run anything. Reply only with "
                         "<<<DONE>>>\nshort summary for the user, in their language: what was built, how to use it and "
                         "anything left unfinished\n<<<END>>>"}]
    result = _ask(final, model_key, sticky)
    if not result.ok:
        return ""
    found = [(body or arg).strip() for kind, arg, body in parse(result.text) if kind == "DONE"]
    if found:
        return found[0][:3000]
    text = result.text.strip()
    return text[:3000] if text and "<<<" not in text and len(text) < 3000 else ""


def _sticky_key(result: ai.AIResult) -> str:
    for item in ai.providers():
        if item.name == result.provider:
            for model in item.models:
                if model.title() == result.model:
                    return model.key
    return ""


def _run_project(request: str, files: list[dict[str, Any]], locale: str, model_key: str) -> dict[str, Any]:
    started = time.monotonic()
    can_run = isolation()
    if can_run:
        _lock_private()
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o711)
    folder = Path(tempfile.mkdtemp(prefix="p", dir=ROOT))
    folder.chmod(0o777)
    steps: list[dict[str, Any]] = []
    summary, used, sticky = "", "", ""
    try:
        write_files(folder, files)
        context = ""
        if files:
            shown = read_files(folder)
            budget = 30_000
            parts = []
            for item in shown:
                body = item.get("text", "[binary file]")
                if budget - len(body) < 0:
                    parts.append(f"<<<FILE {item['path']}>>> (too long to show; read it with a command) <<<END>>>")
                    continue
                budget -= len(body)
                parts.append(f"<<<FILE {item['path']}>>>\n{body}\n<<<END>>>")
            context = "Current project files:\n" + "\n".join(parts) + "\n\n"
        hint = ("\n\n(This looks like a question: answer it in a DONE block and build nothing unless the user clearly asked for it.)"
                if looks_like_question(request) and not files else "")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(locale, can_run)},
            {"role": "user", "content": context + "Message from the user: " + request + hint},
        ]
        for step in range(MAX_STEPS):
            if time.monotonic() - started > TIME_BUDGET:
                break
            progress.phase(f"💻 Programando · paso {step + 1}", f"💻 Coding · step {step + 1}")
            result = _ask(messages, model_key, sticky)
            if not result.ok:
                if step == 0:
                    raise CoderError(ai.describe_error(result.error, locale, result, model_key).replace("⚠️ IA: ", "").replace("⚠️ ", ""))
                break
            used = result.signature()
            sticky = sticky or _sticky_key(result)
            actions = parse(result.text)
            if not actions:
                if step == 0 and not files:
                    summary = result.text.strip()[:3000]
                    break
                messages += [{"role": "assistant", "content": result.text[:3000]},
                             {"role": "user", "content": "Use only the action blocks described above."}]
                continue
            results, done, failed = [], "", False
            for kind, arg, body in actions:
                if kind == "FILE":
                    path = safe_path(arg)
                    if not path:
                        results.append(f"! Skipped unsafe path: {arg}")
                        continue
                    content = _unfence(body)
                    if PLACEHOLDER.match(content.strip() or "..."):
                        results.append(f"! {path} was NOT written: send the complete file content, never a placeholder.")
                        continue
                    target = folder / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content[:MAX_FILE], encoding="utf-8")
                    steps.append({"kind": "write", "path": path, "lines": _unfence(body).count("\n") + 1})
                elif kind == "DELETE":
                    path = safe_path(arg)
                    if path and (folder / path).is_file():
                        (folder / path).unlink()
                        steps.append({"kind": "delete", "path": path})
                elif kind == "DONE":
                    done = (body or arg).strip()
            _open_up(folder)
            runs = [body.strip() for kind, _arg, body in actions if kind == "RUN" and body.strip()][:RUNS_PER_STEP] if can_run else []
            for command in runs:
                code, output = _run(folder, command)
                failed = failed or code != 0
                steps.append({"kind": "run", "cmd": command[:400], "code": code, "out": output[:1500]})
                results.append(f"$ {command}\nexit {code}\n{output}")
            problems = web_check(read_files(folder)) if any(kind in ("FILE", "DELETE") for kind, _a, _b in actions) else []
            if problems:
                failed = True
                report = "\n".join(problems[:12])
                steps.append({"kind": "run", "cmd": "web check", "code": 1, "out": report[:1500]})
                results.append(f"$ web check (HTML, CSS and JS references)\nexit 1\n{report}")
            for message in messages[2:]:
                if message["role"] == "assistant":
                    message["content"] = _compact(message["content"])
            messages.append({"role": "assistant", "content": result.text[:24000]})
            if done and not failed:
                summary = done[:3000]
                break
            if len(messages) > 14:
                messages = messages[:2] + messages[-10:]
            state = "Project files now (read one with: cat path):\n" + tree(read_files(folder))
            if results:
                messages.append({"role": "user", "content": "Results:\n" + "\n\n".join(results)[:7000] + "\n\n" + state +
                                 "\n\nFix any error, or finish with <<<DONE>>> if everything works."})
            else:
                messages.append({"role": "user", "content": state + ("\n\nNow run the code to check it, then finish with <<<DONE>>>."
                                                                     if can_run else "\n\nFinish with <<<DONE>>> when the project is complete.")})
        output = read_files(folder)
        if output and not summary and time.monotonic() - started < TIME_BUDGET + 60:
            summary = _wrap_up(messages, model_key, sticky)
        if not output and not summary:
            raise CoderError(tr(locale, "Los modelos no produjeron código. Reformula la petición o prueba otro modelo.",
                                "The models produced no code. Rephrase the request or try another model."))
        if not summary:
            summary = tr(locale, "Terminé sin confirmación final; revisa el registro de pasos.", "Stopped without a final confirmation; check the step log.")
        return {"files": output, "summary": summary, "steps": steps[-60:], "sig": used, "isolated": can_run,
                "seconds": round(time.monotonic() - started), "name": project_name(output),
                "answer": not any(step["kind"] in {"write", "delete"} for step in steps)}
    finally:
        _remove(folder)
