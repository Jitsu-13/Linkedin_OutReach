# LinkedIn Outreach Automation

An AI-powered, production-ready pipeline that automates personalized LinkedIn connection requests. It extracts profile context via browser automation, likes recent posts, posts an AI-generated comment, generates a two-pass personalized connection note with human-like jitter, sends the request, and tracks every action in both a local SQLite database and Google Sheets.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Local Setup (Windows / macOS / Linux)](#local-setup)
4. [Google Sheets Service Account Setup](#google-sheets-service-account-setup)
5. [Paid LLM API Configuration](#paid-llm-api-configuration)
6. [Environment Configuration](#environment-configuration)
7. [How to Run: Outreach Job](#how-to-run-outreach-job)
8. [How to Run: Follow-up Job](#how-to-run-follow-up-job)
9. [Running with Mock / Test Data](#running-with-mock--test-data)
10. [Safety Configuration Guide](#safety-configuration-guide)
11. [Expected Console Output & Sheet Updates](#expected-console-output--sheet-updates)
12. [Known Limitations & Manual Intervention](#known-limitations--manual-intervention)

---

## Architecture Overview

```
main.py (outreach pipeline)
├── SheetsService        → reads target URLs from Google Sheets
├── BrowserService       → Playwright + stealth patches, persistent session
├── LLMService           → two-pass note/comment generation (draft → review → jitter)
├── ProfileAgent         → extracts name, headline, role, posts from LinkedIn profile
├── EngagementAgent      → likes 2–3 posts, posts AI-reviewed comment on one
├── ConnectionAgent      → clicks Connect → Add a note → Send
└── state_service        → SQLite CRUD, marks sent/skipped/error

followup.py (scheduled every 14 days)
├── FollowupAgent        → checks Sent Invitations, marks accepted or withdraws stale
└── SheetsService        → syncs accepted/withdrawn timestamps back to sheet
```

See `Architecture.md` for detailed design decisions.

---

## Prerequisites

- **Python 3.11+**
- **Google Chrome** (Playwright downloads Chromium automatically)
- A **Google Cloud service account** with Sheets + Drive API access
- An **LLM API key** (OpenAI, Anthropic, NVIDIA free tier, or OpenRouter)

---

## Local Setup

### 1. Clone / unzip the project

```bash
cd /path/to/project
```

### 2. Create and activate a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers

```bash
playwright install chromium
playwright install-deps chromium   # Linux only — installs system deps
```

> **Windows/macOS:** `playwright install-deps` is not needed; Chromium bundles its own dependencies.

### 5. Create required directories

```bash
mkdir -p data/screenshots data/logs browser_data
```

### 6. Copy and fill in the environment file

```bash
cp .env.example .env
# Now edit .env with your credentials (see sections below)
```

---

## Google Sheets Service Account Setup

### Step 1 — Enable APIs in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select an existing one)
3. Navigate to **APIs & Services → Library**
4. Enable **Google Sheets API**
5. Enable **Google Drive API**

### Step 2 — Create a Service Account

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → Service Account**
3. Give it a name (e.g., `linkedin-outreach-bot`)
4. Click **Done**

### Step 3 — Download the JSON key

1. Click the service account you just created
2. Go to the **Keys** tab
3. Click **Add Key → Create new key → JSON**
4. Download the file — rename it `service_account.json`
5. Move it to `credentials/service_account.json`

### Step 4 — Share your Google Sheet with the service account

1. Open your Google Sheet
2. Click **Share**
3. Enter the service account email (looks like `name@project-id.iam.gserviceaccount.com`)
4. Grant **Editor** access

### Step 5 — Get the Spreadsheet ID

From your Sheet URL:
```
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID_HERE/edit
```
Copy the `SPREADSHEET_ID_HERE` value into your `.env`:
```
GOOGLE_SHEETS_SPREADSHEET_ID=your-spreadsheet-id
```

### Sheet Format

Your sheet must have a header row with at minimum a `linkedin_url` column. Use the template:

```bash
# Import linkedin_targets_template.csv as the starting point
```

Required columns: `linkedin_url`, `name`, `company`, `role`  
Output columns (auto-created if missing): `status`, `note_used`, `sent_at`, `accepted_at`, `withdrawn_at`, `comment_posted`, `posts_liked`

---

## Paid LLM API Configuration

Set `LLM_PROVIDER` and `LLM_API_KEY` in your `.env` file:

### OpenAI (default)

```env
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
```

Recommended model: `gpt-4o-mini` (fast + cheap) or `gpt-4o` (higher quality).  
Override in `.env`: `LLM_MODEL=gpt-4o`

### Anthropic (Claude)

```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
```

Recommended model: `claude-haiku-4-5-20251001` (fast) or `claude-sonnet-4-6` (higher quality).  
Override: `LLM_MODEL=claude-haiku-4-5-20251001`

### NVIDIA Free Tier

```env
LLM_PROVIDER=nvidia
LLM_API_KEY=nvapi-...
```

Get a free key at https://build.nvidia.com/  
Recommended model: `meta/llama-3.1-8b-instruct`  
Override: `LLM_MODEL=meta/llama-3.1-8b-instruct`

### OpenRouter

```env
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-...
```

Supports 100+ models. Set `LLM_MODEL` to any OpenRouter model slug.

---

## Environment Configuration

Copy `.env.example` to `.env` and fill in all values:

```env
# LLM
LLM_PROVIDER=openai
LLM_API_KEY=sk-your-key

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE=./credentials/service_account.json
GOOGLE_SHEETS_SPREADSHEET_ID=your-spreadsheet-id

# LinkedIn credentials (used only for initial login)
LINKEDIN_EMAIL=your-email@example.com
LINKEDIN_PASSWORD=your-password

# Who is sending the requests (used by LLM for personalization)
SENDER_NAME=Your Name
SENDER_CONTEXT=Senior software engineer at a fintech startup, interested in ML and distributed systems

# Optional
LOG_LEVEL=INFO
```

All other settings (delays, rate limits, note length, etc.) live in `config/config.yaml`.

---

## How to Run: Outreach Job

### Basic run (up to 25 profiles from config)

```bash
python main.py
```

### Limit to N profiles

```bash
python main.py --limit 5
```

### Dry-run (test pipeline without touching LinkedIn)

```bash
python main.py --dry-run
```

Dry-run will:
- Read targets from Google Sheets
- Initialize the LLM and verify connectivity
- Generate test notes (two-pass + jitter) and log them
- Skip all browser/LinkedIn actions

### Use 200-character notes instead of 300

```bash
python main.py --char-limit 200
```

### Skip post engagement (no liking/commenting)

```bash
python main.py --skip-engage
```

### Full options

```
Options:
  --limit N        Max profiles to process (0 = config default 25)
  --dry-run        Full pipeline without LinkedIn actions
  --char-limit N   Override note character limit (200 or 300)
  --skip-engage    Skip liking and commenting
  --help           Show help
```

### First-run login

On the first run, a Chrome browser window opens. If you are not already logged in:
- The script attempts automatic login with your `.env` credentials
- If LinkedIn shows a CAPTCHA or 2FA prompt, complete it manually in the open browser window
- The script waits up to 5 minutes for manual verification
- Once logged in, the session is saved to `browser_data/` and reused on future runs

### Docker

```bash
docker-compose up outreach
```

Note: Docker runs in headless mode. Initial login must be completed outside Docker or with a pre-populated `browser_data/` volume.

---

## How to Run: Follow-up Job

### Run once immediately

```bash
python followup.py
```

### Run on a recurring 14-day schedule

```bash
python followup.py --schedule
```

### Custom interval

```bash
python followup.py --schedule --interval 7   # every 7 days
```

### Docker (scheduled mode)

```bash
docker-compose up followup
```

The follow-up job:
1. Loads all `sent` records from local SQLite
2. Navigates to LinkedIn Sent Invitations
3. Cross-references names — if a person is no longer in the sent list, they accepted
4. Withdraws requests pending for longer than `withdraw_after_days` (default: 14)
5. Syncs `accepted` / `withdrawn` + timestamps back to Google Sheets

---

## Running with Mock / Test Data

### 1. Dry-run with Sheet data

The simplest mock test — uses real Sheet targets but performs no LinkedIn actions:

```bash
python main.py --dry-run --limit 3
```

This verifies:
- Google Sheets connectivity and target reading
- LLM API connectivity and two-pass note generation
- Jitter logic
- Local state DB initialization

### 2. Using the CSV template

Import `linkedin_targets_template.csv` into a Google Sheet, share it with your service account, and set the spreadsheet ID in `.env`. The template has 3 placeholder profiles.

### 3. Environment for testing

You can point to a separate test Sheet by temporarily changing `GOOGLE_SHEETS_SPREADSHEET_ID` in `.env`. Local state is in `data/state.db` — delete it to start fresh:

```bash
rm data/state.db
python main.py --dry-run
```

---

## Safety Configuration Guide

All safety parameters are in `config/config.yaml`:

```yaml
linkedin:
  # Hard cap on requests per run
  max_requests_per_run: 25

  # Delay between profiles (seconds) — minimum 120 recommended
  delay_min_seconds: 120
  delay_max_seconds: 300

  # In-page action delays (seconds)
  action_delay_min: 2
  action_delay_max: 8

  # Typing speed (ms per character)
  typing_delay_min_ms: 50
  typing_delay_max_ms: 150

  # Post engagement
  posts_to_like: 3
  posts_to_comment: 1

  # Pause automation after N consecutive errors
  max_errors_before_pause: 3
  pause_duration_minutes: 30
```

### Recommendations

| Concern | Setting | Recommended value |
|---------|---------|-------------------|
| Daily limit | `max_requests_per_run` | ≤ 25 (LinkedIn soft limit) |
| Between profiles | `delay_min/max_seconds` | 120–300s |
| CAPTCHA triggered | Reduce to 5–10/run; increase delay | — |
| Account restricted | Stop immediately; resume in 48h | — |

### CAPTCHA / Restriction Handling

The script automatically detects CAPTCHA and restriction pages and halts. Check `data/screenshots/` for the capture of the triggering page. Wait 24–48 hours before resuming.

### Rate Limiting

LinkedIn enforces soft limits: roughly 20–30 connection requests per day for standard accounts, up to ~100 for Premium. The pipeline caps at `max_requests_per_run` (default: 25) and spaces them with 120–300s delays.

---

## Expected Console Output & Sheet Updates

### Successful run (condensed)

```
2025-01-15 10:00:01 | INFO     | LinkedIn Outreach Automation — Starting
2025-01-15 10:00:02 | INFO     | LLM health check passed (openai/gpt-4o-mini)
2025-01-15 10:00:03 | INFO     | Processing 3 targets (limit: 25)
2025-01-15 10:00:05 | INFO     | Target 1/3: Jane Smith
2025-01-15 10:00:08 | INFO     | Step 1: Extracting profile context...
2025-01-15 10:00:12 | INFO     | Step 2: Engaging with posts...
2025-01-15 10:00:18 | INFO     |   Liked post 1/3
2025-01-15 10:00:24 | INFO     |   Liked post 2/3
2025-01-15 10:00:31 | INFO     |   Comment posted: Fascinating take on...
2025-01-15 10:00:33 | INFO     | Step 3: Generating personalized note (two-pass + jitter)...
2025-01-15 10:00:34 | INFO     |   Pass 1: Draft (287 chars): Hi Jane, your work on...
2025-01-15 10:00:35 | INFO     |   Pass 2: Reviewed (291 chars): Hi Jane, your work on...
2025-01-15 10:00:35 | INFO     |   Final (289 chars): Hey Jane, your work on...
2025-01-15 10:00:36 | INFO     | Step 4: Sending connection request...
2025-01-15 10:00:40 | INFO     |   Connection request sent successfully!
2025-01-15 10:00:40 | INFO     | Profile delay: waiting 187.3s before next profile
```

### Google Sheet after a run

| linkedin_url | name | status | note_used | sent_at | posts_liked | comment_posted |
|---|---|---|---|---|---|---|
| linkedin.com/in/... | Jane Smith | sent | Hey Jane... | 2025-01-15 10:00:40 | 2 | Fascinating take... |

### Summary at end of run

```
📊 Outreach Run Summary
  Processed: 3
  Sent:      3
  Skipped:   0
  Errors:    0
```

---

## Known Limitations & Manual Intervention

See `KNOWN_LIMITATIONS.md` for the full list.

**Quick reference:**

- **LinkedIn DOM changes**: Selectors may break after LinkedIn UI updates. Check `data/screenshots/` on failures and update `SELECTORS` in `agents/profile_agent.py`.
- **Acceptance detection**: LinkedIn has no public API for this. The heuristic (not in Sent list = accepted) can produce false positives if someone withdraws your request.
- **CAPTCHA**: Automation halts — manual completion required.
- **Initial login**: First run requires manual login if session doesn't exist.
- **Daily rate limit**: LinkedIn may restrict accounts exceeding ~20–30 requests/day.
