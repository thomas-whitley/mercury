"""Grades an Astro chore: the diff keeps the repo's tests, the site installs,
checks, tests and builds, and the built pages carry the text the chore asked
for. A check is {"page": path under dist/, "contains": [...], "absent": [...]};
the page may be a glob (_astro/*.css), and passes when any matching file does.
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.test_guard import weakened_tests

Run = Callable[[list[str], Path, float], subprocess.CompletedProcess]
STEPS = (["ci"], ["run", "check"], ["test"], ["run", "build"])


def _npm(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    # npm needs the desktop's own environment (APPDATA, its cache), minus
    # Mercury's secrets, like the delegate does (evals/runner.py _delegate_env).
    env = {k: v for k, v in os.environ.items() if not k.startswith("MERCURY_")}
    return subprocess.run(
        cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )  # fmt: skip


def _check(dist: Path, check: dict) -> str | None:
    """None when some file matching the page passes, else why not."""
    files = sorted(p for p in dist.glob(check["page"]) if p.is_file())
    if not files:
        return f"no file matches {check['page']}"
    why = ""
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in check.get("contains", []) if s not in text]
        present = [s for s in check.get("absent", []) if s in text]
        if not missing and not present:
            return None
        why = f"{check['page']}: missing {missing}, still has {present}"
    return why


def grade_astro(
    work: Path,
    checks: list[dict],
    diff: str,
    timeout_seconds: float = 900,
    run: Run | None = None,
) -> tuple[bool, str]:
    """Never raises; the answer is the boolean and the reason."""
    problems = weakened_tests(diff)
    if problems:
        return False, "weakened tests: " + "; ".join(problems)
    run = run or _npm
    npm = shutil.which("npm") or "npm"
    try:
        for step in STEPS:
            result = run([npm, *step], work, timeout_seconds)
            if result.returncode != 0:
                output = (result.stdout or "") + (result.stderr or "")
                return False, f"npm {' '.join(step)} failed: " + output[-3000:]
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_seconds:.0f} s"
    failures = [why for check in checks if (why := _check(work / "dist", check))]
    if failures:
        return False, "; ".join(failures)
    return True, "built, and every page check passed"
