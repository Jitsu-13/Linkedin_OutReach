# Omokai — Interview Walkthrough Script

This document is your personal guide for walking through this project in an interview.
Each section has a **what to say**, a **what to show**, and answers to likely follow-up questions.

---

## Opening — The Elevator Pitch (30 seconds)

> "I built an end-to-end LinkedIn outreach automation pipeline in Python.
> The problem it solves is simple: sending personalized connection requests at scale is
> repetitive and time-consuming if done manually. This system automates the full flow —
> it reads a list of target profiles from a Google Sheet, visits each profile, scrapes
> context about the person, uses an LLM to generate a unique personalized connection note,
> engages with their recent posts, sends the request, and logs everything.
> There's also a scheduled follow-up job that detects accepted connections and
> withdraws stale ones automatically."

**Why it's interesting to an interviewer:**
- Real-world automation problem
- Touches browser automation, LLM APIs, async Python, SQLite, Google Sheets API
- Has a non-trivial anti-detection design requirement

---

## Section 1 — High-Level Architecture

**What to say:**

> "The project is organized into four layers:
>
> - **Agents** — each agent owns one responsibility: scraping a profile, engaging with posts,
>   sending a connection request, or running follow-ups. They only know about the browser
>   and the LLM service — they don't touch the database or Sheets directly.
>
> - **Services** — the browser, LLM, Google Sheets, and SQLite state are all services.
>   Any agent or the main pipeline can use them. Services have no knowledge of each other.
>
> - **Utils** — shared, stateless helpers: random delays, jitter, retry logic, logging,
>   screenshots. These have zero business logic.
>
> - **Config** — a single `get_settings()` function returns a typed Pydantic object
>   that merges `.env` secrets with `config.yaml` tunables. No hardcoded values exist
>   anywhere in the codebase."

**What to show:** The folder structure in the terminal or file explorer.

```
agents/        ← profile, engagement, connection, followup
services/      ← browser, llm, sheets, state
utils/         ← delays, jitter, retry, logger, screenshot
config/        ← settings.py, config.yaml
main.py        ← pipeline entry point
followup.py    ← follow-up job entry point
```

**Likely question:** *Why separate agents from services?*

> "Agents have state and orchestration logic — they decide what to do and in what order.
> Services are pure infrastructure — they know how to do one thing (make an API call,
> drive a browser, write to SQLite). Keeping them separate means I can swap out the
> browser service entirely — say, switch from Playwright to Selenium — without touching
> any agent. It also makes the agents unit-testable by injecting mock services."

---

## Section 2 — Configuration System (`config/settings.py`)

**What to say:**

> "All configuration lives in two files. `config.yaml` holds tunables — delays, LLM model,
> character limits, browser viewport — things that are safe to commit to git.
> `.env` holds secrets — API keys, LinkedIn credentials, spreadsheet ID — things that
> must never be committed.
>
> The `get_settings()` function loads both and merges them into a single validated
> Pydantic `Settings` object. I used `@lru_cache` so this object is built exactly once
> per process and reused everywhere. Priority is: `.env` overrides > `config.yaml` values > defaults.
>
> Every subsystem has its own nested model: `LinkedInConfig`, `LLMConfig`, `BrowserConfig`, etc.
> Pydantic validates types at load time, so if someone puts a string where an int is expected,
> it fails immediately with a clear error rather than crashing later mid-run."

**What to show:** Open `config/settings.py` and `config/config.yaml` side by side.

Point to `get_settings()` — specifically the `@lru_cache` decorator and the `.env` override block at the bottom.

**Likely question:** *Why not just use environment variables directly?*

> "Two reasons. First, environment variables are all strings — you'd have to cast every value manually.
> Pydantic handles that automatically. Second, a flat list of env vars doesn't express structure.
> `config.yaml` gives me nested sections (`linkedin.delay_min_seconds`) which are far more readable
> than `LINKEDIN_DELAY_MIN_SECONDS`. The two-file approach lets me have the best of both:
> structured config in yaml, secrets isolation in `.env`."

---

## Section 3 — Browser Service & Anti-Detection (`services/browser_service.py`)

**What to say:**

