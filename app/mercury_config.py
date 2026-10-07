"""Loads mercury.yaml: the portfolio's sites, checked hourly for uptime, its
pages, checked weekly with Lighthouse and the broken link crawl, its repos,
which a repo_chore may touch, the one Telegram chat the bot answers and its
timezone, the retention windows the cleanup applies, and each task type's
provider ladder and token budget.

budgets: and providers: were in the first sample and never read. A config
that still has them, or a tasks: entry in the old provider: shape, is
refused at startup rather than left to state something false.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.cleanup import EVENT_BODIES_DAYS, RUNS_DAYS


@dataclass(frozen=True)
class RepoConfig:
    """owner/name, and the command that runs its tests from the repo root.
    A repo with no test command cannot have a chore, since a chore opens a
    pull request only when the tests pass."""

    name: str
    test_command: str | None = None
    # true in mercury.yaml lets a chore from the API, MCP or n8n start without
    # the Approve button. Meant for the throwaway fixture the evals run on.
    auto_approve: bool = False


@dataclass(frozen=True)
class TaskSettings:
    """One entry under tasks: in mercury.yaml. ladder is the providers a run
    of this type tries in order when one fails; budget_tokens None keeps the
    type's own budget from app/tasks.py."""

    ladder: tuple[str, ...]
    budget_tokens: int | None = None


@dataclass(frozen=True)
class MercuryConfig:
    sites: tuple[str, ...]
    pages: tuple[str, ...] = ()
    # The one chat the bot answers. None, including the sample's 0, answers no one.
    telegram_chat_id: int | None = None
    repos: tuple[RepoConfig, ...] = ()
    event_bodies_days: int = EVENT_BODIES_DAYS
    # The digest's local time is read in this zone.
    timezone: str = "Australia/Melbourne"
    runs_days: int = RUNS_DAYS
    tasks: dict[str, TaskSettings] = field(default_factory=dict)


def load_mercury_config(path: str | Path) -> MercuryConfig:
    """Read mercury.yaml. Raises FileNotFoundError if it is not there,
    which is what a scheduler started with no config mounted should do."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    for gone in ("budgets", "providers"):
        if gone in data:
            raise ValueError(
                f"mercury.yaml: {gone}: is not read. Caps are DAILY_TOKENS_PER_PROVIDER and "
                "MONTHLY_BUDGET_USD in the environment, and providers are PROVIDERS in "
                "app/config.py."
            )
    portfolio = data.get("portfolio") or {}
    telegram = data.get("telegram") or {}
    chat_id = telegram.get("chat_id")
    retention = data.get("retention") or {}
    return MercuryConfig(
        sites=tuple(portfolio.get("sites") or []),
        pages=tuple(portfolio.get("pages") or []),
        telegram_chat_id=int(chat_id) if chat_id else None,
        repos=tuple(_repo(entry) for entry in portfolio.get("repos") or []),
        event_bodies_days=int(retention.get("event_bodies_days", EVENT_BODIES_DAYS)),
        runs_days=int(retention.get("runs_days", RUNS_DAYS)),
        timezone=telegram.get("timezone") or "Australia/Melbourne",
        tasks=_tasks(data.get("tasks") or {}),
    )


def _tasks(section: dict) -> dict[str, TaskSettings]:
    # Imported here because app.tasks imports this module's TaskSettings.
    from app.config import PROVIDERS
    from app.tasks import TASK_TYPES

    tasks = {}
    for name, entry in section.items():
        entry = entry or {}
        if name not in TASK_TYPES:
            raise ValueError(f"mercury.yaml: unknown task type {name!r} under tasks")
        if "provider" in entry:
            raise ValueError(
                f"mercury.yaml: tasks.{name}.provider is no longer read; "
                f"write tasks.{name}.ladder: [first, second] instead"
            )
        ladder = tuple(entry.get("ladder") or ())
        if TASK_TYPES[name].provider is None:
            if ladder:
                raise ValueError(f"mercury.yaml: {name} calls no model, so it takes no ladder")
        elif not ladder:
            raise ValueError(f"mercury.yaml: tasks.{name}.ladder needs at least one provider")
        for provider in ladder:
            if provider not in PROVIDERS:
                raise ValueError(f"mercury.yaml: unknown provider {provider!r} in tasks.{name}")
        budget = entry.get("budget_tokens")
        tasks[name] = TaskSettings(ladder=ladder, budget_tokens=int(budget) if budget else None)
    return tasks


def _repo(entry: str | dict) -> RepoConfig:
    if isinstance(entry, str):
        return RepoConfig(name=entry)
    return RepoConfig(
        name=entry["name"],
        test_command=entry.get("test_command"),
        # Only a YAML boolean true. A quoted "yes" keeps the gate.
        auto_approve=entry.get("auto_approve") is True,
    )
