# Omokai — LinkedIn Outreach Automation: Code Explanation

## What It Does

Omokai automates LinkedIn connection outreach. Given a list of target profiles in a Google Sheet, it:

1. Visits each LinkedIn profile and scrapes context (name, headline, role, about, recent posts)
2. Likes their recent posts and posts an AI-generated comment
3. Generates a personalized connection note using a two-pass LLM pipeline
4. Sends the connection request with the note
5. Logs everything to a local SQLite database and writes results back to the Google Sheet
6. Runs a separate follow-up job to detect accepted connections and withdraw stale ones

---

## Project Structure

```
Omokai/
├── main.py                   # Main pipeline entry point
├── followup.py               # Follow-up / withdrawal job entry point
├── schema.sql                # SQLite database schema
│
├── config/
│   ├── config.yaml           # All tunables (delays, LLM model, limits)
│   └── settings.py           # Pydantic settings loader (merges .env + yaml)
│
├── services/
│   ├── browser_service.py    # Playwright-based stealth browser
│   ├── llm_service.py        # Multi-provider LLM client (two-pass generation)
│   ├── sheets_service.py     # Google Sheets read/write
│   └── state_service.py      # SQLite CRUD for outreach records
│
├── agents/
│   ├── profile_agent.py      # Scrapes profile context from LinkedIn
│   ├── engagement_agent.py   # Likes posts and posts AI comments
│   ├── connection_agent.py   # Sends the connection request with note
│   └── followup_agent.py     # Checks sent requests; marks accepted/withdrawn
│
└── utils/
    ├── logger.py             # Loguru-based structured logging with rotation
    ├── delays.py             # Random human-like wait functions
    ├── jitter.py             # Post-LLM text variation to defeat pattern detection
    ├── retry.py              # Decorator for retrying failed async operations
    └── screenshot.py         # Captures browser screenshots on failure
```

---

## How It Works — End to End

### Entry Point (`main.py`)

`main.py` runs the full outreach pipeline. It's a `click` CLI with four flags:

| Flag | Purpose |
|---|---|
| `--limit N` | Cap how many profiles to process this run |
| `--dry-run` | Full pipeline except actual LinkedIn clicks — generates and logs notes only |
| `--char-limit N` | Override connection note length (200 or 300 chars) |
| `--skip-engage` | Skip liking posts / posting comments |

The pipeline initializes services in order: database → Google Sheets → LLM → browser. Then for each target it runs four sequential steps (profile extraction → engagement → note generation → send) and logs the result.

**Why async?** All I/O — browser automation, HTTP API calls, delays — is non-blocking. `asyncio` lets waits happen concurrently without spawning threads.

---

### Configuration (`config/settings.py`, `config/config.yaml`)

Settings come from two sources merged into one Pydantic `Settings` object:

- **`config.yaml`** — structural tunables: delays, LLM model, limits, browser viewport
- **`.env`** — secrets and runtime overrides: API key, LinkedIn credentials, spreadsheet ID

Priority is: `.env` overrides > `config.yaml` values > Pydantic defaults.

`get_settings()` uses `@lru_cache` — the settings object is built once and reused across the entire run. Nested Pydantic models (`LinkedInConfig`, `LLMConfig`, `BrowserConfig`, etc.) give type safety and auto-validation without boilerplate.

**Why separate yaml from .env?** Secrets never belong in a tracked file. `config.yaml` is safe to commit; `.env` stays in `.gitignore`.

---

### Step 1 — Profile Extraction (`agents/profile_agent.py`)

`ProfileAgent.extract_context()` navigates to a LinkedIn profile URL and scrapes:

| Field | Source |
|---|---|
| Name, headline, location | Top-card selectors |
| About snippet | `#about` section (capped at 500 chars) |
| Current role & company | First entry in experience section |
| Mutual connections | Parsed from text like "12 mutual connections" |
| Recent posts | Navigates to `/recent-activity/all/` and extracts post text |

**Why multiple fallback selectors?** LinkedIn's DOM changes frequently. Each field has a list of CSS selectors tried in order — the first match wins. This means the scraper keeps working even after LinkedIn redesigns a page section.

**Why scroll before extracting?** LinkedIn lazy-loads content — the about section and experience cards only render after the user scrolls down. The agent scrolls before reading.

---

### Step 2 — Engagement (`agents/engagement_agent.py`)

`EngagementAgent.engage_with_posts()`:

1. Navigates to the profile's `/recent-activity/all/` page
2. Finds all like buttons and clicks up to `posts_to_like` of them (skips already-liked ones)
3. Reads the first post's text, generates an AI comment via `LLMService.generate_comment()`, and types + submits it

**Why engage before connecting?** Liking and commenting warms up the interaction. The person may notice the activity before receiving the connection request, making the request feel less cold.

**Why human-like clicks?** `button.click()` fires instantly. `BrowserService.human_click()` moves the mouse to a random point inside the element's bounding box, pauses, then clicks — identical to a real user.

---

### Step 3 — Note Generation (`services/llm_service.py`)

This is the core intelligence. It uses a **two-pass architecture** plus **jitter**:

#### Pass 1 — Draft
A high-temperature (0.7) LLM call generates a personalized connection note from the scraped profile context. The system prompt enforces hard rules: character limit, no buzzwords, must reference something specific from the profile.

#### Pass 2 — Review
A second LLM call at lower temperature (0.3) acts as a quality reviewer. It checks the draft against five criteria (length, personalization, tone, grammar, authenticity) and rewrites it if any fail. Lower temperature = stricter, more predictable output.

#### Jitter (`utils/jitter.py`)
Applied after the LLM review pass, jitter introduces randomness that the LLM cannot apply deterministically:

