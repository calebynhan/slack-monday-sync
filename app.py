"""
Slack → Monday.com sync bot.

Trigger: @mention the bot in any Slack thread (e.g. "@issue-bot create").
The bot reads every message in that thread, parses bullet points labelled
Bug / Enhancement / Feature, and creates one Monday item per bullet:
  - Bug      → Bugs Queue board,    Dev Bugs Queue group
  - Enhancement / Feature → Enhancements board, Incoming Enhancements group

To undo: @mention the bot with "revert" or "undo" in the same thread.
  - Deletes every Monday item created from that thread.
  - Only works once per thread (items are gone after deletion).

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
  UNDO_LOG_PATH                   path to undo log JSON (default: undo_log.json)
  PORT                            default 3000

Run `python inspect_board.py` after setup to find group IDs, column IDs, and your user ID.
"""

import logging
import os
import re

import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

import monday_client
from parser import parse_thread, _extract_files
from utils import safe_item_name, resolve_image_refs, record_created, pop_created, get_created_titles

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


# ── helpers ───────────────────────────────────────────────────────────────────

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


_FILES_NOTE = {
    "Bug":         "• Image/Video of the bug can be found in the Files tab of this item",
    "Enhancement": "• Image/Video of this enhancement can be found in the Files tab of this item",
    "Feature":     "• Image/Video of this feature can be found in the Files tab of this item",
}

# Detects "Image 1", "Video 2", "(img 1 & 2)" etc. in the raw body text.
_MEDIA_REF_RE = re.compile(r"\b(?:image|img|video|vid)\s*\d+", re.IGNORECASE)


def _build_update_body(issue: dict, file_index: list[dict]) -> str:
    """Build the Monday update text. Each body line becomes a bullet point."""
    lines = []
    if issue["body"]:
        for line in resolve_image_refs(issue["body"], file_index).splitlines():
            line = line.strip()
            if line:
                lines.append(f"• {line}")

    # Add the "see Files tab" note if files are attached to this issue OR the
    # body references an image/video (the file may attach to a sibling bullet
    # in a multi-bullet message, so don't rely on issue["files"] alone).
    has_media = bool(issue["files"]) or bool(_MEDIA_REF_RE.search(issue["body"]))
    if has_media:
        note = _FILES_NOTE.get(issue["label"], "• Image/Video can be found in the Files tab of this item")
        lines.append(note)
    return "\n".join(lines) if lines else ""


