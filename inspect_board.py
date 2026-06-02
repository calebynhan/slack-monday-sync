"""
Run this once after setup to find the group IDs, column IDs, and your Monday user ID.
Copy the values into your .env file.

Usage:
    python inspect_board.py
"""

import os
from dotenv import load_dotenv
import monday_client

load_dotenv()


def print_board(board_id: str, label: str) -> None:
    print(f"\n{'='*60}")
    print(f"Board: {label}  (ID: {board_id})")
    print("=" * 60)
    try:
        board = monday_client.get_board_info(board_id)
    except monday_client.MondayError as e:
        print(f"  ERROR: {e}")
        return

    print(f"  Name: {board['name']}\n")
    print("  Groups (copy the ID of the target group into .env):")
    for g in board.get("groups", []):
        print(f"    id={g['id']:30s}  title={g['title']}")

    print("\n  Columns (copy Reporter column ID into .env):")
    for c in board.get("columns", []):
        print(f"    id={c['id']:30s}  type={c['type']:20s}  title={c['title']}")


def print_me() -> None:
    print(f"\n{'='*60}")
    print("Your Monday user (use 'id' as MONDAY_REPORTER_ID)")
    print("=" * 60)
    try:
        me = monday_client.get_me()
        print(f"  id={me['id']}  name={me['name']}")
    except monday_client.MondayError as e:
        print(f"  ERROR: {e}")


bugs_board = os.environ.get("MONDAY_BUGS_BOARD_ID", "")
enh_board  = os.environ.get("MONDAY_ENHANCEMENTS_BOARD_ID", "")

if not bugs_board or not enh_board:
    print("Set MONDAY_BUGS_BOARD_ID and MONDAY_ENHANCEMENTS_BOARD_ID in .env first.")
    raise SystemExit(1)

print_board(bugs_board, "Bugs Queue")
print_board(enh_board,  "Enhancements")
print_me()

print(f"""
{'-'*60}
Add these to your .env:

MONDAY_BUGS_GROUP_ID=<id from "Dev Bugs Queue" group above>
MONDAY_ENHANCEMENTS_GROUP_ID=<id from "Incoming Enhancements" group above>
MONDAY_BUGS_REPORTER_COL=<id of Reporter column on Bugs board>
MONDAY_ENH_REPORTER_COL=<id of Reporter column on Enhancements board>
MONDAY_REPORTER_ID=<your user id from above>
""")
