# Build brief: Mercury as a cheap task runner, with evals and an escalation ladder

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement Phase 1 task by task (Thomas chose native execution, then one review of the whole branch). Steps use checkbox (`- [ ]`) syntax for tracking. Phases 2 to 4 are specs, not tasks: each one is turned into tasks in its own session, after the phase before it has landed.

**Goal:** Mercury completes well defined chores on free models, proves how often it gets them right with tests the model never saw, and escalates what it cannot fix to Thomas and then to a Claude session.

**Architecture:** Phase 1 adds a per repo `auto_approve` flag and a per run `provider` to the API, then an eval runner in `evals/` that queues each task as a `repo_chore` through `POST /runs` on the live deploy (or hands it to `delegate.ps1` on the desktop), grades the result, cleans up, and writes a JSON and Markdown report. Grading fails a result that removes a test `main` has, that fails its own tests, or that fails the hidden grade test. Phases 2 to 4 add the escalation ladder, a report a Claude session reads over MCP, a hint rescue measurement, and chores created from the hourly and weekly findings.

**Tech Stack:** Python 3.12, FastAPI, psycopg, pydantic, httpx2, PyYAML, pytest, uv, git. PowerShell 7 and OpenCode on Ollama for the `delegate.ps1` column, on the Windows desktop only.

**Spec:** `docs/mercury.md`, plus the decisions below. Settled with Thomas on 2026-10-05 over six rounds of questions; do not re-ask them.

## Where this starts

**Task 1 is done** (`827a38e`, 2026-10-05): the full suite, `ruff check` and `ruff format --check` passed before it was committed. Start at Task 2. On the Windows desktop the suite does not run natively (`app/sandbox.py` imports `pwd`); run it from WSL against the Windows checkout with its own virtualenv, with the compose database up in Docker Desktop:

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/c/Projects/agent-runs && export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/agent-runs-win && uv run pytest -p no:cacheprovider -q'
```

Live is `bde2233` on the `mercury` image. The front door already exists: Claude Code queues runs over the MCP server at `/mcp`, n8n turns a labelled fixture issue into a chore, and `POST /runs` accepts a `repo_chore` that waits for Approve. One chore has ever run on a real model: run `100c1125` (source n8n, gemini, 597 tokens) added `multiply` to the fixture as PR #4. Every chore runs on gemini with ollama as fallback. The private `mercury.yaml` says `repo_chore: provider: haiku` and carries a `budgets:` section, but no code reads either. No `ANTHROPIC_API_KEY` is deployed. The portfolio lists `thomas-whitley/mercury` (no `test_command`, since its tests need Postgres) and `thomas-whitley/mercury-fixture` (`python -m unittest -v`). On 2026-10-05 a separate session ran `gpt-oss:20b` locally on the fixture twice, and both times it replaced the `add` test with its own while a grade that tested only the new code passed.

## Decisions (2026-10-05)

1. **Who the eval is for.** Both Thomas and interviewers. When they pull apart, Thomas's question wins: can he hand real chores to Mercury.
2. **Tasks.** Eight small exact tasks plus three realistic ones on a standard library `orders` package seeded into the fixture. Every task is graded by a hidden test. Nothing in the fixture comes from Thomas's employer.
3. **Columns.** gemini and ollama through Mercury, and `delegate.ps1` on the desktop with both local models, `delegate:local` (`qwen3-coder:30b`) and `delegate:local-gpt` (`gpt-oss:20b`), so the eval also decides whether Mercury replaces `delegate.ps1` and which local model is its default. On 2026-10-05 `qwen3-coder:30b` passed 2 of 2 fixture chores with clean diffs and `gpt-oss:20b` passed 2 of 2 while deleting existing tests both times, which is why `local` now means `qwen3-coder:30b` in `Cheap AI` commit `18dddd8`.
4. **No paid model anywhere.** No Anthropic API rung, no Haiku baseline, no new key. The monthly dollar cap stays as it is.
5. **Repeats.** One repeat first. Three repeats on a later day, reporting the mean pass rate and how many tasks passed at least once.
6. **The ladder.** Free model (three attempts) → Thomas advises the free model with a hint, at most two advised reruns → a Claude session, which first writes a sharper hint through `advise` and does the chore itself only when it judges the task beyond free models, saying why.
7. **When to escalate.** Red tests after three attempts, or three unusable replies, go up the ladder. A provider outage takes the existing fallback and then retries the same rung an hour later. A budget trip goes straight to Thomas. The next rung starts from `main` with the failed diff and test output as context.
8. **Advice.** One code path, a follow up chore linked to the failed one (as Open it anyway is), reached from a Telegram reply or an MCP `advise(run_id, hint)` tool. An advised rerun starts without Approve.
9. **The report.** An MCP `report` tool returning Markdown, and a script that saves it to `reports/YYYY-MM-DD.md` (gitignored). Escalations first (instruction, every rung with provider and tokens, last diff, test output tail, why it stopped), then chores Mercury started itself with PR links and state, then the latest eval, then spend against the cap. On demand, with one line in the digest when there is something to review.
10. **Config.** Each type's ladder is read from `mercury.yaml`, as the spec always said. The unread `tasks:` and `budgets:` sections are wired in or deleted, so the private config states nothing false.
11. **Findings become chores, last.** Only after the eval says free models are worth it. Mercury first, once it has a `test_command` that needs no database. Instructions are templates filled with the evidence. One open chore per finding, at most three self started chores a day. Only dependency bumps and red CI start without Approve. Node repos later.
12. **Tests may not be weakened.** The eval grades it from Phase 1: a result that loses a test id `main` has, or fails its own tests, fails. From Phase 2 every chore enforces it before pushing: a diff that removes a test function or test file, or adds `skip`, `xfail` or `@unittest.skip`, is rejected, and the reason "weakened tests" sends it up the ladder.
13. **Approval.** `auto_approve: true` on `thomas-whitley/mercury-fixture` only. A chore asked for in Telegram chat always asks.
14. **Phases.** (1) eval foundation and the baseline run, (2) escalation, `advise`, the report and the config ladder, (3) the eval with one Claude hint per failure, and the README claims, (4) findings become chores.
15. **Models for the build.** Phase 1 is built on Sonnet 5.5 on the laptop. The review of the branch, the failure triage in Task 7, and turning Phases 2 to 4 into tasks run on Opus. A Sonnet session that meets something this brief does not cover stops and hands back rather than improvising.

## Global Constraints

- Writing rules from `CLAUDE.md` apply to every README line, doc and commit message: no em or en dashes, complete sentences, numbers over adjectives, none of the banned words.
- Commit messages are plain sentences saying what now works. No prefixes, no emoji.
- CI uses the stub model and never a real key. The eval is not a CI job; it runs by hand against the live deploy.
- No paid resource and no paid model. The eval's Mercury columns are `gemini` and `ollama`.
- The runner never merges. The eval closes every PR it caused and deletes its branch.
- No token in a commit, a log line, a report file or a URL. git gets the GitHub token only as `http.extraheader` through `GIT_CONFIG_*` environment variables, as `app/repo_chore.py` does.
- `auto_approve` is set on `thomas-whitley/mercury-fixture` alone.
- A README claim is written only after its proof exists, with the output pasted under it. Phase 1 writes none.
- Every `read_text` and `write_text` in `evals/` passes `encoding="utf-8"`, and every subprocess decodes as UTF-8, because the `delegate.ps1` column runs on Windows.
- When another session shares the working copy, run tests with `TEST_DATABASE_URL=postgresql://agent:agent@localhost:5432/agent_runs_test_chores`.

