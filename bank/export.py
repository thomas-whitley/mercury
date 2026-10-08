"""Builds the bank's training examples (decisions 38 and 59 of
docs/build-brief-evals.md). One example per training chore, in two turns,
the read request and the edit, each a system, user and assistant message:

- self: a run that passed unaided, its first and last recorded calls;
- rescued: a rerun that passed after one hint, with the advice block taken
  out of its prompts, so neither the hint nor the earlier diff remains;
- reference: the commit, built with the prompt functions a chore serves
  (app/chore_prompts.py) from its base, replying with its source files.

No validation chore, eval chore or fixture chore is exported.

  python -m bank.export
reads every bank/results/*.json and the compose Mercury's GET
/runs/{id}/calls, and writes bank/data/examples.jsonl and manifest.json.
"""

import ast
import json
import os
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx2

from app.advice_text import advice_block
from app.chore_prompts import (
    MAX_FILES_READ,
    SYSTEM,
    edit_prompt,
    read_prompt,
    shown_files,
    tree_listing,
)
from bank.chores import FIXTURE, HERE, TRAINING, BankChore, Library, load_bank, load_libraries
from bank.grade import checkout, ensure_mirror
from bank.mine import kind
from bank.run import RESULTS
from evals.runner import RESCUABLE, load_rows

DATA = HERE / "data"
NOT_EXPORTED = "validation, not exported"


def record(chore_id, origin, turn, system, prompt, reply) -> dict:
    return {
        "chore": chore_id,
        "origin": origin,
        "turn": turn,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": reply},
        ],
    }


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def from_calls(chore_id: str, origin: str, calls: list[dict], strip: str = "") -> list[dict] | None:
    """The read turn is a run's first call and the edit turn its last, the
    one that went green. None when either reply is not the shape asked for,
    or strip is given and a prompt lacks it."""
    if len(calls) < 2:
        return None
    first, last = calls[0], calls[-1]
    read, edit = _json(first["reply"]), _json(last["reply"])
    if not isinstance(read, dict) or "read" not in read:
        return None
    if not isinstance(edit, dict) or not isinstance(edit.get("files"), dict):
        return None
    records = []
    for turn, call in (("read", first), ("edit", last)):
        prompt = call["prompt"]
        if strip:
            if strip not in prompt:
                return None
            prompt = prompt.replace(strip, "")
        records.append(record(chore_id, origin, turn, call["system"], prompt, call["reply"]))
    return records


def rescued(chore_id: str, hint: str, advice: str, calls: list[dict]) -> list[dict] | None:
    """Trained without the hint (decision 38): the advice block comes out of
    both prompts, and an example still carrying the hint anywhere is dropped."""
    records = from_calls(chore_id, "rescued", calls, strip=advice)
    if records is None:
        return None
    if any(hint in message["content"] for r in records for message in r["messages"]):
        return None
    return records


def _module_paths(module: str, library: Library) -> list[str]:
    root = f"{library.pythonpath}/" if library.pythonpath else ""
    stem = root + module.replace(".", "/")
    return [f"{stem}.py", f"{stem}/__init__.py"]


def reference_reads(
    tree: list[str], sources: list[str], tests: dict[str, str], library: Library
) -> list[str]:
    """The changed source files that exist on the base, then the source
    modules the commit's tests import, at most MAX_FILES_READ."""
    present = set(tree)
    reads = [path for path in sources if path in present]
    for text in tests.values():
        try:
            nodes = list(ast.walk(ast.parse(text)))
        except SyntaxError:
            continue
        for node in nodes:
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                modules = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for module in modules:
                for path in _module_paths(module, library):
                    if path in present and kind(path) == "source" and path not in reads:
                        reads.append(path)
    return reads[:MAX_FILES_READ]


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(tree), *args], check=True, capture_output=True, text=True,
        encoding="utf-8",
    ).stdout  # fmt: skip


