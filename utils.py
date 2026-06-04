import json
import os
import re

MONDAY_ITEM_NAME_MAX = 255


def safe_item_name(label: str, title: str) -> str:
    """Build a Monday item name (no label prefix), truncated to the API limit."""
    return title[:MONDAY_ITEM_NAME_MAX]


def get_undo_log_path() -> str:
    return os.environ.get("UNDO_LOG_PATH", "undo_log.json")


def load_undo_log() -> dict:
    path = get_undo_log_path()
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_undo_log(log_data: dict) -> None:
    with open(get_undo_log_path(), "w") as f:
        json.dump(log_data, f, indent=2)


def record_created(thread_ts: str, items: list[dict]) -> None:
    log_data = load_undo_log()
    existing = log_data.get(thread_ts, [])
    log_data[thread_ts] = existing + items
    save_undo_log(log_data)


def get_created_titles(thread_ts: str) -> set[str]:
    """Return the set of lowercased titles already created for this thread."""
    log_data = load_undo_log()
    return {item["title"].lower() for item in log_data.get(thread_ts, [])}


def pop_created(thread_ts: str) -> list[dict]:
    log_data = load_undo_log()
    items = log_data.pop(thread_ts, [])
    save_undo_log(log_data)
    return items


def resolve_image_refs(text: str, file_index: list[dict]) -> str:
    """
    Strip file references from body text (files are uploaded directly to Monday).

    Supported formats removed (with or without parentheses):
      Image 1         (Image 1)
      Video 2         (Video 2)
      Image 1 & 2     (Image 1 & 2)
      Image 1, 2      (img 1, 2)
    """
    # Matches: optional ( + keyword + N + optional (& or ,) + optional N2 + optional )
    pattern = re.compile(
        r"\(?"
        r"(?:image|img|video|vid)"
        r"\s*\d+"
        r"(?:\s*[&,]\s*\d+)?"
        r"\)?",
        re.IGNORECASE,
    )
    return pattern.sub("", text)