## Review Focus

- A chore posted for an `auto_approve` repo on a deploy with no Telegram bot should still start, not return 503, because nothing needs asking. Test in Task 1.
- A chore asked for in Telegram chat on an `auto_approve` repo should still wait for Approve, because chat replies "waiting for approval". Test in Task 1.
- `auto_approve: "yes"` (a quoted string) or any non boolean should leave the gate on. Only YAML `true` turns it off. Test in Task 1.
- A provider on a `site_check`, or a provider name not in `PROVIDERS`, should be a 422 that creates no run. Test in Task 2.
- A result that passes the hidden grade but deletes a test `main` has should fail. `gpt-oss:20b` did this in 2 of 2 local trials on 2026-10-05. Tests in Tasks 3 and 5.
- A grade test that cannot import what the model was asked to write should count as a fail and let the batch carry on. Test in Task 3.
- A task whose grade already passes on the unmodified fixture measures nothing. Every shipped grade must fail on the seed. Test in Task 4.

---

## Phase 1

### Task 1: `auto_approve` per repo

**Files:**
- Modify: `app/mercury_config.py` (`RepoConfig`, `_repo`)
- Modify: `app/chores.py` (add `starts_unasked`, `start_chore`)
- Modify: `app/run_api.py` (`_request_chore`)
- Modify: `app/mcp_server.py` (module docstring, `CREATE_RUN`, server `instructions`)
- Modify: `config/mercury.sample.yaml`
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
Expected: FAIL. The config test fails on the unknown `auto_approve` argument or attribute, and the posted chore comes back `awaiting_approval`.

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

`app/chores.py`: add to the module docstring that a repo marked `auto_approve` skips the question for every source but chat. Below `_SET_MESSAGE_FROM_APPROVAL` add:

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

`app/run_api.py`: import `start_chore, starts_unasked` from `app.chores`. In `_request_chore`, right after the `find_repo` try block and before `settings = state.settings`:

```python
    if starts_unasked(repo, source):
        with connect(state.settings.database_url, autocommit=True) as conn:
            run_id = start_chore(
                conn, repo, run.inputs["task"], source, TASK_TYPES["repo_chore"].provider
            )
        return RunCreated(id=run_id, status="pending")
```

`app/mcp_server.py`: the docstring line about the Approve button gains "unless its repo is marked auto_approve"; in `CREATE_RUN`, say a `repo_chore` waits for Approve on Telegram unless the repo is marked `auto_approve` in the config; the server `instructions` become `"Queue and read Mercury runs. Repo chores need approval on Telegram unless the repo is marked auto_approve."`

`config/mercury.sample.yaml`, under `owner/repo-one`'s `test_command`:

```yaml
      auto_approve: false  # true starts chores from the API, MCP or n8n without asking; throwaway repos only
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_repo_chore_approval.py tests/test_mcp.py -v`
Expected: PASS.
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass; integration tests that need a token or compose skip as before.

- [ ] **Step 5: Commit**

```bash
git add app/mercury_config.py app/chores.py app/run_api.py app/mcp_server.py config/mercury.sample.yaml tests/test_repo_chore_approval.py
git commit -m "Start a chore without asking on a repo marked auto_approve, except one asked for in chat"
```

---

### Task 2: A run may name its provider

**Files:**
- Modify: `app/run_request.py`, `app/run_api.py`, `app/chores.py`, `app/mcp_server.py`, `app/worker.py`
- Test: `tests/test_runs.py`, `tests/test_repo_chore_approval.py`, `tests/test_mcp.py`, `tests/test_fallback.py`

**Interfaces:**
- Consumes: `start_chore(conn, repo, instruction, source, provider)` from Task 1.
- Produces: `POST /runs` body field `provider: str | None` (a key of `app.config.PROVIDERS`); MCP `create_run` argument `provider`; `request_chore(..., source, provider: str | None = None)`. The worker builds a run's model from `runs.provider`.

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
        json={
            "type": "site_check",
            "inputs": {"task": "https://example.com"},
            "provider": "gemini",
        },
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

