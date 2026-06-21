# Omokai — Running the Application

This guide covers running Omokai on **Windows**, **Linux**, and **Linux inside WSL on Windows**.

---

## Prerequisites (All Platforms)

Before you start, you need:

- **Python 3.10 or higher**
- **Git** (to clone the repo)
- A **Google Service Account** JSON key with access to your Google Sheet
- An **LLM API key** (OpenAI, Anthropic, NVIDIA, or OpenRouter)
- A **LinkedIn account**

---

## Step 1 — Configure Environment

This step is the same on all platforms.

### 1a. Copy and fill in `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
LLM_PROVIDER=openai                        # openai | anthropic | nvidia | openrouter
LLM_API_KEY=sk-your-api-key-here
LLM_MODEL=gpt-4o-mini                      # optional — overrides config.yaml

GOOGLE_SHEETS_CREDENTIALS_FILE=./credentials/service_account.json
GOOGLE_SHEETS_SPREADSHEET_ID=your-spreadsheet-id-here

LINKEDIN_EMAIL=your-email@example.com
LINKEDIN_PASSWORD=your-password-here

SENDER_NAME=Your Name
SENDER_CONTEXT=Software engineer passionate about AI and distributed systems
```

### 1b. Place your Google credentials

Put your `service_account.json` file inside the `credentials/` folder:

```
credentials/service_account.json
```

### 1c. Review `config/config.yaml`

Open `config/config.yaml` and confirm the settings match your needs. Key values:

```yaml
linkedin:
  max_requests_per_run: 25    # how many profiles per run
  delay_min_seconds: 120      # min wait between profiles
  delay_max_seconds: 300      # max wait between profiles

llm:
  provider: "openai"
  model: "gpt-4o-mini"
  default_char_limit: 300     # 200 (standard) or 300 (premium LinkedIn)

browser:
  headless: false             # keep false — headed mode is harder to detect
```

### 1d. Prepare your Google Sheet

Your sheet must have at minimum a `linkedin_url` column. The default expected columns (all configurable in `config.yaml` under `sheets.columns`) are:

| Column | Purpose |
|---|---|
| `linkedin_url` | Target profile URL (input) |
| `name` | Target's name (input, optional) |
| `company` | Company (input, optional) |
| `role` | Role (input, optional) |
| `status` | Written by the app (output) |
| `note_used` | Connection note that was sent (output) |
| `sent_at` | Timestamp of send (output) |
| `comment_posted` | Comment text (output) |
| `posts_liked` | Count of liked posts (output) |

---

## Running on Windows

### Requirements

- Python 3.10+ from [python.org](https://www.python.org/downloads/) — check "Add Python to PATH" during install
- PowerShell or Command Prompt

### Setup

Open PowerShell in the project directory:

```powershell
# Create a virtual environment
python -m venv .venv

# Activate it
.venv\Scripts\Activate.ps1

# If you get an execution policy error, run this first:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser (Chromium)
playwright install chromium
```

### Run the outreach pipeline

```powershell
python main.py
```

With options:

```powershell
# Process only 5 profiles
python main.py --limit 5

# Test run — no actual LinkedIn actions, just generates notes
python main.py --dry-run

# Skip liking/commenting, just send connection requests
python main.py --skip-engage

# Use 200-char notes instead of 300
python main.py --char-limit 200
```

### Run the follow-up job

```powershell
# Run once immediately
python followup.py

# Run on a recurring schedule (every 14 days, persists restarts)
python followup.py --schedule
```

### First-run login

On the first run, the browser window will open and the app will attempt to log in using your `.env` credentials. If LinkedIn requires 2FA or a CAPTCHA:

1. Complete the verification manually in the browser window that opens
2. The script will wait up to 5 minutes for you to finish
3. Once logged in, close nothing — the script continues automatically
4. Future runs reuse the saved session from `browser_data/` and skip login entirely

---

## Running on Linux

### Requirements

Install Python and system dependencies:

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# Fedora / RHEL
sudo dnf install -y python3 python3-pip python3-venv git
```

Playwright on Linux requires system dependencies for Chromium:

```bash
# After installing Python packages (see below), run:
playwright install-deps chromium
```

### Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Chromium and its system deps
playwright install chromium
playwright install-deps chromium
```

### Run the outreach pipeline

```bash
python main.py
```

With options:

```bash
python main.py --limit 5
python main.py --dry-run
python main.py --skip-engage --limit 10
python main.py --char-limit 200
```

### Run the follow-up job

```bash
# Run once
python followup.py

# Run on schedule
python followup.py --schedule

# Custom interval
python followup.py --schedule --interval 7
```

### Headed mode on Linux (display required)

By default `config.yaml` sets `headless: false`. On a desktop Linux, the browser window opens normally.

On a **headless Linux server** (no display), you have two options:

**Option A — Switch to headless mode**

Edit `config/config.yaml`:

```yaml
browser:
  headless: true
