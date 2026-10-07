"""Save Mercury's report to reports/YYYY-MM-DD.md, with the newest local eval
summary from evals/results/ in place of the server's pointer to it.

uv run python scripts/mercury_report.py [--since 2026-10-01]
reads MERCURY_URL and MERCURY_BEARER_TOKEN. reports/ is gitignored.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POINTER = "The latest eval report is the newest file in evals/results/ in the public repo."


def with_latest_eval(report: str, results: Path) -> str:
    """Swap the eval pointer for the newest local summary, when there is one."""
    newest = max(results.glob("*.md"), default=None) if results.is_dir() else None
    if newest is None or POINTER not in report:
        return report
    summary = newest.read_text(encoding="utf-8").strip()
    return report.replace(POINTER, f"From evals/results/{newest.name}:\n\n{summary}")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - calls the live api
    import httpx2

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="an ISO date; the api's default is 7 days ago")
    args = parser.parse_args(argv)
    url, token = os.environ.get("MERCURY_URL"), os.environ.get("MERCURY_BEARER_TOKEN")
    if not url or not token:
        print("set MERCURY_URL and MERCURY_BEARER_TOKEN", file=sys.stderr)
        return 2
    response = httpx2.get(
        f"{url.rstrip('/')}/report",
        params={"since": args.since} if args.since else None,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    response.raise_for_status()
    out = ROOT / "reports" / f"{date.today():%Y-%m-%d}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(with_latest_eval(response.text, ROOT / "evals" / "results"), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
