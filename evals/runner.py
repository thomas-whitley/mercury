"""Runs Mercury's chore evals and grades each result with a test the model
never saw.

A task is one YAML file under evals/chores/: the repo, an instruction that
names every file and function it expects, and a grade test. Each task runs
once per column per repeat. A Mercury column queues it as a repo_chore
through POST /runs, and a chore that opens a pull request is graded on its
branch, which is then closed and deleted so the fixture keeps only main.
The delegate column (Task 5) runs delegate.ps1 on a local clone instead.

A result passes when it still has every test id main has, its own tests
pass, and the grade test passes.

uv run python -m evals.runner --columns gemini,ollama --repeats 1
reads MERCURY_URL, MERCURY_BEARER_TOKEN and MERCURY_GITHUB_TOKEN.
"""

import argparse
import base64
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import httpx2
import yaml

from app.config import PROVIDERS

OPEN = {"pending", "running", "awaiting_approval"}
# Final statuses a hint might fix: a wrong pull request, an escalation, or a
# delegate change that stayed red. A timeout, an error or a refusal is not
# the model's answer, so it is not rescued (Phase 3 of docs/build-brief-evals.md).
RESCUABLE = {"succeeded", "escalated", "failed"}
# How much of a failed attempt the rescue brief shows.
EVIDENCE_DIFF_CHARS = 6000
EVIDENCE_TAIL_CHARS = 2000
GRADE_MODULE = "grade_hidden"
HERE = Path(__file__).parent
FIXTURE_URL = "https://github.com/thomas-whitley/mercury-fixture.git"
# The fixture's own tests, as its test_command in mercury.yaml runs them.
REPO_TESTS = [sys.executable, "-m", "unittest", "discover", "-v"]
# unittest's exit status when it finds no tests, which a repo with none returns.
NO_TESTS_RAN = 5
# Prints every test id unittest discovers, one per line, without running any.
LIST_TESTS = (
    "import unittest\n"
    "def walk(suite):\n"
    "    for t in suite:\n"
    "        walk(t) if isinstance(t, unittest.TestSuite) else print(t.id())\n"
    "walk(unittest.defaultTestLoader.discover('.'))\n"
)
# Runs the suite quietly and prints the id of every test it skipped or expected to fail.
LIST_SKIPPED = (
    "import io, unittest\n"
    "suite = unittest.defaultTestLoader.discover('.')\n"
    "result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)\n"
    "for test, _ in result.skipped + result.expectedFailures:\n"
    "    print(test.id())\n"
)
_TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


class DiscoveryFailed(RuntimeError):
    """Listing a checkout's tests crashed, so its test ids are not known. An
    empty set would look like a repo with no tests and switch the removal
    check off, so this is raised instead."""


class EvalAborted(Exception):
    """The batch cannot go on, for example because chores wait for Approve."""


@dataclass(frozen=True)
class EvalTask:
    id: str
    repo: str
    instruction: str
    grade: str


@dataclass
class EvalRow:
    task: str
    provider: str  # the column asked for: a provider, or delegate:<model>
    answered_by: str | None  # runs.provider at the end, after any fallback
    run_id: str | None
    status: str  # succeeded, failed, timeout, refused, or another final run status
    graded: bool  # kept main's tests, passed its own, and passed the hidden test
    tokens: int | None  # None where the column cannot count them
    seconds: float | None
    usd: float
    detail: str = ""
    # Replies the chore could not use (app/repo_chore.py). None where the
    # column cannot count them.
    unusable: int | None = None
    repeat: int = 1
    # The last attempt's diff and the tail of the repo's own test output, for
    # the rescue brief. Never text from grading, which goes to detail.
    diff: str = ""
    test_tail: str = ""
    # The one Claude hint this row got in the rescue pass, and the rerun's row.
    rescue_hint: str | None = None
    rescue: "EvalRow | None" = None


def row_key(row: EvalRow) -> str:
    return f"{row.task}/{row.provider}/{row.repeat}"


def row_from_dict(data: dict) -> EvalRow:
    data = dict(data)
    rescue = data.pop("rescue", None)
    return EvalRow(**data, rescue=row_from_dict(rescue) if rescue else None)


def load_rows(path: Path) -> list[EvalRow]:
    return [row_from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]


def load_tasks(directory: Path) -> list[EvalTask]:
    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tasks.append(
            EvalTask(
                id=path.stem,
                repo=data["repo"],
                instruction=data["instruction"].strip(),
                grade=data["grade"],
            )
        )
    return tasks


