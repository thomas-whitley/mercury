"""The prompts a repo chore serves, built in app/chore_prompts.py so the
bank's export builds a reference example from the same text (decision 59 of
docs/build-brief-evals.md)."""

from app.chore_prompts import (
    MAX_FILE_CHARS,
    MAX_TREE_ENTRIES,
    edit_prompt,
    read_prompt,
    shown_files,
    tree_listing,
)


def test_a_long_tree_is_cut_with_a_count():
    listing = tree_listing([f"f{i}.py" for i in range(MAX_TREE_ENTRIES + 3)])

    assert listing.endswith("\n... and 3 more")
    assert listing.count("\n") == MAX_TREE_ENTRIES


def test_the_read_prompt_asks_for_files_by_name():
    prompt = read_prompt("Add sub.", "", "pkg/core.py")

    assert prompt == (
        "Instruction:\nAdd sub.\n\nFiles in the repository:\npkg/core.py\n\n"
        'Reply {"read": ["path", ...]} naming up to 10 files you need to see.'
    )


def test_the_edit_prompt_shows_each_file_and_says_none_when_empty():
    shown = edit_prompt("Add sub.", "", "pkg/core.py", {"pkg/core.py": "x = 1\n"})

    assert "Contents:\n=== pkg/core.py ===\nx = 1\n\n\n" in shown
    assert "Contents:\n(none)" in edit_prompt("Add sub.", "", "pkg/core.py", {})


def test_files_are_shown_cut_to_the_limit_and_missing_ones_skipped(tmp_path):
    (tmp_path / "big.py").write_text("x" * (MAX_FILE_CHARS + 5))

    shown = shown_files(tmp_path, ["big.py", "gone.py"])

    assert list(shown) == ["big.py"]
    assert len(shown["big.py"]) == MAX_FILE_CHARS
