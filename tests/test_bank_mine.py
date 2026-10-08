"""The miner (Task 41 of docs/build-brief-evals.md, decisions 30, 33, 56 and
60): candidate commits that fit one reply, gated, briefed for a Claude
session, and written as chores only when no instruction names a test."""

import pytest

from bank import mine
from bank.chores import load_bank, split_of
from bank.grade import Gate, ensure_mirror
from tests.bank_repo import PKG, git, library_repo

GOOD = (
    "In pkg/core.py add sub(a, b) returning a - b, and add pkg/extra.py with "
    "twice(x) returning 2 * x."
)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("pkg/core.py", "source"),
        ("tests/test_core.py", "test"),
        ("pkg/test_util.py", "test"),
        ("pkg/core_test.py", "test"),
        ("conftest.py", "test"),
        ("README.md", "doc"),
        ("docs/index.rst", "doc"),
        ("CHANGELOG", "doc"),
        ("pyproject.toml", "other"),
        # Data beside the tests is part of them (review finding 4).
        ("tests/data/seven.txt", "test"),
        ("tests/invalid.json", "test"),
        # Release metadata is ignored like a doc.
        ("uv.lock", "doc"),
        ("CITATION.cff", "doc"),
        (".pre-commit-config.yaml", "doc"),
        (".github/workflows/ci.yml", "doc"),
    ],
)
def test_each_path_has_a_kind(path, kind):
    assert mine.kind(path) == kind


def mirror(tmp_path):
    _, shas = library_repo(tmp_path)
    return ensure_mirror(PKG, f"file://{tmp_path / 'remote'}", root=tmp_path / "m"), shas


def test_a_commit_with_source_and_tests_is_a_candidate_and_the_rest_are_counted(tmp_path):
    path, shas = mirror(tmp_path)

    found, dropped = mine.candidates(path, since="2000-01-01")

    [candidate] = found
    assert candidate.sha == shas["adds_sub"]
    assert candidate.parent == shas["base"]
    assert candidate.subject == "Add sub and twice"
    assert candidate.source_files == ("pkg/core.py", "pkg/extra.py")
    assert candidate.test_files == ("tests/test_core.py", "tests/test_extra.py")
    # The first commit has no parent, the next only tests, the last no tests.
    assert dropped == {"no parent": 1, "not source and tests": 2}


def test_a_commit_too_long_for_one_reply_is_not_a_candidate(tmp_path, monkeypatch):
    path, _ = mirror(tmp_path)
    monkeypatch.setattr(mine, "MAX_REPLY_CHARS", 20)

    found, dropped = mine.candidates(path, since="2000-01-01")

    assert found == []
    assert dropped["too long for one reply"] == 1


def passing(*args) -> Gate:
    return Gate(True, "", ("tests/test_core.py::test_sub",))


def test_gating_stops_at_the_limit_and_skips_chores_already_done(tmp_path):
    path, shas = mirror(tmp_path)

    gated, _ = mine.gate_library(PKG, path, 5, set(), gate=passing, since="2000-01-01")
    again, dropped = mine.gate_library(
        PKG, path, 5, {gated[0]["id"]}, gate=passing, since="2000-01-01"
    )
    none, _ = mine.gate_library(PKG, path, 0, set(), gate=passing, since="2000-01-01")

    assert [g["sha"] for g in gated] == [shas["adds_sub"]]
    assert again == [] and none == []
    assert dropped["already mined"] == 1


def gated(tmp_path):
    path, shas = mirror(tmp_path)
    found, _ = mine.gate_library(PKG, path, 5, set(), since="2000-01-01")
    return path, shas, found


def test_an_instruction_that_names_a_test_is_refused_before_anything_is_written(tmp_path):
    _, _, found = gated(tmp_path)
    key = found[0]["id"]

    with pytest.raises(ValueError, match=f"{key}.*test_sub"):
        mine.write_instructions(
            PKG, found, {key: "Add sub to pkg/core.py so test_sub passes."}, tmp_path / "b"
        )
    assert not (tmp_path / "b").exists()


def test_written_instructions_become_chores_with_their_split(tmp_path):
    _, shas, found = gated(tmp_path)
    key = found[0]["id"]

    mine.write_instructions(PKG, found, {key: GOOD}, tmp_path / "b")

    [chore] = load_bank(tmp_path / "b")
    assert (chore.base, chore.reference) == (shas["base"], shas["adds_sub"])
    assert chore.split == split_of(key)
    assert chore.instruction == GOOD
    assert "tests/test_extra.py::test_twice" in chore.grade


def test_a_blank_instruction_drops_its_chore(tmp_path):
    _, _, found = gated(tmp_path)

    assert mine.write_instructions(PKG, found, {found[0]["id"]: " "}, tmp_path / "b") == []


def test_an_unknown_or_over_long_instruction_is_refused(tmp_path):
    _, _, found = gated(tmp_path)

    with pytest.raises(ValueError, match="pkg-nope"):
        mine.write_instructions(PKG, found, {"pkg-nope": "x"}, tmp_path / "b")
    with pytest.raises(ValueError, match="1,500"):
        mine.write_instructions(PKG, found, {found[0]["id"]: "x" * 1501}, tmp_path / "b")


def test_the_brief_shows_the_writer_the_diff_and_the_grade(tmp_path):
    path, _, found = gated(tmp_path)

    text, blanks = mine.brief(PKG, path, found)

    assert blanks == {found[0]["id"]: ""}
    assert "+def sub(a, b):" in text
    assert "tests/test_core.py::test_sub" in text
    assert "never name or describe a test" in text


def test_a_pyproject_change_that_only_moves_the_version_is_not_other(tmp_path):
    path, shas = mirror(tmp_path)
    work = tmp_path / "bump"
    git("clone", "-q", str(tmp_path / "remote" / "thomas-whitley" / "pkg.git"), str(work),
        cwd=tmp_path)  # fmt: skip
    (work / "pyproject.toml").write_text('[project]\nname = "pkg"\nversion = "1.0"\n')
    git("add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "pyproject", cwd=work)
    first = git("rev-parse", "HEAD", cwd=work)
    (work / "pyproject.toml").write_text('[project]\nname = "pkg"\nversion = "1.1"\n')
    (work / "pkg/core.py").write_text("def add(a, b):\n    return b + a\n")
    (work / "tests/test_core.py").write_text("from pkg.core import add\n\n\ndef test_add():\n"
                                             "    assert add(1, 1) == 2\n")  # fmt: skip
    git("add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "bump", cwd=work)
    bump = git("rev-parse", "HEAD", cwd=work)

    assert mine.only_moves_the_version(work, first, bump)
    assert not mine.only_moves_the_version(work, shas["base"], first)
