"""The caps above a run's own token budget, per docs/mercury.md: tokens per
day per provider, and dollars per month across providers. Both are checked
before a run that calls a model starts, and count the tokens every step has
recorded, including those of runs still going. A run already under way
finishes under its own budget, which bounds how far one run can overshoot.
"""

from dataclasses import dataclass

import psycopg

from app.config import HOME_PROVIDERS, PROVIDERS

# The runs counted against MAX_RUNS_PER_DAY and MAX_LOCAL_RUNS_PER_DAY. The
# worker refuses a run once its own claim takes the day over the limit, and the
# review notes step (app/review_notes.py) waits rather than start a chore then.
# site_check makes no model call, and the checks worker claims it too, so it
# is left out of the limit that protects the model key. A run on a home
# provider costs no key either, and has its own limit.
_STARTED_TODAY = """
SELECT count(*) FROM runs
WHERE claimed_by IS NOT NULL
  AND type <> 'site_check'
  AND created_at >= date_trunc('day', now())
  AND (provider IS NULL OR NOT (provider = ANY(%s)))
"""
_HOME_STARTED_TODAY = """
SELECT count(*) FROM runs
WHERE claimed_by IS NOT NULL
  AND created_at >= date_trunc('day', now())
  AND provider = ANY(%s)
"""

_TODAY = """
SELECT coalesce(sum(s.tokens), 0) FROM steps s JOIN runs r ON r.id = s.run_id
WHERE r.provider = %s AND s.finished_at >= date_trunc('day', now())
"""

_THIS_MONTH = """
SELECT r.provider, coalesce(sum(s.tokens), 0) FROM steps s JOIN runs r ON r.id = s.run_id
WHERE r.provider IS NOT NULL AND s.finished_at >= date_trunc('month', now())
GROUP BY r.provider
"""


@dataclass(frozen=True)
class BudgetTrip:
    cap: str  # "daily_tokens" or "monthly_usd"
    message: str


def runs_started_today(conn: psycopg.Connection) -> int:
    return conn.execute(_STARTED_TODAY, (HOME_PROVIDERS,)).fetchone()[0]


def home_runs_started_today(conn: psycopg.Connection) -> int:
    return conn.execute(_HOME_STARTED_TODAY, (HOME_PROVIDERS,)).fetchone()[0]


def month_spend_usd(conn: psycopg.Connection) -> float:
    total = 0.0
    for provider, tokens in conn.execute(_THIS_MONTH).fetchall():
        config = PROVIDERS.get(provider)
        rate = config.usd_per_million_tokens if config else 0.0
        total += tokens * rate / 1_000_000
    return total


def check_budget(
    conn: psycopg.Connection, provider: str, daily_tokens: int, monthly_usd: float
) -> BudgetTrip | None:
    """None when a new run on this provider may start."""
    config = PROVIDERS.get(provider)
    # A home provider costs nothing and has no quota to protect (decision 25
    # of docs/build-brief-evals.md).
    if not (config and config.home):
        today = conn.execute(_TODAY, (provider,)).fetchone()[0]
        if today >= daily_tokens:
            return BudgetTrip(
                cap="daily_tokens",
                message=f"{provider} has used {today:,} of its {daily_tokens:,} tokens today.",
            )
    spent = month_spend_usd(conn)
    if spent >= monthly_usd:
        return BudgetTrip(
            cap="monthly_usd",
            message=f"This month's model spend is {spent:.2f} of {monthly_usd:.2f} USD.",
        )
    return None