def reference(chore: BankChore, library: Library, mirror: Path, workdir: Path) -> list[dict]:
    """The commit as an example: the read turn names what it changed and what
    its tests import, and the edit turn replies with its full source files."""
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir, ignore_cleanup_errors=True) as home:
        base = checkout(mirror, chore.base, Path(home) / "base")
        ref = checkout(mirror, chore.reference, Path(home) / "reference")
        tree = _git(base, "ls-files").splitlines()
        changed = _git(ref, "diff", "--name-only", chore.base, chore.reference).splitlines()
        sources = [path for path in changed if kind(path) == "source" and (ref / path).is_file()]
        tests = {path: (ref / path).read_text() for path in chore.test_files}
        reads = reference_reads(tree, sources, tests, library)
        listing = tree_listing(tree)
        files = {path: (ref / path).read_text() for path in sources}
        summary = _git(ref, "log", "-1", "--format=%s").strip()
        return [
            record(
                chore.id, "reference", "read", SYSTEM,
                read_prompt(chore.instruction, "", listing), json.dumps({"read": reads}),
            ),
            record(
                chore.id, "reference", "edit", SYSTEM,
                edit_prompt(chore.instruction, "", listing, shown_files(base, reads)),
                json.dumps({"files": files, "summary": summary}),
            ),
        ]  # fmt: skip


class ExportError(RuntimeError):
    """A graded run's record could not be read. The export stops rather than
    fall back to a reference example and overwrite examples.jsonl, since a
    wrong MERCURY_URL or a lost compose volume would turn every self and
    rescued example into one."""


def _get(api, path: str):
    response = api.get(path)
    if response.status_code != 200:
        raise ExportError(
            f"GET {path} answered {response.status_code}; is MERCURY_URL the compose Mercury "
            "that ran these rows?"
        )
    return response.json()


def _calls(api, run_id: str) -> list[dict]:
    """A graded run's calls; one with none recorded stops the export."""
    calls = _get(api, f"/runs/{run_id}/calls")
    if not calls:
        raise ExportError(f"run {run_id} passed but has no model calls recorded")
    return calls


def _done(api, run_id: str) -> dict:
    """The done step's output, which an advised rerun's advice is built from."""
    events = _get(api, f"/runs/{run_id}/history")
    done = [e.get("output") or {} for e in events if e.get("kind") == "done"]
    return done[-1] if done else {}


def _from_runs(chore: BankChore, mine: list, api) -> list[dict] | None:
    for row in mine:
        if row.graded:
            found = from_calls(chore.id, "self", _calls(api, row.run_id))
            if found:
                return found
    for row in mine:
        if row.rescue and row.rescue.graded and row.rescue_hint:
            advice = advice_block(row.rescue_hint, _done(api, row.run_id))
            found = rescued(chore.id, row.rescue_hint, advice, _calls(api, row.rescue.run_id))
            if found:
                return found
    return None


def export(rows, chores, libraries, api, mirrors, workdir) -> tuple[list[dict], Counter]:
    """One example per training chore that has a row with the model's answer,
    and the count of each origin."""
    by_chore = defaultdict(list)
    for row in rows:
        if row.status in RESCUABLE:
            by_chore[row.task].append(row)
    records, counts = [], Counter()
    for chore in sorted(chores, key=lambda c: c.id):
        mine = by_chore[chore.id]
        if chore.split != TRAINING or chore.repo == FIXTURE:
            if mine:
                counts[NOT_EXPORTED] += 1
            continue
        if not mine:
            counts["not run"] += 1
            continue
        found = _from_runs(chore, mine, api) or reference(
            chore, libraries[chore.library], mirrors[chore.library], workdir
        )
        counts[found[0]["origin"]] += 1
        records.extend(found)
    return records, counts


def main() -> int:  # pragma: no cover - reads the compose Mercury
    rows = [row for path in sorted(RESULTS.glob("*.json")) for row in load_rows(path)]
    chores = load_bank()
    libraries = load_libraries()
    token = os.environ.get("MERCURY_GITHUB_TOKEN")
    mirrors = {name: ensure_mirror(lib, token=token) for name, lib in libraries.items()}
    api = httpx2.Client(
        base_url=os.environ["MERCURY_URL"].rstrip("/"),
        headers={"Authorization": f"Bearer {os.environ['MERCURY_BEARER_TOKEN']}"},
        timeout=60,
    )
    records, counts = export(rows, chores, libraries, api, mirrors, DATA / "tmp")
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "examples.jsonl").open("w", encoding="utf-8") as out:
        for item in records:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    manifest = {"written_at": datetime.now(UTC).isoformat(), "counts": dict(counts)}
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(records)} records; {dict(counts)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
