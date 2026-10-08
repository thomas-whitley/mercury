"""Turns a library's commits into bank chores (decisions 30 to 33, 56 and 60
of docs/build-brief-evals.md). Claude does not invent chores: each is a real
commit, its parent the base, its tests the grade, the commit the reference.

  python -m bank.mine gate <library> [--limit 50]
fetches the fork's mirror, gates each candidate commit from 2025 on, oldest
first, until <limit> pass, and writes bank/work/<library>/gated.json, a brief
for the Claude session that writes the instructions (instructions.md) and a
blank instructions file (instructions.yaml).

  python -m bank.mine write <library>
checks every instruction, then writes one chore file per non blank one.
"""

import argparse
import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from bank.chores import (
    CHORES,
    HERE,
    BankChore,
    Library,
    chore_id,
    load_bank,
    load_libraries,
    split_of,
    write_chore,
)
from bank.grade import ensure_mirror, gate

SINCE = "2025-01-01"
MAX_SOURCE_FILES = 3
# The local rung writes about 3,500 tokens in its 120 s (decision 56).
MAX_REPLY_CHARS = 12_000
MAX_INSTRUCTION_CHARS = 1500
WORK = HERE / "work"
_TEST_DIRS = {"test", "tests", "testing"}
_DOC_SUFFIXES = {".md", ".rst", ".txt"}
_DOC_NAMES = ("CHANGELOG", "CHANGES", "NEWS", "HISTORY", "AUTHORS")
FENCE = "````"

RULES = """# Instructions to write

One paragraph per chore, at most 1,500 characters, in the instructions file
under the chore's id. Say what to change in which source files, and name every
module, function, class, method, parameter and error message the tests rely on,
exactly as the commit spells them. Write it as the owner asking for the change.
Ask for the source change only: never name or describe a test, a test file or
what is tested, and do not ask for tests. Do not paste the diff. Leave a chore
blank to drop it.
"""


def kind(path: str) -> str:
    p = PurePosixPath(path)
    if p.suffix == ".py":
        if (
            p.name == "conftest.py"
            or p.name.startswith("test_")
            or p.name.endswith("_test.py")
            or any(part in _TEST_DIRS for part in p.parts[:-1])
        ):
            return "test"
        return "source"
    if (
        p.suffix in _DOC_SUFFIXES
        or (len(p.parts) > 1 and p.parts[0] in {"doc", "docs"})
        or p.name.upper().startswith(_DOC_NAMES)
    ):
        return "doc"
    return "other"


@dataclass(frozen=True)
class Candidate:
    sha: str
    parent: str
    subject: str
    source_files: tuple[str, ...]
    test_files: tuple[str, ...]


def _git(mirror: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(mirror), *args],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout  # fmt: skip


def _size(mirror: Path, sha: str, path: str) -> int | None:
    try:
        return int(_git(mirror, "cat-file", "-s", f"{sha}:{path}"))
    except subprocess.CalledProcessError:
        return None


def candidates(mirror: Path, since: str = SINCE) -> tuple[list[Candidate], Counter]:
    """Commits on the default branch from since on, oldest first, that change
    1 to 3 source files and at least one test, nothing else but docs, and fit
    one reply. The rest are counted by reason."""
    log = _git(
        mirror, "log", "--reverse", "--no-merges", f"--since={since}",
        "--format=%x00%H %P%x09%s", "--name-only", "HEAD",
    )  # fmt: skip
    found, dropped = [], Counter()
    for record in log.split("\x00")[1:]:
        head, _, names = record.partition("\n")
        shas, _, subject = head.partition("\t")
        sha, *parents = shas.split()
        files = [line for line in names.splitlines() if line.strip()]
        kinds = {path: kind(path) for path in files}
        sources = tuple(p for p in files if kinds[p] == "source")
        tests = tuple(p for p in files if kinds[p] == "test")
        if not parents:
            dropped["no parent"] += 1
        elif not sources or not tests:
            dropped["not source and tests"] += 1
        elif "other" in kinds.values():
            dropped["other files"] += 1
        elif len(sources) > MAX_SOURCE_FILES:
            dropped["too many source files"] += 1
        else:
            after = [_size(mirror, sha, p) for p in sources]
            before = [_size(mirror, parents[0], p) or 0 for p in sources]
            if None in after:
                dropped["deletes a source file"] += 1
            elif sum(after) > MAX_REPLY_CHARS or max(before) > MAX_REPLY_CHARS:
                dropped["too long for one reply"] += 1
            else:
                kept = tuple(p for p in tests if _size(mirror, sha, p) is not None)
                found.append(Candidate(sha, parents[0], subject, sources, kept))
    return found, dropped