def _download_slack_file(url: str, slack_token: str) -> bytes | None:
    """Download a private Slack file using the bot token."""
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {slack_token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content
    except Exception:
        log.exception("Failed to download Slack file: %s", url)
        return None


def _routing(label: str) -> tuple[str, str, str]:
    """Return (board_id, group_id, reporter_col_id) for a given label."""
    if label == "Bug":
        return BUGS_BOARD_ID, BUGS_GROUP_ID, BUGS_REPORTER_COL
    else:
        return ENH_BOARD_ID, ENH_GROUP_ID, ENH_REPORTER_COL


def _strip_bot_mention(text: str, bot_user_id: str) -> str:
    return re.sub(rf"<@{bot_user_id}>", "", text).strip()


# ── event handler ─────────────────────────────────────────────────────────────

@app.event("app_mention")
def handle_mention(event, client, say):
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    bot_user_id = _get_bot_user_id(client)

    mention_text = _strip_bot_mention(event.get("text", ""), bot_user_id).lower()

    # ── revert / undo ──────────────────────────────────────────────────────
    if any(w in mention_text for w in ("revert", "undo", "delete")):
        items = pop_created(thread_ts)
        if not items:
            say(
                text=":shrug: No Monday items found to revert for this thread.",
                thread_ts=thread_ts,
            )
            return

        say(text=f":wastebasket: Reverting {len(items)} item(s)...", thread_ts=thread_ts)

        deleted, failed = [], []
        for item in items:
            try:
                monday_client.delete_item(item["item_id"])
                deleted.append(f"• ~~{item['title']}~~")
                log.info("Deleted Monday item %s ('%s')", item["item_id"], item["title"])
            except monday_client.MondayError as exc:
                log.error("Failed to delete item %s: %s", item["item_id"], exc)
                failed.append(f"• `{item['title']}`: Monday API error (check logs)")
            except Exception:
                log.exception("Unexpected error deleting item %s", item["item_id"])
                failed.append(f"• `{item['title']}`: Unexpected error (check logs)")

        reply_parts = [f":white_check_mark: Deleted *{len(deleted)}* item(s) from Monday:"]
        reply_parts.extend(deleted)
        if failed:
            reply_parts.append(f"\n:warning: *{len(failed)} could not be deleted:*")
            reply_parts.extend(failed)

        say(text="\n".join(reply_parts), thread_ts=thread_ts)
        return

    # ── create ────────────────────────────────────────────────────────────
    log.info("Trigger received in channel=%s thread=%s", channel, thread_ts)

    mention_msg = {
        "text": _strip_bot_mention(event.get("text", ""), bot_user_id),
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

    other_messages = [
        m for m in thread_messages
        if m.get("user") != bot_user_id and m.get("ts") != event["ts"]
    ]

    all_messages = other_messages + [mention_msg]

    # Build file_index only from messages by the same user who triggered the bot,
    # so (Image 1) / (Video 2) refs only count that user's own attachments.
    triggering_user = event.get("user", "")
    file_index: list[dict] = []
    for m in all_messages:
        if m.get("user") == triggering_user:
            file_index.extend(_extract_files(m))

    issues = parse_thread(all_messages)

    if not issues:
        say(
            text=(
                ":mag: No items found. Make sure your bullets use the format:\n"
                "`• Bug: Title here`  or  `• Enhancement: Title`  or  `• Feature: Title`\n\n"
                "To undo a previous sync: `@issue-bot revert`"
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

    # Filter out issues already created from this thread (duplicate @mention guard)
    already_created = get_created_titles(thread_ts)
    skipped = [i for i in issues if i["title"].lower() in already_created]
    issues = [i for i in issues if i["title"].lower() not in already_created]

    if not issues and skipped:
        say(
            text=":white_check_mark: All items in this thread have already been added to Monday.",
            thread_ts=thread_ts,
        )
        return

    say(text=f":hourglass: Creating {len(issues)} item(s) on Monday...", thread_ts=thread_ts)

    created_links = []
    created_log = []
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
            update_id = monday_client.add_update(item_id, update_body or "(no additional details)")

            # Upload attached files directly to the Monday update
            slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
            log.info("Issue '%s' has %d file(s) to upload", issue["title"], len(issue["files"]))
            for f in issue["files"]:
                log.info("Downloading '%s' from Slack: %s", f["name"], f["url"])
                content = _download_slack_file(f["url"], slack_token)
                if not content:
                    log.warning("Skipped upload — could not download '%s' from Slack", f["name"])
                    continue
                mimetype = f.get("mimetype", "application/octet-stream")
                log.info("Uploading '%s' (%d bytes, %s) to Monday update %s", f["name"], len(content), mimetype, update_id)
                try:
                    monday_client.upload_file_to_update(update_id, content, f["name"], mimetype)
                    log.info("SUCCESS: uploaded '%s' to Monday update %s", f["name"], update_id)
                except monday_client.MondayError:
                    log.exception("Failed to upload file '%s' to Monday", f["name"])

            url = monday_client.get_item_url(board_id, item_id)
            created_links.append(
                f"• *[{issue['label']}]* {issue['title']} → <{url}|View on Monday>"
            )
            created_log.append({"item_id": item_id, "title": issue["title"], "board_id": board_id})
            log.info("Created Monday item %s for '%s' on board %s", item_id, issue["title"], board_id)

        except monday_client.MondayError as exc:
            log.error("Monday API error for '%s': %s", issue.get("title"), exc)
            errors.append(f"• `{issue.get('title', '?')}`: Monday API error (check logs)")
        except Exception:
            log.exception("Unexpected error creating Monday item for '%s'", issue.get("title"))
            errors.append(f"• `{issue.get('title', '?')}`: Unexpected error (check logs)")

    if created_log:
        record_created(thread_ts, created_log)

    reply_parts = [f":white_check_mark: Created *{len(created_links)}* item(s) on Monday:"]
    reply_parts.extend(created_links)
    if skipped:
        reply_parts.append(f"\n:skip: *{len(skipped)} already existed (skipped):*")
        reply_parts.extend(f"• {i['title']}" for i in skipped)
    if errors:
        reply_parts.append(f"\n:warning: *{len(errors)} failed:*")
        reply_parts.extend(errors)
    if created_log:
        reply_parts.append("\n_To undo: `@issue-bot revert`_")

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
