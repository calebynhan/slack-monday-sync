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
    log_data[thread_ts] = items
    save_undo_log(log_data)


def pop_created(thread_ts: str) -> list[dict]:
    log_data = load_undo_log()
    items = log_data.pop(thread_ts, [])
    save_undo_log(log_data)
    return items


def resolve_image_refs(text: str, file_index: list[dict]) -> str:
    """
    Resolve file references in body text to Slack file name + URL.

    Supported formats (with or without parentheses):
      Image 1         (Image 1)
      Video 2         (Video 2)
      Image 1 & 2     (Image 1 & 2)
      Image 1, 2      (img 1, 2)
    """
    def _link(n: int) -> str:
        if 1 <= n <= len(file_index):
            return file_index[n - 1]["url"]
        return f"(file {n} not found)"

    def replacer(m):
        n1 = int(m.group(2))
        n2 = m.group(3)
        if n2:
            return f"{_link(n1)}\n{_link(int(n2))}"
        return _link(n1)

    # Matches: optional ( + keyword + N + optional (& or ,) + optional N2 + optional )
    pattern = re.compile(
        r"\(?"
        r"(image|img|video|vid)"
        r"\s*(\d+)"
        r"(?:\s*[&,]\s*(\d+))?"
        r"\)?",
        re.IGNORECASE,
    )
    return pattern.sub(replacer, text)
