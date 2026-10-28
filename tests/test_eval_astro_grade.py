"""Grading an Astro chore by its build and the text on the built page."""

import subprocess
from pathlib import Path

from evals.astro_grade import grade_astro

WEAKENING_DIFF = """diff --git a/tests/site.test.ts b/tests/site.test.ts
--- a/tests/site.test.ts
+++ b/tests/site.test.ts
@@ -1,4 +1,2 @@
-it('formats the phone', () => {
-});
"""


def _built(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / "dist" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _run(failing: str | None = None):
    """Every npm step succeeds except the one whose script name is failing."""
    calls: list[list[str]] = []

    def run(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
        calls.append(cmd)
        code = 1 if failing and cmd[-1] == failing else 0
        return subprocess.CompletedProcess(cmd, code, f"{cmd[-1]} output", "")

    run.calls = calls
    return run


def test_grade_astro_passes_when_text_is_on_the_page(tmp_path):
    work = _built(tmp_path, {"services/index.html": "<li>Smoke alarms</li>"})

    ok, detail = grade_astro(
        work, [{"page": "services/index.html", "contains": ["Smoke alarms"]}], "", run=_run()
    )

    assert ok, detail


def test_grade_astro_runs_install_check_test_and_build_in_order(tmp_path):
    work = _built(tmp_path, {"index.html": "Hi"})
    run = _run()

    grade_astro(work, [{"page": "index.html", "contains": ["Hi"]}], "", run=run)

    assert [cmd[1:] for cmd in run.calls] == [["ci"], ["run", "check"], ["test"], ["run", "build"]]


def test_grade_astro_absent_text_fails(tmp_path):
    work = _built(tmp_path, {"index.html": "LED lights, inside and out."})

    ok, detail = grade_astro(
        work, [{"page": "index.html", "absent": ["inside and out."]}], "", run=_run()
    )

    assert not ok
    assert "inside and out." in detail


def test_grade_astro_glob_matches_any_css(tmp_path):
    work = _built(
        tmp_path,
        {"_astro/a.css": "body{margin:0}", "_astro/b.css": ".header-phone{font-size:1.25rem}"},
    )

    ok, detail = grade_astro(
        work, [{"page": "_astro/*.css", "contains": ["font-size:1.25rem"]}], "", run=_run()
    )

    assert ok, detail


def test_grade_astro_build_failure_fails(tmp_path):
    work = _built(tmp_path, {"index.html": "Hi"})

    ok, detail = grade_astro(
        work, [{"page": "index.html", "contains": ["Hi"]}], "", run=_run("build")
    )

    assert not ok
    assert "npm run build" in detail


def test_grade_astro_missing_page_fails(tmp_path):
    work = _built(tmp_path, {"index.html": "Hi"})

    ok, detail = grade_astro(
        work, [{"page": "nope/index.html", "contains": ["Hi"]}], "", run=_run()
    )

    assert not ok
    assert "no file matches nope/index.html" in detail


def test_grade_astro_weakened_tests_fails(tmp_path):
    work = _built(tmp_path, {"index.html": "Hi"})
    run = _run()

    ok, detail = grade_astro(
        work, [{"page": "index.html", "contains": ["Hi"]}], WEAKENING_DIFF, run=run
    )

    assert not ok
    assert detail.startswith("weakened tests: ")
    assert "formats the phone" in detail
    assert run.calls == []


def test_grade_astro_timeout_fails(tmp_path):
    def slow(cmd, cwd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    ok, detail = grade_astro(tmp_path, [], "", run=slow, timeout_seconds=5)

    assert not ok
    assert detail == "timed out after 5 s"
