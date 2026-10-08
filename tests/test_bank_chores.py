"""The bank's chore files, libraries and split (Task 39 of
docs/build-brief-evals.md, decisions 34 and 54)."""

import pytest
import yaml

from bank.chores import (
    FIXTURE,
    BankChore,
    Library,
    chore_id,
    load_bank,
    load_libraries,
    split_of,
    write_chore,
)

SHA = "a" * 40
REF = "b" * 40


def chore(**changes) -> BankChore:
    fields = {
        "id": chore_id("pkg", REF), "library": "pkg", "repo": "thomas-whitley/pkg",
        "instruction": "In pkg/core.py add sub(a, b).\nIt returns a - b.", "base": SHA,
        "reference": REF, "grade": ("tests/test_core.py::test_sub",),
        "test_files": ("tests/test_core.py",), "split": split_of(chore_id("pkg", REF)),
    }  # fmt: skip
    return BankChore(**(fields | changes))


def test_a_chore_id_is_the_library_and_ten_characters_of_the_commit():
    assert chore_id("pkg", REF) == "pkg-bbbbbbbbbb"


def test_the_split_is_fixed_and_about_one_in_five_is_validation():
    ids = [f"pkg-{i:010x}" for i in range(1000)]
    splits = [split_of(i) for i in ids]

    assert splits == [split_of(i) for i in ids]
    assert set(splits) == {"training", "validation"}
    assert 150 <= splits.count("validation") <= 250


def test_a_written_chore_loads_back_the_same(tmp_path):
    write_chore(chore(), tmp_path)

    assert load_bank(tmp_path) == [chore()]
    assert (tmp_path / "pkg" / "pkg-bbbbbbbbbb.yaml").is_file()


def test_the_bank_refuses_the_fixture(tmp_path):
    write_chore(chore(repo=FIXTURE), tmp_path)

    with pytest.raises(ValueError, match="fixture"):
        load_bank(tmp_path)


def test_the_bank_refuses_a_split_that_is_not_the_hash(tmp_path):
    wrong = "validation" if chore().split == "training" else "training"
    write_chore(chore(split=wrong), tmp_path)

    with pytest.raises(ValueError, match="split"):
        load_bank(tmp_path)


def test_the_bank_refuses_a_file_not_named_by_its_id(tmp_path):
    path = write_chore(chore(), tmp_path)
    path.rename(path.with_name("other.yaml"))

    with pytest.raises(ValueError, match="other"):
        load_bank(tmp_path)


def test_libraries_load_with_their_test_command(tmp_path):
    path = tmp_path / "libraries.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "libraries": [
                    {"name": "pkg", "upstream": "up/pkg", "repo": "thomas-whitley/pkg"},
                    {
                        "name": "lay",
                        "upstream": "up/lay",
                        "repo": "thomas-whitley/lay",
                        "pythonpath": "src",
                    },
                ]
            }  # fmt: skip
        )
    )

    libraries = load_libraries(path)

    assert libraries["pkg"] == Library("pkg", "up/pkg", "thomas-whitley/pkg")
    assert libraries["pkg"].test_command == "python -m pytest -q -p no:cacheprovider -o addopts="
    assert libraries["lay"].test_command.startswith("PYTHONPATH=src python -m pytest")


def test_a_library_must_be_a_fork_under_thomas_whitley(tmp_path):
    path = tmp_path / "libraries.yaml"
    path.write_text(
        yaml.safe_dump({"libraries": [{"name": "pkg", "upstream": "up/pkg", "repo": "up/pkg"}]})
    )

    with pytest.raises(ValueError, match="thomas-whitley"):
        load_libraries(path)


def test_the_bank_s_own_files_load():
    assert isinstance(load_bank(), list)
    assert isinstance(load_libraries(), dict)
