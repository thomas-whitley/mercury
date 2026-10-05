# Build brief: chore evals on cheap models

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, with numbers, how often a cheap model turns a well defined instruction into a pull request that passes a test it never saw, and make that measurement repeatable.

**Architecture:** Two small changes to the API (a per repo `auto_approve` flag and a per run `provider`), then an eval runner in `evals/` that queues each task as a `repo_chore` through `POST /runs` on the live deploy, waits on `GET /runs/{id}`, clones the `agent/<run id>` branch, checks that no test from `main` is gone and the repo's own tests still pass, runs a hidden grade test, closes the PR and deletes the branch, and writes a JSON and Markdown report per provider.

**Tech Stack:** Python 3.12, FastAPI, psycopg, pydantic, httpx2, PyYAML, pytest, uv. git on the machine that runs the eval.

**Spec:** `docs/mercury.md` (task types, autonomy ceiling, repo chores, budgets) and this brief. Decided with Thomas on 2026-10-05: the front door already exists (MCP, `POST /runs`, n8n), so the work is proof, not plumbing; the eval runs against the live deploy, not CI; an eval batch passes the Approve gate through `auto_approve: true` on `thomas-whitley/mercury-fixture` only.

## Where this starts

Live is `bde2233` on the `mercury` image. One chore has ever run on a real model: run `100c1125` (source n8n, gemini, 597 tokens) added `multiply` to the fixture as PR #4. Every chore today runs on gemini with ollama as fallback, and every chore waits for Approve on Telegram, which could not connect on 2026-10-02. There is no measurement of how often a cheap model gets a chore right.

## Global Constraints

- Writing rules from `CLAUDE.md` apply to every README line, doc and commit message: no em or en dashes, complete sentences, numbers over adjectives, none of the banned words.
- Commit messages are plain sentences saying what now works. No prefixes, no emoji.
- CI uses the stub model and never a real key. The eval is not a CI job; it runs by hand against the live deploy.
- No paid resource. The eval's default providers are `gemini` and `ollama`, both free tiers. `haiku` costs money and runs only if Thomas says yes in the conversation.
- The runner never merges. The runner closes every PR it caused and deletes its branch.
- No token in a commit, a log line, a report file or a URL. git gets the GitHub token only as `http.extraheader` through `GIT_CONFIG_*` environment variables, as `app/repo_chore.py` does.
- `auto_approve` is set on `thomas-whitley/mercury-fixture` alone. No real repo gets it.
- A README claim is written only after its proof exists, with the output pasted under it.
- When another session shares the working copy, run tests with `TEST_DATABASE_URL=postgresql://agent:agent@localhost:5432/agent_runs_test_chores`.

## Review Focus

- A chore posted for an `auto_approve` repo on a deploy with no Telegram bot should still start, not return 503, because nothing needs asking. Test in Task 1.
- A chore asked for in Telegram chat on an `auto_approve` repo should still wait for Approve, because chat replies "waiting for approval" and the owner is there to press it. Test in Task 1.
- `auto_approve: "yes"` (a quoted string) or any non boolean in `mercury.yaml` should leave the gate on. Only YAML `true` turns it off. Test in Task 1.
- A `provider` on a `site_check`, or a provider name not in `PROVIDERS`, should be a 422 that creates no run. Test in Task 2.
- A grade test that cannot import what the model was asked to write should count as a fail and let the batch carry on, not crash the runner. Test in Task 3.
- A branch that passes the hidden grade but deletes a test that `main` has should fail. On 2026-10-05 `gpt-oss:20b` did this in 2 of 2 local trials on the fixture (it replaced the `add` test with its own), and a grade that tests only the new code passed both. Test in Task 3.

---

### Task 1: `auto_approve` per repo

**Files:**
- Modify: `app/mercury_config.py` (`RepoConfig`, `_repo`)
- Modify: `app/chores.py` (add `starts_unasked`, `start_chore`)
- Modify: `app/run_api.py` (`_request_chore`)
- Modify: `app/mcp_server.py` (the `CREATE_RUN` description and the server `instructions`)
- Modify: `config/mercury.sample.yaml` (document the key)
- Test: `tests/test_repo_chore_approval.py`

**Interfaces:**
- Produces: `RepoConfig.auto_approve: bool = False`; `starts_unasked(repo: RepoConfig, source: str) -> bool`; `start_chore(conn, repo: RepoConfig, instruction: str, source: str, provider: str) -> str` (the run id). `POST /runs` for a chore on such a repo returns 201 with `status: "pending"`.

- [ ] **Step 1: Write the failing tests**

Add `from app.chores import request_chore` to the imports at the top of `tests/test_repo_chore_approval.py`, then append:

```python
def _auto_config(tmp_path, with_telegram: bool = True):
    config = tmp_path / "mercury.yaml"
    data = {
        "portfolio": {
            "repos": [{"name": REPO, "test_command": "uv run pytest", "auto_approve": True}]
        }
    }
    if with_telegram:
        data["telegram"] = {"chat_id": CHAT}
    config.write_text(yaml.dump(data))
    return config


@pytest.fixture
def auto_bot(start_server, fake_telegram, monkeypatch, tmp_path):
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(_auto_config(tmp_path)))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_API_URL", fake_telegram.url)
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", "test-bearer-token")
    return start_server()


@pytest.fixture
def auto_bot_without_telegram(start_server, monkeypatch, tmp_path):
    monkeypatch.setenv("MERCURY_CONFIG_PATH", str(_auto_config(tmp_path, with_telegram=False)))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("MERCURY_BEARER_TOKEN", "test-bearer-token")
    return start_server()


def test_a_posted_chore_on_an_auto_approved_repo_starts_without_asking(
    auto_bot, fake_telegram, migrated_db
):
    response = post_chore(auto_bot)

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert fake_telegram.sent() == []
    row = migrated_db.execute("SELECT status, repo, source FROM runs").fetchone()
    assert row == ("pending", REPO, "api")
    assert str(claim_next_run(migrated_db, "worker-1")) == response.json()["id"]


def test_an_auto_approved_chore_needs_no_telegram_to_start(
    auto_bot_without_telegram, migrated_db
):
    response = post_chore(auto_bot_without_telegram)

    assert response.status_code == 201
    assert response.json()["status"] == "pending"


def test_a_chore_asked_for_in_chat_still_waits_on_an_auto_approved_repo(
    fake_telegram, migrated_db
):
    repo = RepoConfig(name=REPO, test_command="uv run pytest", auto_approve=True)
    telegram = TelegramClient("123:abc", fake_telegram.url)

    run_id = request_chore(migrated_db, telegram, CHAT, repo, INSTRUCTION, "telegram")

    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert status == ("awaiting_approval",)
    assert len(fake_telegram.sent()) == 1


def test_auto_approve_is_on_only_for_a_yaml_true(tmp_path):
    config = tmp_path / "mercury.yaml"
    config.write_text(
        "portfolio:\n"
        "  repos:\n"
        "    - {name: a/on, test_command: t, auto_approve: true}\n"
        "    - {name: a/quoted, test_command: t, auto_approve: 'yes'}\n"
        "    - {name: a/absent, test_command: t}\n"
    )

    repos = {repo.name: repo.auto_approve for repo in load_mercury_config(config).repos}

    assert repos == {"a/on": True, "a/quoted": False, "a/absent": False}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_repo_chore_approval.py -k "auto_approve or auto_approved" -v`
