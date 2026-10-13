# Michiflin AI

**Your internet over e-mail.** Michiflin AI is a private [Delta Chat](https://delta.chat) bot that searches, reads web pages, answers with free AI models, creates images and downloads files, then delivers everything as small chat messages. It is built for mailboxes with tight quotas and slow, expensive connections.

<p align="center">
  <img src="docs/media/en/home.png" width="200" alt="Home screen of the mini app">
  <img src="docs/media/en/agent.png" width="200" alt="Agent answering a question">
  <img src="docs/media/en/web-reader.png" width="200" alt="Web page in the reader">
  <img src="docs/media/en/downloads.png" width="200" alt="Download sent in parts">
</p>

<p align="center">
  <a href="docs/GUIDE.md"><b>User guide</b></a> ·
  <a href="README.es.md"><b>Español</b></a>
</p>

## Highlights

- **One mini app for everything.** The bot sends a WebXDC app on first contact, with a short welcome that explains it, and everything happens there: home, AI, web, apps, downloads and settings. A brief introduction runs the first time the app opens. The chat only carries delivered media and files.
- **An agent that needs no AI.** Write normally or paste a link; the agent searches, reads the sources and builds the answer from them, with cited sentences, plus calculator, weather, rates, translation and summaries. It never calls an AI model, so it touches no quota.
- **Free AI only.** Routes across free tiers (Gemini, Groq, Mistral, Z.AI, OpenRouter, Cloudflare, BazaarLink, OrcaRouter, plus the keyless LLM7 and Kilo gateways) with per-model quotas and automatic fallback. Each model shows why it is paused: limit reached, key rejected or no longer free, and the bot notifies you when a model stops or comes back. Pick the exact image model or let it choose. Each model chat shows its maker's mark and takes the attachments that model can read: photos, PDF and documents, and audio on Gemini.
- **A coding agent.** Describe a program or a web page; free coding models write the files, run them in an isolated sandbox without network or secrets, and fix errors until the tests pass. Preview web pages inside the app and export Delta Chat mini apps as ready-to-open `.xdc` files named after the project (or the source as a ZIP). Plain questions get an answer instead of a build.
- **Light web browsing.** Pages arrive as a compact text view with tappable links. PDF and sharp screenshots on request. Search the web, news, videos or Wikipedia with the standard engine (no limits), or switch the bar to the advanced engine when you need better results.
- **Downloads that fit a mailbox.** Videos, audio and files are split into small parts. Media parts are playable segments; other files are numbered parts with a checksum. Downloaded `.xdc` files arrive as mini apps that open in the chat.
- **Fair sharing.** When several authorized people use the bot, downloads and deliveries take turns: whoever has fewer jobs running and has received less today goes first. Each person has a limit of simultaneous downloads and an optional daily quota that only moves them to the back of the line. AI is shared the same way: each person has a daily allowance of AI requests, images and Coder projects, runs one AI request at a time and sees what is left in the app; when little free AI remains for the day, a reserve keeps the larger models for administrators.
- **Join parts on any phone.** A built-in tool puts the parts in order by itself, even if the phone renamed them, verifies them and joins them, including video and audio segments into one playable file.
- **Useful without AI.** Translator, unit converter, local time, weather, headlines, informal exchange rates and a calculator.
- **Private by design.** Owner-only access, unknown senders are blocked silently, and no prompts, answers or files are stored.
- **Administration.** A live panel shows CPU, memory, disk, network, response times, the queue and the host session, runs a bounded stress test, and lists each person's share of the traffic (amounts only, never content) so disproportionate use stands out.

## The mini app

<p align="center">
  <img src="docs/media/en/clip-tour.gif" width="260" alt="Mini app tour">
  <img src="docs/media/en/clip-web.gif" width="260" alt="Searching and reading a page">
</p>
<p align="center"><sub>Tour (<a href="docs/media/en/clip-tour.mp4">MP4</a>) · Search and read (<a href="docs/media/en/clip-web.mp4">MP4</a>)</sub></p>

The app is sent by the bot and talks to it through WebXDC updates, so it works wherever Delta Chat works, with no internet access of its own.

| Tab | What it does |
|---|---|
| **Home** | Search box, shortcuts, queue status and time until the next server restart |
| **AI** | Agent, automatic model rotation, image studio and one chat per model with remaining uses |
| **Web** | Results from the selected engine, reader view, history, PDF, screenshot and download actions |
| **Apps** | YouTube, translator, rates, weather, news, utilities, status and administration |
| **Downloads** | Queue with progress, pause, resume, cancel, retry and resend; the tab shows a badge with the downloads in progress |
| **Settings** | App language and theme, default engine, every bot setting (changed by the administrator) and data cleanup |

The app follows the device language (Spanish or English) and theme, and adapts from phones to desktop.

## Chat usage

By default the bot works **only through the mini app**. It sends the app automatically when a contact first connects, and any text written in the chat is answered with a pointer to the latest app. `/app` sends a fresh copy at any time. Files sent to the chat (voice notes, photos, documents) are still processed.

Setting `chat` to `full` (or `CHAT_MODE=full` as the default) restores classic chat mode, where every feature is also a bilingual command. The command list is in the [guide](docs/GUIDE.md#classic-chat-mode).

### Settings

Each person has their own bot settings, set in the mini app or with `/settings NAME VALUE` in classic chat mode (Spanish name in parentheses). A new person starts from the administrator's values and can reset to them at any time. Only the **For everyone** group is shared, and only administrators see and change it.

| Group | Setting | Values |
|---|---|---|
| Downloads | `video` (`video`) | 144–1080 · low · medium · high (default 360) |
| | `audio` (`audio`) | 32–160 kbps · low · medium · high |
| | `format` (`formato`) | m4a · mp3 · opus |
| | `part` (`parte`) | 1–20 MB per part |
| | `packing` (`empaque`) | parts · 7z · zip |
| Delivery | `auto` (`auto`) | yes · no |
| | `batch` (`lote`) | 0 = all · N parts then pause |
| | `delay` (`pausa`) | seconds between parts |
| | `window` (`ventana`) | e.g. 2200-0600 · no |
| | `cap` (`tope`) | MB received per 24 h · 0 = no cap |
| Web | `page` (`pagina`) | 30–900 KB per reader page |
| | `images` (`imagenes`) | no · low |
| | `links` (`enlaces`) | chat · web |
| | `capture` (`captura`) | mobile · desktop |
| | `sharpness` (`nitidez`) | normal · high · max |
| General | `language` (`idioma`) | auto · es · en |
| | `notices` (`avisos`) | minimal · normal |
| | `progress` (`progreso`) | yes · no |
| | `reactions` (`reacciones`) | yes · no · all |
| | `imagesize` (`imagen`) | 512 · 768 · 1024 |
| | `chat` (`chat`) | app · full |
| For everyone | `jobs` (`trabajos`) | 1–20 downloads at once per person (default 3; administrators are exempt) |
| | `quota` (`cuota`) | MB per person a day · 0 = none; over it, a person is served last |
| | `airequests` (`consultas`) | AI requests per person a day (default 60) · 0 = no limit |
| | `imagesday` (`dibujos`) | images per person a day (default 15) · 0 = no limit |
| | `projects` (`proyectos`) | Coder projects per person a day (default 4) · 0 = no limit |
| | `reserve` (`reserva`) | % of the day's free AI kept for administrators (default 25) · 0 = none |
| | `retention` (`retencion`) | hours to keep finished jobs |

## Configuration

Copy `.env.example` and fill in what you need. Only `OWNER_ADDRESS` is required.

- **Access:** `OWNER_ADDRESS` is the administrator. `ALLOWED_SENDERS` adds more addresses (comma separated); the owner can also grant access from the app.
- **Owner notice:** `OWNER_NOTICE` (optional) is shown once in the owner's app after the next start; a new text is shown again.
- **AI providers:** one key per provider, all optional: `GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `ZAI_API_KEY`, `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_AI_TOKEN`, `GITHUB_MODELS_TOKEN`, `POLLINATIONS_API_KEY`, `BAZAARLINK_API_KEY`, `ORCAROUTER_API_KEY`. Only free models are used. LLM7 and Kilo work without a key; their optional free tokens `LLM7_API_KEY` and `KILO_API_KEY` raise the limits, and `FREE_GATEWAYS=0` turns both off.
- **Images:** Cloudflare models, a Hugging Face Space (`HF_TOKEN`, `HF_IMAGE_SPACE`), AI Horde volunteer GPUs (keyless and slower; `AI_HORDE_API_KEY` adds priority, `AI_HORDE=0` disables) and Pollinations (`POLLINATIONS_PUBLIC=0` disables the keyless endpoint). Automatic mode tries them in order; any of them can be chosen by hand.
- **Coder:** project commands run as an unprivileged user in a network-less namespace with CPU, memory and time limits; this needs passwordless `sudo`, `unshare`, `setpriv` and `prlimit`. Without them, or with `CODE_RUN=0`, the coder only writes files.
- **Search:** the standard engine is keyless. `YDC_API_KEY` (optional, `YDC_DAILY` limit) enables the advanced engine.
- **Other services:** `ELTOQUE_API_TOKEN` uses the official elTOQUE API for rates (the public table is read without it). `MICHIFLIN_GITHUB_TOKEN` enables `/github`.
- **Blocked sources:** `MEDIA_PROXY` and `WEB_PROXY` route downloads and pages through a SOCKS or HTTP proxy. `YTDLP_COOKIES` accepts a Netscape cookie file.
- **Extra providers:** `EXTRA_PROVIDERS` adds OpenAI-compatible free providers as JSON:

  ```json
  [{"key": "example", "name": "Example", "base_url": "https://api.example.com/v1",
    "api_key_env": "EXAMPLE_API_KEY", "models": [{"id": "model-name", "roles": ["chat"], "daily": 200}]}]
  ```

- **Chat mode:** `CHAT_MODE` is `app` (mini app only, the default) or `full` (classic commands too).
- **Defaults and limits:** every setting above has an environment default (`DEFAULT_VIDEO_HEIGHT`, `CHUNK_MB`, `READER_PAGE_KB`, `NOTIFY_MODE`…), and `MAX_FILE_MB`, `MAX_QUEUE_MB` and `MIN_FREE_DISK_MB` protect the disk.

The account state (Delta Chat keys, settings, queue metadata) lives in `CONFIG_DIR`. `state_backup.py save|restore` keeps an encrypted copy in a private repository (`STATE_BACKUP_REPO`, `STATE_BACKUP_PASSPHRASE`); large files are excluded.

## Running

Requirements: Python 3.11+, ffmpeg, 7-Zip (`p7zip-full`) and Chromium for Playwright. Installing deno is recommended for yt-dlp.

```bash
pip install -r requirements.txt
python -m playwright install --with-deps chromium
python bot.py --config-dir ./state init DCACCOUNT:nine.testrun.org
python bot.py --config-dir ./state serve
```

Each session lasts `SESSION_DURATION_SECONDS`. The status view shows uptime and the time left until the planned restart, and pending jobs resume in the next session.

### Reliable delivery

- **Every message is taken exactly once.** Live core events are backed by the core's bot cursor (`get_next_msgs` / `markseen_msgs`) and a small inbox kept in the state, checked every 20 seconds. A message whose event was missed, or that arrived while the bot was offline, is still answered; one interrupted by a crash is run again (at most twice).
- **Per-chat order without blocking.** Each chat has its own queue, so a slow request never holds the threads that serve app updates or other chats.
- **Graceful stop.** On `SIGTERM` or `SIGINT` the bot stops taking new work, lets running requests finish (up to 75 s), waits for outgoing mail to leave and saves the state before closing the core. Unstarted requests stay unread for the next session.
- **Self-update.** The bot checks the deployed branch every five minutes; when a new commit appears and nothing is running, it hands over to a fresh session (the job writes `RESTART_MARKER` and starts the next run).
- **App instances are kept.** History pruning never removes the mini app message, so app requests can always be matched to it.

## Development

```bash
python -m pytest -q tests/
python tests/test_webxdc.py
```

`bot.py` is the entry point and `michiflin/` holds the package:

| Module | Role |
|---|---|
| `agent`, `answer` | Intent routing and the agent's extractive answers |
| `ai` | Providers, models and quotas |
| `web`, `reader`, `browser` | Pages, reader view, PDF and screenshots |
| `media`, `files`, `queue` | Downloads, parts and delivery |
| `commands`, `names` | Chat commands and their names in both languages |
| `miniapp` | WebXDC bridge; the app itself lives in `webxdc/` |
| `admin` | Access control and alerts |
| `usage`, `perf` | Fair-share accounting, server metrics and the stress test |
| `extras`, `tools` | Translator, converter, weather, rates and search |

## Privacy

Prompts, answers and downloaded files are never stored in the state. Usage accounting keeps only daily totals per address (bytes delivered, number of downloads and requests) for seven days. The bot deletes its local copy of old messages and removes temporary files after one hour. Messages from unknown senders get no reply: the owner receives one alert and the contact is blocked.

## License

All rights reserved. The code is published for reading and learning only; running it for others or redistributing it requires permission. See [LICENSE](LICENSE).