```

Note: headless Chromium is more detectable. Recommended only for testing.

**Option B — Use a virtual display (Xvfb)**

```bash
sudo apt install -y xvfb
Xvfb :99 -screen 0 1366x768x24 &
export DISPLAY=:99
python main.py
```

---

## Running on Linux via WSL (Windows Subsystem for Linux)

WSL lets you run a full Linux environment inside Windows. This is the best option if you want the Linux setup while staying on a Windows machine.

### Step 1 — Install WSL

Open PowerShell **as Administrator** and run:

```powershell
wsl --install
```

This installs WSL 2 with Ubuntu by default. Restart when prompted.

After restart, Ubuntu will launch and ask you to create a Linux username and password.

To verify WSL is running correctly:

```powershell
wsl --list --verbose
```

### Step 2 — Install dependencies inside WSL

Open a WSL terminal (search "Ubuntu" in Start menu, or run `wsl` in PowerShell):

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git

# Playwright system dependencies for Chromium
sudo apt install -y \
  libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
  libgbm1 libasound2 libxshmfence1 libx11-xcb1 \
  libxcomposite1 libxdamage1 libxrandr2 libxfixes3 \
  libxext6 libxi6 libpango-1.0-0 libcairo2 libgtk-3-0
```

### Step 3 — Access the project from WSL

Your Windows files are mounted in WSL at `/mnt/c/`. Navigate to the project:

```bash
cd /mnt/c/Users/DELL/Desktop/Omokai
```

Or copy the project into the Linux filesystem for better performance:

```bash
cp -r /mnt/c/Users/DELL/Desktop/Omokai ~/Omokai
cd ~/Omokai
```

### Step 4 — Set up the Python environment

> **Important:** If you already have a `.venv` created on Windows, it will not work inside WSL. Windows venvs contain Windows executables. Delete it and create a fresh one using Linux Python:

```bash
# If a Windows .venv already exists, remove it first
rm -rf .venv

# Create a Linux-native venv
python3 -m venv .venv

# Activate using the Linux path (bin/, NOT Scripts/)
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

### Step 5 — Configure display for headed mode (WSL)

WSL 2 with **WSLg** (Windows 11 and recent Windows 10 builds) supports GUI apps natively — no extra setup needed. The browser window will appear directly on your Windows desktop.

To check if WSLg is available:

```bash
echo $DISPLAY
# Should print something like :0
```

If `$DISPLAY` is empty, you need to configure it manually. Install an X server on Windows (e.g., [VcXsrv](https://sourceforge.net/projects/vcxsrv/) or [GWSL](https://opticos.github.io/gwsl/)):

1. Launch VcXsrv with "Multiple windows", display number 0, "Disable access control" checked
2. In WSL, set the display:

```bash
export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0
```

Add that `export` line to `~/.bashrc` so it persists:

```bash
echo 'export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '"'"'{print $2}'"'"'):0' >> ~/.bashrc
source ~/.bashrc
```

**Alternatively**, switch to headless mode to skip the display requirement entirely:

```yaml
# config/config.yaml
browser:
  headless: true
```

### Step 6 — Run in WSL

Once set up, commands are identical to native Linux:

```bash
# Activate environment (if not already active)
source .venv/bin/activate

# Run outreach
python main.py

# Dry run
python main.py --dry-run --limit 3

# Follow-up
python followup.py --schedule
```

---

## Running with Docker

Docker is the easiest path if you already have it installed. It handles all dependencies automatically.

### Build

```bash
docker-compose build
```

### Run outreach (one-shot)

```bash
docker-compose run --rm outreach
```

With CLI flags:

```bash
docker-compose run --rm outreach python main.py --limit 5 --dry-run
```

### Run follow-up (persistent scheduler)

```bash
docker-compose up followup
```

### Notes on Docker + headed mode

The Docker setup defaults to headless mode inside the container. Headed mode in Docker requires X11 forwarding (Linux host only):

```yaml
# docker-compose.yml — uncomment these sections:
environment:
  - DISPLAY=${DISPLAY}
volumes:
  - /tmp/.X11-unix:/tmp/.X11-unix
```

On Windows with Docker Desktop, headed mode inside Docker is not straightforward. Use native Python setup or WSL instead.

---

## Troubleshooting

### `playwright install` fails

Run with the system deps flag:

```bash
playwright install-deps chromium
playwright install chromium
```

On Windows, run PowerShell as Administrator.

### Login fails / CAPTCHA appears

1. The browser window will open and wait up to 5 minutes for manual completion
2. Complete the CAPTCHA or 2FA manually
3. The session is then saved to `browser_data/` — future runs skip login

### `GOOGLE_SHEETS_CREDENTIALS_FILE not found`

Ensure `credentials/service_account.json` exists. The path is relative to the project root by default. Double-check the value in `.env`:

```env
GOOGLE_SHEETS_CREDENTIALS_FILE=./credentials/service_account.json
```

### `LLM health check failed`

- Verify `LLM_API_KEY` is set in `.env`
- Verify `LLM_PROVIDER` matches the key type (`openai` for OpenAI keys, `anthropic` for Anthropic, etc.)
- Check your API key has a valid balance/quota

### `No unprocessed targets found`

The sheet is read and rows with a non-empty `status` column are skipped. If all rows already have a status, the run exits early. Clear or blank out the `status` column for rows you want to re-process.

### Execution policy error on Windows

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then re-run `.venv\Scripts\Activate.ps1`.

---

## Generated Data

After running, these directories are created automatically:

| Path | Contents |
|---|---|
| `data/state.db` | SQLite database — full audit trail of all outreach |
| `data/logs/outreach.log` | Rotating log file (10 MB max, 5 files kept) |
| `data/screenshots/` | Browser screenshots captured on errors |
| `browser_data/` | Persistent Chromium session (cookies, localStorage) |
