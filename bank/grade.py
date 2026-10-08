"""The bank's gate and grader (decisions 33 and 55 of
docs/build-brief-evals.md).

The gate decides whether a commit is a chore. Its grade is every test id in
the commit's test files that passes on the commit and fails on its parent
once the commit's test files are copied over the parent. The grader checks a
chore's branch the way the eval checks the fixture's: every test the base
has is still there, its own suite passes, and with the commit's test files
copied over it every grade id passes.

Pytest runs every library, on test files rather than on ids, so a test file
that cannot import makes its ids fail instead of stopping the run. Nothing
here reaches the model: the grade output goes to a row's detail, which the
rescue brief never shows for a pull request (evals/rescue.py)."""

import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from bank.chores import BankChore, Library
from evals.runner import _env, clone

MIRRORS = Path.home() / ".cache" / "mercury-bank"
SUITE_SECONDS = 60
TEST_TIMEOUT_SECONDS = 300
GIT_TIMEOUT_SECONDS = 300
NO_TESTS_RAN = 5
_TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}

BASE_RED = "base suite red"
SLOW = f"suite over {SUITE_SECONDS} s"
REFERENCE_RED = "reference suite red"
FLAKY = "grade flaky on the reference"
NOTHING = "grade passes on base"
NO_CHECKOUT = "checkout failed"


def ensure_mirror(
    library: Library,
    clone_base: str = "https://github.com",
    token: str | None = None,
    root: Path = MIRRORS,
) -> Path:
    """A local mirror of the fork, fetched again when it exists."""
    path = root / f"{library.name}.git"
    root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        command = ["git", "-C", str(path), "fetch", "-q", "--prune", "origin"]
    else:
        url = f"{clone_base.rstrip('/')}/{library.repo}.git"
        command = ["git", "clone", "-q", "--mirror", url, str(path)]
    subprocess.run(
        command, env=_env(str(root), token), check=True, timeout=GIT_TIMEOUT_SECONDS, **_TEXT
    )
    return path


def checkout(mirror: Path, sha: str, dest: Path) -> Path:
    """A working tree of one commit. Raises CalledProcessError for a sha the
    mirror does not have."""
    env = _env(str(dest.parent), None)
    for command in (
        ["git", "clone", "-q", "--shared", "--no-checkout", str(mirror), str(dest)],
        ["git", "-C", str(dest), "checkout", "-q", "--detach", sha],
    ):
        subprocess.run(command, env=env, check=True, timeout=GIT_TIMEOUT_SECONDS, **_TEXT)
    return dest


def _pytest(work: Path, library: Library, *args: str) -> subprocess.CompletedProcess:
    env = _env(str(work.parent), None)
    # pytest cuts its summary lines to the terminal's width.
    env["COLUMNS"] = "1000"
    if library.pythonpath:
        env["PYTHONPATH"] = str(work / library.pythonpath)
    command = [
        sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", "-p", "no:cacheprovider",
        "-o", "addopts=", "--rootdir=.", "--continue-on-collection-errors", *args,
    ]  # fmt: skip
    return subprocess.run(command, cwd=work, env=env, timeout=TEST_TIMEOUT_SECONDS, **_TEXT)


@dataclass(frozen=True)
class Outcome:
    returncode: int
    passed: frozenset[str]
    seconds: float
    tail: str


def run_pytest(work: Path, library: Library, paths: tuple[str, ...] = ()) -> Outcome:
    """Run the suite, or only the given test files, and name what passed."""
    start = time.monotonic()
    result = _pytest(work, library, *paths)
    passed = frozenset(
        line.removeprefix("PASSED ").strip()
        for line in result.stdout.splitlines()
        if line.startswith("PASSED ")
    )
    output = result.stdout + result.stderr
    return Outcome(result.returncode, passed, time.monotonic() - start, output[-3000:])


def collect(work: Path, library: Library) -> set[str]:
    result = _pytest(work, library, "--collect-only")
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(("ERROR", "FAILED", "PASSED"))
    }


def overlay(work: Path, source: Path, paths: tuple[str, ...]) -> None:
    """Copy these files from the source tree over the work tree."""
    for path in paths:
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / path, target)


@dataclass(frozen=True)
class Gate:
    ok: bool
    reason: str
    grade: tuple[str, ...] = ()
    seconds: float = 0.0


def gate(
    mirror: Path, library: Library, base: str, reference: str, test_files: tuple[str, ...]
) -> Gate:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        try:
            base_tree = checkout(mirror, base, Path(home) / "base")
            reference_tree = checkout(mirror, reference, Path(home) / "reference")
        except subprocess.CalledProcessError:
            return Gate(False, NO_CHECKOUT)
        on_base = run_pytest(base_tree, library)
        if on_base.returncode not in (0, NO_TESTS_RAN):
            return Gate(False, BASE_RED)
        if on_base.seconds > SUITE_SECONDS:
            return Gate(False, SLOW, seconds=on_base.seconds)
        on_reference = run_pytest(reference_tree, library)
        if on_reference.returncode != 0:
            return Gate(False, REFERENCE_RED)
        ids = {i for i in collect(reference_tree, library) if i.split("::")[0] in test_files}
        again = run_pytest(reference_tree, library, test_files)
        if (ids & on_reference.passed) != (ids & again.passed):
            return Gate(False, FLAKY)
        overlay(base_tree, reference_tree, test_files)
        before = run_pytest(base_tree, library, test_files)
        grade = tuple(sorted((ids & on_reference.passed) - before.passed))
        if not grade:
            return Gate(False, NOTHING)
        return Gate(True, "", grade, on_base.seconds)


def grade_branch(
    chore: BankChore,
    library: Library,
    mirror: Path,
    clone_base: str,
    token: str | None,
    branch: str,
) -> tuple[bool, str]:
    """Grade a chore's branch. Never raises for a bad branch; the answer is
    the boolean, and the text is for the row's detail only."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        work = Path(home) / "work"
        try:
            error = clone(f"{clone_base.rstrip('/')}/{chore.repo}.git", branch, work, token, 120)
            if error:
                return False, error
            base_tree = checkout(mirror, chore.base, Path(home) / "base")
            reference_tree = checkout(mirror, chore.reference, Path(home) / "reference")
            lost = collect(base_tree, library) - collect(work, library)
            if lost:
                return False, "tests removed: " + ", ".join(sorted(lost))
            own = run_pytest(work, library)
            if own.returncode not in (0, NO_TESTS_RAN):
                return False, "own tests failed: " + own.tail
            overlay(work, reference_tree, chore.test_files)
            graded = run_pytest(work, library, chore.test_files)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as failure:
            return False, f"grading could not run: {type(failure).__name__}"
        missing = sorted(set(chore.grade) - graded.passed)
        if missing:
            return False, f"grade failed: {len(missing)} of {len(chore.grade)}\n{graded.tail}"
        return True, graded.tail