def _env(home: str, token: str | None) -> dict[str, str]:
    """No secret but the token, and that only as git's own header."""
    env = {
        "PATH": os.environ["PATH"],
        "HOME": home,
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONUTF8": "1",
        # Importing tests would otherwise leave __pycache__ that looks like a change.
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if "SYSTEMROOT" in os.environ:  # Windows cannot start a process without it
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    return env


def clone(
    clone_url: str, branch: str | None, dest: Path, token: str | None, timeout_seconds: float
) -> str | None:
    """None when the branch (or the default branch) is cloned into dest, else
    why not. Raises subprocess.TimeoutExpired, which callers turn into a row."""
    pick = ["--branch", branch] if branch else []
    result = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", *pick, clone_url, str(dest)],
        env=_env(str(dest.parent), token),
        timeout=timeout_seconds,
        **_TEXT,
    )
    return None if result.returncode == 0 else "clone failed: " + result.stderr[-1000:]


def _listed(script: str, work: Path, timeout_seconds: float) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=work,
        env=_env(str(work.parent), None),
        timeout=timeout_seconds,
        **_TEXT,
    )
    if result.returncode != 0:
        raise DiscoveryFailed(result.stderr[-1000:])
    return set(result.stdout.split())


def test_ids(work: Path, timeout_seconds: float = 120) -> set[str]:
    return _listed(LIST_TESTS, work, timeout_seconds)


test_ids.__test__ = False  # a helper, not a test, for pytest's collector


def grade_dir(
    work: Path,
    grade_source: str,
    base_ids: set[str] | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Grade a checkout. With base_ids, every one of main's test ids must
    still be there. Then its own tests must pass, then the grade test. Never
    raises for a bad checkout or a bad grade; the answer is the boolean."""
    env = _env(str(work.parent), None)
    try:
        if base_ids is not None:
            lost = base_ids - test_ids(work, timeout_seconds)
            if lost:
                return False, "tests removed: " + ", ".join(sorted(lost))
        own = subprocess.run(REPO_TESTS, cwd=work, env=env, timeout=timeout_seconds, **_TEXT)
        if own.returncode not in (0, NO_TESTS_RAN):
            return False, "own tests failed: " + (own.stdout + own.stderr)[-3000:]
        if base_ids is not None:
            # A test that is skipped or expected to fail still exists and "passes".
            skipped = base_ids & _listed(LIST_SKIPPED, work, timeout_seconds)
            if skipped:
                return False, "tests skipped: " + ", ".join(sorted(skipped))
        (work / f"{GRADE_MODULE}.py").write_text(grade_source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", GRADE_MODULE],
            cwd=work,
            env=env,
            timeout=timeout_seconds,
            **_TEXT,
        )
    except DiscoveryFailed as crash:
        return False, f"test discovery failed: {crash}"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_seconds:.0f} s"
    return result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def grade_branch(
    clone_url: str,
    branch: str,
    grade_source: str,
    token: str | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Clone the branch and the default branch, and grade the branch against
    the default branch's test ids."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        work, base = Path(home) / "work", Path(home) / "base"
        try:
            error = clone(clone_url, branch, work, token, timeout_seconds) or clone(
                clone_url, None, base, token, timeout_seconds
            )
            if error:
                return False, error
            base_ids = test_ids(base, timeout_seconds)
        except DiscoveryFailed as crash:
            return False, f"test discovery failed on the default branch: {crash}"
        except subprocess.TimeoutExpired:
            return False, f"clone timed out after {timeout_seconds:.0f} s"
        return grade_dir(work, grade_source, base_ids, timeout_seconds)


def close_pull_and_branch(github, repo: str, branch: str) -> None:
    owner = repo.split("/")[0]
    pulls = github.get(
        f"/repos/{repo}/pulls", params={"head": f"{owner}:{branch}", "state": "open"}
    )
    pulls.raise_for_status()
    for pull in pulls.json():
        github.patch(
            f"/repos/{repo}/pulls/{pull['number']}", json={"state": "closed"}
        ).raise_for_status()
    deleted = github.delete(f"/repos/{repo}/git/refs/heads/{branch}")
    # 404 and 422 mean there was no such branch, as after a chore that timed
    # out before it pushed. Anything else leaves a branch behind on the fixture.
    if deleted.status_code not in (404, 422):
        deleted.raise_for_status()


DELEGATE_SCRIPT = Path(r"C:\Projects\Cheap AI\scripts\delegate.ps1")


def _kill_tree(process: subprocess.Popen) -> None:  # pragma: no cover - Windows branch
    """Kill the process and everything it started. On Windows a timeout that
    killed only pwsh would leave OpenCode and its children holding the pipe."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _run_tree(
    command: list[str], out_path: Path, timeout_seconds: float, env: dict[str, str] | None
) -> subprocess.CompletedProcess:
    """Run command with stdout and stderr in a file, not a pipe, in its own
    process group. On timeout the whole tree is killed, then TimeoutExpired is
    raised. The CompletedProcess carries the combined output as stderr."""
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with out_path.open("wb") as out:
        process = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, env=env, **group)
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            raise
    output = out_path.read_text(encoding="utf-8", errors="replace")
    return subprocess.CompletedProcess(command, process.returncode, "", output)


