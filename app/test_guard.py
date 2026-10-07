"""Whether a chore's diff weakens the repo's tests, per decision 12 of
docs/build-brief-evals.md. It reads the staged diff, so it works for any
language a repo's test command runs, and it never runs the repo's code.

A test is named by its function or its it()/test() title. One that is
removed and not added back anywhere in the diff is lost, so a test moved
within a file is fine and a test renamed is not. A skip or xfail marker
added to a test file counts too, and so does a deleted test file.
"""

import re

_TEST_FILE = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*\.(test|spec)\.[cm]?[jt]sx?)$|(^|/)(tests|__tests__)/"
)
_PY_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(")
_JS_TEST = re.compile(r"""^\s*(?:it|test)\s*\(\s*(['"`])(.+?)\1""")
_SKIP = re.compile(
    r"@unittest\.skip|@pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(|unittest\.expectedFailure"
    r"|\b(it|test|describe)\.(skip|todo)\(|\bx(it|describe|test)\("
)


def _test_name(line: str) -> str | None:
    if match := _PY_TEST.match(line):
        return match.group(1)
    if match := _JS_TEST.match(line):
        return match.group(2)
    return None


def weakened_tests(diff: str) -> list[str]:
    """One line per way the diff weakens the tests, empty when it keeps them all."""
    problems: list[str] = []
    removed: dict[str, set[str]] = {}
    added: set[str] = set()
    path: str | None = None
    deleted = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path, deleted = line.split(" b/", 1)[-1], False
            continue
        if line.startswith("deleted file mode"):
            deleted = True
            continue
        if path is None or line.startswith(("--- ", "+++ ", "@@")):
            if line.startswith("+++ ") and deleted and _TEST_FILE.search(path or ""):
                problems.append(f"{path}: deleted")
            continue
        if not _TEST_FILE.search(path):
            continue
        body = line[1:]
        if line.startswith("-"):
            if name := _test_name(body):
                removed.setdefault(path, set()).add(name)
        elif line.startswith("+"):
            if name := _test_name(body):
                added.add(name)
            if _SKIP.search(body):
                problems.append(f"{path}: added a skip ({body.strip()})")
    for file, names in removed.items():
        problems += [f"{file}: removed {name}" for name in sorted(names - added)]
    return problems
