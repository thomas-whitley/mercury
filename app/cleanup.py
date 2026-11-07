"""Retention, run by the scheduler Job on every tick.

A finished run older than event_bodies_days loses its bodies: the task input,
every step's input and output, and every event's output, so a reconnect a month
later still replays each step's seq and kind and the done event's status, the
same shape a caller with no token sees (app/stream.py without_body). A
site_check keeps everything, because its step 1 is the summary the digest
compares week over week. A chore's model calls go at the same age, except
a bank run's, which are Phase 5's training data. A review note that is
finished (merged, closed or gone) loses the reviewer's words copied onto its
row at the same age, counted from when it finished. A run older than runs_days
goes, steps, events and model calls with it.

The deal finder's vote snapshots go at event_bodies_days, and so does a
deal never sent once it has not been seen for as long. A deal that was sent
keeps its row, its messages and its rating, which the learning reads, until
its last message is runs_days old.

Both statements only touch rows that still have something to remove, so a
second pass in the same hour finds nothing.
"""

import logging
from dataclasses import dataclass

import psycopg

logger = logging.getLogger("agent_runs.cleanup")

EVENT_BODIES_DAYS = 30
RUNS_DAYS = 365

# The runs past the window that still hold a body. task = '' marks one done,
# since every step and event of the run is stripped in the same transaction.
_STRIP_RUNS = """
UPDATE runs SET task = ''
WHERE type <> 'site_check'
  AND finished_at < now() - make_interval(days => %s)
  AND task <> ''
RETURNING id
"""

_STRIP_STEPS = """
UPDATE steps SET
    input = NULL,
    output = CASE WHEN kind = 'done'
                  THEN jsonb_build_object('status', output -> 'status')
                  ELSE NULL END
WHERE run_id = ANY(%s)
"""

_STRIP_EVENTS = """
UPDATE events SET payload =
    jsonb_build_object('seq', payload -> 'seq', 'kind', payload -> 'kind')
    || CASE WHEN payload ->> 'kind' = 'done'
            THEN jsonb_build_object('output', jsonb_build_object(
                     'status', coalesce(payload -> 'output' -> 'status', payload -> 'status')))
            ELSE '{}'::jsonb END
WHERE run_id = ANY(%s)
"""

# An open anyway run points at the run it reapplied. The source is hours
# older, so it can pass the year first, and the reference is dropped rather
# than blocking the delete.
_DELETE_RUNS = """
WITH doomed AS (
    SELECT id FROM runs WHERE created_at < now() - make_interval(days => %s)
), unlinked AS (
    UPDATE runs SET source_run_id = NULL WHERE source_run_id IN (SELECT id FROM doomed)
)
DELETE FROM runs WHERE id IN (SELECT id FROM doomed)
"""

# A chore's model calls go when its bodies do, except a bank run's, which are
# Phase 5's training data (decision 28 of docs/build-brief-evals.md). A bank
# run's calls go with the run itself after a year, by the cascade.
_DROP_CALLS = """
DELETE FROM model_calls c USING runs r
WHERE c.run_id = r.id
  AND r.source <> 'bank'
  AND r.finished_at < now() - make_interval(days => %s)
"""


# The reviewer's words, copied onto a note's row for its pull request
# (migration 018), go once the note is finished and past the window.
_STRIP_NOTES = """
UPDATE review_notes SET note_body = NULL, note_anchor = NULL, note_quote = NULL
WHERE state IN ('merged', 'closed', 'gone')
  AND updated_at < now() - make_interval(days => %s)
  AND (note_body IS NOT NULL OR note_anchor IS NOT NULL OR note_quote IS NOT NULL)
"""


_DROP_DEAL_SNAPSHOTS = """
DELETE FROM deal_snapshots WHERE seen_at < now() - make_interval(days => %s)
"""
_DROP_UNSENT_DEALS = """
DELETE FROM deals d
WHERE d.last_seen_at < now() - make_interval(days => %s)
  AND NOT EXISTS (SELECT 1 FROM deal_sends s WHERE s.node_id = d.node_id)
  AND NOT EXISTS (SELECT 1 FROM deal_ratings r WHERE r.node_id = d.node_id)
"""
# A sent deal goes once its last message passes the runs window: its rating,
# its messages, then the deal, then roundups no message points at.
_OLD_SENT_DEALS = """
SELECT node_id FROM deal_sends GROUP BY node_id
HAVING max(sent_at) < now() - make_interval(days => %s)
"""
_DROP_DEAL_RATINGS = "DELETE FROM deal_ratings WHERE node_id = ANY(%s)"
_DROP_DEAL_SENDS = "DELETE FROM deal_sends WHERE node_id = ANY(%s)"
_DROP_DEALS = "DELETE FROM deals WHERE node_id = ANY(%s)"
_DROP_DEAL_ROUNDUPS = """
DELETE FROM deal_roundups r
WHERE r.sent_at < now() - make_interval(days => %s)
  AND NOT EXISTS (SELECT 1 FROM deal_sends s WHERE s.roundup_id = r.id)
"""


@dataclass(frozen=True)
class CleanupResult:
    runs_stripped: int
    runs_deleted: int


def run_cleanup(
    conn: psycopg.Connection,
    event_bodies_days: int = EVENT_BODIES_DAYS,
    runs_days: int = RUNS_DAYS,
) -> CleanupResult:
    with conn.transaction():
        stripped = [row[0] for row in conn.execute(_STRIP_RUNS, (event_bodies_days,))]
        if stripped:
            conn.execute(_STRIP_STEPS, (stripped,))
            conn.execute(_STRIP_EVENTS, (stripped,))
        conn.execute(_DROP_CALLS, (event_bodies_days,))
        conn.execute(_STRIP_NOTES, (event_bodies_days,))
        deleted = conn.execute(_DELETE_RUNS, (runs_days,)).rowcount
        conn.execute(_DROP_DEAL_SNAPSHOTS, (event_bodies_days,))
        conn.execute(_DROP_UNSENT_DEALS, (event_bodies_days,))
        old_deals = [row[0] for row in conn.execute(_OLD_SENT_DEALS, (runs_days,))]
        if old_deals:
            for statement in (_DROP_DEAL_RATINGS, _DROP_DEAL_SENDS, _DROP_DEALS):
                conn.execute(statement, (old_deals,))
        conn.execute(_DROP_DEAL_ROUNDUPS, (runs_days,))

    result = CleanupResult(runs_stripped=len(stripped), runs_deleted=deleted)
    if stripped or deleted:
        logger.info(
            "cleanup stripped the bodies of %s run(s) and deleted %s run(s)",
            result.runs_stripped,
            result.runs_deleted,
        )
    return result
