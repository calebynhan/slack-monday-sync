# slack-monday-sync

A lightweight bot that reads bug/enhancement/feature bullets from a Slack thread and creates Monday.com items from them — triggered by a simple @mention.

---

## How it works

1. Write your notes in a Slack thread using bullet points labelled `Bug:`, `Enhancement:`, or `Feature:`:
   ```
   • Bug: Onboarding screen crashes on Android 14
     Happens when tapping "Continue" after permissions prompt
   • Enhancement: Add dark mode toggle to settings
   • Feature: Export report as PDF
   ```
2. Attach any screenshots or videos directly in the thread as normal Slack uploads.
3. @mention the bot anywhere in that thread:
   ```
   @issue-bot create
   ```
4. The bot parses every message in the thread, creates one Monday item per bullet, adds the description + file links as an update, and replies with links.

---

## Setup

### 1. Create the Slack app

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Give it a name (e.g. `issue-bot`) and pick your workspace
3. Under **OAuth & Permissions → Scopes → Bot Token Scopes**, add:
   - `app_mentions:read`
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
   - `chat:write`
   - `files:read`
4. **Install the app** to your workspace and copy the **Bot User OAuth Token** (`xoxb-...`)
5. Under **Basic Information**, copy the **Signing Secret**
6. **Enable Socket Mode** (easiest for Railway/Render):
   - Go to **Socket Mode** → enable it
   - Generate an **App-Level Token** with scope `connections:write` → copy it (`xapp-...`)
7. Under **Event Subscriptions** → **Subscribe to Bot Events**, add `app_mention`
8. Invite the bot to your channel: `/invite @issue-bot`

### 2. Get Monday.com credentials

1. Go to your Monday profile → **Developers** → **My Access Tokens** → copy your token
2. Find your **Board ID**: open the board in Monday, the number in the URL is the board ID
   (`https://yourteam.monday.com/boards/1234567890` → `1234567890`)
3. Optional — find column IDs: open the board, click the three-dot menu on a column → **Column Settings** → the ID appears in the URL or settings panel

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your actual values
```

Key variables:

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | `xoxb-...` bot token |
| `SLACK_SIGNING_SECRET` | Yes | From Basic Information |
| `SLACK_APP_TOKEN` | Yes (Socket Mode) | `xapp-...` app-level token |
| `MONDAY_API_TOKEN` | Yes | Monday personal API token |
| `MONDAY_BOARD_ID` | Yes | Numeric board ID |
| `MONDAY_STATUS_COLUMN_ID` | No | Column ID to receive Bug/Enhancement/Feature label |
| `MONDAY_TEXT_COLUMN_ID` | No | Column ID for long-text notes |

### 4. Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

### 5. Deploy to Railway (free tier)

1. Push this repo to GitHub
2. Go to https://railway.app → **New Project** → **Deploy from GitHub repo**
3. Select this repo; Railway auto-detects the `Procfile`
4. Add all environment variables in the Railway **Variables** tab
5. Deploy — no public URL needed because Socket Mode handles the connection

---

## Item naming & status mapping

Monday items are created as `[Bug] Title here`, `[Enhancement] Title here`, etc.

If you set `MONDAY_STATUS_COLUMN_ID`, the bot sets the status column to:

| Slack label | Monday status value |
|---|---|
| Bug | Bug |
| Enhancement | Enhancement |
| Feature | Feature Request |

Adjust the `STATUS_MAP` dict in `app.py` to match your board's exact label names.

---

## Trigger words

The bot activates when it is @mentioned and the message contains any of:
`create`, `sync`, `add`, `log`, `push`

Mentioning it without one of these words returns usage help.
