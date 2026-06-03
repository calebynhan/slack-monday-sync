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
    """Replace (Image N) / (img N) / (Video N) / (vid N) with the actual Slack file name + URL."""
    def replacer(m):
        n = int(m.group(1))
        if 1 <= n <= len(file_index):
            f = file_index[n - 1]
            return f"{f['name']}: {f['url']}"
        return m.group(0)
    return re.sub(r"\((?:image|img|video|vid)\s*(\d+)\)", replacer, text, flags=re.IGNORECASE)