Expected: FAIL. The config test fails with `TypeError: RepoConfig.__init__() got an unexpected keyword argument 'auto_approve'` or an `AttributeError`, and the posted chore comes back `awaiting_approval`.

- [ ] **Step 3: Implement**

`app/mercury_config.py`, in `RepoConfig` after `test_command`:

```python
    # true in mercury.yaml lets a chore from the API, MCP or n8n start without
    # the Approve button. Meant for the throwaway fixture the evals run on.
    auto_approve: bool = False
```

and `_repo` becomes:

```python
def _repo(entry: str | dict) -> RepoConfig:
    if isinstance(entry, str):
        return RepoConfig(name=entry)
    return RepoConfig(
        name=entry["name"],
        test_command=entry.get("test_command"),
        # Only a YAML boolean true. A quoted "yes" keeps the gate.
        auto_approve=entry.get("auto_approve") is True,
    )
```

`app/chores.py`, update the module docstring's last sentence to say a repo marked `auto_approve` skips the question for every source but chat, then add below `_SET_MESSAGE_FROM_APPROVAL`:

```python
_CREATE_STARTED = """
INSERT INTO runs (task, type, provider, repo, status, source)
VALUES (%s, 'repo_chore', %s, %s, 'pending', %s) RETURNING id
"""
```

and below `find_repo`:

```python
def starts_unasked(repo: RepoConfig, source: str) -> bool:
    """A repo marked auto_approve skips the question, except for a chore asked
    for in chat, where the owner is there to press the button and the chat
    has already told them it is waiting."""
    return repo.auto_approve and source != "telegram"


def start_chore(
    conn: psycopg.Connection, repo: RepoConfig, instruction: str, source: str, provider: str
) -> str:
    """Create the chore pending, where the worker claims it. Only for a repo
    starts_unasked allows. No chat id, so no progress message and no Open it
    anyway button."""
    run_id = conn.execute(
        _CREATE_STARTED, (instruction.strip(), provider, repo.name, source)
    ).fetchone()[0]
    return str(run_id)
```

`app/run_api.py`, import `start_chore, starts_unasked` from `app.chores`, and in `_request_chore` insert right after the `find_repo` try block, before `settings = state.settings`:

```python
    if starts_unasked(repo, source):
        with connect(state.settings.database_url, autocommit=True) as conn:
            run_id = start_chore(
                conn, repo, run.inputs["task"], source, TASK_TYPES["repo_chore"].provider
            )
        return RunCreated(id=run_id, status="pending")
```

`app/mcp_server.py`: in `CREATE_RUN`, change "A repo_chore does not start here: it waits for the owner to press Approve on Telegram" to say it waits for Approve on Telegram unless the repo is marked `auto_approve` in the config, and change the server `instructions` string to `"Queue and read Mercury runs. Repo chores need approval on Telegram unless the repo is marked auto_approve."`. Update the module docstring line "There is no approve tool. A chore created here waits for the Approve button" to add "unless its repo is marked auto_approve".

`config/mercury.sample.yaml`, under the `repos:` comment, add a line after `owner/repo-one`'s `test_command`:

```yaml
      auto_approve: false  # true starts chores from the API, MCP or n8n without asking; throwaway repos only
```

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_repo_chore_approval.py tests/test_mcp.py -v`
Expected: PASS.
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass, integration tests that need a token or compose skip as before.

- [ ] **Step 5: Commit**

```bash
git add app/mercury_config.py app/chores.py app/run_api.py app/mcp_server.py config/mercury.sample.yaml tests/test_repo_chore_approval.py
git commit -m "Start a chore without asking on a repo marked auto_approve, except one asked for in chat"
```

---

### Task 2: A run may name its provider

**Files:**
- Modify: `app/run_request.py` (`provider` field and validators)
- Modify: `app/run_api.py` (`create_run`, `_request_chore`)
- Modify: `app/chores.py` (`request_chore` takes `provider`)
- Modify: `app/mcp_server.py` (`create_run_tool` takes `provider`)
- Modify: `app/worker.py` (`_process_run`, `_with_fallback`)
- Test: `tests/test_runs.py`, `tests/test_repo_chore_approval.py`, `tests/test_mcp.py`, `tests/test_fallback.py`

**Interfaces:**
- Consumes: `start_chore(conn, repo, instruction, source, provider)` from Task 1.
- Produces: `POST /runs` body field `provider: str | None` (a key of `app.config.PROVIDERS`); MCP `create_run` argument `provider`; `request_chore(..., source, provider: str | None = None)`. The worker builds a run's model from `runs.provider`, which is the type's provider unless the caller named one.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runs.py`:

