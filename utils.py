MONDAY_ITEM_NAME_MAX = 255


def safe_item_name(label: str, title: str) -> str:
    """Build a Monday item name, truncated to the API limit."""
    name = f"[{label}] {title}"
    return name[:MONDAY_ITEM_NAME_MAX]