- **Greeting variation** — randomly picks from 10 greeting templates (`Hi`, `Hey`, `Hello`, `{name} —`, etc.)
- **Synonym substitution** — randomly swaps 1-2 phrases from a curated pair list (`excited` → `thrilled`, `great` → `wonderful`)
- **Emoji** — 30% chance to add one; 20% chance to strip any existing ones
- **Punctuation** — 25% chance to change the final `.` to `!` or vice versa

**Why jitter?** LinkedIn's detection systems flag repeated message templates. Even if two notes start from identical LLM output, jitter ensures the final text sent differs in subtle ways, defeating pattern-matching heuristics.

**Why two passes instead of one?** A single LLM call can produce good drafts but sometimes fails on length enforcement or tone. The review pass acts as a quality gate and catches these failures before sending — avoiding a bad first impression.

**Supported LLM providers:** OpenAI, Anthropic, NVIDIA (free-tier), OpenRouter. The provider-specific API differences (OpenAI vs Anthropic request/response format) are abstracted inside `_call_llm()` and `_call_anthropic()`.

---

### Step 4 — Connection Request (`agents/connection_agent.py`)

`ConnectionAgent.send_request()` drives the LinkedIn UI:

1. **Detect state** — checks if already connected, pending, or not connected yet. Skips if already sent.
2. **Find the Connect button** — LinkedIn hides it in different places depending on the profile type. The agent tries a direct button first, then opens the "More actions" dropdown.
3. **Add a note** — clicks "Add a note", waits for the textarea, types the personalized note character-by-character with human-like speed.
4. **Send** — clicks the Send/Send now button.
5. **Verify** — checks for a success toast notification, or infers success if the dialog disappears.

---

### State Persistence (`services/state_service.py`, `schema.sql`)

Every profile processed gets a row in the SQLite database (`data/state.db`). The status column follows a strict workflow:

```
pending → sent → accepted
                → withdrawn
         → error
         → skipped
```

The `upsert_record()` function uses INSERT OR UPDATE logic — safe to call multiple times for the same URL. If the script crashes mid-run, restarting it skips already-sent profiles (checked at the start of each loop iteration).

The schema also stores all three versions of the note (draft, reviewed, final), engagement counts, and timestamps — a full audit trail for every outreach action.

**Why SQLite and not the sheet directly?** The Google Sheet is the user-facing view. SQLite is the authoritative source of truth. If the sheet sync fails (network issue, quota hit), the local state is intact and the sheet can be synced later.

---

### Browser Service (`services/browser_service.py`)

Built on **Playwright** with **playwright-stealth** patches.

Key design decisions:

- **Persistent context** (`launch_persistent_context`) — cookies, localStorage, and session data are saved in `./browser_data/`. After the first manual login, all subsequent runs reuse the session without logging in again.
- **Stealth patches** — `stealth_async()` patches browser fingerprints (WebGL, Canvas, `navigator.webdriver`, etc.) that automation detection scripts check for.
- **Headed mode by default** — `headless: false` in config. A visible browser window is significantly harder to detect than headless Chromium.
- **Human-like mouse movement** — `human_click()` moves to a random point within the element's bounding box in multiple steps, not a direct teleport to the center.
- **Variable typing speed** — `human_type()` types character by character with random per-keystroke delays (50–150ms).

---

### Google Sheets Integration (`services/sheets_service.py`)

Uses the `gspread` library with a Google Service Account. The sheet is used as:

- **Input** — reads unprocessed rows (those without a "sent" status in the status column)
- **Output** — writes back the note used, timestamp, comment posted, and posts liked

The column mapping is configurable in `config.yaml` → `sheets.columns`, so users can adapt it to their own sheet structure without changing code.

---

### Follow-up Job (`followup.py`, `agents/followup_agent.py`)

A separate script run independently (or on a schedule via APScheduler).

It reads all records with `status='sent'` from SQLite, navigates to LinkedIn's Sent Invitations page, and for each one:

- If accepted → marks `accepted` in local state and sheet
- If still pending and older than `withdraw_after_days` → withdraws the request and marks `withdrawn`

`--schedule` flag keeps it running indefinitely, firing every `check_interval_days` (default 14). APScheduler persists job state in a second SQLite database (`data/scheduler.db`) so it survives restarts.

---

### Anti-Detection Layer

Multiple layers work together to avoid LinkedIn's bot detection:

| Layer | Mechanism |
|---|---|
| Browser fingerprint | playwright-stealth patches navigator, WebGL, Canvas |
| Session reuse | Persistent context avoids repeated logins |
| Visible browser | Headed mode; headless Chromium has known fingerprints |
| Human-like timing | Random delays between profiles (120–300s), random click positions, variable typing speed |
| Request volume cap | Max 25 connection requests per run (configurable) |
| Error backoff | After 3 consecutive errors, pauses for 30 minutes |
| CAPTCHA detection | Checks URL and page content for restriction indicators after every profile; stops immediately if detected |
| Note uniqueness | Jitter ensures no two notes are textually identical |

---

## Data Flow Summary

```
Google Sheet (targets)
        │
        ▼
  main.py reads unprocessed rows
        │
        ▼ for each target:
  ProfileAgent.extract_context()       ← browser navigates LinkedIn
        │
        ▼
  EngagementAgent.engage_with_posts()  ← likes posts, posts AI comment
        │
        ▼
  LLMService.generate_note()           ← draft → review → jitter
        │
        ▼
  ConnectionAgent.send_request()       ← sends request with note
        │
        ▼
  state_service.mark_sent()            ← SQLite record updated
        │
        ▼
  SheetsService.update_status()        ← Google Sheet row updated
```
