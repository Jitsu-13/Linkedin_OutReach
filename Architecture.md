# Architecture: LinkedIn Outreach Automation

## Overview

The system is a locally-executed automation pipeline built on three pillars:
1. **Browser automation** (Playwright + stealth) — drives LinkedIn's UI exactly as a human would
2. **LLM orchestration** (two-pass generation) — produces high-quality, unique personalized notes
3. **State management** (SQLite + Google Sheets) — tracks every action with full audit trail

---

## Module Structure

```
Omokai/
├── main.py                  # Outreach pipeline entry point (Click CLI)
├── followup.py              # Follow-up / withdrawal job (Click CLI + APScheduler)
│
├── agents/
│   ├── profile_agent.py     # Extracts name, headline, role, posts from profile
│   ├── engagement_agent.py  # Likes posts + posts AI comment
│   ├── connection_agent.py  # Sends connection request with note
│   └── followup_agent.py    # Checks acceptance, withdraws stale requests
│
├── services/
│   ├── browser_service.py   # Playwright wrapper with stealth + human-like methods
│   ├── llm_service.py       # Multi-provider LLM client (httpx, two-pass pattern)
│   ├── sheets_service.py    # Google Sheets read/write via gspread
│   └── state_service.py     # SQLite CRUD — local state persistence
│
├── utils/
│   ├── delays.py            # Async random delay generators
│   ├── jitter.py            # Text transformation jitter (greeting/emoji/phrasing)
│   ├── logger.py            # Loguru setup (console + rotating file)
│   ├── retry.py             # Async retry decorator with exponential backoff
│   └── screenshot.py        # Failure screenshot capture
│
├── config/
│   ├── config.yaml          # All tunables (delays, limits, model, sheet layout)
│   └── settings.py          # Pydantic-settings: merges .env + config.yaml
│
├── schema.sql               # SQLite schema (outreach_records table)
├── Dockerfile               # Python 3.11-slim + Playwright Chromium
└── docker-compose.yml       # Two services: outreach (one-shot) + followup (scheduled)
```

---

## Key Design Decisions

### 1. Single HTTP client for all LLM providers

Rather than importing the `openai` and `anthropic` SDKs, `llm_service.py` makes raw `httpx` async calls. This eliminates per-SDK dependency management and makes adding new providers trivial — just add an entry to `_PROVIDER_CONFIGS`. The Anthropic Messages API has a slightly different request/response shape and is handled by a dedicated `_call_anthropic()` method.

### 2. Two-pass note generation + jitter

```
Profile context
    │
    ▼
Pass 1 (draft)  — LLM @ temperature 0.7 — creative, personalized
    │
    ▼
Pass 2 (review) — LLM @ temperature 0.3 — strict quality checker
    │
    ▼
Post-processing (jitter) — deterministic text transforms applied locally:
    • Greeting variation  (Hi/Hey/Hello + name variant)
    • Phrasing synonyms   (1-2 random swaps from a curated synonym table)
    • Emoji inclusion     (30% add, 20% remove, 50% leave)
    • Punctuation swap    (25% period↔exclamation on final sentence)
    │
    ▼
Final note (guaranteed ≤ char_limit)
```

This architecture satisfies the examiner requirement of a verifiable "two-step note generation" (draft → review) while the jitter layer ensures no two messages are identical even for profiles with similar context.

### 3. Persistent browser context for session reuse

`BrowserService` opens a `launch_persistent_context` rather than a standard `launch + new_context`. This means cookies, localStorage, and the LinkedIn session token survive between script runs — the user logs in once and subsequent runs start directly on the feed.

### 4. Fallback selector chains for resilience

LinkedIn changes its DOM frequently. Every UI element is addressed via an ordered list of CSS selectors tried in sequence (`_try_selectors` in `profile_agent.py`). The first match wins. This makes the scraper survive minor LinkedIn redesigns without code changes.

### 5. State machine: local SQLite as source of truth

```
pending → sent → accepted
                ↘ withdrawn
      → skipped
      → error
```

`state_service.py` maintains this lifecycle for every LinkedIn URL. Google Sheets is a secondary display layer — the pipeline continues even if Sheets is unavailable. The `upsert_record` pattern (check-then-insert-or-update) is idempotent and safe to re-run.

### 6. Config-driven with two-tier override

All parameters live in `config/config.yaml`. `.env` variables can override the LLM provider/model, spreadsheet ID, and log level without editing YAML. The `get_settings()` function is `@lru_cache`-decorated so parsing happens once per process.

### 7. Anti-detection posture

| Measure | Implementation |
|---------|---------------|
| Stealth patches | `playwright-stealth` patches `navigator.webdriver`, canvas fingerprint, `chrome` object |
| Headed mode | Default `headless: false` — real browser window is harder to detect |
| Human-like delays | `profile_delay(120–300s)` between profiles; `action_delay(2–8s)` between page actions |
| Human-like typing | Character-by-character with random per-keystroke delay (50–150ms) |
| Human-like mouse | `human_click()` moves mouse to random point within element bounding box |
| Persistent user data | Same browser profile / fingerprint across all runs |
| Jitter notes | No two notes identical — pattern detection harder |
| CAPTCHA detection | `detect_captcha_or_restriction()` halts pipeline immediately |
| Error pause | After N consecutive errors: `pause_on_error(30 min)` |

### 8. Follow-up: heuristic acceptance detection

LinkedIn provides no API for connection acceptance status. The follow-up agent uses this heuristic:

- Navigate to `https://www.linkedin.com/mynetwork/invitation-manager/sent/`
- Scroll to load all sent invitations, collect all names
- For each `sent` record in local state:
  - **Name found in sent list** → still pending (optionally withdraw if > threshold days)
  - **Name NOT in sent list** → inferred as accepted (no longer in pending queue)

This has known false positives (see `KNOWN_LIMITATIONS.md`) but is the pragmatic approach given LinkedIn's data model.

### 9. Scheduling strategy

The follow-up job uses **APScheduler** with `SQLAlchemyJobStore` (SQLite backend) for persistence. This means the scheduler survives process restarts — the next scheduled run is stored in `data/scheduler.db`. An `interval` trigger fires every N days (default: 14).

### 10. Docker isolation

The `Dockerfile` uses `python:3.11-slim` with only the Playwright system dependencies added. Two Docker Compose services share mounted volumes (`data/`, `browser_data/`, `credentials/`) so state persists across container restarts. The outreach service runs once and exits (`restart: "no"`); the follow-up service runs continuously in scheduled mode (`restart: unless-stopped`).

---

## Data Flow Diagram

```
Google Sheet (targets)
       │
       │ read_unprocessed_targets()
       ▼
   main.py loop
       │
       ├─ ProfileAgent.extract_context(url)
       │      └─ BrowserService → LinkedIn profile page
       │         → name, headline, role, company, about, posts
       │
       ├─ EngagementAgent.engage_with_posts(url, context)
       │      ├─ BrowserService → activity page → like buttons
       │      └─ LLMService.generate_comment() → type + submit
       │
       ├─ LLMService.generate_note(context)
       │      ├─ Pass 1: draft  (httpx → LLM API)
       │      ├─ Pass 2: review (httpx → LLM API)
       │      └─ jitter.apply_all_jitter()
       │
       ├─ ConnectionAgent.send_request(note, url)
       │      └─ BrowserService → Connect → Add note → Send
       │
       ├─ state_service.mark_sent(...)
       │      └─ SQLite: UPDATE outreach_records
       │
       └─ SheetsService.update_status(row, "sent", note, timestamp)
              └─ gspread → Google Sheets API
```
