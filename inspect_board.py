"""
Run this once after setup to print your board's column IDs.
Copy the relevant IDs into your .env file.

Usage:
    python inspect_board.py
"""

import os
from dotenv import load_dotenv
import monday_client

load_dotenv()

board_id = os.environ["MONDAY_BOARD_ID"]
print(f"Fetching board {board_id}...\n")

try:
    board = monday_client.get_board_columns(board_id)
except monday_client.MondayError as e:
    print(f"Error: {e}")
    raise SystemExit(1)

print(f"Board: {board['name']}\n")
print("Groups:")
for g in board.get("groups", []):
    print(f"  {g['id']:30s}  {g['title']}")

print("\nColumns:")
for c in board.get("columns", []):
    print(f"  {c['id']:30s}  {c['type']:20s}  {c['title']}")

print("\nSet MONDAY_STATUS_COLUMN_ID to the ID of your status/label column.")