```python
def test_a_run_may_name_its_provider(start_server, clean_db, auth_headers):
    base_url = start_server()

    response = httpx2.post(
        f"{base_url}/runs",
        json={"type": "pytest", "inputs": {"task": "x"}, "provider": "ollama"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    with psycopg.connect(clean_db) as conn:
        row = conn.execute(
            "SELECT provider FROM runs WHERE id = %s", (response.json()["id"],)
        ).fetchone()
    assert row == ("ollama",)


def test_an_unknown_provider_is_refused(start_server, clean_db, auth_headers):
    base_url = start_server()

    response = httpx2.post(
        f"{base_url}/runs",
        json={"type": "pytest", "inputs": {"task": "x"}, "provider": "gpt-9"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    with psycopg.connect(clean_db) as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone() == (0,)


def test_a_provider_on_a_site_check_is_refused(start_server, auth_headers):
    base_url = start_server()

    response = httpx2.post(
        f"{base_url}/runs",
        json={"type": "site_check", "inputs": {"task": "https://example.com"}, "provider": "gemini"},
        headers=auth_headers,
    )

    assert response.status_code == 422
```

Append to `tests/test_repo_chore_approval.py`:

```python
def test_an_auto_approved_chore_runs_on_the_provider_it_names(
    auto_bot, fake_telegram, migrated_db
):
    response = post_chore(auto_bot, provider="ollama")

    assert response.status_code == 201
    assert migrated_db.execute("SELECT provider FROM runs").fetchone() == ("ollama",)


def test_a_gated_chore_keeps_the_provider_it_names(bot, fake_telegram, migrated_db):
    post_chore(bot, provider="ollama")

    assert migrated_db.execute("SELECT status, provider FROM runs").fetchone() == (
        "awaiting_approval",
        "ollama",
    )
```

Append to `tests/test_mcp.py` (it reuses the file's `api` fixture and `call` helper):

```python
def test_create_run_takes_a_provider(api, migrated_db):
    created = call(api, "create_run", type="pytest", task=TEST_FILE, provider="ollama")

    row = migrated_db.execute(
        "SELECT provider, source FROM runs WHERE id = %s", (created["id"],)
    ).fetchone()
    assert row == ("ollama", "mcp")
```

Append to `tests/test_fallback.py`:

```python
def _recording(seen: list[str]):
    def build(settings, provider_name):
        seen.append(provider_name)
        return StubModel(replies=['{"action": "ask", "question": "Which URL?"}'])

    return build


def _chat_run_on(conn, provider: str) -> str:
    run_id = conn.execute(
        "INSERT INTO runs (task, type, provider, telegram_chat_id, telegram_message_id) "
        "VALUES ('check my site', 'chat', %s, 42, 7) RETURNING id::text",
        (provider,),
    ).fetchone()[0]
    claim_run(conn, run_id, "worker-test")
    return run_id


def test_a_run_is_built_on_the_provider_its_row_names(migrated_db, fake_telegram):
    run_id = _chat_run_on(migrated_db, "haiku")
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )
    seen: list[str] = []

    process_run(migrated_db, run_id, settings, model_builder=_recording(seen))

    # chat's own fallback, gemini, still stands behind the provider the row named.
    assert seen == ["haiku", "gemini"]


def test_a_run_already_on_its_types_fallback_gets_no_fallback_behind_it(
    migrated_db, fake_telegram
):
    run_id = _chat_run_on(migrated_db, "gemini")
    settings = settings_with(
        worker_id="worker-test", telegram_bot_token="1:a", telegram_api_url=fake_telegram.url
    )
    seen: list[str] = []

    process_run(migrated_db, run_id, settings, model_builder=_recording(seen))

    assert seen == ["gemini"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_runs.py tests/test_repo_chore_approval.py tests/test_mcp.py tests/test_fallback.py -k "provider" -v`
Expected: FAIL. The posted provider is ignored (row says `gemini`), the unknown provider is accepted with 201, the MCP tool rejects the unexpected `provider` argument, and the worker builds `ollama` for the chat run.

- [ ] **Step 3: Implement**

`app/run_request.py`: import `PROVIDERS` from `app.config`, add the field after `source`, and two validators:

```python
    # A key of app.config.PROVIDERS. None runs on the type's own provider.
    provider: str | None = None

    @field_validator("provider")
    @classmethod
    def provider_must_be_registered(cls, value: str | None) -> str | None:
        if value is not None and value not in PROVIDERS:
            raise ValueError(f"unknown provider {value!r}")
        return value

    @model_validator(mode="after")
    def only_a_model_run_names_a_provider(self) -> "RunRequest":
        if self.provider is not None and TASK_TYPES[self.type].provider is None:
            raise ValueError(f"a {self.type} run calls no model, so it takes no provider")
        return self
```

`app/chores.py`, `request_chore` gains a keyword `provider: str | None = None` after `source`, and its insert uses `provider or TASK_TYPES["repo_chore"].provider` in place of `TASK_TYPES["repo_chore"].provider`. Chat calls it without a provider and is unchanged.

`app/run_api.py`:
- In `create_run`, replace `TASK_TYPES[run.type].provider,` in the insert values with `run.provider or TASK_TYPES[run.type].provider,`.
- In `_request_chore`, pass `run.provider or TASK_TYPES["repo_chore"].provider` to `start_chore` in place of `TASK_TYPES["repo_chore"].provider`, and call `request_chore(conn, telegram, chat_id, repo, run.inputs["task"], source, provider=run.provider)`.

`app/mcp_server.py`, `create_run_tool`:

```python
    async def create_run_tool(
        type: str,
        task: str,
        kind: str | None = None,
        repo: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        inputs: dict[str, Any] = {"task": task}
        if kind is not None:
            inputs["kind"] = kind
        if repo is not None:
            inputs["repo"] = repo
        try:
            run = RunRequest(type=type, inputs=inputs, provider=provider)
```

(the rest of the function is unchanged). Add one sentence to `CREATE_RUN`: `provider is optional, one of gemini, ollama or haiku; leave it out to use the type's default.`

`app/worker.py`, in `_process_run`, after `task_type = TASK_TYPES[task_type_name]`:

```python
    # The row's provider is the type's own unless the caller named one.
    provider = (
        conn.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()[0]
        or task_type.provider
    )
```

then use `provider` in place of `task_type.provider` in the `check_budget(...)` call, the `model_builder(settings, ...)` call and the `run_agent_loop(..., provider=...)` argument, and call `_with_fallback(conn, run_id, model, task_type, settings, model_builder, provider)`. `_with_fallback` gains a final parameter `provider: str`, returns `model` unchanged when `task_type.fallback is None or task_type.fallback == provider`, and logs `provider` in place of `task_type.provider` in `switch()`.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_runs.py tests/test_repo_chore_approval.py tests/test_mcp.py tests/test_fallback.py -v`
Expected: PASS.
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass. If an older worker test inserts a run whose `provider` differs from its type's and asserts on the builder's argument, make the row's provider match the type. Do not change the new behaviour.

- [ ] **Step 5: Commit**

```bash
git add app/run_request.py app/run_api.py app/chores.py app/mcp_server.py app/worker.py tests/test_runs.py tests/test_repo_chore_approval.py tests/test_mcp.py tests/test_fallback.py
git commit -m "Let a run name its provider, and build its model from the provider on its row"
```

---

### Task 3: The eval runner and the task set

**Files:**
- Create: `evals/__init__.py` (empty)
- Create: `evals/runner.py`
- Create: `evals/chores/divide.yaml`, `clamp.yaml`, `slugify.yaml`, `roman.yaml`, `duration.yaml`, `word_count.yaml`, `most_common.yaml`, `cli.yaml`
- Create: `evals/results/.gitkeep`
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `POST /runs` with `provider` (Task 2) on a repo with `auto_approve` (Task 1); `GET /runs/{id}` returning `status`, `provider`, `tokens`, `duration_seconds`; `app.config.PROVIDERS[name].usd_per_million_tokens`.
- Produces: `uv run python -m evals.runner --providers gemini,ollama [--repeats N] [--only id,id]`, reading `MERCURY_URL`, `MERCURY_BEARER_TOKEN` and `MERCURY_GITHUB_TOKEN` from the environment, writing `evals/results/<UTC stamp>.json` and `.md`.

**How to write a task.** Each instruction names the file, the function signature, the behaviour on the edge cases and the error to raise, and asks for a test in the repo's own `test_<module>.py`. A task a reader would have to ask a question about is not well defined and does not belong in the set. The grade test checks only what the instruction states. The runner adds two checks of its own to every task, so a grade never needs to repeat them. Every test id on `main` must still exist on the branch, and the branch's own `unittest discover` must pass.

- [ ] **Step 1: Write the failing tests**

`tests/test_eval_runner.py`:

```python
"""The eval runner, against a local bare repo and fake API and GitHub
clients. The live run is in the README, not here."""

import subprocess
from pathlib import Path

import pytest

from app.config import PROVIDERS
from evals import runner
from evals.runner import EvalAborted, EvalRow, EvalTask, grade_branch, load_tasks, run_one, summarise

GRADE_PASS = "import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
GRADE_FAIL = GRADE_PASS.replace("5)", "6)")
SEED_TEST = "import unittest\nfrom calc import add\n\n\nclass AddTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
GRADE_CALLABLE = "import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add_exists(self):\n        self.assertTrue(callable(add))\n"
GRADE_MISSING = "import unittest\nfrom roman import to_roman\n\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(to_roman(1), 'I')\n"


def _remote(
    tmp_path: Path, branch: str = "agent/run-1", seed_test: bool = False,
    on_branch: dict[str, str] | None = None,
) -> str:
    work = tmp_path / "work"
    work.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    if seed_test:
        (work / "test_calc.py").write_text(SEED_TEST)
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    git("checkout", "-q", "-b", branch)
    for name, text in (on_branch or {}).items():
        (work / name).write_text(text)
    if on_branch:
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "chore")
    git("checkout", "-q", "main")  # the remote's HEAD is main, as on GitHub
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare.as_uri()


