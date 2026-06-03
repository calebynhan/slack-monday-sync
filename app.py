"""
Slack → Monday.com sync bot.

Trigger: @mention the bot in any Slack thread (e.g. "@issue-bot create").
The bot reads every message in that thread, parses bullet points labelled
Bug / Enhancement / Feature, and creates one Monday item per bullet:
  - Bug      → Bugs Queue board,    Dev Bugs Queue group
  - Enhancement / Feature → Enhancements board, Incoming Enhancements group

Required environment variables (copy .env.example → .env and fill in):
  SLACK_BOT_TOKEN                 xoxb-...
  SLACK_SIGNING_SECRET            ...
  SLACK_APP_TOKEN                 xapp-... (Socket Mode — recommended)
  MONDAY_API_TOKEN                ...
  MONDAY_BUGS_BOARD_ID            numeric ID of the Bugs Queue board
  MONDAY_BUGS_GROUP_ID            group ID of "Dev Bugs Queue" group
  MONDAY_ENHANCEMENTS_BOARD_ID    numeric ID of the Enhancements board
  MONDAY_ENHANCEMENTS_GROUP_ID    group ID of "Incoming Enhancements" group
  MONDAY_REPORTER_ID              your Monday user ID (run inspect_board.py to find it)

Optional:
  SLACK_BOT_USER_ID               auto-fetched on first run if not set
  MONDAY_BUGS_REPORTER_COL        column ID for Reporter on Bugs board
  MONDAY_ENH_REPORTER_COL         column ID for Reporter on Enhancements board
  PORT                            default 3000

Run `python inspect_board.py` after setup to find group IDs, column IDs, and your user ID.
"""

import logging
import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

import monday_client
from parser import parse_thread
from utils import safe_item_name, resolve_image_refs

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

# Board / group routing
BUGS_BOARD_ID       = os.environ["MONDAY_BUGS_BOARD_ID"]
BUGS_GROUP_ID       = os.environ.get("MONDAY_BUGS_GROUP_ID", "")
ENH_BOARD_ID        = os.environ["MONDAY_ENHANCEMENTS_BOARD_ID"]
ENH_GROUP_ID        = os.environ.get("MONDAY_ENHANCEMENTS_GROUP_ID", "")

# Reporter column IDs (may differ between boards)
BUGS_REPORTER_COL   = os.environ.get("MONDAY_BUGS_REPORTER_COL", "")
ENH_REPORTER_COL    = os.environ.get("MONDAY_ENH_REPORTER_COL", "")

# Monday user ID for "Caleb Han" — set via MONDAY_REPORTER_ID env var
REPORTER_ID         = os.environ.get("MONDAY_REPORTER_ID", "")

MAX_ITEMS_PER_RUN = 25

_bot_user_id_cache: str = ""


def _get_bot_user_id(client: WebClient) -> str:
    global _bot_user_id_cache
    if _bot_user_id_cache:
        return _bot_user_id_cache
    env_val = os.environ.get("SLACK_BOT_USER_ID", "")
    if env_val:
        _bot_user_id_cache = env_val
        return _bot_user_id_cache
    resp = client.auth_test()
    _bot_user_id_cache = resp["user_id"]
    return _bot_user_id_cache


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


def _build_update_body(issue: dict, file_index: list[dict]) -> str:
    parts = []
    body = resolve_image_refs(issue["body"], file_index) if issue["body"] else ""
    if body:
        parts.append(body)
    if issue["files"]:
        parts.append("\n*Attachments* (Slack login required to view):")
        for f in issue["files"]:
            parts.append(f"• {f['name']}: {f['url']}")
    return "\n".join(parts) if parts else "(no additional details)"


def _routing(label: str) -> tuple[str, str, str]:
    """Return (board_id, group_id, reporter_col_id) for a given label."""
    if label == "Bug":
        return BUGS_BOARD_ID, BUGS_GROUP_ID, BUGS_REPORTER_COL
    else:
        # Enhancement and Feature both go to the Enhancements board
        return ENH_BOARD_ID, ENH_GROUP_ID, ENH_REPORTER_COL


def _strip_bot_mention(text: str, bot_user_id: str) -> str:
    """Remove the @mention from the message so it doesn't interfere with parsing."""
    import re
    return re.sub(rf"<@{bot_user_id}>", "", text).strip()


