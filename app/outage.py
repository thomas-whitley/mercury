"""Retry a chore whose model never answered on any provider, per decision 17
of docs/build-brief-evals.md.

Such a chore ends in error with the reason OUTAGE (app/repo_chore.py). The
hourly scheduler Job calls retry_outages, which queues a retry for each one
that finished at least half an hour ago, so a run that failed a minute
before the tick still gets its hour. A retry copies the instruction, repo,
source and any hint, links back by source_run_id, and starts pending on the
type's first rung. After MAX_OUTAGE_RETRIES retries in a row have also hit
an outage, the last one is escalated and announced instead. An eval chore is
never retried: the eval runner has already recorded it and moved on, and a
late retry could open a pull request on the fixture that nobody closes.

The scheduler inserts retries itself rather than POSTing them: a retry is
the same chore continuing, already approved, not a new request through the
chore gate. Nothing keeps the worker awake while it waits, because the run
is finished until the Job queues the next one.
"""

import logging

import psycopg

from app.escalation import announce_escalation, chain_ids
from app.repo_chore import OUTAGE
from app.tasks import TASK_TYPES
from app.telegram import TelegramClient

logger = logging.getLogger("agent_runs.outage")

MAX_OUTAGE_RETRIES = 3
WAIT = "30 minutes"

_OUTAGE = """
r.type = 'repo_chore' AND r.status = 'error'
AND EXISTS (
    SELECT 1 FROM steps s WHERE s.run_id = r.id AND s.kind = 'done' AND s.output ->> 'reason' = %s
)
"""
_CANDIDATES = (
    "SELECT r.id FROM runs r WHERE "
    + _OUTAGE
    + """AND r.finished_at < now() - %s::interval
AND NOT EXISTS (SELECT 1 FROM runs n WHERE n.source_run_id = r.id)
AND r.source NOT IN ('eval', 'bank')
ORDER BY r.finished_at"""
)
_IS_OUTAGE = "SELECT count(*) FROM runs r WHERE r.id = %s AND " + _OUTAGE
_RETRY = """
INSERT INTO runs (task, type, provider, repo, status, source, source_run_id, hint)
SELECT task, 'repo_chore', %s, repo, 'pending', source, id, hint FROM runs WHERE id = %s
RETURNING id
"""
_ESCALATE = "UPDATE runs SET status = 'escalated', escalation_reason = %s WHERE id = %s"


def _outages_in_a_row(conn: psycopg.Connection, run_id: str) -> int:
    count = 0
    for earlier in chain_ids(conn, run_id):
        if not conn.execute(_IS_OUTAGE, (earlier, OUTAGE)).fetchone()[0]:
            break
        count += 1
    return count


def retry_outages(
    conn: psycopg.Connection,
    telegram: TelegramClient | None,
    chat_id: int | None,
    page_base_url: str,
) -> list[str]:
    """Queue a retry for each outage due one, or escalate it after the last
    retry. Returns the ids of the retries queued."""
    queued = []
    for (run_id,) in conn.execute(_CANDIDATES, (OUTAGE, WAIT)).fetchall():
        run_id = str(run_id)
        with conn.transaction():
            if _outages_in_a_row(conn, run_id) <= MAX_OUTAGE_RETRIES:
                provider = TASK_TYPES["repo_chore"].provider
                retry = str(conn.execute(_RETRY, (provider, run_id)).fetchone()[0])
                queued.append(retry)
                logger.info("retrying %s after an outage as %s", run_id, retry)
                continue
            conn.execute(_ESCALATE, (OUTAGE, run_id))
        logger.warning("escalated %s after %s outage retries", run_id, MAX_OUTAGE_RETRIES)
        announce_escalation(conn, telegram, chat_id, run_id, page_base_url)
    return queued