> "The browser service is built on Playwright — Microsoft's modern alternative to Selenium.
> I chose Playwright over Selenium because it has a much better async API, built-in
> waiting strategies, and a persistent context feature that Selenium doesn't have natively.
>
> The most important anti-detection decision is running in **headed mode** — a visible
> browser window — by default. Headless Chromium has well-known fingerprints that
> LinkedIn's bot detection picks up immediately. A visible browser with stealth patches
> is much harder to distinguish from a real user.
>
> I also use `playwright-stealth`, which patches about 20 browser properties that
> automation detection scripts check: `navigator.webdriver`, WebGL renderer strings,
> Canvas fingerprints, and others.
>
> The third key decision is **persistent context** — `launch_persistent_context()` saves
> cookies and localStorage to a `browser_data/` directory. After the first manual login,
> every subsequent run reuses the session. No repeated logins means no repeated login events
> to flag."

**What to show:** Open `browser_service.py`. Walk through these three methods:

1. `start()` — point to `launch_persistent_context`, `stealth_async`, and the Chrome args
2. `human_click()` — show the bounding box math and `mouse.move()` with random steps
3. `human_type()` — show the character-by-character loop with `typing_delay_ms()`

**Likely question:** *Why does human_click use a random point inside the element instead of just clicking the center?*

> "Real users almost never click the exact center of a button. They aim roughly for it
> and land somewhere in the middle third. Automation frameworks default to center-clicks.
> LinkedIn's ML-based detection can flag that pattern. Moving to a random point within
> the element's bounding box and moving the mouse in multiple steps — not teleporting —
> makes the click pattern statistically indistinguishable from a real mouse."

**Likely question:** *How does CAPTCHA detection work?*

> "After every profile, I check `detect_captcha_or_restriction()`. It looks at the current URL
> and page content for six strings: `/checkpoint/`, `security verification`, `unusual activity`,
> `restricted`, `captcha`, `verify your identity`. If any match, the pipeline stops
> immediately and takes a screenshot for debugging. It's simple string matching, but
> LinkedIn's restriction pages are consistent in their wording."

---

## Section 4 — Profile Extraction (`agents/profile_agent.py`)

**What to say:**

> "The profile agent navigates to a LinkedIn profile URL and extracts structured context:
> name, headline, current role, company, about snippet, mutual connections, and recent posts.
>
> The key design challenge here is that LinkedIn's DOM changes frequently — they A/B test
> UI layouts constantly. If I hardcoded one CSS selector per field, the scraper would break
> every few weeks. Instead, each field has a list of fallback selectors tried in order.
> The first one that returns text wins. This makes the scraper resilient to layout changes
> without requiring code updates.
>
> For recent posts, I navigate to the profile's `/recent-activity/all/` subpage, scroll to
> load dynamic content, and extract post text snippets. Those snippets are later used by the
> LLM to reference something the person actually said — making the connection note feel
> genuinely researched rather than templated."

**What to show:** Open `profile_agent.py`. Point to:

1. The `SELECTORS` dictionary at the top — show that `name` has 5 fallbacks
2. `_try_selectors()` — the loop that tries each one and returns the first match
3. `_extract_recent_posts()` — the navigation to `/recent-activity/all/`

**Likely question:** *What happens if none of the selectors match?*

> "The field returns an empty string and the LLM generates the note with whatever context
> it does have. For name specifically, if extraction fails I also take a screenshot
> immediately — that captures the page state so I can debug what changed in LinkedIn's DOM.
> The pipeline never hard-crashes on a missing field; it degrades gracefully."

---

## Section 5 — Two-Pass LLM Note Generation (`services/llm_service.py`)

This is the most technically interesting part. Spend the most time here.

**What to say:**

> "Note generation uses a two-pass architecture with a post-processing jitter step.
>
> **Pass 1 — Draft:** I send the scraped profile context to the LLM at temperature 0.7
> — relatively creative. The system prompt enforces hard rules: stay within the character
> limit, reference something specific from the profile, no buzzwords, sound human.
> The output is a raw draft.
>
> **Pass 2 — Review:** A second LLM call at temperature 0.3 — much stricter — acts
> as a quality gate. It checks the draft against five criteria: length, personalization,
> tone, grammar, authenticity. If any fail, it rewrites. Lower temperature means more
> deterministic, rule-following output — exactly what you want from a reviewer.
>
> **Jitter:** After both LLM passes, I apply four post-processing transformations:
> greeting variation (10 different opening templates), synonym substitution (1-2 random
> swaps from a curated pair list), emoji randomization (30% add / 20% remove), and
> punctuation variation (swap final period/exclamation). The goal is that even if two
> notes start from identical LLM output, the final text sent is always different. This
> defeats LinkedIn's pattern-detection heuristics, which look for repeated message
> templates."

**What to show:** Open `llm_service.py` and `utils/jitter.py`.