def _delegate_env(environ: dict[str, str]) -> dict[str, str]:
    """The desktop's environment, whole, minus the runner's own secrets. The
    model behind delegate.ps1 has a shell and must not find Mercury's bearer
    token or the GitHub token there. Windows names are case insensitive."""
    return {k: v for k, v in environ.items() if not k.upper().startswith("MERCURY_")}


def _call_delegate_script(
    work: Path, instruction: str, model: str, timeout_seconds: float
) -> subprocess.CompletedProcess:
    """delegate.ps1 needs the desktop's own environment (OpenCode, Ollama), so
    it gets it whole, less the MERCURY_ variables. It edits the clean checkout
    and does not commit."""
    command = [
        "pwsh",
        "-NoProfile",
        "-File",
        str(DELEGATE_SCRIPT),
        "-Dir",
        str(work),
        "-Task",
        instruction,
        "-Model",
        model,
    ]
    return _run_tree(
        command, work.parent / "delegate.log", timeout_seconds, _delegate_env(dict(os.environ))
    )


def run_delegate(
    task: EvalTask,
    model: str,
    clone_url: str,
    *,
    delegate: Callable[[Path, str, str, float], subprocess.CompletedProcess] | None = None,
    timeout_seconds: float = 1800,
    clock: Callable[[], float] = time.monotonic,
    instruction: str | None = None,
) -> EvalRow:
    """instruction replaces the task's own, as the rescue pass does to add a hint."""
    column = f"delegate:{model}"
    delegate = delegate or _call_delegate_script

    def row(
        status: str,
        graded: bool,
        seconds: float | None,
        detail: str,
        diff: str = "",
        tail: str = "",
    ) -> EvalRow:
        return EvalRow(
            task.id, column, column, None, status, graded, None, seconds, 0.0, detail[-2000:],
            diff=diff[:EVIDENCE_DIFF_CHARS], test_tail=tail[-EVIDENCE_TAIL_CHARS:],
        )  # fmt: skip

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
        work = Path(home) / "work"
        seconds = None
        try:
            error = clone(clone_url, "main", work, None, 120)
            if error:
                return row("refused", False, None, error)
            try:
                base_ids = test_ids(work)
            except DiscoveryFailed as crash:
                return row("error", False, None, f"test discovery failed on main: {crash}")
            start = clock()
            try:
                result = delegate(work, instruction or task.instruction, model, timeout_seconds)
            except subprocess.TimeoutExpired:
                return row("timeout", False, clock() - start, "delegate.ps1 timed out")
            except FileNotFoundError as missing:
                return row("error", False, clock() - start, f"could not start pwsh: {missing}")
            seconds = clock() - start
            if result.returncode != 0:
                stderr = (result.stderr or "")[-2000:]
                return row("failed", False, seconds, stderr, tail=stderr)
            changed = subprocess.run(
                ["git", "status", "--porcelain"], cwd=work, env=_env(home, None), **_TEXT
            )
            if not [line for line in changed.stdout.splitlines() if "__pycache__" not in line]:
                return row("failed", False, seconds, "no change")
            diff = _staged_diff(work, home)
            # Mercury opens a pull request only when the repo's own tests pass.
            tests = subprocess.run(REPO_TESTS, cwd=work, env=_env(home, None), timeout=600, **_TEXT)
            if tests.returncode not in (0, NO_TESTS_RAN):
                output = tests.stdout + tests.stderr
                return row("failed", False, seconds, output, diff, output)
            graded, detail = grade_dir(work, task.grade, base_ids)
            return row("succeeded", graded, seconds, detail, diff)
        except subprocess.TimeoutExpired:
            return row("timeout", False, seconds, "a clone, test listing or test run timed out")


def _staged_diff(work: Path, home: str) -> str:
    """The delegate's change as a diff, new files included, before any
    grade file is written into the checkout."""
    env = _env(home, None)
    subprocess.run(
        ["git", "add", "-A", "--", ".", ":(exclude)**/__pycache__/**"], cwd=work, env=env, **_TEXT
    )
    return subprocess.run(["git", "diff", "--cached"], cwd=work, env=env, **_TEXT).stdout