@app.event("app_mention")
def handle_mention(event, client, say):
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    bot_user_id = _get_bot_user_id(client)

    log.info("Trigger received in channel=%s thread=%s", channel, thread_ts)

    # Build a synthetic message from the mention itself (bot mention stripped)
    # so bullets written in the same message as @bot are parsed too.
    mention_text = _strip_bot_mention(event.get("text", ""), bot_user_id)
    mention_msg = {
        "text": mention_text,
        "user": event.get("user", ""),
        "ts": event["ts"],
        "files": event.get("files", []),
    }

    try:
        thread_messages = _fetch_thread(client, channel, thread_ts)
    except Exception:
        log.exception("Failed to fetch thread")
        say(text=":x: Could not read thread messages. Check bot channel permissions.", thread_ts=thread_ts)
        return

    # Exclude bot messages and the mention message itself (we already have it above)
    other_messages = [
        m for m in thread_messages
        if m.get("user") != bot_user_id and m.get("ts") != event["ts"]
    ]

    all_messages = other_messages + [mention_msg]

    # Build a sequential file index across all messages so (Image 1), (Image 2) etc. resolve correctly
    from parser import _extract_files
    file_index: list[dict] = []
    for m in all_messages:
        file_index.extend(_extract_files(m))

    # Parse: rest of thread first, then the mention message (so mention bullets aren't duplicated)
    issues = parse_thread(all_messages)

    if not issues:
        say(
            text=(
                ":mag: No items found. Make sure your bullets use the format:\n"
                "`• Bug: Title here`  or  `• Enhancement: Title`  or  `• Feature: Title`"
            ),
            thread_ts=thread_ts,
        )
        return

    if len(issues) > MAX_ITEMS_PER_RUN:
        say(
            text=(
                f":warning: Found {len(issues)} items — over the safety limit of {MAX_ITEMS_PER_RUN}. "
                f"Please split into multiple threads or raise MAX_ITEMS_PER_RUN."
            ),
            thread_ts=thread_ts,
        )
        return

    say(text=f":hourglass: Creating {len(issues)} item(s) on Monday...", thread_ts=thread_ts)

    created_links = []
    errors = []

    for issue in issues:
        try:
            board_id, group_id, reporter_col = _routing(issue["label"])

            column_values: dict = {}
            if reporter_col and REPORTER_ID:
                column_values[reporter_col] = {
                    "personsAndTeams": [{"id": int(REPORTER_ID), "kind": "person"}]
                }

            item_id = monday_client.create_item(
                board_id=board_id,
                item_name=safe_item_name(issue["label"], issue["title"]),
                group_id=group_id or None,
                column_values=column_values if column_values else None,
            )

            update_body = _build_update_body(issue, file_index)
            monday_client.add_update(item_id, update_body)

            url = monday_client.get_item_url(board_id, item_id)
            created_links.append(
                f"• *[{issue['label']}]* {issue['title']} → <{url}|View on Monday>"
            )
            log.info("Created Monday item %s for '%s' on board %s", item_id, issue["title"], board_id)

        except monday_client.MondayError as exc:
            log.error("Monday API error for '%s': %s", issue.get("title"), exc)
            errors.append(f"• `{issue.get('title', '?')}`: Monday API error (check logs)")
        except Exception:
            log.exception("Unexpected error creating Monday item for '%s'", issue.get("title"))
            errors.append(f"• `{issue.get('title', '?')}`: Unexpected error (check logs)")

    reply_parts = [f":white_check_mark: Created *{len(created_links)}* item(s) on Monday:"]
    reply_parts.extend(created_links)
    if errors:
        reply_parts.append(f"\n:warning: *{len(errors)} failed:*")
        reply_parts.extend(errors)

    say(text="\n".join(reply_parts), thread_ts=thread_ts)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    log.info("Starting Slack bot on port %d", port)

    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if app_token:
        log.info("Using Socket Mode (SLACK_APP_TOKEN found)")
        handler = SocketModeHandler(app, app_token)
        handler.start()
    else:
        log.info("Using HTTP mode on port %d", port)
        app.start(port=port)