Append to `tests/test_mcp.py` (it uses the file's `api` fixture, `call` helper and `TEST_FILE`):

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

The `haiku` row here only proves the worker reads the row; the stub builder never calls Anthropic.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_runs.py tests/test_repo_chore_approval.py tests/test_mcp.py tests/test_fallback.py -k "provider" -v`
Expected: FAIL. The posted provider is ignored (the row says `gemini`), the unknown provider gets 201, the MCP tool rejects the `provider` argument, and the worker builds `ollama` for the chat run.

- [ ] **Step 3: Implement**

`app/run_request.py`: import `PROVIDERS` from `app.config`, add after `source`:

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

`app/chores.py`: `request_chore` gains a keyword `provider: str | None = None` after `source`, and its insert uses `provider or TASK_TYPES["repo_chore"].provider`. Chat calls it without a provider and is unchanged.

`app/run_api.py`: in `create_run`, the insert's provider value becomes `run.provider or TASK_TYPES[run.type].provider`. In `_request_chore`, pass `run.provider or TASK_TYPES["repo_chore"].provider` to `start_chore`, and call `request_chore(conn, telegram, chat_id, repo, run.inputs["task"], source, provider=run.provider)`.

`app/mcp_server.py`, `create_run_tool` gains `provider: str | None = None` as its last argument and builds `RunRequest(type=type, inputs=inputs, provider=provider)`; the rest is unchanged. Add to `CREATE_RUN`: `provider is optional, one of the configured providers such as gemini or ollama; leave it out to use the type's default.`

`app/worker.py`, in `_process_run` after `task_type = TASK_TYPES[task_type_name]`:

```python
    # The row's provider is the type's own unless the caller named one.
    provider = (
        conn.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()[0]
        or task_type.provider
    )
```

Use `provider` in place of `task_type.provider` in the `check_budget(...)` call, the `model_builder(settings, ...)` call and `run_agent_loop(..., provider=...)`, and call `_with_fallback(conn, run_id, model, task_type, settings, model_builder, provider)`. `_with_fallback` gains a last parameter `provider: str`, returns `model` unchanged when `task_type.fallback is None or task_type.fallback == provider`, and logs `provider` in `switch()`.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_runs.py tests/test_repo_chore_approval.py tests/test_mcp.py tests/test_fallback.py -v`
Expected: PASS.
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass. If an older worker test inserts a run whose `provider` differs from its type's and asserts on the builder's argument, make that row's provider match the type; do not change the new behaviour.

- [ ] **Step 5: Commit**

```bash
git add app/run_request.py app/run_api.py app/chores.py app/mcp_server.py app/worker.py tests/test_runs.py tests/test_repo_chore_approval.py tests/test_mcp.py tests/test_fallback.py
git commit -m "Let a run name its provider, and build its model from the provider on its row"
```

---

### Task 3: The eval runner and the eight small tasks

**Files:**
- Create: `evals/__init__.py` (empty), `evals/runner.py`, `evals/results/.gitkeep`
- Create: `evals/chores/divide.yaml`, `clamp.yaml`, `slugify.yaml`, `roman.yaml`, `duration.yaml`, `word_count.yaml`, `most_common.yaml`, `cli.yaml`
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `POST /runs` with `provider` (Task 2) on a repo with `auto_approve` (Task 1); `GET /runs/{id}` returning `status`, `provider`, `tokens`, `duration_seconds`; `PROVIDERS[name].usd_per_million_tokens`.
- Produces, for Tasks 4 and 5: `EvalTask(id, repo, instruction, grade)`; `EvalRow(task, provider, answered_by, run_id, status, graded, tokens: int | None, seconds, usd, detail="")`; `load_tasks(directory) -> list[EvalTask]`; `clone(clone_url, branch: str | None, dest, token, timeout_seconds) -> str | None` (None on success, else the error; `branch=None` clones the default branch); `test_ids(work, timeout_seconds=120) -> set[str]`; `grade_dir(work, grade_source, base_ids: set[str] | None = None, timeout_seconds=120) -> tuple[bool, str]`; `grade_branch(clone_url, branch, grade_source, token=None, timeout_seconds=120) -> tuple[bool, str]`; `REPO_TESTS` and `NO_TESTS_RAN`; `FIXTURE_URL`; `summarise(rows) -> str`; `write_results(rows, out) -> Path`; `main(argv)`.

**How to write a task.** Each instruction names the file, the function signature, the behaviour on the edge cases and the error to raise, and asks for tests in the repo's own `test_<module>.py`. A task a reader would have to ask a question about is not well defined and does not belong in the set. The grade test checks only what the instruction states. The runner adds two checks of its own to every task, so a grade never needs to repeat them: every test id on `main` must still exist in the result, and the result's own tests must pass.

- [ ] **Step 1: Write the failing tests**

`tests/test_eval_runner.py`:

```python
"""The eval runner, against a local bare repo and fake API and GitHub
clients. The live runs are in evals/results/, not here."""

import subprocess
from pathlib import Path

import pytest

from app.config import PROVIDERS
from evals import runner
from evals.runner import (
    EvalAborted,
    EvalRow,
    EvalTask,
    grade_branch,
    load_tasks,
    run_one,
    summarise,
)

GRADE_PASS = (
    "import unittest\nfrom calc import add\n\n\n"
    "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
)
GRADE_FAIL = GRADE_PASS.replace("5)", "6)")
GRADE_CALLABLE = (
    "import unittest\nfrom calc import add\n\n\n"
    "class T(unittest.TestCase):\n    def test_add_exists(self):\n"
    "        self.assertTrue(callable(add))\n"
)
GRADE_MISSING = (
    "import unittest\nfrom roman import to_roman\n\n\n"
    "class T(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(to_roman(1), 'I')\n"
)
SEED_TEST = (
    "import unittest\nfrom calc import add\n\n\n"
    "class AddTest(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
)


def remote(
    tmp_path: Path,
    branch: str = "agent/run-1",
    seed_test: bool = False,
    on_branch: dict[str, str] | None = None,
) -> str:
    """A bare repo whose main holds calc.py (and test_calc.py with seed_test),
    plus one more branch carrying on_branch's files. HEAD is main, as on GitHub."""
    work = tmp_path / "seed"
    work.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=work, check=True, capture_output=True)

    def commit(message: str) -> None:
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)

    git("init", "-q", "-b", "main")
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    if seed_test:
        (work / "test_calc.py").write_text(SEED_TEST, encoding="utf-8")
    commit("seed")
    git("checkout", "-q", "-b", branch)
    for name, text in (on_branch or {}).items():
        (work / name).write_text(text, encoding="utf-8")
    if on_branch:
        commit("chore")
    git("checkout", "-q", "main")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare.as_uri()


def test_a_branch_that_meets_the_grade_passes(tmp_path):
    passed, output = grade_branch(remote(tmp_path), "agent/run-1", GRADE_PASS)
    assert passed
    assert "OK" in output


def test_a_branch_that_misses_the_grade_fails(tmp_path):
    passed, _ = grade_branch(remote(tmp_path), "agent/run-1", GRADE_FAIL)
    assert not passed


def test_a_grade_that_cannot_import_its_module_fails_without_raising(tmp_path):
    passed, output = grade_branch(remote(tmp_path), "agent/run-1", GRADE_MISSING)
    assert not passed
    assert "roman" in output


def test_a_missing_branch_fails_the_grade(tmp_path):
    passed, output = grade_branch(remote(tmp_path), "agent/other", GRADE_PASS)
    assert not passed
    assert output.startswith("clone failed")


def test_a_branch_that_deletes_a_test_from_main_fails(tmp_path):
    url = remote(tmp_path, seed_test=True, on_branch={"test_calc.py": "import unittest\n"})

    passed, output = grade_branch(url, "agent/run-1", GRADE_PASS)

    assert not passed
    assert output.startswith("tests removed")
    assert "test_add" in output


def test_a_branch_that_breaks_its_own_tests_fails(tmp_path):
    url = remote(
        tmp_path, seed_test=True, on_branch={"calc.py": "def add(a, b):\n    return a - b\n"}
    )

    passed, output = grade_branch(url, "agent/run-1", GRADE_CALLABLE)

    assert not passed
    assert output.startswith("own tests failed")


def test_a_branch_that_keeps_main_s_tests_and_adds_its_own_passes(tmp_path):
    extra = SEED_TEST + "\n    def test_add_negative(self):\n        self.assertEqual(add(-1, 1), 0)\n"
    url = remote(tmp_path, seed_test=True, on_branch={"test_calc.py": extra})

    passed, output = grade_branch(url, "agent/run-1", GRADE_PASS)

    assert passed, output


def test_tasks_load_from_yaml_named_by_their_file(tmp_path):
    (tmp_path / "b.yaml").write_text(
        "repo: o/r\ninstruction: |\n  Do b.\ngrade: |\n  x = 1\n", encoding="utf-8"
    )
    (tmp_path / "a.yaml").write_text(
        "repo: o/r\ninstruction: Do a.\ngrade: x = 2\n", encoding="utf-8"
    )

    tasks = load_tasks(tmp_path)

    assert [t.id for t in tasks] == ["a", "b"]
    assert tasks[1] == EvalTask(id="b", repo="o/r", instruction="Do b.", grade="x = 1\n")


class _Response:
    def __init__(self, status_code: int, body=None, text: str = "") -> None:
        self.status_code, self._body, self.text = status_code, body, text

    def json(self):
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Api:
    """POST /runs answers created; GET /runs/{id} walks through statuses,
    repeating the last one."""

    def __init__(self, created: _Response, statuses: list[dict]) -> None:
        self.created, self.statuses, self.posted = created, list(statuses), []

    def post(self, path: str, json: dict) -> _Response:
        self.posted.append(json)
        return self.created

    def get(self, path: str) -> _Response:
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return _Response(200, status)


class _GitHub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, params: dict | None = None) -> _Response:
        self.calls.append(("get", path))
        return _Response(200, [{"number": 7}])

    def patch(self, path: str, json: dict) -> _Response:
        self.calls.append(("patch", path))
        return _Response(200)

    def delete(self, path: str) -> _Response:
        self.calls.append(("delete", path))
        return _Response(204)


TASK = EvalTask(id="divide", repo="o/fixture", instruction="Add divide.", grade=GRADE_PASS)
DONE = {"status": "succeeded", "provider": "gemini", "tokens": 900, "duration_seconds": 40.0}
PENDING = _Response(201, {"id": "run-1", "status": "pending"})


