"""
Thin Monday.com GraphQL client.

Uses the v2 API (api.monday.com/v2).
All requests are synchronous (requests library).
"""

import json
import os

import requests

MONDAY_API_URL = "https://api.monday.com/v2"


class MondayError(Exception):
    """Raised for Monday API-level errors. Message is safe to log but not expose to end users."""


def _headers() -> dict:
    return {
        "Authorization": os.environ["MONDAY_API_TOKEN"],
        "Content-Type": "application/json",
        "API-Version": "2023-10",
    }


def _run(query: str, variables: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        resp = requests.post(MONDAY_API_URL, json=payload, headers=_headers(), timeout=15)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise MondayError(f"HTTP {exc.response.status_code} from Monday API") from exc
    except requests.RequestException as exc:
        raise MondayError(f"Network error reaching Monday API: {type(exc).__name__}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise MondayError("Monday API returned non-JSON response") from exc

    if "errors" in data:
        messages = [e.get("message", str(e)) for e in data["errors"]]
        raise MondayError(f"Monday API error: {'; '.join(messages)}")

    return data


def create_item(board_id: str, item_name: str, column_values: dict | None = None) -> str:
    """Create an item on the board and return its ID."""
    cv_json = "{}" if not column_values else json.dumps(column_values)
    query = """
    mutation ($board: ID!, $name: String!, $cv: JSON!) {
      create_item(board_id: $board, item_name: $name, column_values: $cv) {
        id
      }
    }
    """
    result = _run(query, {"board": board_id, "name": item_name, "cv": cv_json})
    return result["data"]["create_item"]["id"]


def add_update(item_id: str, body: str) -> str:
    """Add a text update (comment) to an item and return the update ID."""
    query = """
    mutation ($item: ID!, $body: String!) {
      create_update(item_id: $item, body: $body) {
        id
      }
    }
    """
    result = _run(query, {"item": item_id, "body": body})
    return result["data"]["create_update"]["id"]


def get_item_url(board_id: str, item_id: str) -> str:
    """Return a direct link to the item on Monday."""
    return f"https://app.monday.com/boards/{board_id}/items/{item_id}"


def get_board_columns(board_id: str) -> list[dict]:
    """Return column metadata for a board. Useful for initial setup."""
    query = """
    query ($board: ID!) {
      boards(ids: [$board]) {
        name
        columns { id title type }
        groups { id title }
      }
    }
    """
    result = _run(query, {"board": board_id})
    boards = result["data"]["boards"]
    if not boards:
        raise MondayError(f"Board {board_id} not found or not accessible")
    return boards[0]
