import re

MONDAY_ITEM_NAME_MAX = 255


def safe_item_name(label: str, title: str) -> str:
    """Build a Monday item name (no label prefix), truncated to the API limit."""
    return title[:MONDAY_ITEM_NAME_MAX]


def resolve_image_refs(text: str, file_index: list[dict]) -> str:
    """Replace (Image N) / (img N) / (Video N) / (vid N) with the actual Slack file name + URL."""
    def replacer(m):
        n = int(m.group(1))
        if 1 <= n <= len(file_index):
            f = file_index[n - 1]
            return f"{f['name']}: {f['url']}"
        return m.group(0)
    return re.sub(r"\((?:image|img|video|vid)\s*(\d+)\)", replacer, text, flags=re.IGNORECASE)
