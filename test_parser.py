"""
Unit tests for parser.py — no network required.
Run with: python -m pytest test_parser.py -v
"""

import pytest
from parser import parse_thread, _parse_message, _extract_files


# ── _parse_message ────────────────────────────────────────────────────────────

def test_single_bug():
    issues = _parse_message("• Bug: App crashes on login", "U123", "111")
    assert len(issues) == 1
    assert issues[0]["label"] == "Bug"
    assert issues[0]["title"] == "App crashes on login"
    assert issues[0]["body"] == ""


def test_single_enhancement():
    issues = _parse_message("- Enhancement: Add dark mode", "U123", "111")
    assert issues[0]["label"] == "Enhancement"
    assert issues[0]["title"] == "Add dark mode"


def test_single_feature():
    issues = _parse_message("* Feature: PDF export", "U123", "111")
    assert issues[0]["label"] == "Feature"
    assert issues[0]["title"] == "PDF export"


def test_case_insensitive_label():
    issues = _parse_message("• BUG: Something broken", "U123", "111")
    assert issues[0]["label"] == "Bug"

    issues = _parse_message("• ENHANCEMENT: Improve speed", "U123", "111")
    assert issues[0]["label"] == "Enhancement"


def test_label_with_dash_separator():
    issues = _parse_message("• Bug - Title with dash", "U123", "111")
    assert issues[0]["label"] == "Bug"
    assert issues[0]["title"] == "Title with dash"


def test_multiple_bullets_in_one_message():
    text = (
        "• Bug: First bug\n"
        "• Enhancement: Second item\n"
        "• Feature: Third item"
    )
    issues = _parse_message(text, "U123", "111")
    assert len(issues) == 3
    assert issues[0]["label"] == "Bug"
    assert issues[1]["label"] == "Enhancement"
    assert issues[2]["label"] == "Feature"


def test_body_lines_captured():
    text = (
        "• Bug: Crash on startup\n"
        "  Happens every time on iOS 17\n"
        "  Steps: open app, tap login"
    )
    issues = _parse_message(text, "U123", "111")
    assert len(issues) == 1
    assert "Happens every time on iOS 17" in issues[0]["body"]
    assert "Steps: open app, tap login" in issues[0]["body"]


def test_body_belongs_to_correct_bullet():
    text = (
        "• Bug: First bug\n"
        "  Details about first bug\n"
        "• Enhancement: Second item\n"
        "  Details about second item"
    )
    issues = _parse_message(text, "U123", "111")
    assert "Details about first bug" in issues[0]["body"]
    assert "Details about second item" in issues[1]["body"]
    assert "Details about second item" not in issues[0]["body"]


def test_no_bullets_returns_empty():
    issues = _parse_message("Just a regular message with no labels", "U123", "111")
    assert issues == []


def test_empty_string_returns_empty():
    issues = _parse_message("", "U123", "111")
    assert issues == []


def test_user_and_ts_captured():
    issues = _parse_message("• Bug: Something", "UABC", "999.000")
    assert issues[0]["slack_user"] == "UABC"
    assert issues[0]["slack_ts"] == "999.000"


def test_no_bullet_character_still_matches():
    issues = _parse_message("Bug: Title without bullet", "U123", "111")
    assert len(issues) == 1
    assert issues[0]["title"] == "Title without bullet"


# ── _extract_files ────────────────────────────────────────────────────────────

def test_extract_files_url_private():
    msg = {
        "files": [
            {"name": "screenshot.png", "url_private": "https://files.slack.com/files-pri/T1/screenshot.png"},
        ]
    }
    files = _extract_files(msg)
    assert len(files) == 1
    assert files[0]["name"] == "screenshot.png"
    assert "files.slack.com" in files[0]["url"]


def test_extract_files_fallback_to_permalink():
    msg = {
        "files": [
            {"name": "vid.mp4", "permalink": "https://slack.com/files/T1/vid.mp4"},
        ]
    }
    files = _extract_files(msg)
    assert files[0]["url"] == "https://slack.com/files/T1/vid.mp4"


def test_extract_files_no_files():
    assert _extract_files({}) == []
    assert _extract_files({"files": []}) == []


def test_extract_files_skips_entries_without_url():
    msg = {"files": [{"name": "bad.png"}]}
    assert _extract_files(msg) == []


# ── parse_thread ──────────────────────────────────────────────────────────────

def test_parse_thread_single_message():
    messages = [
        {"text": "• Bug: Login crash", "user": "U1", "ts": "1.0"},
    ]
    issues = parse_thread(messages)
    assert len(issues) == 1
    assert issues[0]["title"] == "Login crash"


def test_parse_thread_multiple_messages():
    messages = [
        {"text": "• Bug: First", "user": "U1", "ts": "1.0"},
        {"text": "• Enhancement: Second", "user": "U1", "ts": "2.0"},
    ]
    issues = parse_thread(messages)
    assert len(issues) == 2


def test_parse_thread_files_attached_to_last_issue_in_message():
    messages = [
        {
            "text": "• Bug: A\n• Enhancement: B",
            "user": "U1",
            "ts": "1.0",
            "files": [{"name": "img.png", "url_private": "https://slack.com/img.png"}],
        }
    ]
    issues = parse_thread(messages)
    # Files go to the last bullet in the message
    assert len(issues[1]["files"]) == 1
    assert issues[0]["files"] == []


def test_parse_thread_files_in_followup_message_attach_to_previous_issue():
    messages = [
        {"text": "• Bug: Crash on open", "user": "U1", "ts": "1.0"},
        {
            "text": "Here's a screenshot",
            "user": "U1",
            "ts": "2.0",
            "files": [{"name": "shot.png", "url_private": "https://slack.com/shot.png"}],
        },
    ]
    issues = parse_thread(messages)
    assert len(issues) == 1
    assert len(issues[0]["files"]) == 1
    assert issues[0]["files"][0]["name"] == "shot.png"


def test_parse_thread_bot_messages_excluded_by_caller():
    # The bot exclusion happens in app.py before calling parse_thread.
    # Verify parse_thread itself is agnostic to user ID.
    messages = [
        {"text": "• Bug: From bot", "user": "UBOT", "ts": "1.0"},
    ]
    issues = parse_thread(messages)
    assert len(issues) == 1  # parse_thread doesn't filter; app.py does


def test_parse_thread_empty():
    assert parse_thread([]) == []


def test_title_truncation_in_safe_item_name():
    from utils import safe_item_name
    long_title = "X" * 300
    result = safe_item_name("Bug", long_title)
    assert len(result) <= 255


def test_safe_item_name_normal():
    from utils import safe_item_name
    result = safe_item_name("Bug", "Login crash")
    assert result == "[Bug] Login crash"
