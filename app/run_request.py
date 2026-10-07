"""The body of POST /runs, validated against the task registry. A chat run
creates its run through the same model, so both paths refuse the same input."""

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from app.config import PROVIDERS
from app.tasks import CHECK_KINDS, DEFAULT_CHECK_KIND, TASK_TYPES

# What a caller of POST /runs may say it is. telegram and mcp are set inside
# the app (app/telegram_webhook.py, app/chat.py, the MCP server), so a POST
# cannot claim either. eval is the eval runner (evals/runner.py), whose
# escalations reach the report and never Telegram. bank is the Phase 5 chore
# bank (part 5b), quiet in the same ways as eval.
# A full commit sha, so the run row says exactly where a chore started.
_SHA = re.compile(r"[0-9a-f]{40}")

PostedSource = Literal["api", "n8n", "scheduler", "eval", "bank"]


class RunRequest(BaseModel):
    type: str
    inputs: dict[str, Any]
    source: PostedSource = "api"
    # A key of app.config.PROVIDERS that costs nothing. None runs on the type's
    # own provider. A caller cannot spend money by naming one: a paid provider
    # is only ever a type's own choice.
    provider: str | None = None

    @field_validator("provider")
    @classmethod
    def provider_must_be_registered(cls, value: str | None) -> str | None:
        if value is not None and value not in PROVIDERS:
            raise ValueError(f"unknown provider {value!r}")
        if value is not None and PROVIDERS[value].usd_per_million_tokens != 0:
            raise ValueError(f"{value!r} is not free, and a caller may only name a free provider")
        return value

    @model_validator(mode="after")
    def only_a_model_run_names_a_provider(self) -> "RunRequest":
        if self.provider is not None and TASK_TYPES[self.type].provider is None:
            raise ValueError(f"a {self.type} run calls no model, so it takes no provider")
        return self

    @field_validator("type")
    @classmethod
    def type_must_be_registered(cls, value: str) -> str:
        if value not in TASK_TYPES:
            raise ValueError(f"unknown task type {value!r}")
        return value

    @field_validator("inputs")
    @classmethod
    def inputs_must_carry_a_task(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Every registered type stores its input on the same task column for
        # now; per type input shapes are future work, not this step's.
        task = value.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("inputs.task must not be blank")
        return value

    @model_validator(mode="after")
    def only_a_check_has_a_kind(self) -> "RunRequest":
        kind = self.inputs.get("kind")
        if kind is None:
            return self
        if self.type != "site_check":
            raise ValueError("inputs.kind is only for site_check")
        if kind not in CHECK_KINDS:
            raise ValueError(f"unknown check kind {kind!r}")
        return self

    @model_validator(mode="after")
    def only_a_chore_has_a_base(self) -> "RunRequest":
        # The commit a repo chore starts from (decision 29 of
        # docs/build-brief-evals.md). None is the tip of the default branch.
        base = self.inputs.get("base")
        if base is None:
            return self
        if self.type != "repo_chore":
            raise ValueError("inputs.base is only for repo_chore")
        if not isinstance(base, str) or not _SHA.fullmatch(base):
            raise ValueError("inputs.base must be a full 40 character commit sha")
        return self

    @property
    def check_kind(self) -> str | None:
        if self.type != "site_check":
            return None
        return self.inputs.get("kind", DEFAULT_CHECK_KIND)