def run_one(
    api,
    github,
    task: EvalTask,
    provider: str,
    clone_base: str,
    token: str | None,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> EvalRow:
    created = api.post(
        "/runs",
        json={
            "type": "repo_chore",
            "inputs": {"task": task.instruction, "repo": task.repo},
            "provider": provider,
            "source": "eval",
        },
    )
    if created.status_code != 201:
        return EvalRow(
            task.id, provider, None, None, "refused", False, 0, None, 0.0, created.text[:300]
        )
    run = created.json()
    if run["status"] == "awaiting_approval":
        raise EvalAborted(
            f"run {run['id']} is waiting for Approve: {task.repo} is not auto_approve in the "
            "live mercury.yaml. Decline it on Telegram, set auto_approve, and run again."
        )
    return follow(
        api, github, task, provider, run["id"], clone_base, token,
        timeout_seconds=timeout_seconds, poll_seconds=poll_seconds, sleep=sleep, clock=clock,
    )  # fmt: skip


def follow(
    api,
    github,
    task: EvalTask,
    column: str,
    run_id: str,
    clone_base: str,
    token: str | None,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> EvalRow:
    """Wait for a queued chore to finish, grade it on its own branch, close
    its pull request and branch, and return its row. The rescue pass follows
    an advised rerun the same way."""
    # The clock for the run itself starts once it leaves pending, so time spent
    # queued behind other runs does not count against it. A run that never
    # leaves pending still ends, after three timeouts of waiting.
    queue_deadline = clock() + 3 * timeout_seconds
    deadline = None
    while True:
        response = api.get(f"/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] not in OPEN:
            break
        now = clock()
        if deadline is None and run["status"] != "pending":
            deadline = now + timeout_seconds
        if now >= (deadline if deadline is not None else queue_deadline):
            run = {**run, "status": "timeout"}
            break
        sleep(poll_seconds)

    if run["status"] == "refused":
        # The worker closes a run it will not execute as refused. Past the daily
        # run limit it refuses every model run, so going on would record fails
        # that measure the limit and not the model.
        raise EvalAborted(
            f"run {run_id} was refused by the worker, most likely because the daily run limit "
            "MAX_RUNS_PER_DAY is reached. Raise the MAX_RUNS_PER_DAY Actions variable in "
            "mercury-config and re-run its Deploy, or continue tomorrow. Its events give the "
            "exact reason."
        )
    graded, detail = False, ""
    branch = f"agent/{run_id}"
    try:
        if run["status"] == "timeout":
            # Stop the worker too, so it does not push a branch after the row is
            # written. A failed cancel still cleans up, then fails the row.
            api.post(f"/runs/{run_id}/cancel").raise_for_status()
        if run["status"] == "succeeded":
            graded, detail = grade_branch(
                f"{clone_base}/{task.repo}.git", branch, task.grade, token
            )
        else:
            detail = run.get("escalation_reason") or ""
    finally:
        if run["status"] in ("succeeded", "timeout"):
            # A timed out chore may have pushed its branch before the cancel landed.
            close_pull_and_branch(github, task.repo, branch)
    tokens = run.get("tokens") or 0
    answered = run.get("provider")
    rate = PROVIDERS[answered].usd_per_million_tokens if answered in PROVIDERS else 0.0
    diff, test_tail = _evidence(api, run_id)
    return EvalRow(
        task.id,
        column,
        answered,
        run_id,
        run["status"],
        graded,
        tokens,
        run.get("duration_seconds"),
        tokens * rate / 1_000_000,
        detail[-2000:],
        unusable=run.get("unusable_replies"),
        diff=diff,
        test_tail=test_tail,
    )


def _evidence(api, run_id: str) -> tuple[str, str]:
    """The done step's diff and test output tail, for the rescue brief. A
    run whose events cannot be read keeps its row, with no evidence."""
    response = api.get(f"/runs/{run_id}/events")
    if response.status_code != 200:
        return "", ""
    done = [event.get("output") or {} for event in response.json() if event.get("kind") == "done"]
    output = done[-1] if done else {}
    return (
        (output.get("diff") or "")[:EVIDENCE_DIFF_CHARS],
        (output.get("test_output") or "")[-EVIDENCE_TAIL_CHARS:],
    )


def contained(run: Callable[[], EvalRow], task_id: str, column: str, token: str | None) -> EvalRow:
    """One row's failure is that row's result, not the batch's. The text is
    scrubbed of the token, in the form git or an HTTP client might echo it."""
    try:
        return run()
    except EvalAborted:
        raise
    except Exception as error:
        text = f"{type(error).__name__}: {error}"
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            text = text.replace(token, "[token]").replace(basic, "[token]")
        return EvalRow(task_id, column, None, None, "error", False, None, None, 0.0, text[-2000:])


def summarise(rows: list[EvalRow]) -> str:
    lines = [
        "| Column | Passed the hidden test | Opened a PR | Median tokens | Median seconds "
        "| Cost USD | Fell back | Weakened tests | Unusable replies |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for column in sorted({row.provider for row in rows}):
        mine = [row for row in rows if row.provider == column]
        tokens = [row.tokens for row in mine if row.tokens is not None]
        seconds = [row.seconds for row in mine if row.seconds is not None]
        lines.append(
            f"| {column} | {sum(r.graded for r in mine)} of {len(mine)} "
            f"| {sum(r.status == 'succeeded' for r in mine)} of {len(mine)} "
            f"| {f'{statistics.median(tokens):.0f}' if tokens else 'n/a'} "
            f"| {f'{statistics.median(seconds):.0f}' if seconds else 'n/a'} "
            f"| {sum(r.usd for r in mine):.4f} "
            f"| {sum(r.answered_by not in (None, r.provider) for r in mine)} "
            # Chores Mercury's test guard escalated (app/test_guard.py).
            f"| {sum(r.detail == 'weakened tests' for r in mine)} "
            f"| {sum(r.unusable or 0 for r in mine)} |"
        )
    lines += [
        "",
        "| Task | Column | Answered by | Status | Graded |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in sorted(rows, key=lambda r: (r.task, r.provider)):
        verdict = "pass" if row.graded else "fail"
        lines.append(
            f"| {row.task} | {row.provider} | {row.answered_by or 'n/a'} "
            f"| {row.status} | {verdict} |"
        )
    return "\n".join(lines)


def write_rows(rows: list[EvalRow], path: Path) -> Path:
    """Write the rows to path (.json) and their summary beside it (.md),
    and return the summary's path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in rows], indent=2) + "\n", encoding="utf-8")
    report = path.with_suffix(".md")
    report.write_text(summarise(rows) + "\n", encoding="utf-8")
    return report


def write_results(rows: list[EvalRow], out: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    return write_rows(rows, out / f"{stamp}.json")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the live deploy
    parser = argparse.ArgumentParser(description="Run the chore evals.")
    parser.add_argument(
        "--columns", default="gemini,ollama", help="providers, and delegate:<model> (Task 5)"
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--only", default="", help="comma separated task ids")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)

    columns = [c for c in args.columns.split(",") if c]
    unknown = [c for c in columns if c not in PROVIDERS and not c.startswith("delegate:")]
    if unknown:
        parser.error(f"unknown column {unknown[0]}; providers: {', '.join(PROVIDERS)}")
    tasks = load_tasks(HERE / "chores")
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t.id in wanted]

    api = github = token = None
    if any(not c.startswith("delegate:") for c in columns):
        token = os.environ["MERCURY_GITHUB_TOKEN"]
        api = httpx2.Client(
            base_url=os.environ["MERCURY_URL"].rstrip("/"),
            headers={"Authorization": f"Bearer {os.environ['MERCURY_BEARER_TOKEN']}"},
            timeout=60,
        )
        github = httpx2.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=30,
        )
    rows: list[EvalRow] = []
    try:
        for repeat in range(1, args.repeats + 1):
            for task in tasks:
                for column in columns:
                    row = contained(
                        partial(_run_column, column, task, api, github, token, args.timeout),
                        task.id,
                        column,
                        token,
                    )
                    row.repeat = repeat
                    rows.append(row)
                    print(
                        f"{task.id} {column}->{row.answered_by} {row.status} "
                        f"graded={'pass' if row.graded else 'fail'} tokens={row.tokens}",
                        flush=True,
                    )
    except EvalAborted as stop:
        print(stop, file=sys.stderr)
    finally:
        if rows:
            report = write_results(rows, HERE / "results")
            print(report.read_text(encoding="utf-8"))
            print(f"written to {report}")
    return 0 if rows else 1


def _run_column(column, task, api, github, token, timeout) -> EvalRow:  # pragma: no cover
    if column.startswith("delegate:"):
        return run_delegate(task, column.split(":", 1)[1], FIXTURE_URL, timeout_seconds=timeout)
    return run_one(
        api,
        github,
        task,
        column,
        "https://github.com",
        token,
        timeout_seconds=timeout,
        poll_seconds=5.0,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