def test_a_branch_that_meets_the_grade_passes(tmp_path):
    passed, output = grade_branch(_remote(tmp_path), "agent/run-1", GRADE_PASS)
    assert passed
    assert "OK" in output


def test_a_branch_that_misses_the_grade_fails(tmp_path):
    passed, _ = grade_branch(_remote(tmp_path), "agent/run-1", GRADE_FAIL)
    assert not passed


def test_a_grade_that_cannot_import_its_module_fails_without_raising(tmp_path):
    passed, output = grade_branch(_remote(tmp_path), "agent/run-1", GRADE_MISSING)
    assert not passed
    assert "roman" in output


def test_a_missing_branch_fails_the_grade(tmp_path):
    passed, output = grade_branch(_remote(tmp_path), "agent/other", GRADE_PASS)
    assert not passed
    assert output.startswith("clone failed")


def test_a_branch_that_deletes_a_test_from_main_fails(tmp_path):
    remote = _remote(tmp_path, seed_test=True, on_branch={"test_calc.py": "import unittest\n"})
    passed, output = grade_branch(remote, "agent/run-1", GRADE_PASS)
    assert not passed
    assert output.startswith("tests removed")
    assert "test_add" in output


def test_a_branch_that_breaks_its_own_tests_fails(tmp_path):
    remote = _remote(tmp_path, seed_test=True, on_branch={"calc.py": "def add(a, b):\n    return a - b\n"})
    passed, output = grade_branch(remote, "agent/run-1", GRADE_CALLABLE)
    assert not passed
    assert output.startswith("own tests failed")


def test_a_branch_that_keeps_main_tests_and_adds_its_own_passes(tmp_path):
    extra = SEED_TEST + "\n    def test_add_negative(self):\n        self.assertEqual(add(-1, 1), 0)\n"
    remote = _remote(tmp_path, seed_test=True, on_branch={"test_calc.py": extra})
    passed, output = grade_branch(remote, "agent/run-1", GRADE_PASS)
    assert passed, output


def test_tasks_load_from_yaml_named_by_their_file(tmp_path):
    (tmp_path / "b.yaml").write_text("repo: o/r\ninstruction: |\n  Do b.\ngrade: |\n  x = 1\n")
    (tmp_path / "a.yaml").write_text("repo: o/r\ninstruction: Do a.\ngrade: x = 2\n")

    tasks = load_tasks(tmp_path)

    assert [t.id for t in tasks] == ["a", "b"]
    assert tasks[1] == EvalTask(id="b", repo="o/r", instruction="Do b.", grade="x = 1\n")


def test_every_shipped_task_names_the_fixture_and_has_a_grade():
    tasks = load_tasks(Path("evals/chores"))
    assert len(tasks) == 8
    assert {t.repo for t in tasks} == {"thomas-whitley/mercury-fixture"}
    assert all("unittest" in t.grade for t in tasks)


