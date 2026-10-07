"""advise: rerun an escalated repo chore from main with a hint, per decisions
6 and 8 of docs/build-brief-evals.md. The MCP tool and a Telegram reply to
an escalation message both come here.

The rerun copies the chore's instruction and repo, links back with
source_run_id, carries the hint, and starts pending on the type's first
rung, so it needs no Approve: the owner, or a Claude session working for
them, is the one advising. A chore takes at most MAX_ADVISED advised reruns;
when the last of them escalates too, it is marked needs_claude and advise
refuses another.

An advised rerun is a run with a hint whose source run ended escalated. An
outage retry (app/outage.py) copies the hint too, but comes from a run that
ended in error, so it is not counted.
"""

import psycopg

from app.chores import ChoreRefused, find_repo
from app.escalation import chain_ids
from app.mercury_config import RepoConfig
from app.tasks import TASK_TYPES

MAX_ADVISED = 2
MAX_HINT_CHARS = 2000

_RUN = "SELECT type, status, task, repo FROM runs WHERE id = %s"
_NEWER = "SELECT count(*) FROM runs WHERE source_run_id = %s"
_ADVISED = """
SELECT count(*) FROM runs r JOIN runs prior ON prior.id = r.source_run_id
WHERE r.id = ANY(%s::uuid[]) AND r.hint IS NOT NULL AND prior.status = 'escalated'
"""
_CREATE = """
INSERT INTO runs (task, type, provider, repo, status, source, source_run_id, hint)
VALUES (%s, 'repo_chore', %s, %s, 'pending', %s, %s, %s) RETURNING id
"""


class AdviceRefused(ValueError):
    """The hint cannot be acted on. The message says why, for the owner."""


def advised_count(conn: psycopg.Connection, run_id: str) -> int:
    """How many advised reruns the chain ending at this run holds."""
    return conn.execute(_ADVISED, (chain_ids(conn, run_id),)).fetchone()[0]


def advise(
    conn: psycopg.Connection,
    run_id: str,
    hint: str,
    source: str,
    repos: tuple[RepoConfig, ...],
) -> str:
    """Queue the advised rerun and return its id, or raise AdviceRefused."""
    hint = (hint or "").strip()
    if not hint:
        raise AdviceRefused("The hint is blank.")
    if len(hint) > MAX_HINT_CHARS:
        raise AdviceRefused(f"The hint is over {MAX_HINT_CHARS:,} characters.")
    row = conn.execute(_RUN, (run_id,)).fetchone()
    if row is None:
        raise AdviceRefused(f"No run {run_id}.")
    type_, status, task, repo_name = row
    if type_ != "repo_chore":
        raise AdviceRefused("Only a repo chore takes advice.")
    if status != "escalated":
        raise AdviceRefused(f"Run {run_id[:8]} is {status}, not escalated.")
    if conn.execute(_NEWER, (run_id,)).fetchone()[0]:
        raise AdviceRefused(f"Run {run_id[:8]} already has a newer run; advise that one.")
    if advised_count(conn, run_id) >= MAX_ADVISED:
        raise AdviceRefused(
            f"This chore has had {MAX_ADVISED} advised reruns. Take it to a Claude session."
        )
    try:
        repo = find_repo(repos, repo_name)
    except ChoreRefused as refused:
        raise AdviceRefused(str(refused)) from None
    new_id = conn.execute(
        _CREATE,
        (task, TASK_TYPES["repo_chore"].provider, repo.name, source, run_id, hint),
    ).fetchone()[0]
    return str(new_id)


def mark_if_needs_claude(conn: psycopg.Connection, run_id: str) -> bool:
    """After an escalation: when the chain has used every advised rerun,
    mark this run for a Claude session. True when it was marked."""
    if advised_count(conn, run_id) < MAX_ADVISED:
        return False
    conn.execute("UPDATE runs SET needs_claude = true WHERE id = %s", (run_id,))
    return True
