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
    # Seconds the test command may run. None keeps REPO_TEST_TIMEOUT_SECONDS.
    test_timeout_seconds: float | None = None


@dataclass(frozen=True)
class TaskSettings:
    """One entry under tasks: in mercury.yaml. ladder is the providers a run
    of this type tries in order when one fails; budget_tokens None keeps the
    type's own budget from app/tasks.py."""

    ladder: tuple[str, ...]
    budget_tokens: int | None = None


@dataclass(frozen=True)
class ReviewNotesConfig:
    """The review_notes: section. Notes left on a site are read from the
    Cloudflare D1 database account_id/database_id and become chores on repo.
    Only a note on one of live_hosts starts one. preview_pattern holds {alias},
    a branch preview's hostname label. allowed_paths, shared_paths and
    sensitive_files are the diff guard's lists (a later task reads them).
    daily_cap is the most note chores started in any 24 hours."""

    enabled: bool
    repo: str
    live_hosts: tuple[str, ...]
    preview_pattern: str
    account_id: str
    database_id: str
    allowed_paths: tuple[str, ...]
    shared_paths: tuple[str, ...]
    sensitive_files: tuple[str, ...]
    daily_cap: int = 10


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
    review_notes: ReviewNotesConfig | None = None


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
    repos = tuple(_repo(entry) for entry in portfolio.get("repos") or [])
    return MercuryConfig(
        sites=tuple(portfolio.get("sites") or []),
        pages=tuple(portfolio.get("pages") or []),
        telegram_chat_id=int(chat_id) if chat_id else None,
        repos=repos,
        event_bodies_days=int(retention.get("event_bodies_days", EVENT_BODIES_DAYS)),
        runs_days=int(retention.get("runs_days", RUNS_DAYS)),
        timezone=telegram.get("timezone") or "Australia/Melbourne",
        tasks=_tasks(data.get("tasks") or {}),
        review_notes=_review_notes(data.get("review_notes"), repos),
    )


def _review_notes(section: object, repos: tuple[RepoConfig, ...]) -> ReviewNotesConfig | None:
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError("mercury.yaml: review_notes: must be a mapping")

    def text(key: str) -> str:
        value = section.get(key)
        if value is None or isinstance(value, (bool, dict, list)) or not str(value).strip():
            raise ValueError(f"mercury.yaml: review_notes.{key} is required")
        return str(value).strip()

    def names(key: str, *, required: bool) -> tuple[str, ...]:
        value = section.get(key)
        if value is None and not required:
            return ()
        listed = isinstance(value, list) and all(
            isinstance(item, str) and item.strip() for item in value
        )
        if not listed or (required and not value):
            kind = "a non empty list of strings" if required else "a list of strings"
            raise ValueError(f"mercury.yaml: review_notes.{key} must be {kind}")
        return tuple(item.strip() for item in value)

    repo = text("repo")
    if not any(entry.name == repo and entry.test_command for entry in repos):
        raise ValueError(
            f"mercury.yaml: review_notes.repo {repo!r} must be listed under portfolio.repos "
            "with a test_command"
        )
    preview_pattern = text("preview_pattern")
    if "{alias}" not in preview_pattern:
        raise ValueError("mercury.yaml: review_notes.preview_pattern must contain {alias}")
    daily_cap = section.get("daily_cap", 10)
    if not isinstance(daily_cap, int) or isinstance(daily_cap, bool) or daily_cap < 1:
        raise ValueError("mercury.yaml: review_notes.daily_cap must be a positive whole number")
    return ReviewNotesConfig(
        # Only a YAML boolean true. A quoted "true" keeps notes off.
        enabled=section.get("enabled") is True,
        repo=repo,
        live_hosts=names("live_hosts", required=True),
        preview_pattern=preview_pattern,
        account_id=text("account_id"),
        database_id=text("database_id"),
        allowed_paths=names("allowed_paths", required=True),
        shared_paths=names("shared_paths", required=False),
        sensitive_files=names("sensitive_files", required=False),
        daily_cap=daily_cap,
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
        test_timeout_seconds=(
            float(entry["test_timeout_seconds"]) if "test_timeout_seconds" in entry else None
        ),
    )