class _Response:
    def __init__(self, status_code: int, body: dict | None = None, text: str = "") -> None:
        self.status_code, self._body, self.text = status_code, body or {}, text

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Api:
    """POST /runs answers created; GET /runs/{id} walks through statuses."""

    def __init__(self, created: _Response, statuses: list[dict]) -> None:
        self.created, self.statuses, self.posted = created, list(statuses), []

    def post(self, path: str, json: dict) -> _Response:
        self.posted.append(json)
        return self.created

    def get(self, path: str) -> _Response:
        return _Response(200, self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])


class _GitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, params: dict | None = None) -> _Response:
        self.calls.append(("get", path))
        return _Response(200, [{"number": 7}])  # type: ignore[arg-type]

    def patch(self, path: str, json: dict) -> _Response:
        self.calls.append(("patch", path))
        return _Response(200)

    def delete(self, path: str) -> _Response:
        self.calls.append(("delete", path))
        return _Response(204)


TASK = EvalTask(id="divide", repo="o/fixture", instruction="Add divide.", grade=GRADE_PASS)
DONE = {"status": "succeeded", "provider": "gemini", "tokens": 900, "duration_seconds": 40.0}


def _run(api, github, **kw) -> EvalRow:
    ticks = iter(range(0, 10_000, 5))
    return run_one(
        api, github, TASK, "gemini", "file:///unused", None,
        timeout_seconds=kw.get("timeout", 900), poll_seconds=0,
        sleep=lambda s: None, clock=lambda: next(ticks),
    )


