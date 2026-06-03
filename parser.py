"""
Parses Slack thread messages into structured issue items.

Expected format (one message may contain multiple bullets):
  • Bug: Title of the bug
    More detail about the bug here
  • Enhancement: Some enhancement
  • Feature: A new feature idea

Labels are case-insensitive. Bullets may be -, •, *, or a numbered list.
Files/images attached to a Slack message are included with whichever item
they appear alongside (or the last item parsed from that message).
"""

import re
from typing import Optional

BULLET_RE = re.compile(
    r"^[\-\*•·]?\s*"                         # optional top-level bullet
    r"(bug|enhancement|feature)\s*[:\-]\s*"  # label
    r"(.+)",                                  # title (rest of line)
    re.IGNORECASE,
)

# Sub-bullet characters to strip from body lines (○ ◦ – — · etc.)
SUB_BULLET_RE = re.compile(r"^[○◦\-–—·>]+\s*")

LABEL_ALIASES = {
    "bug": "Bug",
    "enhancement": "Enhancement",
    "feature": "Feature",
}


def parse_thread(messages: list[dict]) -> list[dict]:
    """
    Given a list of Slack message dicts (from conversations.replies),
    return a list of issue dicts:
        {
            "label": "Bug" | "Enhancement" | "Feature",
            "title": str,
            "body":  str,          # extra lines / sub-bullets
            "files": [{"name": str, "url": str}],
            "slack_user": str,     # Slack user ID
            "slack_ts":  str,      # message timestamp
        }
    """
    issues: list[dict] = []

    for msg in messages:
        text = msg.get("text", "")
        user = msg.get("user", "")
        ts = msg.get("ts", "")
        files = _extract_files(msg)

        new_issues = _parse_message(text, user, ts)

        if not new_issues:
            # Message has no labelled bullets — if there are files, attach
            # them to the most recently parsed issue from this thread.
            if files and issues:
                issues[-1]["files"].extend(files)
            continue

        # Attach files: split evenly if multiple issues, else all to last.
        if files:
            new_issues[-1]["files"].extend(files)

        issues.extend(new_issues)

    return issues


def _parse_message(text: str, user: str, ts: str) -> list[dict]:
    issues: list[dict] = []
    current: Optional[dict] = None
    body_lines: list[str] = []

    for line in text.splitlines():
        m = BULLET_RE.match(line.strip())
        if m:
            if current is not None:
                current["body"] = "\n".join(body_lines).strip()
                issues.append(current)
            label_raw, title = m.group(1), m.group(2).strip()
            current = {
                "label": LABEL_ALIASES.get(label_raw.lower(), label_raw.title()),
                "title": title,
                "body": "",
                "files": [],
                "slack_user": user,
                "slack_ts": ts,
            }
            body_lines = []
        elif current is not None:
            stripped = SUB_BULLET_RE.sub("", line.strip())
            if stripped:
                body_lines.append(stripped)

    if current is not None:
        current["body"] = "\n".join(body_lines).strip()
        issues.append(current)

    return issues


def _extract_files(msg: dict) -> list[dict]:
    result = []
    for f in msg.get("files", []):
        name = f.get("name", f.get("id", "file"))
        mimetype = f.get("mimetype", "application/octet-stream")
        # url_private_download is the correct URL for downloading file bytes;
        # url_private is a view URL that may redirect rather than stream bytes.
        url = f.get("url_private_download") or f.get("url_private") or f.get("permalink", "")
        if url:
            result.append({"name": name, "url": url, "mimetype": mimetype})
    return result
