"""The task type registry. One row per type, naming its tools, its provider
ladder and its token budget. The defaults are here in code; the tasks:
section of mercury.yaml replaces a type's ladder and budget at startup
(configure_task_types). A run's type picks its row here; nothing about that
row comes from MODEL, and a request may only name a free provider for its
own run.

Nothing is added to this table until every row in the README's claims table
for this phase is green, per docs/mercury.md.
"""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.mercury_config import TaskSettings


@dataclass(frozen=True)
class TaskType:
    name: str
    tools: tuple[str, ...]
    # The providers a run tries in order, each taking over when the one
    # before it fails (app/model.py FallbackModel). The first is the type's
    # own. Empty for a type that calls no model.
    ladder: tuple[str, ...]
    budget_tokens: int
    public: bool = False

    @property
    def provider(self) -> str | None:
        return self.ladder[0] if self.ladder else None


_CHAT_TOOLS = (
    "list_runs",
    "read_run_events",
    "portfolio_status",
    "create_task",
)

_TYPES = (
    TaskType(name="pytest", tools=(), ladder=("gemini", "ollama"), budget_tokens=50_000),
    TaskType(name="chat", tools=_CHAT_TOOLS, ladder=("ollama", "gemini"), budget_tokens=20_000),
    TaskType(name="repo_chore", tools=(), ladder=("gemini", "ollama"), budget_tokens=50_000),
    TaskType(name="site_check", tools=(), ladder=(), budget_tokens=0),
    TaskType(name="digest", tools=(), ladder=("gemini", "ollama"), budget_tokens=20_000),
)

TASK_TYPES: dict[str, TaskType] = {task_type.name: task_type for task_type in _TYPES}


def configure_task_types(tasks: "dict[str, TaskSettings]") -> None:
    """Apply mercury.yaml's tasks: section over the defaults above. Called
    once at startup by the api, the worker and the scheduler, after the
    config has loaded."""
    for name, settings in tasks.items():
        TASK_TYPES[name] = replace(
            TASK_TYPES[name],
            ladder=settings.ladder,
            budget_tokens=settings.budget_tokens or TASK_TYPES[name].budget_tokens,
        )


# The kinds a site_check can be. The scheduler Job creates and closes its
# own kinds in the cloud: uptime is plain HTTP against a site, ci_watch reads
# a repo's workflow runs from GitHub, and dependency_audit reads a repo's lock
# files. Neither worker claims them. lighthouse and broken_links need a
# browser, so only the self hosted checks worker runs them, through the claim
# endpoints.
SCHEDULER_CHECK_KINDS = ("uptime", "ci_watch", "dependency_audit")
SELF_HOSTED_CHECK_KINDS = ("lighthouse", "broken_links")
CHECK_KINDS = SCHEDULER_CHECK_KINDS + SELF_HOSTED_CHECK_KINDS
DEFAULT_CHECK_KIND = "uptime"
# The kinds the cloud takes over when no self hosted worker claims them in the
# window. PageSpeed Insights runs Lighthouse but cannot crawl, and the crawl
# lives only in checks/, so broken_links waits for the self hosted worker.
CLOUD_FALLBACK_CHECK_KINDS = ("lighthouse",)