def test_a_green_chore_is_graded_and_its_pull_request_closed(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", lambda *a, **k: (True, "OK"))
    api = _Api(_Response(201, {"id": "run-1", "status": "pending"}), [{"status": "running"}, DONE])
    github = _GitHub()

    row = _run(api, github)

    assert api.posted == [
        {"type": "repo_chore", "inputs": {"task": "Add divide.", "repo": "o/fixture"}, "provider": "gemini"}
    ]
    assert (row.status, row.graded, row.tokens, row.answered_by) == ("succeeded", True, 900, "gemini")
    assert ("patch", "/repos/o/fixture/pulls/7") in github.calls
    assert ("delete", "/repos/o/fixture/git/refs/heads/agent/run-1") in github.calls


def test_a_red_chore_is_not_graded_and_nothing_is_closed(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", pytest.fail)
    api = _Api(_Response(201, {"id": "run-1", "status": "pending"}), [{**DONE, "status": "failed"}])
    github = _GitHub()

    row = _run(api, github)

    assert (row.status, row.graded) == ("failed", False)
    assert github.calls == []


def test_a_chore_that_never_finishes_is_a_timeout():
    api = _Api(_Response(201, {"id": "run-1", "status": "pending"}), [{"status": "running", "tokens": 0}])

    row = _run(api, _GitHub(), timeout=60)

    assert (row.status, row.graded) == ("timeout", False)


def test_a_refused_chore_is_recorded_not_raised():
    api = _Api(_Response(422, text='{"detail":"I can only work on a/b."}'), [])

    row = _run(api, _GitHub())

    assert (row.status, row.run_id) == ("refused", None)
    assert "only work on" in row.detail


def test_a_chore_waiting_for_approval_stops_the_batch():
    api = _Api(_Response(201, {"id": "run-1", "status": "awaiting_approval"}), [])

    with pytest.raises(EvalAborted, match="auto_approve"):
        _run(api, _GitHub())


def test_cost_uses_the_rate_of_the_provider_that_answered(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", lambda *a, **k: (True, "OK"))
    answered = {**DONE, "provider": "haiku", "tokens": 1_000_000}
    api = _Api(_Response(201, {"id": "run-1", "status": "pending"}), [answered])

    row = _run(api, _GitHub())

    assert row.usd == pytest.approx(PROVIDERS["haiku"].usd_per_million_tokens)


def test_the_summary_counts_hidden_test_passes_per_provider():
    def row(provider: str, graded: bool, status: str = "succeeded") -> EvalRow:
        return EvalRow("t", provider, provider, "id", status, graded, 1000, 30.0, 0.0)

    table = summarise([row("gemini", True), row("gemini", False, "failed"), row("ollama", True)])

    assert "| gemini | 1 of 2 | 1 of 2 | 1000 | 30 | 0.0000 |" in table
    assert "| ollama | 1 of 1 | 1 of 1 | 1000 | 30 | 0.0000 |" in table
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals'`.

- [ ] **Step 3: Write the runner**

`evals/__init__.py` is empty. `evals/runner.py`:

```python
"""Runs Mercury's chore evals against a live deploy and grades each result
with a test the model never saw.

A task is one YAML file under evals/chores/: the repo, an instruction that
names every file and function it expects, and a grade test. Each task runs
once per provider per repeat as a repo_chore through POST /runs. A chore
that opens a pull request is graded by cloning its branch and the default
branch. It passes when no test the default branch has is gone, the repo's
own tests pass, and the grade test passes. The pull request is then closed and the branch
deleted, so the fixture keeps only main.

uv run python -m evals.runner --providers gemini,ollama --repeats 1
reads MERCURY_URL, MERCURY_BEARER_TOKEN and MERCURY_GITHUB_TOKEN.
"""

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import yaml

from app.config import PROVIDERS

OPEN = {"pending", "running", "awaiting_approval"}
GRADE_MODULE = "grade_hidden"
# Prints every test id unittest discovers, one per line, without running any.
LIST_TESTS = (
    "import unittest\n"
    "def walk(suite):\n"
    "    for t in suite:\n"
    "        walk(t) if isinstance(t, unittest.TestSuite) else print(t.id())\n"
    "walk(unittest.defaultTestLoader.discover('.'))\n"
)
HERE = Path(__file__).parent


class EvalAborted(Exception):
    """The batch cannot go on, for example because chores wait for Approve."""


@dataclass(frozen=True)
class EvalTask:
    id: str
    repo: str
    instruction: str
    grade: str


@dataclass
class EvalRow:
    task: str
    provider: str  # asked for
    answered_by: str | None  # runs.provider at the end, after any fallback
    run_id: str | None
    status: str  # the run's final status, or timeout, or refused
    graded: bool  # passed the hidden test
    tokens: int
    seconds: float | None
    usd: float
    detail: str = ""


def load_tasks(directory: Path) -> list[EvalTask]:
    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        tasks.append(
            EvalTask(
                id=path.stem,
                repo=data["repo"],
                instruction=data["instruction"].strip(),
                grade=data["grade"],
            )
        )
    return tasks


def _env(home: str, token: str | None) -> dict[str, str]:
    """No secret but the token, and that only as git's own header."""
    env = {"PATH": os.environ["PATH"], "HOME": home, "GIT_TERMINAL_PROMPT": "0"}
    if "SYSTEMROOT" in os.environ:  # Windows cannot start a process without it
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    return env


def _run(args: list[str], cwd: Path | str, env: dict[str, str], timeout: float):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def _test_ids(work: Path, env: dict[str, str], timeout: float) -> set[str]:
    return set(_run([sys.executable, "-c", LIST_TESTS], work, env, timeout).stdout.split())


def grade_branch(
    clone_url: str, branch: str, grade_source: str, token: str | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Clone the branch and the default branch. The branch passes when no
    test the default branch has is gone, its own tests pass and the grade
    test passes. Never raises for a bad branch or a bad grade; the answer is
    the boolean."""
    with tempfile.TemporaryDirectory() as home:
        plain = _env(home, None)
        try:
            for name, extra in (("work", ["--branch", branch]), ("base", [])):
                clone = _run(
                    ["git", "clone", "-q", "--depth", "1", *extra, clone_url, name],
                    home, _env(home, token), timeout_seconds,
                )
                if clone.returncode != 0:
                    return False, "clone failed: " + clone.stderr[-1000:]
            work = Path(home) / "work"
            lost = _test_ids(Path(home) / "base", plain, timeout_seconds) - _test_ids(work, plain, timeout_seconds)
            if lost:
                return False, "tests removed: " + ", ".join(sorted(lost))
            own = _run([sys.executable, "-m", "unittest", "discover", "-v"], work, plain, timeout_seconds)
            # 5 is unittest's "no tests ran", which a repo with no tests yet returns.
            if own.returncode not in (0, 5):
                return False, "own tests failed: " + (own.stdout + own.stderr)[-3000:]
            (work / f"{GRADE_MODULE}.py").write_text(grade_source)
            result = _run([sys.executable, "-m", "unittest", "-v", GRADE_MODULE], work, plain, timeout_seconds)
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout_seconds:.0f} s"
        return result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def close_pull_and_branch(github, repo: str, branch: str) -> None:
    owner = repo.split("/")[0]
    pulls = github.get(f"/repos/{repo}/pulls", params={"head": f"{owner}:{branch}", "state": "open"})
    for pull in pulls.json():
        github.patch(f"/repos/{repo}/pulls/{pull['number']}", json={"state": "closed"})
    github.delete(f"/repos/{repo}/git/refs/heads/{branch}")


def run_one(
    api, github, task: EvalTask, provider: str, clone_base: str, token: str | None, *,
    timeout_seconds: float, poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
) -> EvalRow:
    created = api.post(
        "/runs",
        json={
            "type": "repo_chore",
            "inputs": {"task": task.instruction, "repo": task.repo},
            "provider": provider,
        },
    )
    if created.status_code != 201:
        return EvalRow(task.id, provider, None, None, "refused", False, 0, None, 0.0,
                       created.text[:300])
    run = created.json()
    if run["status"] == "awaiting_approval":
        raise EvalAborted(
            f"run {run['id']} is waiting for Approve: {task.repo} is not auto_approve in the "
            "live mercury.yaml. Decline it on Telegram, set auto_approve, and run again."
        )
    run_id = run["id"]
    deadline = clock() + timeout_seconds
    while True:
        response = api.get(f"/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["status"] not in OPEN:
            break
        if clock() >= deadline:
            run = {**run, "status": "timeout"}
            break
        sleep(poll_seconds)

    graded, detail = False, ""
    if run["status"] == "succeeded":
        branch = f"agent/{run_id}"
        graded, detail = grade_branch(f"{clone_base}/{task.repo}.git", branch, task.grade, token)
        close_pull_and_branch(github, task.repo, branch)
    tokens = run.get("tokens") or 0
    answered = run.get("provider")
    rate = PROVIDERS[answered].usd_per_million_tokens if answered in PROVIDERS else 0.0
    return EvalRow(task.id, provider, answered, run_id, run["status"], graded, tokens,
                   run.get("duration_seconds"), tokens * rate / 1_000_000, detail[-2000:])


def summarise(rows: list[EvalRow]) -> str:
    lines = [
        "| Provider | Passed the hidden test | Opened a PR | Median tokens | Median seconds | Cost USD |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for provider in sorted({row.provider for row in rows}):
        mine = [row for row in rows if row.provider == provider]
        seconds = [row.seconds for row in mine if row.seconds is not None]
        lines.append(
            f"| {provider} | {sum(r.graded for r in mine)} of {len(mine)} "
            f"| {sum(r.status == 'succeeded' for r in mine)} of {len(mine)} "
            f"| {statistics.median(r.tokens for r in mine):.0f} "
            f"| {f'{statistics.median(seconds):.0f}' if seconds else 'n/a'} "
            f"| {sum(r.usd for r in mine):.4f} |"
        )
    lines += ["", "| Task | Provider | Status | Hidden test |", "| --- | --- | --- | --- |"]
    for row in sorted(rows, key=lambda r: (r.task, r.provider)):
        lines.append(f"| {row.task} | {row.provider} | {row.status} | {'pass' if row.graded else 'fail'} |")
    return "\n".join(lines)


def write_results(rows: list[EvalRow], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    (out / f"{stamp}.json").write_text(json.dumps([asdict(r) for r in rows], indent=2) + "\n")
    report = out / f"{stamp}.md"
    report.write_text(summarise(rows) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the live deploy
    parser = argparse.ArgumentParser(description="Run the chore evals against a live Mercury.")
    parser.add_argument("--providers", default="gemini,ollama")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--only", default="", help="comma separated task ids")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)

    providers = [p for p in args.providers.split(",") if p]
    unknown = [p for p in providers if p not in PROVIDERS]
    if unknown:
        parser.error(f"unknown provider {unknown[0]}; known: {', '.join(PROVIDERS)}")
    tasks = load_tasks(HERE / "chores")
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t.id in wanted]

    token = os.environ["MERCURY_GITHUB_TOKEN"]
    api = httpx2.Client(
        base_url=os.environ["MERCURY_URL"].rstrip("/"),
        headers={"Authorization": f"Bearer {os.environ['MERCURY_BEARER_TOKEN']}"},
        timeout=60,
    )
    github = httpx2.Client(
        base_url="https://api.github.com",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    rows: list[EvalRow] = []
    try:
        for _ in range(args.repeats):
            for task in tasks:
                for provider in providers:
                    row = run_one(api, github, task, provider, "https://github.com", token,
                                  timeout_seconds=args.timeout, poll_seconds=5.0)
                    rows.append(row)
                    print(f"{task.id} {provider}->{row.answered_by} {row.status} "
                          f"hidden={'pass' if row.graded else 'fail'} tokens={row.tokens}",
                          flush=True)
    except EvalAborted as stop:
        print(stop, file=sys.stderr)
    finally:
        if rows:
            report = write_results(rows, HERE / "results")
            print(report.read_text())
            print(f"written to {report}")
    return 0 if rows else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

Check `_env` against the header `app/repo_chore.py` builds (`grep -n extraheader app/repo_chore.py`). If that module uses a different scheme or user name, copy its form exactly so both paths authenticate the same way. Run `uv run ruff format evals tests/test_eval_runner.py` to wrap the long lines.

- [ ] **Step 4: Write the eight tasks**

Every file has `repo: thomas-whitley/mercury-fixture`. The fixture's `main` holds `calc.py` with `add(a, b)` and `test_calc.py`; Task 4 seeds `textstats.py` and `test_textstats.py` for the two textstats tasks.

`evals/chores/divide.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  In calc.py, add divide(a, b) that returns a / b as a float. If b is 0 it must raise
  ValueError with the message "cannot divide by zero". Add tests for both cases to test_calc.py.
grade: |
  import unittest
  from calc import divide


  class Grade(unittest.TestCase):
      def test_divides(self):
          self.assertEqual(divide(7, 2), 3.5)

      def test_zero(self):
          with self.assertRaisesRegex(ValueError, "cannot divide by zero"):
              divide(1, 0)
```

`evals/chores/clamp.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  In calc.py, add clamp(value, low, high) that returns low if value is below low, high if
  value is above high, and value otherwise. If low is greater than high it must raise
  ValueError. Add tests to test_calc.py.
grade: |
  import unittest
  from calc import clamp


  class Grade(unittest.TestCase):
      def test_inside(self):
          self.assertEqual(clamp(5, 1, 10), 5)

      def test_edges(self):
          self.assertEqual(clamp(-3, 0, 10), 0)
          self.assertEqual(clamp(30, 0, 10), 10)
          self.assertEqual(clamp(10, 0, 10), 10)

      def test_bad_range(self):
          with self.assertRaises(ValueError):
              clamp(5, 10, 1)
```

`evals/chores/slugify.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  Create slug.py with slugify(text) that lowercases the text, replaces every run of
  characters that are not ASCII letters or digits with a single hyphen, and strips hyphens
  from both ends. slugify("Hello, World!") is "hello-world" and slugify("") is "".
  Add test_slug.py with tests.
grade: |
  import unittest
  from slug import slugify


  class Grade(unittest.TestCase):
      def test_basic(self):
          self.assertEqual(slugify("Hello, World!"), "hello-world")

      def test_runs_and_ends(self):
          self.assertEqual(slugify("  --A__b--  "), "a-b")
          self.assertEqual(slugify("Café au lait"), "caf-au-lait")

      def test_empty(self):
          self.assertEqual(slugify(""), "")
          self.assertEqual(slugify("!!!"), "")
```

`evals/chores/roman.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  Create roman.py with to_roman(n) that returns the Roman numeral for an int from 1 to 3999
  using subtractive notation (4 is IV, 9 is IX, 40 is XL, 90 is XC, 400 is CD, 900 is CM).
  Any other value must raise ValueError. Add test_roman.py with tests.
grade: |
  import unittest
  from roman import to_roman


  class Grade(unittest.TestCase):
      def test_values(self):
          cases = {1: "I", 4: "IV", 9: "IX", 14: "XIV", 40: "XL", 90: "XC",
                   400: "CD", 1994: "MCMXCIV", 2026: "MMXXVI", 3999: "MMMCMXCIX"}
          for n, numeral in cases.items():
              self.assertEqual(to_roman(n), numeral)

      def test_out_of_range(self):
          for n in (0, -1, 4000):
              with self.assertRaises(ValueError):
                  to_roman(n)
```

`evals/chores/duration.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  Create duration.py with parse_duration(text) that returns a number of seconds as an int.
  The text is one or more of an integer followed by h, m or s, in that order, each at most
  once, with no spaces: "1h30m" is 5400, "45s" is 45, "2h" is 7200, "1h0m5s" is 3605.
  Anything else, including "", "5x", "m5", "30m1h" and "1h1h", must raise ValueError.
  Add test_duration.py with tests.
grade: |
  import unittest
  from duration import parse_duration


  class Grade(unittest.TestCase):
      def test_values(self):
          self.assertEqual(parse_duration("1h30m"), 5400)
          self.assertEqual(parse_duration("45s"), 45)
          self.assertEqual(parse_duration("2h"), 7200)
          self.assertEqual(parse_duration("1h0m5s"), 3605)

      def test_invalid(self):
          for text in ("", "5x", "m5", "30m1h", "1h1h", "1 h"):
              with self.assertRaises(ValueError, msg=text):
                  parse_duration(text)
```

`evals/chores/word_count.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  word_count in textstats.py is wrong when words are separated by more than one space, by a
  newline or by a tab, and it returns 1 for an empty string. Fix it so it returns the number
  of whitespace separated words. Add tests for those cases to test_textstats.py.
grade: |
  import unittest
  from textstats import word_count


  class Grade(unittest.TestCase):
      def test_spacing(self):
          self.assertEqual(word_count("a  b"), 2)
          self.assertEqual(word_count("a\nb\tc"), 3)
          self.assertEqual(word_count("  lead and trail  "), 3)

      def test_empty(self):
          self.assertEqual(word_count(""), 0)
          self.assertEqual(word_count("   "), 0)
```

`evals/chores/most_common.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  In textstats.py, add most_common(text, n) that returns a list of the n most frequent words
  as (word, count) tuples. Words are whitespace separated and compared lowercased. Order by
  count, highest first, and break ties alphabetically. If there are fewer than n distinct
  words, return them all. n below 1 must raise ValueError. Add tests to test_textstats.py.
grade: |
  import unittest
  from textstats import most_common


  class Grade(unittest.TestCase):
      def test_order_and_ties(self):
          text = "b a B c a b"
          self.assertEqual(most_common(text, 2), [("b", 3), ("a", 2)])
          self.assertEqual(most_common("z y x", 3), [("x", 1), ("y", 1), ("z", 1)])

      def test_fewer_words_than_n(self):
          self.assertEqual(most_common("one", 5), [("one", 1)])

      def test_bad_n(self):
          with self.assertRaises(ValueError):
              most_common("a b", 0)
```

`evals/chores/cli.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  Make calc.py runnable as python -m calc add A B, which prints the sum of the integers A and
  B followed by a newline and exits 0. Any other command, a wrong number of arguments or an
  argument that is not an integer must print a message to stderr and exit with status 2.
  Use only the standard library and keep add importable. Add tests to test_calc.py.
grade: |
  import subprocess
  import sys
  import unittest


  def run(*args):
      return subprocess.run([sys.executable, "-m", "calc", *args], capture_output=True, text=True)


  class Grade(unittest.TestCase):
      def test_add(self):
          result = run("add", "2", "3")
          self.assertEqual((result.returncode, result.stdout), (0, "5\n"))

      def test_bad_input(self):
          for args in (["sub", "2", "3"], ["add", "2"], ["add", "two", "3"]):
              result = run(*args)
              self.assertEqual(result.returncode, 2, args)
              self.assertTrue(result.stderr, args)
```

Create the empty `evals/results/.gitkeep`.

- [ ] **Step 5: Run the tests to verify they pass, then the whole suite**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: PASS, 16 tests.
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add evals tests/test_eval_runner.py
git commit -m "Add an eval runner that grades chores with a hidden test, and eight fixture tasks"
```

---

### Task 4: Deploy, seed the fixture, mark it auto_approve

Every step here is outward and is Thomas's to approve, one at a time. The agent prepares each change and shows it; Thomas says yes before each push.

- [ ] **Step 1: Push the public commits** from Tasks 1 to 3 and wait for CI and Publish to go green on `thomas-whitley/mercury`.

- [ ] **Step 2: Seed the fixture.** On `thomas-whitley/mercury-fixture` `main`, add these two files in one commit, `Seed textstats with a known word_count bug for the evals`:

`textstats.py`:

```python
"""Text statistics for Mercury's evals. word_count has a known bug the evals ask a model to fix."""


def word_count(text: str) -> int:
    return len(text.split(" "))
```

`test_textstats.py`:

```python
import unittest

from textstats import word_count


class WordCount(unittest.TestCase):
    def test_single_spaces(self):
        self.assertEqual(word_count("one two three"), 3)
```

Check `python -m unittest -v` passes in a clone before pushing.

- [ ] **Step 3: Configure and deploy.** In `mercury-config`, add `auto_approve: true` to the `thomas-whitley/mercury-fixture` entry under `portfolio.repos` in `mercury.yaml`, and bump `PUBLIC_SHA` to the Task 3 commit, in one commit. Wait for Deploy to go green.

- [ ] **Step 4: Smoke test.** With `MERCURY_URL` set to the live API and the two tokens loaded from `.env`, run:

```bash
uv run python -m evals.runner --providers gemini --only divide
```

Expected: one line `divide gemini->gemini succeeded hidden=pass tokens=<n>` (or a fail with a reason), a report under `evals/results/`, no message on Telegram, and no PR or `agent/` branch left on the fixture (`gh pr list -R thomas-whitley/mercury-fixture` shows only PR #4).

---

### Task 5: The first measured run, and the README

- [ ] **Step 1: Run the full set once on both free providers**, in the background since it takes up to an hour:

```bash
uv run python -m evals.runner --providers gemini,ollama --repeats 1
```

Sixteen runs. Each chore is capped at 50,000 tokens and the daily cap is 500,000 per provider, so one repeat cannot trip the daily cap. Run `--repeats 3` only on a later day, or after checking the day's token use in `/status`.

- [ ] **Step 2: Read the failures before writing anything.** For every row that is not a hidden test pass, read the run's events (`get_run_events` over MCP, or the run page with the token) and sort it into one of three causes: the model's change was wrong, the instruction was ambiguous, or Mercury itself failed (clone, push, timeout, provider error). A task whose instruction was ambiguous gets fixed and the batch is rerun for that task with `--only`. A Mercury failure is a bug and gets its own test first.

- [ ] **Step 3: Commit the report** `evals/results/<stamp>.json` and `.md`.

- [ ] **Step 4: README.** Add a section `## Evals` after the repo chore section, saying in complete sentences what a task is, that the grade test never reaches the model, how a run is graded, and the command to rerun it. Paste the provider table from the report under it. Add a claims table row `A cheap model completes well defined chores, graded by tests it never saw | evals/runner.py, evals/results/<stamp>.md | <gemini x of 8, ollama y of 8, measured <date>>`. State the numbers as measured, whatever they are; a low pass rate is a finding, not a reason to hold the row.

- [ ] **Step 5: Handoff and commit.** Add a dated section at the top of `docs/handoff.md` saying what changed, the live `PUBLIC_SHA`, the pass rates, and the failure causes from Step 2. Commit `Measure chores on gemini and ollama against hidden tests: <x> and <y> of 8`.

## What not to do

Do not give any repo but the fixture `auto_approve`. Do not run `haiku` without a yes from Thomas, because it costs money. Do not tune an instruction after seeing a model fail on it unless Step 2 of Task 5 found it ambiguous, and say in the report which tasks were changed and why. Do not merge any PR the eval opens. Do not add the eval to CI.
