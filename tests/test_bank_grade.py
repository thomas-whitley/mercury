"""The bank's gate and grader (Task 40 of docs/build-brief-evals.md,
decisions 33 and 55): the grade is what the commit's tests pass that its
parent fails, and a branch passes when it keeps the base's tests, passes its
own, and passes every grade id."""

import subprocess

import pytest

from bank import grade
from bank.chores import BankChore
from tests.bank_repo import CORE, CORE_SUB, EXTRA, PKG, library_repo, push_branch

SUB_IDS = {
    "tests/test_core.py::test_sub",
    "tests/test_core.py::test_sub_many[1]",
    "tests/test_core.py::test_sub_many[2]",
    "tests/test_core.py::TestSub::test_neg",
}
TEST_FILES = ("tests/test_core.py", "tests/test_extra.py")


def mirror(tmp_path):
    _, shas = library_repo(tmp_path)
    return grade.ensure_mirror(PKG, f"file://{tmp_path / 'remote'}", root=tmp_path / "m"), shas


def test_the_grade_is_what_fails_on_the_base_and_passes_on_the_reference(tmp_path):
    path, shas = mirror(tmp_path)

    result = grade.gate(path, PKG, shas["base"], shas["adds_sub"], TEST_FILES)

    assert result.ok, result.reason
    # A new test file that cannot import on the base belongs to the grade;
    # a test that already passed there does not.
    assert set(result.grade) == SUB_IDS | {"tests/test_extra.py::test_twice"}


def test_a_commit_whose_tests_already_pass_on_its_base_is_dropped(tmp_path):
    path, shas = mirror(tmp_path)

    result = grade.gate(path, PKG, shas["adds_sub"], shas["test_only"], ("tests/test_core.py",))

    assert (result.ok, result.reason) == (False, grade.NOTHING)


def test_a_commit_on_a_red_base_is_dropped(tmp_path):
    path, shas = mirror(tmp_path)

    result = grade.gate(path, PKG, shas["breaks_base"], shas["breaks_base"], ())

    assert (result.ok, result.reason) == (False, grade.BASE_RED)


def test_a_commit_that_is_not_in_the_mirror_is_dropped(tmp_path):
    path, shas = mirror(tmp_path)

    result = grade.gate(path, PKG, shas["base"], "f" * 40, TEST_FILES)

    assert (result.ok, result.reason) == (False, grade.NO_CHECKOUT)


def test_a_mirror_is_fetched_again_when_it_exists(tmp_path):
    path, _ = mirror(tmp_path)

    assert grade.ensure_mirror(PKG, f"file://{tmp_path / 'remote'}", root=tmp_path / "m") == path


def bank_chore(shas) -> BankChore:
    return BankChore(
        "pkg-x", "pkg", "thomas-whitley/pkg", "Add sub.", shas["base"], shas["adds_sub"],
        tuple(sorted(SUB_IDS | {"tests/test_extra.py::test_twice"})), TEST_FILES, "training",
    )  # fmt: skip


def graded(tmp_path, files):
    path, shas = mirror(tmp_path)
    bare = tmp_path / "remote" / "thomas-whitley" / "pkg.git"
    push_branch(bare, tmp_path, "agent/1", shas["base"], files)
    return grade.grade_branch(
        bank_chore(shas), PKG, path, f"file://{tmp_path / 'remote'}", None, "agent/1"
    )


def test_a_branch_that_makes_the_change_passes(tmp_path):
    ok, detail = graded(tmp_path, {"pkg/core.py": CORE_SUB, "pkg/extra.py": EXTRA})

    assert ok, detail


def test_a_branch_with_a_wrong_change_fails(tmp_path):
    wrong = CORE_SUB.replace("a - b", "b - a")
    ok, detail = graded(tmp_path, {"pkg/core.py": wrong, "pkg/extra.py": EXTRA})

    assert not ok
    assert detail.startswith("grade failed")


def test_a_branch_that_drops_a_test_the_base_has_fails(tmp_path):
    ok, detail = graded(
        tmp_path,
        {"pkg/core.py": CORE_SUB, "pkg/extra.py": EXTRA, "tests/test_core.py": "x = 1\n"},
    )

    assert not ok
    assert detail.startswith("tests removed: tests/test_core.py::test_add")


def test_a_branch_that_breaks_its_own_suite_fails(tmp_path):
    broken = CORE.replace("a + b", "a")
    ok, detail = graded(tmp_path, {"pkg/core.py": broken, "pkg/extra.py": EXTRA})

    assert not ok
    assert detail.startswith("own tests failed")


def test_a_branch_that_cannot_be_fetched_raises_rather_than_failing_the_model(tmp_path):
    # A succeeded chore pushed its branch, so a clone that fails is GitHub's
    # fault, and the row must be queued again, not graded wrong (finding 3).
    path, shas = mirror(tmp_path)

    with pytest.raises(grade.GradingError, match="clone failed"):
        grade.grade_branch(
            bank_chore(shas), PKG, path, f"file://{tmp_path / 'remote'}", None, "agent/none"
        )


def test_a_library_s_ignored_test_files_are_left_out_of_every_run(tmp_path):
    path, shas = mirror(tmp_path)
    tree = grade.checkout(path, shas["breaks_base"], tmp_path / "t")
    quiet = grade.Library("pkg", "up/pkg", "thomas-whitley/pkg", ignore=("tests/test_core.py",))

    assert grade.run_pytest(tree, PKG).returncode == 1
    assert grade.run_pytest(tree, quiet).returncode in (0, grade.NO_TESTS_RAN)


def test_a_commit_whose_source_breaks_an_existing_test_of_the_base_is_dropped(tmp_path):
    # The worker runs the base's own tests on the branch, so a correct answer
    # to this chore could never go green there (review finding 1).
    path, shas = mirror(tmp_path)

    result = grade.gate(
        path, PKG, shas["adds_sub"], shas["changes_expectation"], ("tests/test_core.py",)
    )

    assert (result.ok, result.reason) == (False, grade.REFERENCE_BREAKS_BASE)


def test_a_data_file_beside_the_commit_s_tests_is_copied_to_grade(tmp_path):
    path, shas = mirror(tmp_path)
    files = ("tests/data/seven.txt", "tests/test_read.py")

    result = grade.gate(path, PKG, shas["adds_sub"], shas["needs_data"], files)

    assert result.ok, result.reason
    assert result.grade == ("tests/test_read.py::test_read",)


def test_a_commit_whose_tests_hang_is_dropped_as_slow(tmp_path, monkeypatch):
    path, shas = mirror(tmp_path)

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired("pytest", 300)

    monkeypatch.setattr(grade, "run_pytest", hang)

    result = grade.gate(path, PKG, shas["base"], shas["adds_sub"], TEST_FILES)

    assert (result.ok, result.reason) == (False, grade.SLOW)
