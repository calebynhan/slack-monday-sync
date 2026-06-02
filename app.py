"""
Slack → Monday.com sync bot.

Trigger: @mention the bot in any Slack thread (e.g. "@issue-bot create").
The bot reads every message in that thread authored by any user, parses
bullet points labelled Bug / Enhancement / Feature, and creates one Monday
item per bullet.  It then replies in the thread with links to the new items.

Required environment variables (copy .env.example → .env and fill in):
  SLACK_BOT_TOKEN       xoxb-...
  SLACK_SIGNING_SECRET  ...
  MONDAY_API_TOKEN      ...
  MONDAY_BOARD_ID       numeric board ID

Optional:
  SLACK_BOT_USER_ID     U... (auto-fetched on startup if not set)
  MONDAY_STATUS_COLUMN_ID  column ID for the label (Bug/Enhancement/Feature)
  MONDAY_TEXT_COLUMN_ID    column ID for long-text notes
  PORT                  default 3000
"""

import logging
import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

import monday_client
from parser import parse_thread

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

BOARD_ID = os.environ["MONDAY_BOARD_ID"]
STATUS_COL = os.environ.get("MONDAY_STATUS_COLUMN_ID", "")
TEXT_COL = os.environ.get("MONDAY_TEXT_COLUMN_ID", "")

# Label → Monday status value mapping.
# Adjust these to match your board's actual status labels.
STATUS_MAP = {
    "Bug": "Bug",
    "Enhancement": "Enhancement",
    "Feature": "Feature Request",
}


def _get_bot_user_id(client: WebClient) -> str:
    cached = os.environ.get("SLACK_BOT_USER_ID", "")
    if cached:
        return cached
    resp = client.auth_test()
    uid = resp["user_id"]
    os.environ["SLACK_BOT_USER_ID"] = uid
    return uid


def _fetch_thread(client: WebClient, channel: str, thread_ts: str) -> list[dict]:
    messages = []
    cursor = None
    while True:
        kwargs = {"channel": channel, "ts": thread_ts, "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        resp = client.conversations_replies(**kwargs)
        messages.extend(resp["messages"])
        meta = resp.get("response_metadata", {})
        cursor = meta.get("next_cursor", "")
        if not cursor:
            break
    return messages


def _build_update_body(issue: dict) -> str:
    parts = []
    if issue["body"]:
        parts.append(issue["body"])
    if issue["files"]:
        parts.append("\n*Attachments:*")
        for f in issue["files"]:
            parts.append(f"• <{f['url']}|{f['name']}>")
    return "\n".join(parts) if parts else "(no additional details)"


@app.event("app_mention")
def handle_mention(event, client, say):
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    mention_ts = event["ts"]
    bot_user_id = _get_bot_user_id(client)

    text_lower = event.get("text", "").lower()
    trigger_words = ("create", "sync", "add", "log", "push")
    if not any(w in text_lower for w in trigger_words):
        say(
            text=(
                "Hi! Mention me with *create* (or sync/add/log/push) inside a thread "
                "to push all Bug/Enhancement/Feature bullets to Monday. Example:\n"
                "`@issue-bot create`"
            ),
            thread_ts=thread_ts,
        )
        return

    log.info("Trigger received in channel=%s thread=%s", channel, thread_ts)

    try:
        messages = _fetch_thread(client, channel, thread_ts)
    except Exception as exc:
        log.exception("Failed to fetch thread")
        say(text=f":x: Could not read thread messages: {exc}", thread_ts=thread_ts)
        return

    # Exclude the bot's own messages so it doesn't parse its own replies.
    user_messages = [m for m in messages if m.get("user") != bot_user_id]

    issues = parse_thread(user_messages)

    if not issues:
        say(
            text=(
                ":mag: No items found. Make sure your bullets use the format:\n"
                "`• Bug: Title here`  or  `• Enhancement: Title`  or  `• Feature: Title`"
            ),
            thread_ts=thread_ts,
        )
        return

    created_links = []
    errors = []

    for issue in issues:
        try:
            column_values: dict = {}
            if STATUS_COL:
                label = issue["label"]
                status_label = STATUS_MAP.get(label, label)
                column_values[STATUS_COL] = {"label": status_label}
            if TEXT_COL and issue["body"]:
                column_values[TEXT_COL] = {"text": issue["body"]}

            item_id = monday_client.create_item(
                board_id=BOARD_ID,
                item_name=f"[{issue['label']}] {issue['title']}",
                column_values=column_values if column_values else None,
            )

            update_body = _build_update_body(issue)
            monday_client.add_update(item_id, update_body)

            url = monday_client.get_item_url(BOARD_ID, item_id)
            created_links.append(
                f"• *[{issue['label']}]* {issue['title']} → <{url}|View on Monday>"
            )
            log.info("Created Monday item %s for '%s'", item_id, issue["title"])

        except Exception as exc:
            log.exception("Failed to create Monday item for '%s'", issue.get("title"))
            errors.append(f"• `{issue.get('title', '?')}`: {exc}")

    reply_parts = [f":white_check_mark: Created *{len(created_links)}* item(s) on Monday:"]
    reply_parts.extend(created_links)
    if errors:
        reply_parts.append(f"\n:warning: *{len(errors)} error(s):*")
        reply_parts.extend(errors)

    say(text="\n".join(reply_parts), thread_ts=thread_ts)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    log.info("Starting Slack bot on port %d", port)

    # Use Socket Mode if SLACK_APP_TOKEN is set (easier for local dev / Railway).
    # Otherwise fall back to HTTP mode (needs a public URL set in Slack app config).
    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if app_token:
        log.info("Using Socket Mode (SLACK_APP_TOKEN found)")
        handler = SocketModeHandler(app, app_token)
        handler.start()
    else:
        log.info("Using HTTP mode on port %d", port)
        app.start(port=port)
