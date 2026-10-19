"""The report a Claude session or the owner reads, per decision 9 of
docs/build-brief-evals.md: escalations first, then the chores Mercury
started itself, then where the eval results are, then spend against the
caps. Markdown, served behind the bearer token at GET /report and by the MCP
report tool, and saved locally by scripts/mercury_report.py.

Diffs and test output are the repo's own code, which the owner already sees
in its pull requests; they reach this page and never a log line.
"""

from datetime import date, datetime

import psycopg

from app.budget import month_spend_usd
from app.config import PROVIDERS
from app.escalation import chain_root
from app.review_notes import valid_page

MAX_DIFF_CHARS = 6000
MAX_OUTPUT_CHARS = 2000

# Eval and bank chores are left out: their own runners read them (decisions
# 18 and 27 of docs/build-brief-evals.md).
_ESCALATED_SINCE = """
SELECT id FROM runs
WHERE status = 'escalated' AND source NOT IN ('eval', 'bank') AND created_at >= %s
ORDER BY created_at DESC
"""
_CHAIN_FORWARD = """
WITH RECURSIVE chain(id, depth) AS (
    SELECT id, 0 FROM runs WHERE id = %s
    UNION ALL
    SELECT r.id, c.depth + 1 FROM runs r JOIN chain c ON r.source_run_id = c.id
)
SELECT r.id::text, r.provider, r.tokens_used, r.status, r.escalation_reason, r.hint,
       r.needs_claude, r.task, r.repo, s.output
FROM chain JOIN runs r USING (id)
LEFT JOIN steps s ON s.run_id = r.id AND s.kind = 'done'
ORDER BY chain.depth, r.created_at
"""
_STARTED_BY_MERCURY = """
SELECT r.id::text, r.repo, r.task, r.status, s.output FROM runs r
LEFT JOIN steps s ON s.run_id = r.id AND s.kind = 'done'
WHERE r.source = 'scheduler' AND r.type = 'repo_chore' AND r.created_at >= %s
ORDER BY r.created_at DESC
"""
_TOKENS_TODAY = """
SELECT r.provider, coalesce(sum(s.tokens), 0) FROM steps s JOIN runs r ON r.id = s.run_id
WHERE r.provider IS NOT NULL AND s.finished_at >= date_trunc('day', now())
GROUP BY r.provider
"""
_STARTED_TODAY = """
SELECT count(*) FROM runs
WHERE claimed_by IS NOT NULL AND type <> 'site_check' AND created_at >= date_trunc('day', now())
"""
# The newest run of each chain that is escalated, outside the evals.
_WAITING = """
SELECT count(*) FILTER (WHERE NOT needs_claude), count(*) FILTER (WHERE needs_claude)
FROM runs r
WHERE r.status = 'escalated' AND r.source NOT IN ('eval', 'bank')
  AND NOT EXISTS (SELECT 1 FROM runs n WHERE n.source_run_id = r.id)
"""
# Notes still being followed, and the ones that finished since the report began.
# The note's words are never selected: only its id, page, state and pull request.
_NOTES = """
SELECT note_id, page, state, pr_url, edited FROM review_notes
WHERE state NOT IN ('merged', 'closed', 'gone') OR updated_at >= %s
ORDER BY note_id
"""
# A note on the owner: a question to answer, or a pull request to merge.
_NOTES_WAITING = "SELECT count(*) FROM review_notes WHERE state IN ('question', 'reported')"


def notes_section(conn: psycopg.Connection, since: datetime | date) -> list[str]:
    """The review notes: id, page, state, pull request and whether it was edited."""
    lines = ["## Review notes", ""]
    found = conn.execute(_NOTES, (since,)).fetchall()
    for note_id, page, state, pr_url, edited in found:
        shown = page if valid_page(page) else "(not a site path)"
        line = f"- Note {note_id}, {shown}, {state}"
        if pr_url:
            line += f", {pr_url}"
        if edited:
            line += ", edited"
        lines.append(line)
    if not found:
        lines.append("None yet.")
    return lines + [""]


def notes_waiting(conn: psycopg.Connection) -> int:
    """Review notes waiting on the owner: a question, or a pull request to merge."""
    return conn.execute(_NOTES_WAITING).fetchone()[0]


