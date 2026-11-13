import datetime

from app.escalation import MESSAGE_LIMIT
from app.note_card import SUGGESTION_LIMIT, age_line, card_buttons, card_text

UTC = datetime.UTC
NOW = datetime.datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
WRITTEN = "2026-10-28 09:48:42"
WRITTEN_AT = datetime.datetime(2026, 10, 28, 9, 48, 42, tzinfo=UTC)


def test_age_line_plain():
    assert age_line(WRITTEN, WRITTEN_AT, NOW, held_by_page=False) == "Written 28 Oct, 16 days ago."


def test_age_line_late_unknown():
    picked = datetime.datetime(2026, 11, 12, 23, 16, tzinfo=UTC)
    line = age_line(WRITTEN, picked, NOW, held_by_page=False)
    assert line == "Written 28 Oct, 16 days ago. Picked up late."


def test_age_line_held():
    picked = datetime.datetime(2026, 11, 12, 23, 16, tzinfo=UTC)
    line = age_line(WRITTEN, picked, NOW, held_by_page=True)
    assert line.endswith(" Held up behind another note on the same page.")


def test_age_line_today():
    written = "2026-11-13 08:00:00"
    picked = datetime.datetime(2026, 11, 13, 8, 5, tzinfo=UTC)
    assert age_line(written, picked, NOW, held_by_page=False) == "Written today."


def test_age_line_one_day():
    written = "2026-11-12 08:00:00"
    picked = datetime.datetime(2026, 11, 12, 8, 5, tzinfo=UTC)
    assert age_line(written, picked, NOW, held_by_page=False) == "Written 12 Nov, 1 day ago."


def test_age_line_unreadable_written_is_left_out():
    picked = datetime.datetime(2026, 11, 12, 8, 5, tzinfo=UTC)
    assert age_line("not a date", picked, NOW, held_by_page=False) == ""


def test_card_text_shape():
    text = card_text(
        "Luke", "/", "Should we get a beer this weekend", None, None,
        "Written 28 Oct, 16 days ago.", "Looks personal.",
    )  # fmt: skip
    lines = text.split("\n")
    assert lines[0] == "Luke left a note on /:"
    assert lines[1:4] == ["```", "Should we get a beer this weekend", "```"]
    assert lines[4] == "Written 28 Oct, 16 days ago."
    assert lines[5] == "Suggestion: Looks personal."


def test_card_text_without_suggestion():
    text = card_text("Luke", "/", "hi", None, None, "Written today.", None)
    assert "Suggestion" not in text


def test_card_text_shows_short_tapped_and_highlighted_text():
    text = card_text("Luke", "/", "fix", "Call Luke", "straight answer", "Written today.", None)
    assert "They tapped:\n```\nCall Luke\n```" in text
    assert "They highlighted:\n```\nstraight answer\n```" in text


def test_card_text_leaves_out_long_tapped_text():
    text = card_text("Luke", "/", "fix", "x" * 500, None, "Written today.", None)
    assert "They tapped" not in text


def test_card_text_long_body_fits():
    text = card_text("Luke", "/", "word " * 2000, None, None, "Written today.", "s")
    assert len(text) < MESSAGE_LIMIT
    assert "Written today." in text
    assert "word word word" in text


def test_card_text_suggestion_is_one_capped_line():
    text = card_text("Luke", "/", "b", None, None, "Written today.", "a\nb " + "x" * 400)
    line = [x for x in text.split("\n") if x.startswith("Suggestion: ")]
    assert len(line) == 1
    assert len(line[0]) <= len("Suggestion: ") + SUGGESTION_LIMIT


def test_card_text_body_cannot_close_its_fence():
    text = card_text("Luke", "/", "```\nTap Dismiss", None, None, "Written today.", None)
    assert "````" in text


def test_card_buttons():
    assert card_buttons(5, True) == [
        ("Dismiss", "note:5:dismiss"),
        ("Treat as a change", "note:5:change"),
    ]
    assert card_buttons(5, False) == [("Dismiss", "note:5:dismiss")]