def _run(api, github, timeout: float = 900) -> EvalRow:
    ticks = iter(range(0, 100_000, 5))
    return run_one(
        api,
        github,
        TASK,
        "gemini",
        "file:///unused",
        None,
        timeout_seconds=timeout,
        poll_seconds=0,
        sleep=lambda seconds: None,
        clock=lambda: next(ticks),
    )


def test_a_green_chore_is_graded_and_its_pull_request_closed(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", lambda *a, **k: (True, "OK"))
    api = _Api(PENDING, [{"status": "running"}, DONE])
    github = _GitHub()

    row = _run(api, github)

    assert api.posted == [
        {
            "type": "repo_chore",
            "inputs": {"task": "Add divide.", "repo": "o/fixture"},
            "provider": "gemini",
        }
    ]
    assert (row.status, row.graded, row.tokens, row.answered_by) == (
        "succeeded",
        True,
        900,
        "gemini",
    )
    assert ("patch", "/repos/o/fixture/pulls/7") in github.calls
    assert ("delete", "/repos/o/fixture/git/refs/heads/agent/run-1") in github.calls


def test_a_red_chore_is_not_graded_and_nothing_is_closed(monkeypatch):
    monkeypatch.setattr(runner, "grade_branch", pytest.fail)
    api = _Api(PENDING, [{**DONE, "status": "failed"}])
    github = _GitHub()

    row = _run(api, github)

    assert (row.status, row.graded) == ("failed", False)
    assert github.calls == []


def test_a_chore_that_never_finishes_is_a_timeout():
    api = _Api(PENDING, [{"status": "running", "tokens": 0}])

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
    api = _Api(PENDING, [answered])

    row = _run(api, _GitHub())

    assert row.usd == pytest.approx(PROVIDERS["haiku"].usd_per_million_tokens)


def _row(provider: str, graded: bool, status: str = "succeeded", tokens: int | None = 1000):
    return EvalRow("t", provider, provider, "id", status, graded, tokens, 30.0, 0.0)


def test_the_summary_counts_hidden_test_passes_per_column():
    table = summarise([_row("gemini", True), _row("gemini", False, "failed"), _row("ollama", True)])

    assert "| gemini | 1 of 2 | 1 of 2 | 1000 | 30 | 0.0000 |" in table
    assert "| ollama | 1 of 1 | 1 of 1 | 1000 | 30 | 0.0000 |" in table


def test_the_summary_shows_no_tokens_for_a_column_that_cannot_count_them():
    table = summarise([_row("delegate:local", True, tokens=None)])

    assert "| delegate:local | 1 of 1 | 1 of 1 | n/a | 30 | 0.0000 |" in table
```

The cost test uses `haiku` only because it is the one provider with a nonzero rate in `PROVIDERS`; the eval never runs it.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals'`.

- [ ] **Step 3: Write the runner**

`evals/__init__.py` is empty. `evals/runner.py`:

```python
"""Runs Mercury's chore evals and grades each result with a test the model
never saw.

A task is one YAML file under evals/chores/: the repo, an instruction that
names every file and function it expects, and a grade test. Each task runs
once per column per repeat. A Mercury column queues it as a repo_chore
through POST /runs, and a chore that opens a pull request is graded on its
branch, which is then closed and deleted so the fixture keeps only main.
The delegate column (Task 5) runs delegate.ps1 on a local clone instead.

A result passes when it still has every test id main has, its own tests
pass, and the grade test passes.

uv run python -m evals.runner --columns gemini,ollama --repeats 1
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
HERE = Path(__file__).parent
FIXTURE_URL = "https://github.com/thomas-whitley/mercury-fixture.git"
# The fixture's own tests, as its test_command in mercury.yaml runs them.
REPO_TESTS = [sys.executable, "-m", "unittest", "discover", "-v"]
# unittest's exit status when it finds no tests, which a repo with none returns.
NO_TESTS_RAN = 5
# Prints every test id unittest discovers, one per line, without running any.
LIST_TESTS = (
    "import unittest\n"
    "def walk(suite):\n"
    "    for t in suite:\n"
    "        walk(t) if isinstance(t, unittest.TestSuite) else print(t.id())\n"
    "walk(unittest.defaultTestLoader.discover('.'))\n"
)
_TEXT = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}


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
    provider: str  # the column asked for: a provider, or delegate:<model>
    answered_by: str | None  # runs.provider at the end, after any fallback
    run_id: str | None
    status: str  # succeeded, failed, timeout, refused, or another final run status
    graded: bool  # kept main's tests, passed its own, and passed the hidden test
    tokens: int | None  # None where the column cannot count them
    seconds: float | None
    usd: float
    detail: str = ""


def load_tasks(directory: Path) -> list[EvalTask]:
    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
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
    env = {
        "PATH": os.environ["PATH"],
        "HOME": home,
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONUTF8": "1",
    }
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


def clone(
    clone_url: str, branch: str | None, dest: Path, token: str | None, timeout_seconds: float
) -> str | None:
    """None when the branch (or the default branch) is cloned into dest, else
    why not. Raises subprocess.TimeoutExpired, which callers turn into a row."""
    pick = ["--branch", branch] if branch else []
    result = subprocess.run(
        ["git", "clone", "-q", "--depth", "1", *pick, clone_url, str(dest)],
        env=_env(str(dest.parent), token),
        timeout=timeout_seconds,
        **_TEXT,
    )
    return None if result.returncode == 0 else "clone failed: " + result.stderr[-1000:]


def test_ids(work: Path, timeout_seconds: float = 120) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", LIST_TESTS],
        cwd=work,
        env=_env(str(work.parent), None),
        timeout=timeout_seconds,
        **_TEXT,
    )
    return set(result.stdout.split())


test_ids.__test__ = False  # a helper, not a test, for pytest's collector


def grade_dir(
    work: Path,
    grade_source: str,
    base_ids: set[str] | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Grade a checkout. With base_ids, every one of main's test ids must
    still be there. Then its own tests must pass, then the grade test. Never
    raises for a bad checkout or a bad grade; the answer is the boolean."""
    env = _env(str(work.parent), None)
    try:
        if base_ids is not None:
            lost = base_ids - test_ids(work, timeout_seconds)
            if lost:
                return False, "tests removed: " + ", ".join(sorted(lost))
        own = subprocess.run(REPO_TESTS, cwd=work, env=env, timeout=timeout_seconds, **_TEXT)
        if own.returncode not in (0, NO_TESTS_RAN):
            return False, "own tests failed: " + (own.stdout + own.stderr)[-3000:]
        (work / f"{GRADE_MODULE}.py").write_text(grade_source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", GRADE_MODULE],
            cwd=work,
            env=env,
            timeout=timeout_seconds,
            **_TEXT,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_seconds:.0f} s"
    return result.returncode == 0, (result.stdout + result.stderr)[-4000:]


def grade_branch(
    clone_url: str,
    branch: str,
    grade_source: str,
    token: str | None = None,
    timeout_seconds: float = 120,
) -> tuple[bool, str]:
    """Clone the branch and the default branch, and grade the branch against
    the default branch's test ids."""
    with tempfile.TemporaryDirectory() as home:
        work, base = Path(home) / "work", Path(home) / "base"
        try:
            error = clone(clone_url, branch, work, token, timeout_seconds) or clone(
                clone_url, None, base, token, timeout_seconds
            )
            if error:
                return False, error
            base_ids = test_ids(base, timeout_seconds)
        except subprocess.TimeoutExpired:
            return False, f"clone timed out after {timeout_seconds:.0f} s"
        return grade_dir(work, grade_source, base_ids, timeout_seconds)


def close_pull_and_branch(github, repo: str, branch: str) -> None:
    owner = repo.split("/")[0]
    pulls = github.get(
        f"/repos/{repo}/pulls", params={"head": f"{owner}:{branch}", "state": "open"}
    )
    for pull in pulls.json():
        github.patch(f"/repos/{repo}/pulls/{pull['number']}", json={"state": "closed"})
    github.delete(f"/repos/{repo}/git/refs/heads/{branch}")


def run_one(
    api,
    github,
    task: EvalTask,
    provider: str,
    clone_base: str,
    token: str | None,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
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
        return EvalRow(
            task.id, provider, None, None, "refused", False, 0, None, 0.0, created.text[:300]
        )
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
    return EvalRow(
        task.id,
        provider,
        answered,
        run_id,
        run["status"],
        graded,
        tokens,
        run.get("duration_seconds"),
        tokens * rate / 1_000_000,
        detail[-2000:],
    )


def summarise(rows: list[EvalRow]) -> str:
    lines = [
        "| Column | Passed the hidden test | Opened a PR | Median tokens | Median seconds "
        "| Cost USD |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for column in sorted({row.provider for row in rows}):
        mine = [row for row in rows if row.provider == column]
        tokens = [row.tokens for row in mine if row.tokens is not None]
        seconds = [row.seconds for row in mine if row.seconds is not None]
        lines.append(
            f"| {column} | {sum(r.graded for r in mine)} of {len(mine)} "
            f"| {sum(r.status == 'succeeded' for r in mine)} of {len(mine)} "
            f"| {f'{statistics.median(tokens):.0f}' if tokens else 'n/a'} "
            f"| {f'{statistics.median(seconds):.0f}' if seconds else 'n/a'} "
            f"| {sum(r.usd for r in mine):.4f} |"
        )
    lines += ["", "| Task | Column | Status | Graded |", "| --- | --- | --- | --- |"]
    for row in sorted(rows, key=lambda r: (r.task, r.provider)):
        verdict = "pass" if row.graded else "fail"
        lines.append(f"| {row.task} | {row.provider} | {row.status} | {verdict} |")
    return "\n".join(lines)


def write_results(rows: list[EvalRow], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    (out / f"{stamp}.json").write_text(
        json.dumps([asdict(r) for r in rows], indent=2) + "\n", encoding="utf-8"
    )
    report = out / f"{stamp}.md"
    report.write_text(summarise(rows) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the live deploy
    parser = argparse.ArgumentParser(description="Run the chore evals.")
    parser.add_argument(
        "--columns", default="gemini,ollama", help="providers, and delegate:<model> (Task 5)"
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--only", default="", help="comma separated task ids")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args(argv)

    columns = [c for c in args.columns.split(",") if c]
    unknown = [c for c in columns if c not in PROVIDERS and not c.startswith("delegate:")]
    if unknown:
        parser.error(f"unknown column {unknown[0]}; providers: {', '.join(PROVIDERS)}")
    tasks = load_tasks(HERE / "chores")
    if args.only:
        wanted = set(args.only.split(","))
        tasks = [t for t in tasks if t.id in wanted]

    api = github = token = None
    if any(not c.startswith("delegate:") for c in columns):
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
                for column in columns:
                    row = _run_column(column, task, api, github, token, args.timeout)
                    rows.append(row)
                    print(
                        f"{task.id} {column}->{row.answered_by} {row.status} "
                        f"graded={'pass' if row.graded else 'fail'} tokens={row.tokens}",
                        flush=True,
                    )
    except EvalAborted as stop:
        print(stop, file=sys.stderr)
    finally:
        if rows:
            report = write_results(rows, HERE / "results")
            print(report.read_text(encoding="utf-8"))
            print(f"written to {report}")
    return 0 if rows else 1


def _run_column(column, task, api, github, token, timeout) -> EvalRow:  # pragma: no cover
    return run_one(
        api,
        github,
        task,
        column,
        "https://github.com",
        token,
        timeout_seconds=timeout,
        poll_seconds=5.0,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

Check `_env` against the header `app/repo_chore.py` builds (`grep -n extraheader app/repo_chore.py`). If that module uses a different scheme or user name, copy its form exactly so both paths authenticate the same way.

- [ ] **Step 4: Write the eight small tasks**

Every file names `repo: thomas-whitley/mercury-fixture`.

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
          self.assertEqual(most_common("b a B c a b", 2), [("b", 3), ("a", 2)])
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

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: PASS, 16 tests.
Run: `uv run ruff format evals tests/test_eval_runner.py && uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add evals tests/test_eval_runner.py
git commit -m "Add an eval runner that fails a chore which drops main's tests, and eight small fixture tasks"
```

---

### Task 4: The fixture seed and the three orders tasks

The fixture's `main` will hold exactly what `evals/fixture-seed/` holds, so a test here can prove that the seed's own tests pass and that every grade fails before a model touches the repo.

**Files:**
- Create: `evals/fixture-seed/calc.py`, `test_calc.py` (copies of the fixture's current files), `textstats.py`, `test_textstats.py`, `orders/__init__.py`, `orders/parse.py`, `orders/pricing.py`, `orders/report.py`, `test_orders.py`
- Create: `evals/chores/orders_quantity.yaml`, `orders_gst.yaml`, `orders_report.yaml`
- Modify: `pyproject.toml` (ruff `extend-exclude` gains `evals/fixture-seed`, the fixture's code rather than Mercury's; pytest already collects only `tests/` through `testpaths`)
- Test: `tests/test_eval_seed.py`

**Interfaces:**
- Consumes: `load_tasks`, `grade_dir`, `REPO_TESTS` from Task 3.
- Produces: the seed Task 6 pushes to the fixture, and three more tasks (eleven in all).

- [ ] **Step 1: Write the failing tests**

`tests/test_eval_seed.py`:

```python
"""The fixture as the evals expect it: its own tests pass, and every task's
hidden grade fails on it, so each task asks for a real change."""

import shutil
import subprocess
from pathlib import Path

import pytest

from evals.runner import REPO_TESTS, grade_dir, load_tasks

SEED = Path("evals/fixture-seed")
TASKS = load_tasks(Path("evals/chores"))


@pytest.fixture
def seeded(tmp_path) -> Path:
    work = tmp_path / "work"
    shutil.copytree(SEED, work, ignore=shutil.ignore_patterns("__pycache__"))
    return work


def test_the_seed_s_own_tests_pass(seeded):
    result = subprocess.run(REPO_TESTS, cwd=seeded, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_there_are_eleven_tasks_all_on_the_fixture():
    assert len(TASKS) == 11
    assert {t.repo for t in TASKS} == {"thomas-whitley/mercury-fixture"}


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_every_grade_fails_on_the_unchanged_seed(seeded, task):
    passed, output = grade_dir(seeded, task.grade)
    assert not passed, output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_eval_seed.py -v`
Expected: FAIL, because `evals/fixture-seed` does not exist and there are eight tasks.

- [ ] **Step 3: Write the seed**

`evals/fixture-seed/calc.py`, byte for byte the fixture's current file:

```python
"""A deliberately small module for Mercury's repo chore integration test to edit."""


def add(a: int, b: int) -> int:
    return a + b
```

`evals/fixture-seed/test_calc.py`, byte for byte the fixture's current file:

```python
import unittest

from calc import add


class AddTest(unittest.TestCase):
    def test_adds_two_numbers(self):
        self.assertEqual(add(2, 3), 5)


if __name__ == "__main__":
    unittest.main()
```

`evals/fixture-seed/textstats.py`:

```python
"""Text statistics for Mercury's evals. word_count has a known bug the evals ask a model to fix."""


def word_count(text: str) -> int:
    return len(text.split(" "))
```

`evals/fixture-seed/test_textstats.py`:

```python
import unittest

from textstats import word_count


class WordCount(unittest.TestCase):
    def test_single_spaces(self):
        self.assertEqual(word_count("one two three"), 3)
```

`evals/fixture-seed/orders/__init__.py`:

```python
"""A small order importer for Mercury's evals. Standard library only."""

from orders.parse import InvalidOrders, Line, parse_orders
from orders.pricing import line_total, order_total
from orders.report import summary

__all__ = ["InvalidOrders", "Line", "line_total", "order_total", "parse_orders", "summary"]
```

`evals/fixture-seed/orders/parse.py`:

```python
"""Parses an order CSV with the header sku,quantity,unit_price and no blank lines."""

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Line:
    sku: str
    quantity: int
    unit_price: Decimal


class InvalidOrders(ValueError):
    """Raised with every bad line's number, counting the header as line 1."""

    def __init__(self, line_numbers: list[int]) -> None:
        self.line_numbers = line_numbers
        super().__init__("invalid lines: " + ", ".join(map(str, line_numbers)))


def parse_orders(text: str) -> list[Line]:
    lines, bad = [], []
    for number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            lines.append(
                Line(row["sku"].strip(), int(row["quantity"]), Decimal(row["unit_price"]))
            )
        except (ValueError, InvalidOperation, TypeError, AttributeError):
            bad.append(number)
    if bad:
        raise InvalidOrders(bad)
    return lines
```

`evals/fixture-seed/orders/pricing.py`:

```python
"""Prices lines. Ten or more of one SKU takes 5 percent off. GST is 10 percent."""

from decimal import ROUND_HALF_UP, Decimal

from orders.parse import Line

GST = Decimal("0.10")
BULK_QUANTITY = 10
BULK_DISCOUNT = Decimal("0.05")
CENT = Decimal("0.01")


def line_total(line: Line) -> Decimal:
    """The line's total before GST, after any bulk discount, not rounded."""
    total = line.quantity * line.unit_price
    if line.quantity >= BULK_QUANTITY:
        total -= total * BULK_DISCOUNT
    return total


def order_total(lines: list[Line]) -> Decimal:
    """The order's total including GST, rounded to the cent once, on the whole order."""
    before_gst = sum((line_total(line) for line in lines), Decimal(0))
    return (before_gst * (1 + GST)).quantize(CENT, rounding=ROUND_HALF_UP)
```

`evals/fixture-seed/orders/report.py`:

```python
"""A plain text summary of an order."""

from decimal import Decimal

from orders.parse import Line


def summary(lines: list[Line]) -> str:
    """One row per line, then the total before GST. Prices each line itself."""
    rows, total = [], Decimal(0)
    for line in lines:
        amount = line.quantity * line.unit_price
        rows.append(f"{line.sku} x{line.quantity} {amount:.2f}")
        total += amount
    rows.append(f"TOTAL {total:.2f}")
    return "\n".join(rows)
```

`evals/fixture-seed/test_orders.py`:

```python
import unittest
from decimal import Decimal

from orders import InvalidOrders, order_total, parse_orders, summary

CSV = "sku,quantity,unit_price\nA,2,10.00\nB,1,2.50\n"


class Orders(unittest.TestCase):
    def test_parses_lines(self):
        self.assertEqual([line.sku for line in parse_orders(CSV)], ["A", "B"])

    def test_reports_every_bad_price_by_line_number(self):
        with self.assertRaises(InvalidOrders) as caught:
            parse_orders("sku,quantity,unit_price\nA,1,x\nB,1,1\nC,1,y\n")
        self.assertEqual(caught.exception.line_numbers, [2, 4])

    def test_order_total_includes_gst(self):
        self.assertEqual(order_total(parse_orders(CSV)), Decimal("24.75"))

    def test_summary_ends_with_the_total(self):
        self.assertEqual(summary(parse_orders(CSV)).splitlines()[-1], "TOTAL 22.50")
```

- [ ] **Step 4: Write the three orders tasks**

`evals/chores/orders_quantity.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  In orders/parse.py, parse_orders accepts a quantity of zero or below. Treat a quantity below
  1 as a bad line, reported the same way a bad price already is: one InvalidOrders listing every
  bad line's number, counting the header as line 1, with bad quantities and bad prices in the
  same list in line order. Add tests to test_orders.py.
grade: |
  import unittest
  from orders import InvalidOrders, parse_orders


  class Grade(unittest.TestCase):
      def test_bad_quantities_and_prices_together(self):
          text = "sku,quantity,unit_price\nA,0,1\nB,2,1\nC,-3,1\nD,1,x\n"
          with self.assertRaises(InvalidOrders) as caught:
              parse_orders(text)
          self.assertEqual(caught.exception.line_numbers, [2, 4, 5])

      def test_good_lines_still_parse(self):
          lines = parse_orders("sku,quantity,unit_price\nA,1,2.00\n")
          self.assertEqual(lines[0].quantity, 1)
```

`evals/chores/orders_gst.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  In orders/pricing.py, order_total rounds GST once on the whole order. Change it so each line's
  total including GST (line_total times 1.10) is rounded to the cent, half up, and the order total
  is the sum of those rounded lines. Leave line_total as it is. Add tests to test_orders.py.
grade: |
  import unittest
  from decimal import Decimal
  from orders import order_total, parse_orders


  class Grade(unittest.TestCase):
      def test_rounds_per_line(self):
          lines = parse_orders("sku,quantity,unit_price\nA,1,0.05\nB,1,0.05\n")
          self.assertEqual(order_total(lines), Decimal("0.12"))

      def test_plain_order(self):
          lines = parse_orders("sku,quantity,unit_price\nA,2,10.00\nB,1,2.50\n")
          self.assertEqual(order_total(lines), Decimal("24.75"))
```

`evals/chores/orders_report.yaml`:

```yaml
repo: thomas-whitley/mercury-fixture
instruction: |
  orders/report.py prices each line itself, so summary misses the bulk discount that
  orders/pricing.py line_total applies. Make summary use line_total for every row and for the
  total, keeping the output format exactly as it is (SKU, x and quantity, the amount to two
  decimal places, then a TOTAL row). Add tests to test_orders.py.
grade: |
  import unittest
  from orders import parse_orders, summary


  class Grade(unittest.TestCase):
      def test_bulk_lines_are_discounted(self):
          lines = parse_orders("sku,quantity,unit_price\nA,10,1.00\nB,1,2.50\n")
          self.assertEqual(summary(lines), "A x10 9.50\nB x1 2.50\nTOTAL 12.00")
```

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_eval_seed.py -v`
Expected: PASS, 13 tests (the seed's own tests, the count, and eleven grades that fail on the seed). If a grade passes on the seed, the task asks for nothing; fix the task, not the test.
Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add evals pyproject.toml tests/test_eval_seed.py
git commit -m "Seed the fixture's eval code in the repo, add three orders tasks, and prove every grade fails on the seed"
```

---

### Task 5: The `delegate.ps1` column

Runs only on the Windows desktop, where `C:\Projects\Cheap AI\scripts\delegate.ps1`, OpenCode and Ollama live. `delegate.ps1` edits a clean checkout once and does not run tests or retry, so this column applies Mercury's own gate afterwards: the change counts as an opened PR only if the repo's tests pass, and only then is it graded, with the same check that `main`'s test ids are all still there.

**Files:**
- Modify: `evals/runner.py` (add `run_delegate`, `_call_delegate_script`, route `delegate:<model>` columns in `_run_column`)
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `clone`, `test_ids`, `grade_dir`, `REPO_TESTS`, `NO_TESTS_RAN`, `EvalRow`, `FIXTURE_URL` from Task 3.
- Produces: `run_delegate(task, model, clone_url, *, delegate=None, timeout_seconds=1800, clock=time.monotonic) -> EvalRow` with `provider` and `answered_by` both `delegate:<model>`, `tokens=None`, `usd=0.0`; `--columns delegate:local,delegate:local-gpt` on the command line, where the part after the colon is passed to `delegate.ps1 -Model` unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_eval_runner.py`, and add `run_delegate` to its import from `evals.runner`:

```python
GRADE_DIVIDE = (
    "import unittest\nfrom calc import divide\n\n\n"
    "class T(unittest.TestCase):\n    def test_divide(self):\n"
    "        self.assertEqual(divide(6, 3), 2)\n"
)
DIVIDE_TASK = EvalTask(id="divide", repo="o/fixture", instruction="Add divide.", grade=GRADE_DIVIDE)
CALC_WITH_DIVIDE = "def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    return a / b\n"


def _delegate_writing(files: dict[str, str]):
    def delegate(work, instruction, model, timeout_seconds):
        for name, text in files.items():
            (work / name).write_text(text, encoding="utf-8")

    return delegate


def test_a_delegate_change_that_keeps_the_tests_green_is_graded(tmp_path):
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": CALC_WITH_DIVIDE}),
    )

    assert (row.provider, row.status, row.graded, row.tokens) == (
        "delegate:local",
        "succeeded",
        True,
        None,
    )


def test_a_delegate_change_that_breaks_the_tests_is_failed_and_not_graded(tmp_path):
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": "oops("}),
    )

    assert (row.status, row.graded) == ("failed", False)


def test_a_delegate_change_that_replaces_main_s_test_is_not_graded_a_pass(tmp_path):
    own_test = (
        "import unittest\nfrom calc import divide\n\n\n"
        "class DivideTest(unittest.TestCase):\n    def test_divide(self):\n"
        "        self.assertEqual(divide(4, 2), 2)\n"
    )
    row = run_delegate(
        DIVIDE_TASK,
        "local",
        remote(tmp_path, seed_test=True),
        delegate=_delegate_writing({"calc.py": CALC_WITH_DIVIDE, "test_calc.py": own_test}),
    )

    assert (row.status, row.graded) == ("succeeded", False)
    assert row.detail.startswith("tests removed")


def test_a_delegate_that_runs_too_long_is_a_timeout(tmp_path):
    def slow(work, instruction, model, timeout_seconds):
        raise subprocess.TimeoutExpired("pwsh", timeout_seconds)

    row = run_delegate(DIVIDE_TASK, "local", remote(tmp_path, seed_test=True), delegate=slow)

    assert (row.status, row.graded) == ("timeout", False)
```

The third test is the 2026-10-05 `gpt-oss:20b` behaviour: the repo's tests pass, so the change would have become a PR, but it dropped the `add` test, so it is not a pass.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_eval_runner.py -k delegate -v`
Expected: FAIL with `ImportError: cannot import name 'run_delegate'`.

- [ ] **Step 3: Implement**

In `evals/runner.py`, add below `close_pull_and_branch`:

```python
DELEGATE_SCRIPT = Path(r"C:\Projects\Cheap AI\scripts\delegate.ps1")


def _call_delegate_script(work: Path, instruction: str, model: str, timeout_seconds: float):
    """delegate.ps1 needs the desktop's own environment (OpenCode, Ollama), so
    it gets it whole. It edits the clean checkout and does not commit."""
    subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(DELEGATE_SCRIPT),
            "-Dir",
            str(work),
            "-Task",
            instruction,
            "-Model",
            model,
        ],
        timeout=timeout_seconds,
        check=False,
        **_TEXT,
    )


def run_delegate(
    task: EvalTask,
    model: str,
    clone_url: str,
    *,
    delegate: Callable[[Path, str, str, float], None] | None = None,
    timeout_seconds: float = 1800,
    clock: Callable[[], float] = time.monotonic,
) -> EvalRow:
    column = f"delegate:{model}"
    delegate = delegate or _call_delegate_script

    def row(status: str, graded: bool, seconds: float | None, detail: str) -> EvalRow:
        return EvalRow(
            task.id, column, column, None, status, graded, None, seconds, 0.0, detail[-2000:]
        )

    with tempfile.TemporaryDirectory() as home:
        work = Path(home) / "work"
        error = clone(clone_url, "main", work, None, 120)
        if error:
            return row("refused", False, None, error)
        base_ids = test_ids(work)
        start = clock()
        try:
            delegate(work, task.instruction, model, timeout_seconds)
        except subprocess.TimeoutExpired:
            return row("timeout", False, clock() - start, "delegate.ps1 timed out")
        seconds = clock() - start
        # Mercury opens a pull request only when the repo's own tests pass.
        tests = subprocess.run(REPO_TESTS, cwd=work, env=_env(home, None), timeout=600, **_TEXT)
        if tests.returncode not in (0, NO_TESTS_RAN):
            return row("failed", False, seconds, tests.stdout + tests.stderr)
        graded, detail = grade_dir(work, task.grade, base_ids)
        return row("succeeded", graded, seconds, detail)
```

and make `_run_column` route the column:

```python
def _run_column(column, task, api, github, token, timeout) -> EvalRow:  # pragma: no cover
    if column.startswith("delegate:"):
        return run_delegate(task, column.split(":", 1)[1], FIXTURE_URL)
    return run_one(
        api,
        github,
        task,
        column,
        "https://github.com",
        token,
        timeout_seconds=timeout,
        poll_seconds=5.0,
    )
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_eval_runner.py -v`
Expected: PASS, 20 tests.
Run: `uv run ruff format evals && uv run pytest -q && uv run ruff check && uv run ruff format --check`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add evals/runner.py tests/test_eval_runner.py
git commit -m "Add a delegate.ps1 column to the evals, held to the same gate and grading as a chore"
```

---

### Task 6: Deploy, seed the fixture, mark it auto_approve

Every step here is outward and is Thomas's to approve, one at a time. Prepare each change, show it, and push only after his yes.

- [ ] **Step 1: Push the public commits** from Tasks 1 to 5 and wait for CI and Publish to go green on `thomas-whitley/mercury`.

- [ ] **Step 2: Seed the fixture.** In a clone of `thomas-whitley/mercury-fixture`, copy `textstats.py`, `test_textstats.py`, `orders/` and `test_orders.py` from `evals/fixture-seed/`. Check that `calc.py` and `test_calc.py` are unchanged, that `diff -r --exclude=.git --exclude=README.md --exclude=.gitignore --exclude=__pycache__ <clone> evals/fixture-seed` prints nothing, and that `python -m unittest discover -v` passes. Commit `Seed textstats and an orders package for Mercury's evals` and push to `main`. PR #4 stays open; it is the record of the n8n claim.

- [ ] **Step 3: Configure and deploy.** In `mercury-config`, add `auto_approve: true` to the `thomas-whitley/mercury-fixture` entry under `portfolio.repos` in `mercury.yaml`, and bump `PUBLIC_SHA` to the Task 5 commit, in one commit. Wait for Deploy to go green.

- [ ] **Step 4: Smoke test.** With `MERCURY_URL` set to the live API and the two tokens loaded from `.env`:

```bash
uv run python -m evals.runner --columns gemini --only divide
```

Expected: one line `divide gemini->gemini succeeded graded=pass tokens=<n>` (or a fail with its reason), a report under `evals/results/`, no message on Telegram, and no new PR or `agent/` branch left on the fixture (`gh pr list -R thomas-whitley/mercury-fixture` shows only PR #4).

---

### Task 7: The baseline run

- [ ] **Step 1: Run the Mercury columns once**, from the laptop, in the background, since it can take an hour:

```bash
uv run python -m evals.runner --columns gemini,ollama --repeats 1
```

Twenty two runs. Each chore is capped at 50,000 tokens and the daily cap is 500,000 per provider, so one repeat stays under it.

The worker also refuses every model run past `MAX_RUNS_PER_DAY` (default 20), chores included, so 22 chores in one day would trip it and the runner stops with an error. Raise `MAX_RUNS_PER_DAY` in `mercury-config` for the day of the baseline, or split the run across two days with `--only`. Do not change the server default.

- [ ] **Step 2: Run the two delegate columns once**, from the Windows desktop after `git pull`, with Docker Desktop stopped so `qwen3-coder:30b` has the RAM:

```powershell
uv run python -m evals.runner --columns delegate:local,delegate:local-gpt --repeats 1
```

Twenty two runs at roughly 1 to 3 minutes each.

- [ ] **Step 3: Triage on Opus.** For every row that is not a pass, read the run's events (`get_run_events` over MCP, or the run page with the token) or the row's detail, and sort it into one cause: the model's change was wrong, the model removed or broke tests, the instruction was ambiguous, or Mercury failed (clone, push, timeout, provider error). A task found ambiguous is fixed and rerun with `--only`, and the report says which tasks changed and why. A Mercury failure is a bug, and gets its own failing test before its fix.

- [ ] **Step 4: Commit and hand over.** Commit the reports from `evals/results/`. Add a dated section at the top of `docs/handoff.md` with the live `PUBLIC_SHA`, the pass rate per column, how many results removed tests, and the failure causes from Step 3. Commit `Measure chores against hidden tests: gemini <a>, ollama <b>, qwen3-coder <c>, gpt-oss 20b <d> of 11`. No README claim yet; that is Phase 3's.

---

## Phase 2 spec: the escalation ladder, advise, and the report

Detailed into tasks in its own session, on Opus, after Phase 1 lands. What it must do:

- **Ladder in config.** `mercury.yaml` gains a ladder per type, for example `repo_chore: {ladder: [gemini, ollama], budget_tokens: 50000}`, read at startup into the registry, replacing the provider and fallback in `app/tasks.py` for those types. The unread `tasks:` and `budgets:` sections are wired in or deleted, so the private config states nothing false. `config/mercury.sample.yaml` documents the shape.
- **Escalation.** A chore that ends red after three attempts, or after three unusable replies, ends `escalated` (a new status, with a migration) and records why. An outage on every free provider retries the same rung an hour later instead. A budget trip escalates straight to Thomas with no retry.
- **Fallback after a reclaim.** A run that already fell back has the fallback provider on its row, so a worker that reclaims or reopens it runs it on that provider with no fallback behind it (Phase 1 left this as it is). The ladder records which rung a run is on and keeps the rungs after it.
- **Weakened tests.** Before any push, the chore rejects a diff that removes a test function or test file, or adds `skip`, `xfail` or `@unittest.skip`, and ends `escalated` with the reason "weakened tests". The same test id comparison the eval runner uses is the simplest form of the check. The eval report counts how often it fires.
- **The message.** One Telegram message per escalation, with the instruction, the reason, the tail of the test output and a link to the run page, and a prompt to reply with a hint. A second escalation of the same chore goes in the report, not a new message.
- **Advise.** A Telegram reply to that message, or the MCP tool `advise(run_id, hint)`, creates a follow up chore with `source_run_id` set, the same instruction, the hint, and the failed diff and test output as context. It starts without Approve. After two advised reruns fail, the chore is marked "take to a Claude session" and `advise` refuses a third.
- **The report.** An MCP tool `report(since)` returns Markdown: escalations first (instruction, every rung with provider, tokens and cost, the last diff, the test output tail, why it stopped), then chores Mercury started itself with PR links and state, then the latest eval summary, then spend against the cap. `scripts/mercury_report.py` saves it to `reports/YYYY-MM-DD.md`, which is gitignored. The digest gains one line when anything is waiting.
- **The Claude session rung.** Documented in the README and in the MCP server's instructions: a Claude session reads `report`, writes a sharper hint through `advise` first, and does the chore itself on a local clone only when it judges the task beyond free models, saying why.

## Phase 3 spec: the hint rescue eval, and the README

- The eval runner gains a rescue pass: for every row that failed, a Claude session (Opus) writes one hint from the failure, and the runner sends it with `advise` and grades the result. The report gains two figures per column: passed first time, and passed after one Claude hint.
- Three repeats on a later day, reporting the mean pass rate and how many tasks passed at least once.
- README: a section `## Evals` saying what a task is, that the grade test never reaches the model, that a result which drops `main`'s tests fails, how a run is graded, and the command to rerun it, with the column table pasted under it. A claims row `A free model completes well defined chores, graded by tests it never saw`, with the measured numbers whatever they are.

## Phase 4 spec: findings become chores

Starts only if Thomas decides, on Phase 3's numbers, that free models are worth trusting on a real repo.

- Mercury gains a `test_command` that needs no database: the tests that need Postgres are marked `db`, and the command is `uv run pytest -m "not db" && uv run ruff check`. `thomas-whitley/mercury` gets that `test_command` in `mercury.yaml`.
- The CI watch and the dependency audit create chores from templates filled with the evidence. A dependency bump names the package, both versions and the advisory, and asks for the lock file updated with the tests green. A red CI names the job and carries the last 150 lines of its log, and asks for it green without deleting, skipping or weakening any test.
- One open chore per finding (repo and failing job, or repo and advisory), none while an earlier one's PR is open or it waits on advice, and at most three self started chores a day across all repos, the rest listed in the report.
- Dependency bumps and red CI start without Approve. Every other self started chore asks.
- Node repos (`ludo-electrical`, `nextset`) wait until a Python repo has proven this.

## What not to do

Do not give any repo but the fixture `auto_approve`. Do not add a paid model or an Anthropic key. Do not tune an instruction after seeing a model fail on it unless triage found it ambiguous, and say so in the report. Do not merge any PR the eval opens. Do not add the eval to CI. Do not start Phase 2 in the Phase 1 session.
