"""Which runs may name which provider. A home provider answers in JSON mode
(decision 23 of docs/build-brief-evals.md), which only a chore's reply
format survives."""

import pytest
from pydantic import ValidationError

from app.run_request import RunRequest


@pytest.mark.parametrize("type_", ["pytest", "chat", "digest"])
def test_a_home_provider_is_refused_on_anything_but_a_repo_chore(type_):
    with pytest.raises(ValidationError, match="repo chore"):
        RunRequest(type=type_, inputs={"task": "x"}, provider="local")


def test_a_home_provider_is_accepted_on_a_repo_chore():
    run = RunRequest(type="repo_chore", inputs={"task": "x", "repo": "o/r"}, provider="local")

    assert run.provider == "local"