def waiting_counts(conn: psycopg.Connection) -> tuple[int, int]:
    """Chores waiting for a hint, and chores marked for a Claude session."""
    waiting, claude = conn.execute(_WAITING).fetchone()
    return waiting, claude


def _usd(provider: str | None, tokens: int) -> float:
    config = PROVIDERS.get(provider or "")
    return tokens * (config.usd_per_million_tokens if config else 0.0) / 1_000_000


def _state(newest: tuple) -> str:
    _, _, _, status, _, _, needs_claude, _, _, output = newest
    if needs_claude:
        return "Take it to a Claude session."
    if status == "escalated":
        return "Waiting for a hint (reply on Telegram or call advise)."
    if status in ("pending", "running", "awaiting_approval"):
        return "A rerun is under way."
    if status == "succeeded" and (output or {}).get("pr_url"):
        return f"Rescued: {output['pr_url']}"
    return f"Ended {status}."


def _chain_section(rows: list[tuple]) -> list[str]:
    root = rows[0]
    lines = [
        f"### {root[8]}: {root[7].strip().splitlines()[0] if root[7].strip() else 'Repo chore'}",
        "",
        "| Run | Provider | Tokens | USD | Status | Reason | Hint |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run_id, provider, tokens, status, reason, hint, _, _, _, _ in rows:
        hint_cell = (hint or "").replace("|", "/").replace("\n", " ")
        lines.append(
            f"| {run_id[:8]} | {provider or 'none'} | {tokens:,} | {_usd(provider, tokens):.4f} "
            f"| {status} | {reason or ''} | {hint_cell} |"
        )
    last_escalated = [row for row in rows if row[3] == "escalated"][-1]
    output = last_escalated[9] or {}
    diff = (output.get("diff") or "")[:MAX_DIFF_CHARS]
    test_output = (output.get("test_output") or "")[-MAX_OUTPUT_CHARS:]
    lines += ["", f"Why it stopped: {last_escalated[4] or output.get('reason', 'unknown')}."]
    if diff.strip():
        lines += ["", f"Last diff ({last_escalated[0][:8]}):", "", "```diff", diff.rstrip(), "```"]
    if test_output.strip():
        lines += ["", "Its test output ended:", "", "```", test_output.rstrip(), "```"]
    lines += ["", _state(rows[-1]), ""]
    return lines


def build_report(
    conn: psycopg.Connection,
    since: datetime | date,
    *,
    daily_tokens: int,
    monthly_usd: float,
    max_runs_per_day: int,
) -> str:
    lines = [f"# Mercury report since {since:%Y-%m-%d}", "", "## Escalations", ""]
    roots: list[str] = []
    for (run_id,) in conn.execute(_ESCALATED_SINCE, (since,)).fetchall():
        root = chain_root(conn, str(run_id))
        if root not in roots:
            roots.append(root)
    for root in roots:
        lines += _chain_section(conn.execute(_CHAIN_FORWARD, (root,)).fetchall())
    if not roots:
        lines += ["No escalations.", ""]

    lines += ["## Chores Mercury started", ""]
    started = conn.execute(_STARTED_BY_MERCURY, (since,)).fetchall()
    for run_id, repo, task, status, output in started:
        pr = (output or {}).get("pr_url")
        lines.append(f"- {run_id[:8]} {repo}: {task.strip().splitlines()[0]} ({status})")
        if pr:
            lines[-1] += f", {pr}"
    if not started:
        lines.append("None yet.")

    lines.append("")
    lines += notes_section(conn, since)
    lines += [
        "## Eval",
        "",
        "The latest eval report is the newest file in evals/results/ in the public repo.",
        "",
        "## Spend",
        "",
    ]
    today = dict(conn.execute(_TOKENS_TODAY).fetchall())
    for provider in PROVIDERS:
        lines.append(f"- {provider}: {today.get(provider, 0):,} of {daily_tokens:,} tokens today")
    lines.append(f"- {month_spend_usd(conn):.2f} of {monthly_usd:.2f} USD this month")
    started_today = conn.execute(_STARTED_TODAY).fetchone()[0]
    lines.append(f"- {started_today} of {max_runs_per_day} model runs today")
    return "\n".join(lines) + "\n"