In `llm_service.py`:
1. `generate_note()` — walk through the three stages: draft call, review call, `apply_all_jitter()`
2. Point to the different temperatures: `self._temperature` (0.7) for draft, `self._review_temperature` (0.3) for review
3. Show `_PROVIDER_CONFIGS` — the multi-provider dict at the top

In `jitter.py`:
1. `apply_all_jitter()` — the master function calling all four transformers in sequence
2. `apply_greeting_jitter()` — the regex that detects greeting patterns and swaps them
3. The character limit enforcement at the end of `apply_all_jitter()`

**Likely question:** *Why two LLM calls instead of one?*

> "One call with a very long system prompt is tempting, but it tends to produce output
> that satisfies the prompt literally without actually being good. The review pass acts
> like a second pair of eyes. The first call focuses on being creative and personalized.
> The second call focuses on being correct — enforcing rules the first call sometimes
> ignores. The lower temperature on the review pass is important: you want the reviewer
> to be strict and consistent, not creative."

**Likely question:** *Why not just tell the LLM to vary its own phrasing?*

> "LLMs are deterministic at temperature 0 and pseudo-random at higher temperatures,
> but the distribution of their outputs clusters around common phrasings. Two calls
> with the same input at temperature 0.7 will produce similar-sounding notes more
> often than not. Jitter injects true randomness — uniform distribution across 10 greeting
> templates, random synonym selection — that an LLM cannot replicate. It also means
> the variation is predictable and auditable: I can look at the jitter code and know
> exactly what transformations are possible."

**Likely question:** *How do you support multiple LLM providers?*

> "I have a `_PROVIDER_CONFIGS` dictionary that maps provider names to their base URLs,
> chat endpoints, and auth header formats. OpenAI, NVIDIA, and OpenRouter all use the
> OpenAI-compatible API format — same request structure, different base URL and key.
> Anthropic uses a different Messages API format with a different response shape,
> so it gets its own `_call_anthropic()` method. The user switches providers by
> changing two lines in `.env`: `LLM_PROVIDER` and `LLM_API_KEY`. The rest of the
> code is unaffected."

---

## Section 6 — Engagement Agent (`agents/engagement_agent.py`)

**What to say:**

> "Before sending a connection request, the engagement agent interacts with the person's
> recent posts. It navigates to their `/recent-activity/all/` page, likes up to 3 posts,
> then generates and posts an AI comment on one of them using the same two-pass LLM
> pattern.
>
> The reason for engaging first is purely strategic: the person sees a like and a
> thoughtful comment from you before the connection request arrives. It creates context —
> the request feels like a natural follow-up from someone who engaged with their content,
> not a cold blast from a stranger.
>
> The like buttons use multiple selector fallbacks for the same reason as the profile
> scraper. The agent also checks `aria-pressed='true'` before clicking — if a post is
> already liked, it skips it rather than toggling it off."

**What to show:** Open `engagement_agent.py`.
1. `engage_with_posts()` — the top-level flow: navigate, like, comment, navigate back
2. `_like_posts()` — point to the `aria-pressed` check and the multi-selector loop
3. `_comment_on_post()` — the LLM call and the character-by-character typing

---

## Section 7 — Connection Agent (`agents/connection_agent.py`)

**What to say:**

> "The connection agent sends the actual connection request. The tricky part is that
> LinkedIn presents the Connect button in different places depending on the profile type.
> Some profiles show it directly in the action bar. Others bury it in a 'More actions'
> dropdown. Some profiles are in 'Follow' mode where Connect is even harder to find.
>
> The agent handles all three cases: it tries a direct Connect button first, then opens
> the More dropdown and looks for Connect inside it. After clicking Connect, it handles
> the 'Add a note' dialog, types the note character-by-character, and clicks Send.
>
> After sending, it verifies success two ways: it looks for a success toast notification,
> and if that's not present, it checks whether the dialog itself disappeared — which
> also implies success. It also detects and skips profiles that are already connected
> or have a pending request."

**What to show:** Open `connection_agent.py`.
1. `_detect_connection_state()` — show how it returns 4 possible states
2. `_click_connect_button()` — walk through the direct button path and the dropdown path
3. `_verify_sent()` — show both verification strategies

---

## Section 8 — State Management (`services/state_service.py`, `schema.sql`)

**What to say:**

