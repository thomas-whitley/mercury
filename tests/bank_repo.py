"""A small library repo for the bank's tests: a package, its tests, and a
few commits shaped like the ones the miner meets (Tasks 40, 41 and 44 of
docs/build-brief-evals.md)."""

import subprocess
from pathlib import Path

from bank.chores import Library

PKG = Library("pkg", "up/pkg", "thomas-whitley/pkg")

CORE = "def add(a, b):\n    return a + b\n"
CORE_SUB = CORE + "\n\ndef sub(a, b):\n    return a - b\n"
TEST_CORE = "from pkg.core import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
TEST_SUB = (
    TEST_CORE
    + "\n\ndef test_sub():\n    from pkg.core import sub\n\n    assert sub(5, 3) == 2\n"
    + "\n\nimport pytest\n\n\n@pytest.mark.parametrize('a', [1, 2])\n"
    + "def test_sub_many(a):\n    from pkg.core import sub\n\n    assert sub(a, a) == 0\n"
    + "\n\nclass TestSub:\n    def test_neg(self):\n        from pkg.core import sub\n\n"
    + "        assert sub(1, 2) == -1\n"
)
EXTRA = "def twice(x):\n    return 2 * x\n"
TEST_EXTRA = "from pkg.extra import twice\n\n\ndef test_twice():\n    assert twice(4) == 8\n"
READ = "\n\ndef read(path):\n    return int(open(path).read())\n"
TEST_READ = (
    "import pathlib\n\nfrom pkg.core import read\n\n\ndef test_read():\n"
    "    path = pathlib.Path(__file__).parent / 'data' / 'seven.txt'\n"
    "    assert read(path) == 7\n"
)


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(work: Path, message: str, files: dict[str, str | None]) -> str:
    for path, body in files.items():
        target = work / path
        if body is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    git("add", "-A", cwd=work)
    git("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message, cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


def library_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A bare repo at tmp_path/remote/thomas-whitley/pkg.git, and the shas of
    its commits: base, adds_sub (source, tests and a doc), test_only (a test
    that already passes on its parent) and breaks_base (source only)."""
    work = tmp_path / "seed"
    work.mkdir()
    git("init", "-q", "-b", "main", cwd=work)
    shas = {
        "base": _commit(
            work,
            "Start",
            {"pkg/__init__.py": "", "pkg/core.py": CORE, "tests/test_core.py": TEST_CORE},
        )
    }
    shas["adds_sub"] = _commit(
        work,
        "Add sub and twice",
        {
            "pkg/core.py": CORE_SUB,
            "pkg/extra.py": EXTRA,
            "tests/test_core.py": TEST_SUB,
            "tests/test_extra.py": TEST_EXTRA,
            "CHANGELOG.md": "Added sub.\n",
        },
    )
    shas["test_only"] = _commit(
        work,
        "Test add with zero",
        {"tests/test_core.py": TEST_SUB + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"},
    )
    shas["breaks_base"] = _commit(
        work, "Break add", {"pkg/core.py": CORE_SUB.replace("a + b", "a * b")}
    )
    # Off the default branch, so the miner never sees them: a commit that
    # changes what an existing test expects, and one whose test needs a data
    # file beside it.
    git("checkout", "-q", "-b", "side", shas["adds_sub"], cwd=work)
    shas["changes_expectation"] = _commit(
        work,
        "Double add",
        {
            "pkg/core.py": CORE_SUB.replace("return a + b", "return 2 * (a + b)"),
            "tests/test_core.py": TEST_SUB.replace("add(2, 3) == 5", "add(2, 3) == 10"),
        },
    )
    git("checkout", "-q", "-b", "data", shas["adds_sub"], cwd=work)
    shas["needs_data"] = _commit(
        work,
        "Read a number from a file",
        {
            "pkg/core.py": CORE_SUB + READ,
            "tests/data/seven.txt": "7\n",
            "tests/test_read.py": TEST_READ,
        },
    )
    git("checkout", "-q", "main", cwd=work)
    bare = tmp_path / "remote" / "thomas-whitley" / "pkg.git"
    bare.parent.mkdir(parents=True)
    git("clone", "-q", "--mirror", str(work), str(bare), cwd=tmp_path)
    return bare, shas


def push_branch(
    bare: Path, tmp_path: Path, branch: str, start: str, files: dict[str, str | None]
) -> None:
    """Push a branch from start with these files written (None deletes one)."""
    work = tmp_path / f"branch-{branch.replace('/', '-')}"
    git("clone", "-q", str(bare), str(work), cwd=tmp_path)
    git("checkout", "-q", "-b", branch, start, cwd=work)
    _commit(work, "chore", files)
    git("push", "-q", "origin", branch, cwd=work)