def gate_library(
    library: Library, mirror: Path, limit: int, done: set[str], gate=gate, since: str = SINCE
) -> tuple[list[dict], Counter]:
    """Gate candidates, oldest first, until limit pass. The dropped counter
    holds the candidates' own reasons and the gate's."""
    found, dropped = candidates(mirror, since)
    gated = []
    for candidate in found:
        if len(gated) >= limit:
            break
        key = chore_id(library.name, candidate.sha)
        if key in done:
            dropped["already mined"] += 1
            continue
        result = gate(mirror, library, candidate.parent, candidate.sha, candidate.test_files)
        if not result.ok:
            dropped[result.reason] += 1
            continue
        gated.append({
            "id": key, "sha": candidate.sha, "parent": candidate.parent,
            "subject": candidate.subject, "grade": list(result.grade),
            "test_files": list(candidate.test_files),
            "source_files": list(candidate.source_files),
        })  # fmt: skip
    return gated, dropped


def brief(library: Library, mirror: Path, gated: list[dict]) -> tuple[str, dict[str, str]]:
    """The brief the Claude session writes instructions from, and a blank
    instruction per gated chore. The writer sees the tests; the model never
    does, and the instruction must not carry them over."""
    lines = [RULES]
    for item in gated:
        lines += [
            f"## {item['id']}",
            "",
            FENCE,
            _git(mirror, "log", "-1", "--format=%B", item["sha"]).strip(),
            FENCE,
            "",
            "Source diff:",
            "",
            FENCE + "diff",
            _git(mirror, "diff", item["parent"], item["sha"], "--", *item["source_files"]),
            FENCE,
            "",
            "Test diff (for you only; the instruction must not name a test):",
            "",
            FENCE + "diff",
            _git(mirror, "diff", item["parent"], item["sha"], "--", *item["test_files"]),
            FENCE,
            "",
            "Grade: " + ", ".join(item["grade"]),
            "",
        ]
    return "\n".join(lines), {item["id"]: "" for item in gated}


def leaks(instruction: str, grade: tuple[str, ...], test_files: tuple[str, ...]) -> list[str]:
    """Test names, test class names and test file names the instruction
    contains, which would tell the model what is graded."""
    names = {part.split("[")[0] for test in grade for part in test.split("::")[1:]}
    names |= {PurePosixPath(f).name for f in test_files}
    names |= {PurePosixPath(f).stem for f in test_files}
    return sorted(name for name in names if name in instruction)


def write_instructions(
    library: Library, gated: list[dict], instructions: dict[str, str], directory: Path = CHORES
) -> list[Path]:
    """Check every instruction, then write a chore per non blank one. Nothing
    is written when any instruction is refused."""
    by_id = {item["id"]: item for item in gated}
    unknown = sorted(set(instructions) - set(by_id))
    if unknown:
        raise ValueError(f"no gated chore is called {unknown[0]}")
    chores = []
    for key, text in instructions.items():
        text = (text or "").strip()
        if not text:
            continue
        item = by_id[key]
        if len(text) > MAX_INSTRUCTION_CHARS:
            raise ValueError(f"{key}: the instruction is over {MAX_INSTRUCTION_CHARS:,} characters")
        named = leaks(text, tuple(item["grade"]), tuple(item["test_files"]))
        if named:
            raise ValueError(f"{key}: the instruction names {', '.join(named)}")
        chores.append(BankChore(
            key, library.name, library.repo, text, item["parent"], item["sha"],
            tuple(item["grade"]), tuple(item["test_files"]), split_of(key),
        ))  # fmt: skip
    return [write_chore(chore, directory) for chore in chores]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the forks
    parser = argparse.ArgumentParser(description="Mine a library's commits into bank chores.")
    commands = parser.add_subparsers(dest="command", required=True)
    gate_cmd = commands.add_parser("gate", help="gate candidates and write the brief")
    gate_cmd.add_argument("library")
    gate_cmd.add_argument("--limit", type=int, default=50)
    gate_cmd.add_argument("--since", default=SINCE)
    write_cmd = commands.add_parser("write", help="write a chore per instruction")
    write_cmd.add_argument("library")
    args = parser.parse_args(argv)

    library = load_libraries()[args.library]
    work = WORK / library.name
    work.mkdir(parents=True, exist_ok=True)
    gated_path = work / "gated.json"
    mirror = ensure_mirror(library, token=os.environ.get("MERCURY_GITHUB_TOKEN"))
    if args.command == "gate":
        earlier = json.loads(gated_path.read_text()) if gated_path.exists() else []
        done = {chore.id for chore in load_bank()} | {item["id"] for item in earlier}
        gated, dropped = gate_library(library, mirror, args.limit, done, since=args.since)
        gated = earlier + gated
        gated_path.write_text(json.dumps(gated, indent=2) + "\n", encoding="utf-8")
        text, blanks = brief(library, mirror, gated)
        (work / "instructions.md").write_text(text, encoding="utf-8")
        instructions = work / "instructions.yaml"
        if instructions.exists():
            written = yaml.safe_load(instructions.read_text(encoding="utf-8")) or {}
            blanks = blanks | written
        instructions.write_text(
            yaml.safe_dump(blanks, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        print(f"{len(gated)} gated; dropped {dict(dropped)}; brief in {work / 'instructions.md'}")
        return 0
    gated = json.loads(gated_path.read_text())
    instructions = yaml.safe_load((work / "instructions.yaml").read_text(encoding="utf-8")) or {}
    written = write_instructions(library, gated, instructions)
    print(f"{len(written)} chores written to {CHORES / library.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