> "Every profile processed gets a row in a local SQLite database. The status column
> follows a strict workflow: `pending` → `sent` → `accepted` or `withdrawn`.
> There's also `error` and `skipped` for failed and already-connected profiles.
>
> The database is the authoritative source of truth — not the Google Sheet.
> If the Sheet sync fails due to a network issue or quota limit, the local state is intact.
> At the start of each profile loop, the code checks local state first — if a URL
> already has status `sent` or `accepted`, it skips it entirely. This makes the pipeline
> safe to restart mid-run after a crash.
>
> The schema also stores all three versions of every note — draft, reviewed, final —
> along with engagement counts and timestamps. That's a full audit trail for every
> outreach action ever taken."

**What to show:** Open `schema.sql`.
1. Point to the `status CHECK()` constraint — enforces the state machine at the database level
2. Point to `note_draft`, `note_reviewed`, `note_final` — the three-version audit trail
3. Point to the `trg_updated_at` trigger — auto-maintains `updated_at` on every update

**Likely question:** *Why SQLite instead of Postgres or another database?*

> "This is a single-user, single-machine tool. SQLite has zero setup, zero running server,
> the database is a single file you can open in any SQLite browser for debugging,
> and it's fast enough for a few thousand records. Postgres would be over-engineering
> for this use case. The WAL journal mode I enabled (`PRAGMA journal_mode=WAL`) gives
> better concurrent read performance, which matters because the state service opens a
> new connection per call rather than holding one open — a pattern that's safer when
> async code is involved."

---

## Section 9 — Follow-up Job (`followup.py`, `agents/followup_agent.py`)

**What to say:**

> "The follow-up job runs separately from the main outreach pipeline, on a 14-day schedule.
> It reads all records with `status='sent'` from SQLite, navigates to LinkedIn's
> Sent Invitations page, scrolls to load all entries, and cross-references names.
>
> The acceptance detection logic is indirect but effective: LinkedIn's Sent Invitations
> page only shows *pending* requests. If someone accepted your request, they disappear
> from that list. So if a person is in our local state as `sent` but NOT found on the
> Sent Invitations page, they've likely accepted. I mark them as `accepted` in state
> and sync to the Sheet.
>
> For requests still pending after the configured threshold (14 days by default), the
> agent finds their invitation card and clicks Withdraw — then confirms the withdrawal
> dialog. This keeps the account clean and within LinkedIn's weekly invitation limits.
>
> The scheduling uses APScheduler with SQLite persistence — job state survives restarts,
> so if the machine reboots, the scheduler resumes at the correct next-run time."

**Likely question:** *What if someone accepted but their name matches someone else on the sent list?*

> "There's a risk of false positives in the fuzzy name matching. I match on first name
> AND last name together, not just first name alone, which reduces collisions significantly.
> For common names it's still not perfect — that's a known limitation documented in
> `KNOWN_LIMITATIONS.md`. In practice the error rate is low because the sent invitations
> list is typically short, but the right fix would be to cross-reference by profile URL
> rather than by name, which would require navigating to each invitation card."

---

## Section 10 — Retry & Error Handling (`utils/retry.py`)

**What to say:**

> "Two functions that are decorated with `@with_retry` are `profile_agent.extract_context()`
> and `browser_service.safe_navigate()`. These are the most likely to have transient failures —
> network timeouts, page load failures, LinkedIn returning a 429.
>
> The decorator uses exponential backoff: on the first retry it waits `2^1 = 2` seconds,
> second retry `2^2 = 4` seconds, up to a configurable cap of 60 seconds. This prevents
> hammering a server that's already struggling. The decorator takes a `retry_on` tuple —
> you can specify exactly which exception types should trigger a retry versus which should
> bubble up immediately."

**What to show:** Open `utils/retry.py`. Point to the `backoff_base ** attempt` calculation.

---

## Section 11 — The Full Pipeline (Tie It All Together)

**What to say — narrate the full flow:**

> "So putting it all together, when you run `python main.py`:
>
> 1. Settings are loaded and validated. The database is initialized from `schema.sql`.
> 2. Google Sheets connects and reads all rows that don't already have a `sent` status — those are the targets.
> 3. The LLM does a health check — a simple 'Reply with OK' call to verify the API key works.
> 4. The browser launches — headed Chromium with stealth patches — and checks login status.
> 5. For each target, in order:
>    - Skip it if SQLite already shows it as sent or accepted.
>    - Profile agent scrapes the page — name, headline, about, recent posts.
>    - Engagement agent likes up to 3 posts and posts an AI-generated comment.
>    - LLM service runs two passes to generate the connection note, then applies jitter.
>    - Connection agent sends the request with the note through the LinkedIn UI.
>    - SQLite marks it as sent; Google Sheet row is updated.
>    - Wait 2-5 minutes (random) before the next profile.
> 6. If 3 consecutive errors occur, the pipeline pauses for 30 minutes then resumes.
> 7. If a CAPTCHA is detected at any point, it stops immediately."

**What to show:** Open `main.py`. Walk through `run_outreach()` from top to bottom, pointing to each step matching your narration.

---

## Common Interview Questions & Answers

**Q: How do you prevent LinkedIn from banning the account?**

> "Multiple layered defenses. Browser: headed mode, stealth patches, persistent session, human-like click and type patterns. Timing: 2-5 minute random delays between profiles, random keystroke delays. Volume: capped at 25 requests per run. Error handling: auto-pause after 3 consecutive failures, CAPTCHA detection that stops everything. Message uniqueness: jitter ensures no two notes are textually identical. No single measure is sufficient — the value is in the combination."

**Q: How would you scale this to multiple accounts?**

> "Each account needs its own browser profile (separate `user_data_dir`), its own `.env` credentials, and its own state database. The cleanest way would be to pass a profile ID as a CLI argument and use it to namespace all paths. Running multiple instances concurrently would need a distributed queue (Redis, SQS) instead of reading directly from a single Google Sheet, to avoid two instances processing the same target row."

**Q: What would you do differently if you started over?**

> "Profile extraction is the most fragile part — it breaks when LinkedIn changes their DOM. I'd replace the CSS selector chains with a vision model that takes a screenshot and extracts structured data from the visual layout. LinkedIn can change class names and HTML structure but they can't radically change what a profile page looks like to a human eye. That would make extraction much more resilient."

**Q: Why Python for this?**

> "Playwright has first-class Python async support. The LLM client libraries (openai, anthropic) are Python-native. Pydantic and gspread exist. For async I/O-heavy automation work, Python's asyncio is excellent — you get non-blocking waits without the complexity of threading. The alternative would be Node.js with Playwright, which has slightly better browser support, but Python has the better AI/ML ecosystem."

**Q: How do you handle the LinkedIn rate limit on connection requests?**

> "LinkedIn limits non-premium accounts to roughly 100 connection requests per week, premium to around 250. The `max_requests_per_run` config (default 25) keeps a single run well within safe territory. The follow-up job also withdraws stale pending requests, which frees up quota. These numbers are documented in `KNOWN_LIMITATIONS.md`."

**Q: Walk me through a scenario where everything goes wrong mid-run.**

> "Say the browser crashes after 10 profiles are processed. On restart:
> 1. The database already has those 10 as `sent` — they're skipped immediately.
> 2. We resume from profile 11.
>
> Say LinkedIn shows a CAPTCHA on profile 7:
> 1. `detect_captcha_or_restriction()` returns True.
> 2. The pipeline breaks the loop and takes a screenshot.
> 3. Profiles 1-6 are already marked `sent` in the database.
> 4. Profile 7 is marked `error`.
> 5. After the operator resolves the CAPTCHA manually, restarting resumes from profile 7."

---

## Demo Flow (If You Can Show a Live Run)

```bash
# 1. Show the project structure
ls -la

# 2. Show config (no secrets in yaml)
cat config/config.yaml

# 3. Show .env.example (never the real .env)
cat .env.example

# 4. Run a dry run — no LinkedIn actions, just generates notes
python main.py --dry-run --limit 3

# 5. Show the SQLite database after the run
python3 -c "
import sqlite3
conn = sqlite3.connect('data/state.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT name, status, note_final FROM outreach_records LIMIT 5').fetchall()
for r in rows:
    print(dict(r))
"

# 6. Show the log
tail -50 data/logs/outreach.log
```

---

## One-Sentence Answers for Rapid-Fire Questions

| Question | Answer |
|---|---|
| What is Playwright? | Microsoft's browser automation library — modern, async, more reliable than Selenium |
| What is playwright-stealth? | A library that patches ~20 browser properties that automation detection scripts check |
| What is Pydantic? | A Python library for data validation using type annotations — validates config at load time |
| What is gspread? | A Python wrapper for the Google Sheets API |
| What is APScheduler? | A Python job scheduler — used to run the follow-up job every 14 days |
| What does `@lru_cache` do? | Memoizes the function result — `get_settings()` is called many times but builds the object once |
| What is WAL mode in SQLite? | Write-Ahead Logging — allows concurrent reads while a write is in progress |
| What is `asyncio`? | Python's event loop for non-blocking I/O — all browser and HTTP calls run asynchronously |
| What is jitter? | Post-processing random text variation applied after LLM generation to make each note unique |
| What does the retry decorator do? | Wraps async functions with exponential backoff — retries on transient failures |
