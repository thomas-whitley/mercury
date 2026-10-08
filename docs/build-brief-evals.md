# Build brief: Mercury as a cheap task runner, with evals and an escalation ladder

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement Phase 1 task by task (Thomas chose native execution, then one review of the whole branch). Steps use checkbox (`- [ ]`) syntax for tracking. Phase 2 was turned into Tasks 8 to 18 on 2026-10-07 and is done and live at `f453720` the same day. Phases 3, 4 and 5 are still specs, not tasks: each one is turned into tasks in its own session, after the phase before it has landed, except that Phase 5's part 5a comes before Phase 3. Part 5a was turned into Tasks 19 to 27 on 2026-10-07 and built the same day (live at `7ec6995`); by decision 46 the local rung runs in local compose, not live. Phase 3 was turned into Tasks 28 to 35 on 2026-10-07 (decisions 47 to 52) and is done and live at `dd2e934` (2026-10-08; the delegate columns ran 1 repeat, see `docs/handoff.md`). Part 5b is next.

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

## Phase 2

Detailed into tasks on 2026-10-07, on Opus, after Phase 1 landed (`bb64703`, the baseline: gemini 11, ollama 9, qwen3-coder 10, gpt-oss 20b 4 of 11). Thomas chose native execution for Phase 1; use the same unless he says otherwise. Execute with superpowers:executing-plans, one task per commit, the full suite green before each commit.

**Where Phase 2 starts.** `MAX_RUNS_PER_DAY` already reaches the api and the worker (`497897b`, live at 40 through the `MAX_RUNS_PER_DAY` Actions variable in `mercury-config`), so the spec's "plumb it through the Bicep" is done and has no task here. Of the 10 Phase 1 failures, 6 were a result that removed one of `main`'s tests after an instruction that said "Add tests to" an existing file, and every one of them passed the repo's own test command. That is why Task 11 retries with feedback rather than escalating at once.

**What the spec says, condensed.** A ladder per type is read from `mercury.yaml`. A chore that ends red after three attempts, or after three unusable replies, or that still weakens tests on its third attempt, ends `escalated` with a reason. One Telegram message per escalated chore, with a reply or the MCP tool `advise(run_id, hint)` creating an advised rerun from `main` that starts without Approve; after two advised reruns fail the chore is marked for a Claude session and `advise` refuses a third. An outage on every free provider retries an hour later. A budget trip goes straight to Thomas, which the worker already does (`app/worker.py` `_tell_owner` on `budget_exhausted` and on a cap trip), so it keeps its own statuses and gets no task. An MCP `report(since)` and `scripts/mercury_report.py` put it all in one Markdown page.

### Phase 2 decisions (2026-10-07)

16. **Weakened tests get feedback.** A green attempt whose diff removes or skips one of `main`'s tests counts as a failed attempt, and the next prompt names what was dropped. Only a third attempt that still weakens tests ends `escalated` with the reason `weakened tests`.
17. **An outage retries hourly, at most three times.** A chore whose model never answered on any provider ends `error` with the reason `providers unavailable`. The hourly scheduler Job queues a follow up chore for it, linked by `source_run_id`, up to three in a row; the run after the third escalates. Nothing keeps the worker awake while it waits.
18. **Eval chores are silent.** The eval runner posts its chores with `source: eval`. Their escalations reach the report and never Telegram.
19. **`budgets:` and `providers:` are deleted** from the sample and the private config. The caps stay environment variables (`DAILY_TOKENS_PER_PROVIDER`, `MONTHLY_BUDGET_USD`) and providers stay `PROVIDERS` in `app/config.py`.

### Phase 2 Review Focus

- A private `mercury.yaml` still in the old shape (`repo_chore: provider: haiku`) must stop the api at startup with a message naming the key, not run on a default nobody chose. Test in Task 8.
- A run that already fell back to the last rung and is reclaimed must run on that rung with nothing behind it, and a run on the first rung must still get every rung after it. Tests in Task 9.
- A test renamed or rewritten from a `unittest.TestCase` method to a bare function counts as removed, because its id is gone. `ollama` did exactly this on `clamp` and `divide` (fixture PRs #17 and #19). Test in Task 11.
- A reply on Telegram to an escalation message that is not the latest one, or to any other bot message, must not become a hint; only a reply to a chore's own escalation message is. Test in Task 14.
- A cancel that lands between the push and the pull request must not leave an `agent/<id>` branch, but a worker that loses its lease to a takeover must leave the branch for the new worker. Tests in Task 16.

---

### Task 8: Each type's ladder comes from `mercury.yaml`

**Files:**
- Modify: `app/mercury_config.py`, `app/tasks.py`, `app/main.py` (lifespan), `app/worker.py` (`main`), `app/scheduler.py` (`main`), `config/mercury.sample.yaml`
- Test: `tests/test_mercury_config.py`, `tests/test_tasks.py`

**Interfaces:**
- Produces: `TaskSettings(ladder: tuple[str, ...], budget_tokens: int | None)` and `MercuryConfig.tasks: dict[str, TaskSettings]` in `app/mercury_config.py`; `TaskType.ladder: tuple[str, ...]` with `TaskType.provider` now a property (`ladder[0]` or `None`); `configure_task_types(tasks: dict[str, TaskSettings]) -> None` in `app/tasks.py`, which replaces entries of `TASK_TYPES` in place. `TaskType.fallback` is removed; Task 9 replaces its one caller.

- [ ] **Step 1: Write the failing tests.** In `tests/test_mercury_config.py`:

```python
def write(tmp_path, text: str):
    path = tmp_path / "mercury.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_type_reads_its_ladder_and_budget(tmp_path):
    config = load_mercury_config(
        write(tmp_path, "tasks:\n  repo_chore:\n    ladder: [ollama, gemini]\n    budget_tokens: 40000\n")
    )
    assert config.tasks["repo_chore"] == TaskSettings(ladder=("ollama", "gemini"), budget_tokens=40000)


def test_a_type_with_no_tasks_entry_is_absent(tmp_path):
    assert load_mercury_config(write(tmp_path, "portfolio: {}\n")).tasks == {}


@pytest.mark.parametrize(
    "text, words",
    [
        ("tasks:\n  repo_chore:\n    provider: haiku\n", "tasks.repo_chore.provider"),
        ("tasks:\n  repo_chore:\n    ladder: [nobody]\n", "unknown provider 'nobody'"),
        ("tasks:\n  homework:\n    ladder: [gemini]\n", "unknown task type 'homework'"),
        ("tasks:\n  site_check:\n    ladder: [gemini]\n", "site_check calls no model"),
        ("tasks:\n  repo_chore:\n    ladder: []\n", "needs at least one provider"),
        ("budgets:\n  per_month_usd: 5\n", "budgets"),
    ],
)
def test_a_config_mercury_would_misread_stops_it_at_startup(tmp_path, text, words):
    with pytest.raises(ValueError, match=re.escape(words)):
        load_mercury_config(write(tmp_path, text))
```

In `tests/test_tasks.py`:

```python
@pytest.fixture
def restore_task_types():
    saved = dict(TASK_TYPES)
    yield
    TASK_TYPES.clear()
    TASK_TYPES.update(saved)


def test_the_shipped_ladders_are_free_and_start_where_they_did():
    assert TASK_TYPES["repo_chore"].ladder == ("gemini", "ollama")
    assert TASK_TYPES["chat"].ladder == ("ollama", "gemini")
    assert TASK_TYPES["site_check"].ladder == ()
    for name, task_type in TASK_TYPES.items():
        assert all(PROVIDERS[p].usd_per_million_tokens == 0 for p in task_type.ladder), name


def test_the_config_replaces_a_types_ladder_and_budget(restore_task_types):
    configure_task_types({"repo_chore": TaskSettings(ladder=("ollama",), budget_tokens=30_000)})

    assert TASK_TYPES["repo_chore"].provider == "ollama"
    assert TASK_TYPES["repo_chore"].ladder == ("ollama",)
    assert TASK_TYPES["repo_chore"].budget_tokens == 30_000
    assert TASK_TYPES["pytest"].ladder == ("gemini", "ollama")


def test_a_config_with_no_budget_keeps_the_types_own(restore_task_types):
    configure_task_types({"digest": TaskSettings(ladder=("ollama",), budget_tokens=None)})
    assert TASK_TYPES["digest"].budget_tokens == 20_000
```

- [ ] **Step 2: Run them to see them fail.** From WSL as in "Where this starts", `uv run pytest tests/test_mercury_config.py tests/test_tasks.py -q -p no:cacheprovider`. Expected: ImportError on `TaskSettings` and `configure_task_types`.

- [ ] **Step 3: Implement.** In `app/mercury_config.py`, add the dataclass and the loader. The loader imports `PROVIDERS` from `app.config` and `TASK_TYPES` from `app.tasks` lazily inside `_tasks`, because `app.tasks` will import `TaskSettings` from here.

```python
@dataclass(frozen=True)
class TaskSettings:
    """One entry under tasks: in mercury.yaml. ladder is the providers a run
    of this type tries in order when one fails; budget_tokens None keeps the
    type's own budget from app/tasks.py."""

    ladder: tuple[str, ...]
    budget_tokens: int | None = None


def _tasks(section: dict) -> dict[str, TaskSettings]:
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
```

In `load_mercury_config`, refuse the deleted sections and fill the new field:

```python
    for gone in ("budgets", "providers"):
        if gone in data:
            raise ValueError(
                f"mercury.yaml: {gone}: is not read. Caps are DAILY_TOKENS_PER_PROVIDER and "
                "MONTHLY_BUDGET_USD in the environment, and providers are app/config.py PROVIDERS."
            )
    ...
        tasks=_tasks(data.get("tasks") or {}),
```

with `tasks: dict[str, TaskSettings] = field(default_factory=dict)` on `MercuryConfig` (import `field`). In `app/tasks.py`, replace `provider` and `fallback` with `ladder`:

```python
@dataclass(frozen=True)
class TaskType:
    name: str
    tools: tuple[str, ...]
    # The providers a run tries in order; the first is the type's own. Empty
    # for a type that calls no model.
    ladder: tuple[str, ...]
    budget_tokens: int
    public: bool = False

    @property
    def provider(self) -> str | None:
        return self.ladder[0] if self.ladder else None


_TYPES = (
    TaskType(name="pytest", tools=(), ladder=("gemini", "ollama"), budget_tokens=50_000),
    TaskType(name="chat", tools=_CHAT_TOOLS, ladder=("ollama", "gemini"), budget_tokens=20_000),
    TaskType(name="repo_chore", tools=(), ladder=("gemini", "ollama"), budget_tokens=50_000),
    TaskType(name="site_check", tools=(), ladder=(), budget_tokens=0),
    TaskType(name="digest", tools=(), ladder=("gemini", "ollama"), budget_tokens=20_000),
)


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
```

Rewrite the module docstring to say the defaults are in code and `mercury.yaml` overrides the ladder and budget. Call `configure_task_types(config.tasks)` right after each `load_mercury_config` in `app/main.py`'s lifespan, `app/worker.py` `main` and `app/scheduler.py` `main`. In `app/worker.py` keep `_with_fallback` compiling for now by reading `task_type.ladder[1] if len(task_type.ladder) > 1 else None` where it read `task_type.fallback`; Task 9 rewrites it.

In `config/mercury.sample.yaml`, delete `providers:` and `budgets:`, and replace `tasks:` with:

```yaml
tasks:                  # optional; each type's ladder is the providers it tries in order
  pytest:
    ladder: [gemini, ollama]
    budget_tokens: 50000
  chat:
    ladder: [ollama, gemini]
    budget_tokens: 20000
  repo_chore:
    ladder: [gemini, ollama]
    budget_tokens: 50000
  digest:
    ladder: [gemini, ollama]
    budget_tokens: 20000
```

and correct the environment list at the bottom to the names the image reads: `MODEL_API_KEY` (Gemini), `OLLAMA_API_KEY`, `ANTHROPIC_API_KEY` (no type uses it), plus `MAX_RUNS_PER_DAY`, `DAILY_TOKENS_PER_PROVIDER` and `MONTHLY_BUDGET_USD` as plain settings.

- [ ] **Step 4: Run the full suite.** Expected: the new tests pass, and `tests/test_tasks.py::test_every_other_type_names_a_registered_provider` still passes through the `provider` property. `ruff check` and `ruff format --check` clean.

- [ ] **Step 5: Commit** `Read each task type's provider ladder and budget from mercury.yaml, and refuse the unread budgets and providers sections`.

- [ ] **Step 6: The private config, Thomas's step.** Nothing goes live until `mercury-config` changes, and the new image refuses the old `mercury.yaml` at startup, so the config change and the `PUBLIC_SHA` bump go in one commit there. Prepare it as a script under the session scratchpad, as `raise-run-limit.sh` was on 2026-10-07: delete `providers:` and `budgets:`, turn each `provider: x` under `tasks:` into `ladder:` (for `repo_chore`, `[gemini, ollama]`, since the stated `haiku` was never read and no `ANTHROPIC_API_KEY` is deployed), print the diff, and push only with `--yes`. Do not deploy this step alone; it ships with Task 9 so the fallback reads the ladder the moment the ladder is read.

---

### Task 9: A run falls back along its ladder from its own rung

**Files:**
- Modify: `app/worker.py` (`_with_fallback`)
- Test: `tests/test_fallback.py`

**Interfaces:**
- Consumes: `TaskType.ladder` (Task 8).
- Produces: `rungs_after(ladder: tuple[str, ...], provider: str) -> tuple[str, ...]` in `app/worker.py`. The run's model is the run's provider with each later rung behind it in order, through nested `FallbackModel`s, and each switch writes the provider that takes over to the run row.

- [ ] **Step 1: Write the failing tests** in `tests/test_fallback.py`:

```python
from app.worker import rungs_after


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("gemini", ("ollama", "haiku")),
        ("ollama", ("haiku",)),
        # A reclaimed run already on the last rung has nothing behind it.
        ("haiku", ()),
        # A provider the caller named that is not on the ladder gets the whole ladder.
        ("groq", ("gemini", "ollama", "haiku")),
    ],
)
def test_the_rungs_after_a_provider(provider, expected):
    assert rungs_after(("gemini", "ollama", "haiku"), provider) == expected


def test_two_failures_walk_the_run_down_two_rungs_and_the_row_follows(migrated_db, restore_task_types):
    configure_task_types({"pytest": TaskSettings(ladder=("gemini", "ollama", "haiku"))})
    run_id = new_pytest_run(migrated_db, provider="gemini")
    models = {"gemini": _Failing(), "ollama": _Failing(), "haiku": StubModel(replies=["ok"])}
    model = _with_fallback(
        migrated_db, run_id, models["gemini"], TASK_TYPES["pytest"],
        settings_with(), lambda settings, name: models[name], "gemini",
    )  # fmt: skip

    for _ in range(2):
        with pytest.raises(RuntimeError):
            model.complete("s", "p")
    assert model.complete("s", "p").text == "ok"
    provider = migrated_db.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert provider == ("haiku",)


def test_a_rung_with_no_credentials_is_skipped(migrated_db, restore_task_types):
    configure_task_types({"pytest": TaskSettings(ladder=("gemini", "ollama", "haiku"))})
    run_id = new_pytest_run(migrated_db, provider="gemini")

    def build(settings, name):
        if name == "ollama":
            raise RuntimeError("no model credentials: set OLLAMA_API_KEY")
        return StubModel(replies=[name])

    model = _with_fallback(
        migrated_db, run_id, _Failing(), TASK_TYPES["pytest"], settings_with(), build, "gemini"
    )
    with pytest.raises(RuntimeError):
        model.complete("s", "p")
    assert model.complete("s", "p").text == "haiku"
```

`new_pytest_run` inserts a `pytest` run with that provider and returns its id; add it beside the existing helpers in the file if none fits. `restore_task_types` is the fixture from Task 8; move it into `tests/conftest.py` so both files share it.

- [ ] **Step 2: Run to see them fail.** Expected: ImportError on `rungs_after`.

- [ ] **Step 3: Implement** in `app/worker.py`:

```python
def rungs_after(ladder: tuple[str, ...], provider: str) -> tuple[str, ...]:
    """The rungs a run on this provider may still fall back to. A run that
    already fell back, and is then reclaimed, keeps only the rungs below the
    one it reached."""
    if provider in ladder:
        return ladder[ladder.index(provider) + 1 :]
    return tuple(rung for rung in ladder if rung != provider)


def _with_fallback(conn, run_id, model, task_type, settings, model_builder, provider) -> Model:
    """The run's model with every later rung behind it, nearest first. Each
    switch writes the provider taking over to the run's row, so the runs list
    and the daily token cap count the provider that answered."""
    fields = {"run_id": run_id, "worker_id": settings.worker_id}
    chain: list[tuple[str, Model]] = []
    for rung in rungs_after(task_type.ladder, provider):
        try:
            chain.append((rung, model_builder(settings, rung)))
        except RuntimeError as error:
            logger.warning("run %s skips rung %s: %s", run_id, rung, error, extra=fields)
    if not chain:
        return model

    def switch_to(name: str, from_name: str) -> Callable[[], None]:
        def switch() -> None:
            logger.warning(
                "run %s: %s failed, falling back to %s", run_id, from_name, name, extra=fields
            )
            conn.execute("UPDATE runs SET provider = %s WHERE id = %s", (name, run_id))

        return switch

    # Fold from the last rung up, so each FallbackModel's fallback is the rest of the chain.
    tail = chain[-1][1]
    for index in range(len(chain) - 2, -1, -1):
        name, rung_model = chain[index]
        tail = FallbackModel(rung_model, tail, on_switch=switch_to(chain[index + 1][0], name))
    return FallbackModel(model, tail, on_switch=switch_to(chain[0][0], provider))
```

`FallbackModel` re-raises the failing call after switching, so a two rung walk raises twice before the third rung answers; the loop's existing retries (4 attempts) cover two switches. Check that the lease arithmetic in `app/config.py` (`DEFAULT_LEASE_SECONDS`) still holds: a step is still at most 4 calls, whichever rung answers them.

- [ ] **Step 4: Run the full suite.** The existing fallback tests keep passing; `tests/test_tasks.py::test_chat_runs_on_ollama_and_the_rest_on_gemini` still holds.

- [ ] **Step 5: Commit** `Fall back along the type's ladder from the run's own rung, so a reclaimed run keeps only the rungs below it`.

- [ ] **Step 6: Deploy Tasks 8 and 9 together**, Thomas's step: push, wait for CI and Publish, then run the Task 8 script with `PUBLIC_SHA` set to this commit. Confirm with the MCP `status` tool and one `pytest` run that the api started and runs still close `succeeded`.

---

### Task 10: A chore that cannot finish ends `escalated` with its reason

**Files:**
- Create: `migrations/013_escalation.sql`
- Modify: `app/repo_chore.py`, `app/worker.py` (`_run_chore`), `app/run_request.py` (`PostedSource`), `app/run_list.py`, `evals/runner.py` (`run_one`, `summarise`, the refused message)
- Test: `tests/test_repo_chore.py`, `tests/test_run_list.py`, `tests/test_migrations.py`, `tests/test_eval_runner.py`

**Interfaces:**
- Produces: run columns `escalation_reason text`, `hint text`, `escalation_message_id bigint`, `needs_claude boolean`; status `escalated`; source `eval`; constants in `app/repo_chore.py`: `RED = "tests still failing after 3 attempts"`, `UNUSABLE = "three unusable replies"`, `WEAKENED = "weakened tests"` (used from Task 11), `OUTAGE = "providers unavailable"`; `escalation_reason` as the last field of `GET /runs` and `GET /runs/{id}`.

- [ ] **Step 1: The migration.**

```sql
-- Phase 2's escalation ladder. A chore that cannot finish on a free model
-- ends escalated with a reason. hint is the advice an advised rerun carries
-- (source_run_id names the run it advises). escalation_message_id is the
-- Telegram message a reply to which becomes a hint. needs_claude marks a
-- chore whose second advised rerun also failed.
ALTER TABLE runs ADD COLUMN escalation_reason text;
ALTER TABLE runs ADD COLUMN hint text;
ALTER TABLE runs ADD COLUMN escalation_message_id bigint;
ALTER TABLE runs ADD COLUMN needs_claude boolean NOT NULL DEFAULT false;

ALTER TABLE runs DROP CONSTRAINT runs_source_check;
ALTER TABLE runs ADD CONSTRAINT runs_source_check
    CHECK (source IN ('telegram', 'mcp', 'n8n', 'api', 'scheduler', 'eval'));

CREATE INDEX runs_escalated_idx ON runs (created_at DESC) WHERE status = 'escalated';
```

Check the constraint name first with `\d runs` on the compose database; 012 created it unnamed, so Postgres called it `runs_source_check`.

- [ ] **Step 2: Write the failing tests.** In `tests/test_repo_chore.py`, rename `test_three_red_attempts_fail_the_run_with_the_diff_and_push_nothing` to `..._escalate_the_run_...` and change its status assertions to `escalated`, adding:

```python
    assert output["reason"] == RED
    row = migrated_db.execute("SELECT escalation_reason FROM runs WHERE id = %s", (run_id,))
    assert row.fetchone() == (RED,)
```

and add:

```python
def test_three_unusable_replies_escalate_with_their_own_reason(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), "I would change calc.py like so."])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "escalated"
    assert done(migrated_db, run_id)["reason"] == UNUSABLE
    assert remote_branches(remote) == ["main"]


def test_a_model_that_never_answers_ends_in_error_as_an_outage(migrated_db, remote, github, tmp_path):
    run_id = chore_run(migrated_db)

    result = run_repo_chore(
        migrated_db, run_id, _Failing(), setup(tmp_path, github), worker_id=WORKER,
        retry_attempts=1, retry_backoff_seconds=0,
    )  # fmt: skip

    assert result.status == "error"
    assert done(migrated_db, run_id)["reason"] == OUTAGE
```

(`_Failing` as in `tests/test_fallback.py`; import it from there.) Every existing test that expected a chore to end `failed` now expects `escalated`: search `tests/` for `"failed"` beside `repo_chore`, including the Open it anyway tests in `tests/test_repo_chore_approval.py`. In `tests/test_run_list.py`, assert that a run row with `escalation_reason` set serialises it as `"escalation_reason"` and that one without serialises `None`. In `tests/test_eval_runner.py`, assert that `run_one` posts `"source": "eval"` (the fake API there records the body) and that an escalated run's row carries the reason as `detail`.

- [ ] **Step 3: Run to see them fail.**

- [ ] **Step 4: Implement.** In `app/repo_chore.py`, start `state` with `"unusable": 0`, add one each time a reply is not the JSON asked for or names a refused path, and choose the reason when the attempts run out:

```python
    else:
        ...
        reason = UNUSABLE if state["unusable"] == MAX_ATTEMPTS else RED
        return close("escalated", {"reason": reason, "diff": diff[:MAX_DIFF_CHARS], "test_output": test_output})
```

`close` writes `escalation_reason` when the status is `escalated`:

```python
    def close(status: str, output: dict) -> LoopResult:
        write("done", {"status": status, **output})
        if not finish_run(conn, run_id, status, state["tokens"], worker_id=worker_id):
            return LoopResult(status="lost", attempts=state["attempts"], tokens_used=state["tokens"])
        if status == "escalated":
            conn.execute(
                "UPDATE runs SET escalation_reason = %s WHERE id = %s", (output["reason"], run_id)
            )
        ...
```

The `RuntimeError` branch closes `error` with `{"reason": OUTAGE}`. In `app/worker.py` `_run_chore`, offer Open it anyway on `escalated` instead of `failed` (Task 12 replaces the offer). Add `"eval"` to `PostedSource`. In `app/run_list.py` append `escalation_reason` to `_COLUMNS` after `source` and to `serialize_run_row`; the cursor reads columns 0 and 7, so appending is safe. In `evals/runner.py`, post `"source": "eval"`, set `detail` to `run.get("escalation_reason") or ""` for a run that did not succeed, and change the refused message to say the limit is the `MAX_RUNS_PER_DAY` Actions variable in `mercury-config` (set it, re-run Deploy). The web page shows the status string as it is, so `escalated` needs no web change; check `web/src` for a status colour map anyway and give `escalated` the colour `failed` has if there is one.

- [ ] **Step 5: Run the full suite, then commit** `End a chore that cannot finish as escalated, with red tests, unusable replies or an outage as its reason`.

---

### Task 11: A chore may not weaken `main`'s tests

**Files:**
- Create: `app/test_guard.py`
- Modify: `app/repo_chore.py` (`_run`), `app/progress.py` (`_step_line`), `evals/runner.py` (`summarise`)
- Test: `tests/test_test_guard.py`, `tests/test_repo_chore.py`, `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `WEAKENED` (Task 10).
- Produces: `weakened_tests(diff: str) -> list[str]`, one line per problem, empty when the diff keeps every test. A `guard` step `{"attempt": n, "problems": [...]}` after each green test run whose diff weakens tests.

- [ ] **Step 1: Write the failing tests** in `tests/test_test_guard.py`. The diffs are what `git diff --cached` prints.

```python
from app.test_guard import weakened_tests

ADD_TEST = """\
diff --git a/test_calc.py b/test_calc.py
--- a/test_calc.py
+++ b/test_calc.py
@@ -1,6 +1,10 @@
 import unittest
 from calc import add
 
 class AddTest(unittest.TestCase):
     def test_adds_two_numbers(self):
         self.assertEqual(add(2, 3), 5)
+
+    def test_divides(self):
+        self.assertEqual(divide(7, 2), 3.5)
"""

# What ollama did on divide (fixture PR #19): the class became bare functions.
REWRITTEN = """\
diff --git a/test_calc.py b/test_calc.py
--- a/test_calc.py
+++ b/test_calc.py
@@ -1,6 +1,7 @@
-import unittest
-from calc import add
-
-class AddTest(unittest.TestCase):
-    def test_adds_two_numbers(self):
-        self.assertEqual(add(2, 3), 5)
+from calc import divide
+
+def test_divide():
+    assert divide(7, 2) == 3.5
+
+def test_divide_by_zero():
+    pass
"""


def test_adding_a_test_beside_the_old_ones_is_fine():
    assert weakened_tests(ADD_TEST) == []


def test_a_test_that_disappears_is_named():
    assert weakened_tests(REWRITTEN) == ["test_calc.py: removed test_adds_two_numbers"]


def test_moving_a_test_within_the_file_is_not_a_removal():
    moved = ADD_TEST.replace("+    def test_divides", "-    def test_adds_two_numbers(self):\n+    def test_adds_two_numbers(self):\n+    def test_divides")
    assert weakened_tests(moved) == []


@pytest.mark.parametrize(
    "line",
    [
        "+    @unittest.skip('later')",
        "+    @pytest.mark.skip",
        "+    @pytest.mark.xfail",
        "+        pytest.skip('flaky')",
        "+    @unittest.expectedFailure",
        "+  it.skip('adds', () => {",
        "+  xit('adds', () => {",
    ],
)
def test_a_skip_or_xfail_added_to_a_test_file_is_named(line):
    diff = ADD_TEST + line + "\n"
    assert weakened_tests(diff) == [f"test_calc.py: added a skip ({line[1:].strip()})"]


def test_a_skip_word_outside_a_test_file_is_ignored():
    diff = (
        "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1 +1,2 @@\n"
        " def add(a, b):\n+    skip = pytest.mark.skip\n"
    )
    assert weakened_tests(diff) == []


def test_a_deleted_test_file_is_named():
    diff = (
        "diff --git a/test_calc.py b/test_calc.py\ndeleted file mode 100644\n"
        "--- a/test_calc.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def test_add():\n-    pass\n"
    )
    assert weakened_tests(diff) == ["test_calc.py: deleted", "test_calc.py: removed test_add"]


def test_javascript_tests_count_by_their_names():
    diff = (
        "diff --git a/src/sum.test.ts b/src/sum.test.ts\n--- a/src/sum.test.ts\n+++ b/src/sum.test.ts\n"
        "@@ -1,3 +1,3 @@\n-test('adds two numbers', () => {\n+test('adds numbers', () => {\n"
    )
    assert weakened_tests(diff) == ["src/sum.test.ts: removed adds two numbers"]
```

In `tests/test_repo_chore.py`:

```python
REWRITTEN_TEST_CALC = "from calc import subtract\n\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n"


def drop_add(calc: str) -> str:
    """A green change that replaces main's test_add with its own test."""
    return json.dumps({"files": {"calc.py": calc, "test_calc.py": REWRITTEN_TEST_CALC}, "summary": "x"})


def test_a_green_change_that_drops_a_test_is_retried_with_the_test_named(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), drop_add(GOOD_CALC), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert "removed test_add" in model.prompts[2]
    assert "Keep every existing test" in model.prompts[2]
    assert kinds(migrated_db, run_id).count("guard") == 1


def test_three_attempts_that_drop_a_test_escalate_as_weakened_and_push_nothing(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    model = StubModel(replies=[pick("calc.py"), drop_add(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "escalated"
    output = done(migrated_db, run_id)
    assert output["reason"] == WEAKENED
    assert output["problems"] == ["test_calc.py: removed test_add"]
    assert remote_branches(remote) == ["main"]
```

`change()` keeps `test_calc.py` untouched and adds `test_subtract.py`, so the second reply passes the guard.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement `app/test_guard.py`.**

```python
"""Whether a chore's diff weakens the repo's tests, per decision 12 of
docs/build-brief-evals.md. It reads the staged diff, so it works for any
language a repo's test command runs, and it never runs the repo's code.

A test is named by its function or its it()/test() title. One that is
removed and not added back anywhere in the diff is lost, so a test moved
within a file is fine and a test renamed is not. A skip or xfail marker
added to a test file counts too, and so does a deleted test file.
"""

import re
from pathlib import PurePosixPath

_TEST_FILE = re.compile(
    r"(^|/)(test_[^/]*\.py|[^/]*_test\.py|[^/]*\.(test|spec)\.[cm]?[jt]sx?)$|(^|/)(tests|__tests__)/"
)
_PY_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(")
_JS_TEST = re.compile(r"""^\s*(?:it|test)\s*\(\s*(['"`])(.+?)\1""")
_SKIP = re.compile(
    r"@unittest\.skip|@pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(|unittest\.expectedFailure"
    r"|\b(it|test|describe)\.(skip|todo)\(|\bx(it|describe|test)\("
)


def _names(line: str) -> str | None:
    match = _PY_TEST.match(line) or _JS_TEST.match(line)
    if match is None:
        return None
    return match.group(1) if match.re is _PY_TEST else match.group(2)


def weakened_tests(diff: str) -> list[str]:
    problems: list[str] = []
    removed: dict[str, set[str]] = {}
    added: set[str] = set()
    path, deleted = None, False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path, deleted = line.split(" b/", 1)[-1], False
            continue
        if line.startswith("deleted file mode"):
            deleted = True
            continue
        if line.startswith(("--- ", "+++ ", "@@")) or path is None:
            if line.startswith("+++ ") and deleted and _TEST_FILE.search(path or ""):
                problems.append(f"{path}: deleted")
            continue
        if not _TEST_FILE.search(path):
            continue
        body = line[1:]
        if line.startswith("-") and (name := _names(body)):
            removed.setdefault(path, set()).add(name)
        elif line.startswith("+"):
            if name := _names(body):
                added.add(name)
            if _SKIP.search(body):
                problems.append(f"{path}: added a skip ({body.strip()})")
    for file, names in removed.items():
        problems += [f"{file}: removed {name}" for name in sorted(names - added)]
    return problems
```

Tune the regular expressions until every test in Step 1 passes; the tests are the specification, not this sketch. `PurePosixPath` is only needed if you normalise paths; drop the import if not.

In `app/repo_chore.py` `_run`, after a green test run, stage and check before breaking out:

```python
        passed, exit_code, test_output = _run_tests(clone, setup, workdir)
        write("test", {"attempt": attempt, "passed": passed, "exit_code": exit_code})
        if passed:
            git.run("add", "--", *sorted(written), cwd=clone)
            problems = weakened_tests(git.run("diff", "--cached", cwd=clone))
            if not problems:
                break
            write("guard", {"attempt": attempt, "problems": problems})
            state["weakened"] = problems
            current = "\n\n".join(
                f"=== {path} ===\n{(clone / path).read_text()}" for path in sorted(written)
            )
            prompt = (
                f"Instruction:\n{instruction}\n\nFiles in the repository:\n{listing}\n\n"
                f"Your change so far:\n{current}\n\n"
                f"`{setup.repo.test_command}` passed, but your change removes or skips tests "
                "the repository already has:\n" + "\n".join(problems) + "\n\n"
                "Keep every existing test as it is, with the same name, and add new tests "
                'beside them. Reply {"files": {"path": "the full new contents"}, "summary": '
                '"one line"} with the corrected files.'
            )
            continue
        state["weakened"] = None
        ...
```

and when the attempts run out, a last attempt that was green but weakened closes with `{"reason": WEAKENED, "problems": state["weakened"], "diff": ..., "test_output": ""}`, ahead of the `UNUSABLE` and `RED` choice. In `app/progress.py`, a `guard` step reads `attempt {n} dropped or skipped {k} test(s)`; the problem lines name tests, not code, so they may reach Telegram, but keep them out of progress anyway, as the module docstring promises. In `evals/runner.py` `summarise`, add a column `Kept tests` that counts, per column, rows whose `detail` is not `weakened tests`, so the report shows how often the guard ended a chore.

- [ ] **Step 4: Run the full suite, then commit** `Retry a chore whose green diff drops or skips main's tests, naming them, and escalate a third such attempt as weakened tests`.

---

### Task 12: One Telegram message per escalated chore

**Files:**
- Create: `app/escalation.py`
- Modify: `app/worker.py` (`_run_chore`, remove `_offer_open_anyway`), `app/approvals.py` (nothing if `open_anyway` stays as it is)
- Test: `tests/test_escalation.py`, `tests/test_repo_chore_approval.py` (its Open it anyway tests move to the new message)

**Interfaces:**
- Consumes: `escalation_reason`, `escalation_message_id`, `source` (Task 10).
- Produces: `announce_escalation(conn, telegram, chat_id, run_id, page_base_url) -> int | None`, the message id or `None` when nothing was sent; `chain_root(conn, run_id) -> str`, the first run of a chore's chain through `source_run_id`.

**What the message says**, in this order: `Chore on <repo> escalated (<id8>): <reason>`, the instruction, the last 1,000 characters of the test output when there is any (inside a plain text block, since the message is not Markdown), the run page `<API_BASE_URL>/#/runs/<id>`, and `Reply to this message with a hint and I will rerun it from main with your hint.` When the run left a diff, it carries the Open it anyway and Leave it buttons through `ask(..., "open_anyway", ...)`, exactly as the old offer did; otherwise it is a plain `send_message`. Its message id goes to `runs.escalation_message_id`.

**When it is not sent:** the chore's `source` is `eval` (decision 18); there is no bot or owner chat; or the chain already has an escalated run with an `escalation_message_id` (a second escalation of the same chore goes in the report, per the spec). A Telegram error is logged and the run stays escalated with no message id.

- [ ] **Step 1: Write the failing tests** in `tests/test_escalation.py`, against `fake_telegram`:

```python
def test_an_escalated_chore_sends_one_message_with_its_reason_output_and_page(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, reason=RED, test_output="E   assert 8 == 2", diff="+x\n")

    message_id = announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, "https://mercury.test")

    [sent] = fake_telegram.sent()
    assert sent["chat_id"] == CHAT
    assert f"escalated ({run_id[:8]}): {RED}" in sent["text"]
    assert "assert 8 == 2" in sent["text"]
    assert f"https://mercury.test/#/runs/{run_id}" in sent["text"]
    assert "Reply to this message with a hint" in sent["text"]
    assert "Open it anyway" in json.dumps(sent["reply_markup"])
    stored = migrated_db.execute("SELECT escalation_message_id FROM runs WHERE id = %s", (run_id,))
    assert stored.fetchone() == (message_id,)


def test_one_with_no_diff_has_no_open_it_anyway_button(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, reason=UNUSABLE, diff="")
    announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, "https://mercury.test")
    assert "reply_markup" not in fake_telegram.sent()[0]


def test_an_eval_chore_is_never_announced(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, reason=RED, source="eval")
    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, "https://mercury.test") is None
    assert fake_telegram.sent() == []


def test_a_second_escalation_of_the_same_chore_is_not_announced(migrated_db, fake_telegram):
    first = escalated_chore(migrated_db, reason=RED)
    announce_escalation(migrated_db, client(fake_telegram), CHAT, first, "https://mercury.test")
    second = escalated_chore(migrated_db, reason=RED, source_run_id=first, hint="use float division")

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, second, "https://mercury.test") is None
    assert len(fake_telegram.sent()) == 1
```

`client(fake)` is `TelegramClient("test-token", fake.url)`; check `tests/telegram_fake.py` for the attribute and for the key it records buttons under, and match the assertion to it. `CHAT` is any integer. `escalated_chore` inserts a finished `repo_chore` with status `escalated`, the reason, and a `done` step whose output carries `reason`, `diff` and `test_output`. Add a worker level test that `process_run` on a chore that escalates sends the message to the owner chat whatever its source (`api`, `n8n`, `mcp`, `telegram`), replacing the old rule that only a Telegram chore offered Open it anyway.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement** `app/escalation.py` with `chain_root`, `announce_escalation` and the text builder; `chain_root` walks `source_run_id` with a recursive CTE:

```sql
WITH RECURSIVE chain(id, source_run_id) AS (
    SELECT id, source_run_id FROM runs WHERE id = %s
    UNION ALL
    SELECT r.id, r.source_run_id FROM runs r JOIN chain c ON r.id = c.source_run_id
)
SELECT id FROM chain WHERE source_run_id IS NULL
```

"Already announced" is any run whose root is the same and whose `escalation_message_id` is set. In `app/worker.py`, `_run_chore` calls `announce_escalation(conn, telegram, owner_chat_id, run_id, settings.api_base_url)` when the result is `escalated`, which means passing `owner_chat_id` into `_run_chore`. `API_BASE_URL` is the api's public URL on the worker in the Bicep; check `infra/main.bicep`, and if the worker gets the internal URL instead, add `PUBLIC_BASE_URL` beside it in Task 18 rather than linking a page nobody can open.

- [ ] **Step 4: Run the full suite, then commit** `Send one Telegram message per escalated chore, with its reason, test output, page and a hint prompt, and none for eval chores or a second escalation`.

---

### Task 13: `advise` reruns an escalated chore from `main` with a hint

**Files:**
- Create: `app/advice.py`
- Modify: `app/repo_chore.py` (an advised run's prompt), `app/mcp_server.py` (the `advise` tool), `app/worker.py` (mark `needs_claude`)
- Test: `tests/test_advice.py`, `tests/test_repo_chore.py`, `tests/test_mcp.py`

**Interfaces:**
- Consumes: `hint`, `needs_claude`, `escalation_reason`, `chain_root` (Tasks 10 and 12).
- Produces: `advise(conn, run_id: str, hint: str, source: str) -> str`, the new run's id, raising `AdviceRefused(message)` with a message for the owner; `MAX_ADVISED = 2`.

**Rules.** The run must be a `repo_chore`, finished `escalated`, and the newest run of its chain (advice on an older one would fork the chore). The hint is stripped, not blank, and at most 2,000 characters. The chain's advised runs (those with a `hint`) number fewer than `MAX_ADVISED`; otherwise refuse with `This chore has had 2 advised reruns. Take it to a Claude session.` The new run copies `task` and `repo`, sets `source_run_id` to the advised run, `hint`, `source` (`telegram` or `mcp`), `provider` the type's first rung (the free model starts again, per decision 7), status `pending`, so it starts without Approve (decision 8). Its repo must still be listed with a `test_command`, through `find_repo`.

**The advised run's prompt.** `run_repo_chore` already reads `source_run_id` to mean Open it anyway. Tell the two apart by `hint`: a run with a hint takes the normal `_run` path from a fresh clone of `main`, and its first edit prompt gains, after the instruction:

```
The owner's hint: <hint>

An earlier attempt at this chore failed (<reason>). Its diff, which is not applied:
<diff, at most 20,000 characters>

Its test output ended:
<test output>
```

A run with `source_run_id` and no hint stays Open it anyway.

**needs_claude.** When an advised run escalates and its chain now holds `MAX_ADVISED` advised runs, the worker sets `needs_claude = true` on it. Task 17's report lists it under "take to a Claude session".

- [ ] **Step 1: Write the failing tests.** In `tests/test_advice.py`: advice on an escalated chore creates a pending run with the fields above; advice on a `succeeded`, `failed` or running chore, on a non chore, on an older run of a chain, with a blank hint, or on a chain with two advised runs, raises `AdviceRefused` and creates nothing. In `tests/test_repo_chore.py`: an advised run clones `main`, not the failed branch, and its edit prompt contains the hint, the failed diff and the test output. In `tests/test_mcp.py`: the `advise` tool returns `{"id", "status": "pending"}`, and a refusal comes back as a tool error whose text is the refusal.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement.** The MCP tool, beside `create_run`:

```python
ADVISE = """Rerun an escalated repo chore from main with a hint, without asking for \
Approve. run_id is the escalated run (the newest of its chore). The hint is what the \
model got wrong and what to do instead, in a few sentences. A chore takes at most two \
advised reruns; after that, do it in a Claude session. Returns the new run's id."""

    @mcp.tool(name="advise", description=ADVISE)
    async def advise_tool(run_id: str, hint: str) -> dict[str, Any]:
        try:
            new_id = await run_in_threadpool(_advise, app.state, run_id, hint, "mcp")
        except AdviceRefused as refused:
            raise ToolError(f"422: {refused}") from None
        return {"id": new_id, "status": "pending"}
```

where `_advise` opens a connection on `settings.database_url` and passes `app.state.mercury.repos` for the `find_repo` check. Update the server's `instructions` string to name `advise` and `report` (Task 17).

- [ ] **Step 4: Run the full suite, then commit** `Rerun an escalated chore from main with the owner's hint through advise, at most twice, then mark it for a Claude session`.

---

### Task 14: A Telegram reply to an escalation message is a hint

**Files:**
- Modify: `app/telegram_webhook.py`
- Test: `tests/test_telegram_webhook.py`

**Interfaces:**
- Consumes: `advise`, `AdviceRefused` (Task 13), `escalation_message_id` (Task 12).

- [ ] **Step 1: Write the failing tests.** Post updates as the existing webhook tests do. A message from the allowed chat with `reply_to_message.message_id` equal to an escalated run's `escalation_message_id` creates an advised run and gets the answer `Rerunning <id8> from main with your hint.`; no chat run is created. A refusal is answered with the refusal text. A reply to any other message (an old progress message, the "On it." placeholder) is ordinary chat, as today. A reply from a chat not on the allowlist is ignored as every message from it is.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement.** In `telegram_webhook`, after the allowlist check and before the `/` command branch:

```python
    replied_to = (message.get("reply_to_message") or {}).get("message_id")
    if replied_to is not None:
        reply = await _advise_from_reply(request, chat_id, replied_to, text.strip())
        if reply is not None:
            await _send(request, chat_id, reply)
            return {}
```

`_advise_from_reply` looks up `SELECT id FROM runs WHERE escalation_message_id = %s AND telegram_chat_id IS NOT DISTINCT FROM ...`; the message id alone is enough within the one allowed chat, so match on `escalation_message_id` only and return `None` when no run has it. It runs `advise` in the thread pool with source `telegram` and returns the answer text.

- [ ] **Step 4: Run the full suite, then commit** `Turn a Telegram reply to an escalation message into an advised rerun`.

---

### Task 15: An outage on every provider retries hourly, at most three times

**Files:**
- Create: `app/outage.py`
- Modify: `app/scheduler.py` (`main`)
- Test: `tests/test_outage.py`

**Interfaces:**
- Consumes: `OUTAGE` (Task 10), `chain_root` (Task 12), `announce_escalation` (Task 12).
- Produces: `retry_outages(conn, telegram, chat_id, page_base_url) -> list[str]`, the ids of the retries it queued; `MAX_OUTAGE_RETRIES = 3`.

**Rules.** A candidate is a `repo_chore` finished `error` whose `done` reason is `OUTAGE`, that is the newest run of its chain, and that finished at least 30 minutes ago (the hourly Job then never retries a run that failed a minute before the tick). Its chain's consecutive outage runs at the tail are counted. Fewer than `1 + MAX_OUTAGE_RETRIES`: queue a retry with the same `task`, `repo`, `hint` and `source`, `source_run_id` the failed run, `provider` the first rung, status `pending`. Otherwise mark the failed run `escalated` with `escalation_reason = OUTAGE` and announce it (Task 12's rules apply, so an eval chore stays silent). Each candidate is handled in its own transaction.

- [ ] **Step 1: Write the failing tests.** One outage run older than 30 minutes is retried once, with the fields above. One younger than 30 minutes is left. A chain of four consecutive outages escalates the fourth and queues nothing. A run whose chain already has a newer run is left. Running `retry_outages` twice in a row queues one retry, not two.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement**, and call it in `app/scheduler.py` `main` after `expire_due`. The scheduler inserts these runs itself rather than POSTing them, because a retry is the same chore continuing, not a new request through the chore gate; say so in the docstring.

- [ ] **Step 4: Run the full suite, then commit** `Retry a chore that hit an outage on every provider at the next hourly tick, up to three times, then escalate it`.

---

### Task 16: A cancelled chore leaves no branch behind

**Files:**
- Modify: `app/repo_chore.py` (`_run`, `_open_anyway`)
- Test: `tests/test_repo_chore.py`

**The race** (handoff, 2026-10-06): a cancel landing between a chore's green tests and its `git push` lets the push happen, then `write("push", ...)` raises `LostLease` and no pull request is opened, so `agent/<id>` stays on the remote. A takeover must keep the branch, because the next worker resumes from it (`remote_has_branch`).

- [ ] **Step 1: Write the failing tests.** Cancel the run (`cancel_run`) from inside a `FakeGitHub` hook or a wrapped `_Git.run` that fires after the push command returns; assert the result is `lost`, the branch is gone from the bare remote, and no pull request exists. A second test changes `claimed_by` to another worker at the same point instead of cancelling; the branch must still be there.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement.** Wrap the push and the `push` step:

```python
    git.run("push", "-q", "origin", branch, cwd=clone, remote=True)
    try:
        write("push", {"branch": branch})
    except LostLease:
        status = conn.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone()[0]
        if status == "cancelled":
            git.run("push", "-q", "origin", "--delete", branch, cwd=clone, remote=True)
        raise
```

`_run` and `_open_anyway` need `conn` and `run_id` for this; pass them in. Do the same after the push in `_open_anyway`.

- [ ] **Step 4: Run the full suite, then commit** `Delete a chore's pushed branch when it was cancelled before its pull request, and keep it for a takeover`.

---

### Task 17: The report

**Files:**
- Create: `app/report.py`, `scripts/mercury_report.py`
- Modify: `app/main.py` (`GET /report`), `app/mcp_server.py` (the `report` tool), `app/digest.py` (one line), `.gitignore` (`reports/`)
- Test: `tests/test_report.py`, `tests/test_mcp.py`, `tests/test_digest.py`

**Interfaces:**
- Produces: `build_report(conn, since: datetime) -> str`, Markdown; `GET /report?since=<ISO date>` behind the bearer token, `text/markdown`; MCP `report(since: str | None)`; `waiting_line(conn) -> str | None` for the digest.

**What it says**, in this order:

1. `## Escalations`: each escalated chore since `since`, newest first, grouped by chain. For each: the repo and instruction; a table of every run in the chain (id8, provider, tokens, USD from `PROVIDERS` rates, status, reason, hint if any); the last run's diff (at most 6,000 characters) and test output tail (at most 2,000); why it stopped; and `Take to a Claude session` when `needs_claude`. A chain that is waiting on advice says `Waiting for a hint (reply on Telegram or call advise).`
2. `## Chores Mercury started`: runs with `source = 'scheduler'` and `type = 'repo_chore'`, with PR links from their `pr` step and their status. None exist until Phase 4; the section then says `None yet.`
3. `## Eval`: the server has no eval results, so it says `The latest eval report is the newest file in evals/results/ in the public repo.` `scripts/mercury_report.py` replaces this section with the newest local `evals/results/*.md` summary table.
4. `## Spend`: today's tokens per provider against `DAILY_TOKENS_PER_PROVIDER`, this month's USD against `MONTHLY_BUDGET_USD` (`month_spend_usd`), and runs started today against `MAX_RUNS_PER_DAY`.

`since` defaults to 7 days ago. Diffs and test output are the repo's own code, which the owner already sees in the PR, and the report sits behind the bearer token; it never goes to a log line.

**`scripts/mercury_report.py`** reads `MERCURY_URL` and `MERCURY_BEARER_TOKEN`, fetches `GET /report`, swaps in the eval section, and writes `reports/YYYY-MM-DD.md` with `encoding="utf-8"`, printing the path. `reports/` goes in `.gitignore`.

**The digest line.** `gather_facts` gains `"escalations_waiting": n`, the chains whose newest run is escalated and not `needs_claude`, plus `"needs_claude": m`. `render_facts` and the model prompt add one line when either is non zero: `2 chores are waiting for a hint and 1 needs a Claude session; see the report.`

- [ ] **Step 1: Write the failing tests** for each section with seeded runs (an escalated chain of two with a hint, a `needs_claude` chain, one eval chore, spend rows), for the route's bearer guard (401 without it), for the MCP tool's text, and for the digest line appearing only when something waits.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the full suite, then commit** `Add a report of escalations, Mercury's own chores and spend, over GET /report, MCP and a script, with a digest line when something waits`.

---

### Task 18: The Claude session rung, the docs and the deploy

**Files:**
- Modify: `README.md`, `docs/mercury.md`, `app/mcp_server.py` (`instructions`), `docs/handoff.md`, this brief

- [ ] **Step 1: The Claude session rung.** The MCP server's `instructions` become: queue and read runs; repo chores need Approve on Telegram unless the repo is `auto_approve`; read `report` to see escalated chores; for each, write a sharper hint through `advise` first; do the chore yourself on a local clone only when you judge it beyond free models, and say why in the pull request. Write the same as a README section `## When a chore escalates`, in the README's own voice, with no claims row: the ladder claim is Phase 3's, after the rescue measurement.

- [ ] **Step 2: Docs.** `docs/mercury.md` gains the `escalated` status, the four reasons, decisions 16 to 19 and the report. The README's configuration paragraph says `MAX_RUNS_PER_DAY` is 20 by default and set per deploy in the private repo. Check every changed line against the writing rules.

- [ ] **Step 3: Deploy, Thomas's step.** Push, wait for CI and Publish, then a `mercury-config` script that bumps `PUBLIC_SHA`, pushed only with `--yes`. Smoke test on the fixture: `uv run python -m evals.runner --columns ollama --only clamp` and `--only divide` (the two Phase 1 weakened tests failures) and record whether the guard's feedback rescued them. Then one escalation by hand: queue a chore on the fixture through MCP whose instruction cannot be done (for example, make `add` return the product while `test_adds_two_numbers` stays), confirm one Telegram message arrives, reply with a hint, and confirm the advised rerun starts without Approve. Close every PR and branch it leaves, as the eval does.

- [ ] **Step 4: Hand over.** A dated section at the top of `docs/handoff.md` with the live `PUBLIC_SHA`, what the smoke test showed, and that Phase 3 is next, to be detailed into tasks in its own session on Opus. Mark Phase 2 done in this brief's header. Commit `Hand over Phase 2: the escalation ladder, advise and the report are live`.

---

## Phase 3 spec: the hint rescue eval, and the README

- The eval runner gains a rescue pass: for every row that failed, a Claude session (Opus) writes one hint from the failure, and the runner sends it with `advise` and grades the result. The report gains two figures per column: passed first time, and passed after one Claude hint.
- Three repeats on a later day, reporting the mean pass rate and how many tasks passed at least once.
- A `local-base` column for the untuned home model, through the `local` rung that Phase 5's part 5a builds first (decisions 21 to 23), run in the local compose stack (decision 46, `local/README.md`). It is the before figure for Phase 5. Its first single run was 2 of 11.
- README: a section `## Evals` saying what a task is, that the grade test never reaches the model, that a result which drops `main`'s tests fails, how a run is graded, and the command to rerun it, with the column table pasted under it. A claims row `A free model completes well defined chores, graded by tests it never saw`, with the measured numbers whatever they are.

### Phase 3 decisions (2026-10-07)

Settled with Thomas on 2026-10-07, late evening, while detailing Phase 3 on Opus; do not re-ask them.

47. **A chore that opened a pull request but failed the hidden grade can be advised, when it is an eval chore.** `advise` accepts a `succeeded` run whose source is `eval`, as well as any `escalated` run. Three of the 9 `local` failures and most of Phase 1's were of this kind, and refusing them would leave the rescue figure measuring only escalations. A succeeded chore now records its diff in its `done` step, so the rerun starts from `main` with the hint and that diff, as an escalated one does. No other source gains this.
48. **An advised rerun of a quiet chore stays quiet and can stay on its column.** The rerun of an `eval` or `bank` chore keeps that source, so its escalation never reaches Telegram or the report. `POST /runs/{id}/advise` takes an optional free `provider`, so the eval reruns a chore on the column it failed on rather than on the type's first rung, which would measure gemini for every column.
49. **The hint writer sees what an owner sees.** For each failed row the Claude session gets the instruction, the last diff, the tail of the repo's own test output and the reason it stopped. A row that opened a pull request says only that a check outside the repo's tests found it wrong. The grade test and its output never reach the hint writer, so a hint cannot carry the answer. One hint per row, at most 2,000 characters (`MAX_HINT_CHARS`).
50. **Every column gets the rescue pass.** gemini, ollama and `local` through `advise`; `delegate:local` and `delegate:local-gpt` by rerunning `delegate.ps1` on a fresh clone with the same advice block appended to the instruction, since `advise` has no counterpart there.
51. **`local-base` is a plain row in the README table,** labelled an untuned 7B model run in local compose, with no wording about improvement or fine tuning (decision 43).
52. **The compose stack keeps using the real fixture.** It already does, and the runner closes every pull request and deletes every branch it causes. The column is still called `local` in the runner, since columns are provider names; the README labels it `local-base`.

### Phase 3, as tasks

Detailed into tasks on 2026-10-07, on Opus. Execute with superpowers:executing-plans and superpowers:test-driven-development, one task per commit, the full suite, `ruff check` and `ruff format --check` green before each commit (`.superpowers/t.sh`, `.superpowers/lint.sh`). Tasks 28 to 32 are code. Task 33 deploys. Task 34 is the measurement, on the desktop, and needs a Claude session on Opus for the hints. Task 35 writes the README and hands over.

**Phase 3 Global Constraints.** Everything under Global Constraints above still applies. In addition:

- A chore whose source is not `eval` or `bank` takes exactly the path it takes today, through `advise` and everywhere else.
- No hint is written by anything but the Claude session (decision 4: no paid model, so no API call writes one). The runner only carries hints from a file.
- The rescue brief never contains a grade test or any text from grading it (decision 49).
- Every eval PR and branch, first run and rerun, is closed and deleted by the runner.

**Phase 3 Review Focus.**

- A succeeded chore that is not an eval chore (an `api` or `mcp` chore whose PR Thomas has not merged) must still be refused by `advise`. Test in Task 29.
- An advised rerun of an eval chore that escalates must send nothing to Telegram. Before this phase its source became `mcp`, which would have announced it. Test in Task 29.
- A rescue rerun whose PR is opened must be graded on its own branch, `agent/<new id>`, and that branch closed, not the first run's. Test in Task 31.
- A row that ended `timeout`, `error` or `refused` failed for a reason no hint can fix; it is listed as not rescued, not briefed. Test in Task 31.
- A hints file with a blank hint, a missing row, or a key no row has must not stop the pass; blank and missing rows are reported as not rescued, and an unknown key is an error naming it before any rerun is queued. Test in Task 31.

---

### Task 28: A home provider is for repo chores only

The deferred minor from 5a: `RunRequest` accepts `provider: local` on a pytest, chat or digest run, where JSON mode breaks them.

**Files:**
- Modify: `app/run_request.py` (`only_a_model_run_names_a_provider`)
- Test: `tests/test_run_source.py` or the file that already tests `RunRequest`'s provider rules (`grep -ln "takes no provider" tests/`)

- [ ] **Step 1: Write the failing test.**

```python
@pytest.mark.parametrize("type_", ["pytest", "chat", "digest"])
def test_a_home_provider_is_refused_on_anything_but_a_repo_chore(type_):
    with pytest.raises(ValidationError, match="repo chore"):
        RunRequest(type=type_, inputs={"task": "x"}, provider="local")


def test_a_home_provider_is_accepted_on_a_repo_chore():
    run = RunRequest(type="repo_chore", inputs={"task": "x", "repo": "o/r"}, provider="local")
    assert run.provider == "local"
```

Skip any of the three types `TASK_TYPES` does not have, or that has no provider (it already gets "takes no provider").

- [ ] **Step 2: Run it and see it fail.**

- [ ] **Step 3: Implement.** In `only_a_model_run_names_a_provider`, after the existing check:

```python
        # A home provider answers in JSON mode (decision 23), which only a
        # chore's reply format survives.
        if self.provider in HOME_PROVIDERS and self.type != "repo_chore":
            raise ValueError(f"{self.provider!r} runs only a repo chore")
```

importing `HOME_PROVIDERS` from `app.config`.

- [ ] **Step 4: Full suite, lint, commit** `Refuse a home provider on anything but a repo chore`.

### Task 29: `advise` takes an eval chore that opened a wrong pull request, and keeps it quiet

**Files:**
- Modify: `app/repo_chore.py` (the green path of `_run`, `_open_pull`, `_advice_block`), `app/advice.py`
- Test: `tests/test_advice.py`, `tests/test_repo_chore.py`, `tests/test_escalation.py`

**Interfaces:**
- Produces: `advise(conn, run_id, hint, source, repos, provider: str | None = None) -> str`. A succeeded chore's `done` output is `{"status": "succeeded", "pr_url": ..., "diff": ...}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_advice.py`:

```python
def test_an_eval_chore_that_opened_a_pull_request_can_be_advised(migrated_db):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute(
        "UPDATE runs SET status = 'succeeded', source = 'eval' WHERE id = %s", (run_id,)
    )

    new_id = advise(migrated_db, run_id, "Name it divide.", "api", REPOS)

    assert run_row(migrated_db, new_id)["source_run_id"] == run_id


def test_a_succeeded_chore_that_is_not_an_eval_chore_is_still_refused(migrated_db):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute("UPDATE runs SET status = 'succeeded' WHERE id = %s", (run_id,))

    with pytest.raises(AdviceRefused, match="escalated"):
        advise(migrated_db, run_id, "a hint", "mcp", REPOS)


@pytest.mark.parametrize("quiet", ["eval", "bank"])
def test_the_rerun_of_a_quiet_chore_keeps_its_source(migrated_db, quiet):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute("UPDATE runs SET source = %s WHERE id = %s", (quiet, run_id))

    new_id = advise(migrated_db, run_id, "a hint", "mcp", REPOS)

    assert run_row(migrated_db, new_id)["source"] == quiet


def test_a_named_provider_runs_the_rerun(migrated_db):
    run_id = escalated_chore(migrated_db, "x")

    new_id = advise(migrated_db, run_id, "a hint", "api", REPOS, provider="ollama")

    assert run_row(migrated_db, new_id)["provider"] == "ollama"


def test_a_rerun_of_a_succeeded_eval_chore_counts_as_advice(migrated_db):
    run_id = escalated_chore(migrated_db, "x")
    migrated_db.execute(
        "UPDATE runs SET status = 'succeeded', source = 'eval' WHERE id = %s", (run_id,)
    )
    new_id = advise(migrated_db, run_id, "a hint", "api", REPOS)

    assert advised_count(migrated_db, new_id) == 1
```

Change the parametrize of `test_advice_on_a_chore_that_did_not_escalate_is_refused` only if it now fails for `succeeded`: it uses the default source, which is not `eval`, so it should still pass unchanged. In `tests/test_repo_chore.py`, next to the existing green chore test, assert the `done` step's output has `"diff"` containing the written file's path. And an `_advice_block` test:

```python
def test_advice_after_a_wrong_pull_request_says_so_and_shows_its_diff():
    block = _advice_block("Name it divide.", {"status": "succeeded", "diff": "+def div"})

    assert "opened a pull request" in block
    assert "+def div" in block
    assert "test output" not in block
```

In `tests/test_escalation.py`, assert that announcing the escalation of a rerun whose source is `eval` sends nothing (reuse the existing quiet source test with a run that has `source_run_id` and a hint).

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Record the diff on success.** In `_run`'s green path, after `git.run("add", ...)` and before the commit, take `diff = git.run("diff", "--cached", cwd=clone)` and pass it on: `return _open_pull(setup, run_id, instruction, branch, base, write, close, diff=diff)`. `_open_pull` gains `diff: str = ""` and closes with `close("succeeded", {"pr_url": url, "diff": diff[:MAX_DIFF_CHARS]})`. Open it anyway and a resumed chore pass nothing, so they record an empty diff.

- [ ] **Step 4: Say what went wrong in the advice block.** In `_advice_block`, when `output.get("status") == "succeeded"`, the sentence before the diff is `An earlier attempt at this chore passed the repository's tests and opened a pull request, but a check outside those tests found it wrong. Its diff, which is not applied:` and no test output follows. Otherwise it is unchanged.

- [ ] **Step 5: Widen `advise`.** In `app/advice.py`:

```python
# Sources whose chores tell nobody (app/escalation.py). Their advised reruns
# keep the source, so the rerun is as quiet as the chore it follows.
QUIET_SOURCES = ("eval", "bank")
# A chore that opened a pull request is done unless its source grades it
# against a test it never saw (decision 47 of docs/build-brief-evals.md).
_GRADED_ELSEWHERE = ("eval",)
```

`_RUN` also selects `source`. The status check becomes: refused unless `status == "escalated"` or (`status == "succeeded"` and the source is in `_GRADED_ELSEWHERE`), with the same message. The rerun's source is the run's own when it is in `QUIET_SOURCES`, else the `source` argument. A `provider` argument, when given, is the rerun's provider; otherwise the existing home provider rule applies. `_ADVISED` counts `prior.status IN ('escalated', 'succeeded')`, still requiring `r.hint IS NOT NULL`. Update the module docstring: an advised rerun follows an escalated chore, or an eval chore whose pull request failed its grade. If `app/escalation.py` has its own `("eval", "bank")` tuple, import `QUIET_SOURCES` there instead; leave the SQL literals in `app/outage.py`, `app/report.py` and `app/telegram_webhook.py` as they are.

- [ ] **Step 6: Full suite, lint, commit** `Advise an eval chore whose pull request failed its grade, keep a quiet chore's rerun quiet, and let the caller name its provider`.

### Task 30: `POST /runs/{id}/advise`

The runner talks HTTP, and `advise` is reached today only from MCP and Telegram.

**Files:**
- Modify: `app/main.py`, `app/run_api.py`
- Test: `tests/test_advice.py` (route tests use the same client fixture as the cancel route's tests; `grep -n "cancel" tests/test_runs.py` to find it)

**Interfaces:**
- Produces: `POST /runs/{run_id}/advise` with body `{"hint": str, "provider": str | None}`, behind the bearer token. 201 `{"id": <new id>, "status": "pending"}`. 422 with the refusal's text for an `AdviceRefused`, a provider that is unknown or not free, or a blank hint. 401 without the bearer.

- [ ] **Step 1: Write the failing tests:** an escalated chore advised over the route returns 201 and a pending run with the hint; no bearer is 401 and creates nothing; a run that is `running` is 422 with `escalated` in the detail; `provider: "nope"` is 422; the rerun's source is `api` for an `api` chore and `eval` for an eval chore.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.** In `app/run_api.py`:

```python
class AdviceRequest(BaseModel):
    hint: str
    # A free provider for the rerun. The eval names the column the chore
    # failed on (decision 48); leave it out for the usual rung.
    provider: str | None = None

    @field_validator("provider")
    @classmethod
    def provider_must_be_free(cls, value: str | None) -> str | None:
        return RunRequest.provider_must_be_registered(value)


def _advise(state, run_id: str, advice: AdviceRequest) -> RunCreated:
    with connect(state.settings.database_url, autocommit=True) as conn:
        try:
            new_id = advise(
                conn, run_id, advice.hint, "api", state.mercury.repos, advice.provider
            )
        except AdviceRefused as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from None
    return RunCreated(id=new_id, status="pending")


async def advise_run(state, run_id: str, advice: AdviceRequest) -> RunCreated:
    return await run_in_threadpool(_advise, state, run_id, advice)
```

If calling the pydantic classmethod directly does not work, move the body of `provider_must_be_registered` into a module function in `app/run_request.py` and call it from both. In `app/main.py`, beside cancel:

```python
    @app.post("/runs/{run_id}/advise", status_code=201, response_model=RunCreated)
    async def advise_one_run(
        run_id: uuid.UUID, advice: AdviceRequest, request: Request
    ) -> RunCreated:
        require_bearer_token(request)
        return await advise_run(request.app.state, str(run_id), advice)
```

- [ ] **Step 4: Full suite, lint, commit** `Advise a chore over POST /runs/{id}/advise`.

### Task 31: The rescue pass

**Files:**
- Modify: `evals/runner.py` (`EvalRow`, `run_one` split into `post_chore` and `follow`, `run_delegate`, `main`)
- Create: `evals/rescue.py`
- Test: `tests/test_eval_runner.py`, `tests/test_eval_rescue.py`

**Interfaces:**
- Consumes: `POST /runs/{id}/advise` (Task 30); the `done` event's `output.diff` and `output.test_output`, as `GET /runs/{id}/events` returns them (`[{"id", "kind", "seq", "output"}, ...]`).
- Produces: `EvalRow` gains, after `unusable`, `repeat: int = 1`, `diff: str = ""`, `test_tail: str = ""`, `rescue_hint: str | None = None`, `rescue: "EvalRow | None" = None` (stored in the JSON as a nested dict; `load_rows(path) -> list[EvalRow]` rebuilds it). `row_key(row) -> str` is `f"{row.task}/{row.provider}/{row.repeat}"`. `RESCUABLE = {"succeeded", "escalated", "failed"}`. `follow(api, github, task, column, run_id, clone_base, token, *, timeout_seconds, poll_seconds, sleep, clock) -> EvalRow` polls, grades, cleans up and returns the row, as `run_one` does today after its POST. `run_delegate(task, model, clone_url, *, instruction: str | None = None, ...)` runs `instruction or task.instruction`.

**Evidence for the hint writer.** `follow` fetches `GET /runs/{id}/events` once the run is final and takes the `done` event's `diff` and `test_output` into `row.diff` (at most 6,000 characters) and `row.test_tail` (the last 2,000). A delegate row takes `git add -A` then `git diff --cached` in its checkout before grading, and the repo test output on a red result. Neither field ever takes text from `grade_dir` or `grade_branch`; those go to `detail`, as now.

**`evals/rescue.py`**, three commands:

1. `python -m evals.rescue brief evals/results/<stamp>.json` writes `<stamp>.rescue.md` and `<stamp>.hints.yaml` beside it. The brief has one section per row that is not graded and whose status is in `RESCUABLE`, headed by `row_key`, with the instruction, the reason (`detail` for an escalated row, `tests still failing` for a failed delegate row, and `It opened a pull request; a check outside the repo's tests found it wrong.` for a succeeded one), the diff in a fenced block, and the test tail. It never prints `detail` for a succeeded row, because there it is grading output. The hints file maps each briefed key to an empty string. Rows that failed but are not rescuable are listed at the end with their status, as not rescued.
2. The Claude session reads the brief and fills the hints file. Each hint says what the model got wrong and what to do instead, in a few sentences, without guessing at a hidden test.
3. `python -m evals.rescue apply evals/results/<stamp>.json evals/results/<stamp>.hints.yaml [--timeout 900]` checks the hints file first: a key that matches no briefed row is an error naming it, before any rerun. Then, for each non blank hint: a Mercury row is advised with `POST /runs/{run_id}/advise` `{"hint": hint, "provider": row.provider}` and followed with `follow` on the new id; a delegate row runs `run_delegate` with `instruction = task.instruction + advice_block(hint, {"status": "escalated", "reason": row.detail, "diff": row.diff, "test_output": row.test_tail})`, where `advice_block` is `app.repo_chore._advice_block` renamed public (update its callers). The rerun's row goes into `row.rescue` with `row.rescue_hint = hint`. A 422 from advise is recorded as a rescue row with status `refused` and the detail. The JSON is rewritten in place and the Markdown summary regenerated (Task 32). The same `EvalAborted` rules apply: a refused run stops the pass, keeping what is done.

`apply` reads `MERCURY_URL`, `MERCURY_BEARER_TOKEN` and `MERCURY_GITHUB_TOKEN` as the runner does. Run it against the same Mercury that ran the rows: live for gemini and ollama, compose for `local`, either for delegate rows.

- [ ] **Step 1: Write the failing tests.** In `tests/test_eval_rescue.py`, with fake `api` and `github` objects built the way `tests/test_eval_runner.py` builds them:
  - the brief of a succeeded, ungraded row contains its diff and the PR sentence, and not its `detail` (seed `detail` with `grade_hidden` text and assert `"grade_hidden" not in brief`);
  - the brief lists a `timeout` row and an `error` row as not rescued, and the hints file has no key for them;
  - `apply` with a hint for a gemini row posts to `/runs/<id>/advise` with `provider: "gemini"`, follows the new id, grades `agent/<new id>`, and closes that branch (assert on the fake GitHub's deleted refs);
  - `apply` with an unknown key raises before any POST;
  - a blank hint posts nothing and leaves `rescue` as `None`;
  - a delegate row's rerun gets an instruction that starts with the task's and contains the hint and the earlier diff (pass a fake `delegate` callable and capture its instruction);
  - `load_rows` round trips a row with a nested rescue.
  In `tests/test_eval_runner.py`: an escalated Mercury row carries the `done` event's diff and test tail, and a row from a green chore carries the diff and never the grade output.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement** the `EvalRow` fields, `follow`, the evidence capture, `load_rows`, `row_key`, and `evals/rescue.py`. `main` in the runner sets `repeat` on each row from its loop. Keep `run_one`'s signature, implemented as the POST then `follow`, so the existing tests pass unchanged.

- [ ] **Step 4: Full suite, lint, commit** `Add the eval's rescue pass: a brief of each failure for a Claude session, and its hints sent through advise or delegate.ps1 and graded`.

### Task 32: The summary reports first time, after one hint, and repeats

**Files:**
- Modify: `evals/runner.py` (`summarise`), `evals/rescue.py` (a `table` command)
- Test: `tests/test_eval_runner.py`

**Interfaces:**
- Produces: the column table's header is `| Column | Passed first time | Passed after one hint | Mean pass rate | Passed at least once | Opened a PR | Median tokens | Median seconds | Cost USD | Fell back | Weakened tests | Unusable replies |`. `python -m evals.rescue table a.json b.json ...` prints the summary of all their rows together, for the README.

**The figures, per column:**
- Passed first time: `graded` rows of `n` rows, as `Passed the hidden test` was.
- Passed after one hint: rows graded first time plus rows whose `rescue` is graded, of `n`; `n/a` when no row of the column has a `rescue_hint`.
- Mean pass rate: the mean over repeats of (graded rows in that repeat / rows in that repeat), as a percentage with no decimals; first time only.
- Passed at least once: distinct tasks with at least one graded row (first time), of distinct tasks.
- Cost, tokens, seconds, fell back, weakened and unusable count first time rows only; the rescue's own tokens are left out of the table and kept in the JSON.

The per task table gains a `Repeat` column and a `After hint` column (`pass`, `fail`, or blank when not rescued).

- [ ] **Step 1: Write the failing tests:** two repeats of two tasks where one task passes in repeat 1 only gives `Mean pass rate` 25% (half of repeat 1, none of repeat 2) and `Passed at least once` `1 of 2`; a failed row with a graded rescue makes `Passed after one hint` one more than first time; a column with no hints shows `n/a`. Update the existing summary tests' expected header and line endings to the new columns.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Full suite, lint, commit** `Report each column's first time and after one hint figures, its mean pass rate and the tasks it passed at least once`.

### Task 33: Deploy

- [ ] **Step 1:** Push `main`, wait for CI and Publish (`gh run list -c <full sha>`), then run the `mercury-config` script that bumps `PUBLIC_SHA` with `--yes`, and watch its Deploy. Check `/health` is 200.
- [ ] **Step 2: Smoke the route live.** Queue one eval chore with the runner, `--columns ollama --only divide`, and confirm its row. Then advise a chore that cannot succeed: post a chore with `source: eval` on the fixture whose instruction contradicts its own tests (as in Task 18), wait for `escalated`, call `POST /runs/<id>/advise` with a hint and `provider: ollama`, and check the rerun is `eval`, on ollama, and sends nothing to Telegram. Close any PR and branch it leaves.
- [ ] **Step 3:** Rebuild the compose stack on the desktop so `local` gets the same code: `docker compose -f docker-compose.yml -f local/compose.local.yml up -d --build db api proxy worker`.

### Task 34: The measurement

On the Windows desktop, on one day, after Task 33. The runner needs `PYTHONUTF8=1` and the repo `.env` sourced (never print it); its output is buffered until it ends.

- [ ] **Step 1: The cap.** 3 repeats of 11 chores on gemini and ollama is 66 live runs, and the rescues add up to one per failure; at 40 a day the batch would stop part way. Set the `mercury-config` Actions variable `MAX_RUNS_PER_DAY` to 100 and rerun its Deploy (if the classifier blocks it, hand Thomas `! gh variable set MAX_RUNS_PER_DAY --body 100 -R thomas-whitley/mercury-config`). It goes back to 40 in Step 6.
- [ ] **Step 2: Three runs of three repeats.** Each is its own results file:
  - live: `MERCURY_URL=<live> uv run python -m evals.runner --columns gemini,ollama --repeats 3`
  - compose: `MERCURY_URL=http://localhost:8001 uv run python -m evals.runner --columns local --repeats 3`
  - desktop: `uv run python -m evals.runner --columns delegate:local,delegate:local-gpt --repeats 3`
  Run them one after another, not at once: the compose and delegate columns share the GPU.
- [ ] **Step 3: Briefs.** `python -m evals.rescue brief <file>.json` for each. Read each brief in this session (Opus) and write one hint per briefed row into its hints file, following decision 49: from the instruction, the diff and the test output only.
- [ ] **Step 4: Apply.** `python -m evals.rescue apply` for each file, against the same Mercury that ran it (live, compose, and either for delegate).
- [ ] **Step 5: The table.** `python -m evals.rescue table <the three json files>` gives the combined table. Commit the results, briefs and hints: `Measure Phase 3: <column> <first> then <after hint> of 33, ...`.
- [ ] **Step 6:** Set `MAX_RUNS_PER_DAY` back to 40 and rerun the Deploy. List the fixture's open PRs and branches (`gh pr list -R thomas-whitley/mercury-fixture`, `gh api repos/thomas-whitley/mercury-fixture/branches`) and confirm only `main` is left.

### Task 35: The README, the claims row, and the handoff

- [ ] **Step 1: `## Evals` in the README,** before `## When a chore escalates`, in the README's own voice: what a task is (a YAML file with a repo, an instruction naming every file and function, and a grade test); that the grade test never reaches the model; that a result which drops one of `main`'s tests, or skips one, fails; how a row is graded (keeps main's test ids, passes its own tests, passes the grade test); the rescue pass (one hint per failure from a Claude session, which sees the diff and test output but never the grade); the commands to rerun it (`evals.runner`, `evals.rescue brief`, `apply`, `table`); then the combined table from Task 34, pasted. The `local` row is labelled an untuned 7B model (`qwen2.5-coder:7b`) on an RTX 4060, run in local compose (decision 51). Write no sentence about the numbers that the table does not show.
- [ ] **Step 2: The claims row:** `| A free model completes well defined chores, graded by tests it never saw | evals/runner.py, evals/rescue.py, tests/test_eval_runner.py, tests/test_eval_rescue.py, and the table under Evals | gemini <a> of 33 first time, <b> after one hint; ollama ... |` with the measured numbers whatever they are.
- [ ] **Step 3: Docs.** `docs/mercury.md` gains `POST /runs/{id}/advise` and decisions 47 to 48. Check every changed line against the writing rules.
- [ ] **Step 4: Hand over.** A dated section at the top of `docs/handoff.md`: the live `PUBLIC_SHA`, the table, what the rescues showed per column, and that 5b (the bank) is next. Mark Phase 3 done in this brief's header. Rewrite `NEXT.md`. Commit `Hand over Phase 3: the eval with one Claude hint per failure, and the README's evals section`.

## Phase 4 spec: findings become chores

Starts only if Thomas decides, on Phase 3's numbers, that free models are worth trusting on a real repo. It now also waits on Phase 5's outcome (decision 45).

- Mercury gains a `test_command` that needs no database: the tests that need Postgres are marked `db`, and the command is `uv run pytest -m "not db" && uv run ruff check`. `thomas-whitley/mercury` gets that `test_command` in `mercury.yaml`.
- The CI watch and the dependency audit create chores from templates filled with the evidence. A dependency bump names the package, both versions and the advisory, and asks for the lock file updated with the tests green. A red CI names the job and carries the last 150 lines of its log, and asks for it green without deleting, skipping or weakening any test.
- One open chore per finding (repo and failing job, or repo and advisory), none while an earlier one's PR is open or it waits on advice, and at most three self started chores a day across all repos, the rest listed in the report.
- Dependency bumps and red CI start without Approve. Every other self started chore asks.
- Node repos (`ludo-electrical`, `nextset`) wait until a Python repo has proven this.

## Phase 5 spec: a local model that improves, measured

Settled with Thomas on 2026-10-07 over five rounds of questions; do not re-ask them. Phase 5's first part, 5a, is built before Phase 3 runs, because Phase 3's `local-base` column needs it. The rest starts after Phase 3 has landed. Each part is turned into tasks in its own session, on Opus.

**Goal.** A 7B model on the home RTX 4060 (8 GB) does Mercury's chores for nothing, gets better first through retrieved memory and then through fine tuning, and every step is measured on the 11 eval chores, which never reach its memory or its training data. It serves two ends, evidence for an AI engineering application and free chores, and when they pull apart the measured number wins over the story.

**Order.** 5a, then Phase 3 with a `local-base` column, then the 5b pilot, then the full 5b bank, then 5c, then 5d. Phase 4 waits on the outcome.

### Phase 5 decisions (2026-10-07)

20. **The base model is small and trained at home.** `qwen2.5-coder:7b` (Apache 2.0, 4.7 GB in Ollama, 32K context) is the model that improves, and `qwen3-coder:30b` (10 of 11 in Phase 1 through `delegate.ps1`) is the baseline to beat. A 30B model cannot be QLoRA trained in 8 GB of VRAM; a 7B one can, at Unsloth's stated minimum of about 5 GB.
21. **The first measurement goes through Mercury's own format.** Before any tunnel exists, Mercury runs in the local compose stack with a `local` provider pointed at `localhost:11434`, and the eval runner (`MERCURY_URL` set to it) runs `qwen2.5-coder:7b` on the 11 eval chores. The report counts unparseable replies per column as their own figure. Below 2 of 11, the same run is repeated with `qwen3:8b`. If that is also below 2 of 11, Phase 5 stops and goes back to Thomas, because nearly all training data would then come from reference solutions alone, which is a different project.
22. **Mercury reaches the home GPU through Tailscale Funnel.** Tailscale is already installed on the desktop, Funnel gives a free `*.ts.net` HTTPS address, and the repo's rule against a custom domain rules out a named Cloudflare Tunnel. Ollama has no authentication of its own, so Caddy sits in front of it, proxies `/v1/chat/completions` only, and rejects any request without the `LOCAL_MODEL_TOKEN` bearer. The token is a new secret in `mercury-config`.
23. **`local` is a provider and a ladder rung.** A `local` entry in `PROVIDERS` (`openai_compatible`, $0, its address from `LOCAL_MODEL_URL`, its tag from `LOCAL_MODEL`, the bearer from `LOCAL_MODEL_TOKEN`) with a 120 second timeout per call and 8,192 output tokens, because a cold load plus a whole file reply from a 7B model runs long and a chore's own heartbeat thread keeps the lease meanwhile. The tag `mercury-local:base` is `qwen2.5-coder:7b` with a 16K context window, since Ollama's default would cut a chore prompt short. The `local` rung asks Ollama for JSON mode (`response_format` `json_object`), so a 7B model cannot return broken JSON; a schema per call would change every model's interface for little more. No other rung changes, so Phase 1's baseline stays comparable. (Corrected while detailing 5a: the first wording asked for a schema, 50 seconds and 2 attempts.)
24. **The reply format stays full file JSON.** Weaker models do better replacing whole files than writing diffs, which need an exact match, and the bank's files are tens to a few hundred lines. Changing the format would change production for every rung and void the baseline. Parse failures are reported per column so a format problem cannot hide inside the pass rate.
25. **Local runs have their own cap.** `MAX_LOCAL_RUNS_PER_DAY` is 200, an Actions variable beside `MAX_RUNS_PER_DAY`, which keeps protecting the free cloud tiers at 40.
26. **Where `local` runs.** Bank runs and eval columns only. A bank run is pinned to `local` and never falls through to gemini, because a gemini answer would enter the training data as a local success. Real chores keep `gemini → ollama` until a promoted local tag beats gemini on the 11 eval chores, and then Thomas decides.
27. **Bank chores are quiet, exactly as eval chores are (decision 18).** A run posted with `source: bank` sends nothing to Telegram, is never retried after an outage, is left out of the report's escalations and cannot be advised by a Telegram reply. The rescue script in 5b reads them itself.
28. **Every model call of a `repo_chore` is recorded.** A `model_calls` table holds the run id, step, rung, system prompt, prompt, raw reply and tokens, for every chore and not only bank chores, since it also makes an escalation easier to read. Bank rows are exempt from the 30 day cleanup. Training examples are built from these rows, so the prompt the model trains on is the prompt it is served.
29. **A run can start from a commit.** `POST /runs` takes an optional `base` sha on a `repo_chore`, and `app/repo_chore.py` checks it out before it branches. The run row records it, so every result can be reproduced.
30. **The bank is mined from real commits.** Claude does not invent chores. A chore is a real commit from a small Python library: its parent is the base, the tests the commit added are the hidden grade, and the commit is the reference solution. Claude writes only the instruction, one paragraph, from the diff, and never names the tests.
31. **Library criteria.** MIT, BSD or Apache 2.0; pure Python; a suite that runs in under 60 seconds with no service, network or database, on `pytest` or `unittest`; at least 40 commits in 2025 or 2026 that touch both source and tests; roughly 2,000 to 20,000 lines, so the 10 file read limit can reach what a chore needs; not one of the most famous libraries, to lower the chance the model memorised them. Commits come from 2025 and 2026, after `qwen2.5-coder`'s training data ends. A subagent produces the shortlist and Thomas picks 3 to 5.
32. **Each library is a public fork under `thomas-whitley`,** keeping its licence and history, so chore branches land in the fork and never upstream. Each fork gets `auto_approve: true`, a recorded exception to decision 13 that applies to bank forks only. Chore branches are graded, closed and deleted, as on the fixture.
33. **A chore enters the bank only through a gate.** A script checks that the grade fails on the base and passes on the reference. A commit whose tests depend on more than its own change fails the gate and is dropped.
34. **The bank splits 80 to 20 by a hash of the chore id.** Memory and training see the training split only. The validation split chooses between adapters. The 11 eval chores and the fixture never enter the bank. The 11 are run once per stage (`local-base`, `local-memory` and each promoted tag) and never to choose between adapters.
35. **A pilot comes first.** 50 chores from one library go through the whole loop (gate, local runs, rescue, `model_calls`, example export, one small training run, the tag loaded into Ollama) before the other 250 or so are mined.
36. **Batches are started by hand.** `queue-bank.ps1 -Count N` on the desktop sets `OLLAMA_KEEP_ALIVE=-1` for the batch and queues N training split chores. Nothing runs on a schedule, because the GPU is also for games.
37. **Rescues.** Only training split failures are rescued, one hint each, at most 25 per Claude session. The rescuer sees the report entry (instruction, last diff, test output) and never the reference, or a rescued example would be the reference again. Validation chores are never rescued.
38. **A training example is two turns.** The read request and the edit, both trained, because the read turn is where weak models go wrong first. Examples carry an origin, `self` (passed unaided), `reference` (the commit, with a read turn built from the files it touches and the files its tests import) or `rescued` (passed after a hint, trained without the hint).
39. **Memory.** On the `local` rung only, turned on by `memory: true` on the rung in `mercury.yaml`. Before a chore, `app/retrieval.py`'s Postgres full text path finds the 3 most similar solved training split chores and adds each one's instruction, final diff and hint, at most about 3,000 tokens, after the instruction. Embeddings are added only if `local-memory` shows no gain over `local-base`; no Voyage key is deployed today.
40. **Fine tuning.** Unsloth QLoRA in WSL (16 GB) on the 4060. The adapter is merged into the base and exported as GGUF, then loaded into Ollama as `mercury-local:vN`, because Ollama's `ADAPTER` support for Qwen is unconfirmed. Training code lives in `train/` and stays out of CI.
41. **Retraining and promotion.** A new tag is trained after about every 100 new examples. It replaces the current tag only if it passes at least 3 more validation chores and has no more weakened test results. If v2 does not beat `local-memory` on validation, training stops and the null result is published.
42. **What is published.** README numbers, plus the adapter, the dataset and a model card on Hugging Face linking the eval. No GGUF upload.
43. **The job hunt waits for a number.** No CV, letter or form answer mentions fine tuning, or a model that improves, until a promoted tag has a measured `local-tuned` result on the 11 eval chores. Until then it is "building".
44. **Cheap AI.** Once a tag is promoted, `delegate.ps1` gains `-Model local-tuned`. Its `local` default changes only if the tag beats `qwen3-coder:30b` on the same 11 chores.
45. **Real chores come later.** Once a tag is promoted, chores on Thomas's own repos become a second stream, reported apart from the bank. It is the bridge to Phase 4.
46. **The local rung stays in local compose for now (2026-10-07, after Task 25).** Thomas chose not to give the desktop a public address. Every part of Phase 5 that uses the GPU already runs from the desktop (bank batches start by hand there, the eval runner takes any `MERCURY_URL`, training is local), so Mercury in compose on the desktop does all of it, and the bank's rows live in its local Postgres. Decision 22's Funnel and Caddy are parked in `local/parked/`. The Bicep and `deploy.sh` still carry the `local` settings, and with no `LOCAL_MODEL_URL` the live deploy refuses any run on `local`. When a promoted tag earns a place on live chores (decision 26), the preferred route is Tailscale inside the worker container, which gives the GPU no public address. Phase 3's `local-base` column runs in compose.

### 5a: the local rung (before Phase 3)

The measurement in decision 21, then the Funnel and Caddy setup on the desktop with a short `local/README.md`, the `local` provider with constrained decoding, `MAX_LOCAL_RUNS_PER_DAY`, `source: bank`, `base` on `POST /runs`, and the `model_calls` table. Phase 3 then adds a `local-base` column for whichever model decision 21 kept. The eval runner's existing provider column (Task 2) carries it; a run against `local` while the desktop is off ends `error` with `providers unavailable` and is reported as such.

### 5b: the bank

The library shortlist (decision 31), the forks, a miner that turns a commit into a chore file in the same shape as `evals/chores/` plus `base` and `reference`, the gate, the split, `queue-bank.ps1`, the rescue script and the example export. The pilot (decision 35) first.

### 5c: memory

Decision 39, measured as a `local-memory` column on validation and then on the 11.

### 5d: fine tuning

Decisions 40 and 41, measured as `local-tuned` and `local-tuned+memory` columns. A README claims row in the Phase 3 style is written only after the promoted tag's numbers exist, whatever they are.

### Phase 5 Review Focus

- A bank run whose `local` call fails must end `error`, not fall through to gemini. Test in 5a.
- A request to the Funnel address without the bearer, or to any path but `/v1/chat/completions`, must be refused by Caddy. Checked by hand in 5a and written into `local/README.md`.
- A rescued example must not contain the hint, and no example may come from a validation chore or one of the 11. Tests in 5b.
- A chore whose grade passes on its base measures nothing and must be dropped by the gate. Test in 5b.
- Memory must never retrieve a validation chore or one of the 11. Test in 5c.

### Part 5a, as tasks

Detailed into tasks on 2026-10-07, on Opus, in the session that settled Phase 5. Execute with superpowers:executing-plans, one task per commit, the full suite, `ruff check` and `ruff format --check` green before each commit. Tasks 19 to 24 are code and run anywhere the suite runs. Task 25 needs the Windows desktop with the RTX 4060. Task 26 needs the desktop and Thomas for two secrets. Task 27 hands over.

**5a Global Constraints.** Everything under Global Constraints above still applies. In addition:

- No other rung's behaviour changes. A run that does not name `local` must take exactly the path it takes today.
- `LOCAL_MODEL_TOKEN` is never logged, never in a commit, never in a URL, and never printed by a script. Scripts read it from `~/mercury-local-token.txt`.
- Migrations are new files (`014_`, `015_`, `016_`); no existing migration is edited.

**5a Review Focus.** The failure modes below are the ones most likely to bite and that no spec decision names. Each has its test or its check in the task named.

- An empty `LOCAL_MODEL_TOKEN` makes Caddy's header matcher accept the literal `Bearer `, so anyone could reach the GPU. `local/start.ps1` refuses a token under 32 characters. Check in Task 26.
- Ollama's default context window is far smaller than a chore prompt and truncates it without an error. The `mercury-local:base` tag sets `num_ctx` to 16384. Task 25.
- A cold model load plus a whole file reply can outlast a 25 second timeout. The `local` provider has its own 120 second timeout and 8,192 output tokens. Test in Task 20.
- A `base` sha that is not in the repo's history must end the chore in `error` with git's message, not crash the worker. Test in Task 23.
- A `local` run while the desktop is off must end `error` with `providers unavailable` within seconds, not fall through to gemini and not hang. Test in Task 21, checked live in Task 26.

**Decision corrections made while detailing.** Decision 23 now asks for JSON mode rather than a JSON schema, and a 120 second timeout with the usual retries rather than 50 seconds and 2 attempts. A schema differs per call (read, then edit), which would change every model's interface, while JSON mode alone stops broken JSON; and a chore already heartbeats every 30 seconds on its own thread (`_Keepalive` in `app/repo_chore.py`), so the lease does not bound a chore's model call. Decision 27 now says bank chores are quiet in every way eval chores are, which is what "as `source: eval` does" meant.

---

### Task 19: `bank` is a quiet source, like `eval`

**Files:**
- Create: `migrations/014_bank_source.sql`
- Modify: `app/run_request.py` (`PostedSource`), `app/escalation.py:100`, `app/outage.py:45`, `app/report.py:56`, `app/telegram_webhook.py:78`
- Test: `tests/test_run_source.py`, `tests/test_escalation.py`, `tests/test_outage.py`

**Interfaces:**
- Produces: `source: "bank"` accepted by `POST /runs`. A bank chore is never announced on Telegram, never retried after an outage, never in the report's escalations and never matched by a Telegram reply.

- [ ] **Step 1: Write the failing tests.** In `tests/test_run_source.py` change the parametrize of `test_a_caller_may_name_its_source` to `["api", "n8n", "scheduler", "eval", "bank"]`. In `tests/test_escalation.py` add:

```python
def test_a_bank_chore_is_never_announced(migrated_db, fake_telegram):
    run_id = escalated_chore(migrated_db, RED, source="bank")

    assert announce_escalation(migrated_db, client(fake_telegram), CHAT, run_id, PAGE) is None
    assert fake_telegram.sent() == []
```

In `tests/test_outage.py` turn `test_an_eval_chore_is_never_retried` into a parametrized test:

```python
@pytest.mark.parametrize("source", ["eval", "bank"])
def test_a_quiet_chore_is_never_retried(migrated_db, fake_telegram, source):
    """The eval runner and the bank script have already recorded the row and
    moved on, so a later retry could open a pull request nobody closes."""
    failed = outage_run(migrated_db, source=source)

    queued = retry_outages(migrated_db, TelegramClient("123:abc", fake_telegram.url), CHAT, PAGE)

    assert queued == []
    assert retries_of(migrated_db, failed) == []
    status = migrated_db.execute("SELECT status FROM runs WHERE id = %s", (failed,)).fetchone()
    assert status == ("error",)
    assert fake_telegram.sent() == []
```

and add `import pytest` at the top of that file.

- [ ] **Step 2: Run them and see them fail.** `uv run pytest tests/test_run_source.py tests/test_escalation.py tests/test_outage.py -q`. Expected: the `bank` cases fail (422 from `POST /runs`, a check constraint violation from the inserts).

- [ ] **Step 3: Write the migration.** `migrations/014_bank_source.sql`:

```sql
-- Phase 5 (decision 27 of docs/build-brief-evals.md). Bank chores are quiet
-- in every way eval chores are: no Telegram, no outage retry, no place in the
-- report's escalations. The rescue script in part 5b reads them itself.
ALTER TABLE runs DROP CONSTRAINT runs_source_check;
ALTER TABLE runs ADD CONSTRAINT runs_source_check
    CHECK (source IN ('telegram', 'mcp', 'n8n', 'api', 'scheduler', 'eval', 'bank'));
```

- [ ] **Step 4: Accept and honour the source.** In `app/run_request.py` make `PostedSource = Literal["api", "n8n", "scheduler", "eval", "bank"]` and add to its comment: `bank is the Phase 5 chore bank (part 5b), quiet in the same ways as eval.` In `app/escalation.py:100` change `source == "eval"` to `source in ("eval", "bank")`. In `app/outage.py:45`, `app/report.py:56` and `app/telegram_webhook.py:78` change `r.source <> 'eval'` to `r.source NOT IN ('eval', 'bank')`. Then `grep -rn "'eval'\|\"eval\"" app --include=*.py` must show only these and `app/run_request.py`.

- [ ] **Step 5: Run the three files, then the full suite.** Expected: all pass.

- [ ] **Step 6: Commit.** `Treat bank chores as quiet as eval chores: no Telegram, no outage retry, no report entry`.

### Task 20: The `local` provider, with JSON mode and its own timeout

**Files:**
- Modify: `app/config.py` (`ProviderConfig`, `PROVIDERS`), `app/model.py` (`OpenAICompatibleModel`), `app/worker.py` (`build_model`)
- Test: `tests/test_model.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `PROVIDERS["local"]` with `home=True`; `ProviderConfig` fields `home: bool`, `base_url_env: str | None`, `model_env: str | None`, `timeout_seconds: float | None`, `max_tokens: int`, `json_mode: bool`, all defaulted so the three existing entries are unchanged; `OpenAICompatibleModel(..., json_mode: bool = False)`. Task 21 reads `PROVIDERS[name].home`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_model.py`:

```python
def test_json_mode_asks_the_endpoint_for_a_json_object():
    from app.model import OpenAICompatibleModel

    client = _FakeOpenAIClient(content='{"read": []}')
    OpenAICompatibleModel(model="m", client=client, json_mode=True).complete("s", "p")

    assert client.chat.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_without_json_mode_no_response_format_is_sent():
    from app.model import OpenAICompatibleModel

    client = _FakeOpenAIClient()
    OpenAICompatibleModel(model="m", client=client).complete("s", "p")

    assert "response_format" not in client.chat.completions.calls[0]
```

In `tests/test_worker.py`:

```python
def test_build_model_reads_the_local_address_and_tag_from_the_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_TOKEN", "t" * 32)
    monkeypatch.setenv("LOCAL_MODEL_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LOCAL_MODEL", "mercury-local:v1")

    model = build_model(settings_with(model="gemini-3.5-flash-lite"), "local")

    assert isinstance(model, OpenAICompatibleModel)
    assert model._model == "mercury-local:v1"
    assert model._max_tokens == 8192
    assert model._json_mode is True
    assert str(model._client.base_url).startswith("http://127.0.0.1:11434/v1")
    assert model._client.timeout == 120.0


def test_build_model_refuses_local_without_an_address(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_TOKEN", "t" * 32)
    monkeypatch.delenv("LOCAL_MODEL_URL", raising=False)

    with pytest.raises(RuntimeError, match="LOCAL_MODEL_URL"):
        build_model(settings_with(model="gemini-3.5-flash-lite"), "local")


def test_the_local_tag_defaults_to_the_base_model(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_TOKEN", "t" * 32)
    monkeypatch.setenv("LOCAL_MODEL_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("LOCAL_MODEL", raising=False)

    model = build_model(settings_with(model="gemini-3.5-flash-lite"), "local")

    assert model._model == "mercury-local:base"
```

If the OpenAI SDK in the lock file exposes `timeout` as an `httpx.Timeout` rather than a float, compare `model._client.timeout` against what `OpenAI(timeout=120.0).timeout` returns instead of the literal.

- [ ] **Step 2: Run them and see them fail.** `uv run pytest tests/test_model.py tests/test_worker.py -q`. Expected: `TypeError` on `json_mode`, and `no provider registered as 'local'`.

- [ ] **Step 3: Extend `ProviderConfig` and add the entry.** In `app/config.py`, after `usd_per_million_tokens`:

```python
    # A provider on Thomas's own machine (Phase 5, decisions 23, 25 and 26 of
    # docs/build-brief-evals.md). Its runs count against
    # MAX_LOCAL_RUNS_PER_DAY instead of MAX_RUNS_PER_DAY, its tokens against no
    # daily cap, and a run on it never falls back to a cloud rung.
    home: bool = False
    # Read when the model is built, for an address and a tag that differ per machine.
    base_url_env: str | None = None
    model_env: str | None = None
    # None takes MODEL_TIMEOUT_SECONDS.
    timeout_seconds: float | None = None
    max_tokens: int = 2048
    # Ask the endpoint for a JSON object, so the reply always parses.
    json_mode: bool = False
```

and add to `PROVIDERS`, after `ollama`:

```python
    "local": ProviderConfig(
        kind="openai_compatible",
        base_url=None,
        api_key_env="LOCAL_MODEL_TOKEN",
        # qwen2.5-coder:7b with a 16K context window (local/Modelfile.base).
        model="mercury-local:base",
        home=True,
        base_url_env="LOCAL_MODEL_URL",
        model_env="LOCAL_MODEL",
        # A cold load plus a whole file reply on the 4060. The chore's own
        # heartbeat thread keeps the lease meanwhile.
        timeout_seconds=120.0,
        max_tokens=8192,
        json_mode=True,
    ),
```

Extend the comment above `PROVIDERS` with: `LOCAL_MODEL_TOKEN is the bearer Caddy checks in front of Ollama on the home PC (local/README.md).`

- [ ] **Step 4: Teach the client JSON mode.** In `app/model.py`, `OpenAICompatibleModel.__init__` takes `json_mode: bool = False` and stores `self._json_mode = json_mode`. In `complete`:

```python
        extra = {"response_format": {"type": "json_object"}} if self._json_mode else {}
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            **extra,
        )
```

- [ ] **Step 5: Build it from the environment.** In `app/worker.py`, replace the tail of `build_model` after the Anthropic branch with:

```python
    from app.model import OpenAICompatibleModel

    base_url = provider.base_url
    if provider.base_url_env:
        base_url = os.environ.get(provider.base_url_env) or None
        if base_url is None:
            raise RuntimeError(f"no model address: set {provider.base_url_env}")
    model_name = (os.environ.get(provider.model_env) if provider.model_env else None) or provider.model
    return OpenAICompatibleModel(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        max_tokens=provider.max_tokens,
        json_mode=provider.json_mode,
        timeout_seconds=provider.timeout_seconds or settings.model_timeout_seconds,
    )
```

- [ ] **Step 6: Run the two files, then the full suite.** Expected: all pass, including `test_build_model_uses_the_openai_compatible_client_for_gemini` unchanged.

- [ ] **Step 7: Commit.** `Add the local provider: an Ollama address and tag from the environment, JSON mode, a 120 second timeout`.

### Task 21: A run on a home provider never falls back and has its own caps

**Files:**
- Modify: `app/config.py` (`Settings`, `load_settings`), `app/worker.py` (`_STARTED_TODAY`, `runs_started_today`, `_process_run`), `app/budget.py` (`check_budget`)
- Test: `tests/test_worker.py`, `tests/test_budget.py`

**Interfaces:**
- Consumes: `PROVIDERS[name].home` from Task 20.
- Produces: `Settings.max_local_runs_per_day: int = 200` from `MAX_LOCAL_RUNS_PER_DAY`; `home_runs_started_today(conn) -> int` in `app/worker.py`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_worker.py`:

```python
def local_run(conn, task: str = PASSING_TEST) -> str:
    return conn.execute(
        "INSERT INTO runs (task, provider) VALUES (%s, 'local') RETURNING id", (task,)
    ).fetchone()[0]


def test_local_runs_have_their_own_daily_limit(migrated_db):
    """max_runs_per_day=0 would refuse the first run if local runs counted toward it."""
    settings = settings_with(max_runs_per_day=0, max_local_runs_per_day=2)

    statuses = []
    for _ in range(3):
        run_id = local_run(migrated_db)
        claim_next_run(migrated_db, "worker-test")
        process_run(migrated_db, run_id, settings, model_builder=stub_model_builder())
        statuses.append(
            migrated_db.execute("SELECT status FROM runs WHERE id = %s", (run_id,)).fetchone()[0]
        )

    assert statuses == ["succeeded", "succeeded", "refused"]


def test_local_runs_do_not_count_toward_the_cloud_limit(migrated_db):
    migrated_db.execute(
        "INSERT INTO runs (task, provider, claimed_by) VALUES (%s, 'local', 'worker-a')",
        (PASSING_TEST,),
    )
    migrated_db.execute(
        "INSERT INTO runs (task, claimed_by) VALUES (%s, 'worker-a')", (PASSING_TEST,)
    )

    assert runs_started_today(migrated_db) == 1
    assert home_runs_started_today(migrated_db) == 1


def test_a_local_run_gets_no_fallback(migrated_db):
    """A gemini answer would enter the bank's training data as a local success."""
    run_id = local_run(migrated_db)
    claim_next_run(migrated_db, "worker-test")
    seen: list[str] = []

    def builder(settings, provider_name):
        seen.append(provider_name)
        return StubModel(replies=[CORRECT])

    process_run(migrated_db, run_id, settings_with(), model_builder=builder)

    assert seen == ["local"]
```

Add `home_runs_started_today` to the `from app.worker import ...` line. In `tests/test_budget.py`:

```python
def test_a_home_provider_has_no_daily_token_cap(migrated_db):
    for provider in ("local", "gemini"):
        run_id = migrated_db.execute(
            "INSERT INTO runs (task, provider) VALUES ('x', %s) RETURNING id", (provider,)
        ).fetchone()[0]
        record_step(migrated_db, run_id, 1, "act", tokens=10_000)

    assert check_budget(migrated_db, "local", daily_tokens=1_000, monthly_usd=5.0) is None
    assert check_budget(migrated_db, "gemini", daily_tokens=1_000, monthly_usd=5.0).cap == (
        "daily_tokens"
    )
```

importing `record_step` from `app.runs` and `check_budget` from `app.budget` if the file does not already.

- [ ] **Step 2: Run them and see them fail.** Expected: `TypeError` on `max_local_runs_per_day`, an `ImportError` for `home_runs_started_today`, `seen == ["local", "gemini", "ollama"]`, and a daily cap trip on `local`.

- [ ] **Step 3: The setting.** In `app/config.py` add `max_local_runs_per_day: int = 200` to `Settings` after `osv_api_url`, and to `load_settings`:

```python
        max_local_runs_per_day=int(os.environ.get("MAX_LOCAL_RUNS_PER_DAY", "200")),
```

- [ ] **Step 4: Two counts.** In `app/worker.py` replace `_STARTED_TODAY` and `runs_started_today` with:

```python
# The providers on Thomas's own machine, counted apart (decision 25).
HOME_PROVIDERS = [name for name, provider in PROVIDERS.items() if provider.home]

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


def runs_started_today(conn: psycopg.Connection) -> int:
    return conn.execute(_STARTED_TODAY, (HOME_PROVIDERS,)).fetchone()[0]


def home_runs_started_today(conn: psycopg.Connection) -> int:
    return conn.execute(_HOME_STARTED_TODAY, (HOME_PROVIDERS,)).fetchone()[0]
```

- [ ] **Step 5: Use them, and skip the ladder.** In `_process_run`, move the provider lookup above the daily limit check and branch on it. The block from `# Check then act` down to `model = _with_fallback(...)` becomes:

```python
    task_type = TASK_TYPES.get(task_type_name)
    # The row's provider is the type's own unless the caller named one.
    provider = conn.execute("SELECT provider FROM runs WHERE id = %s", (run_id,)).fetchone()[0] or (
        task_type.provider if task_type else None
    )
    home = provider in HOME_PROVIDERS

    # Check then act, which is safe only because the worker runs at one replica
    # (maxReplicas is 1 in the Bicep). Two workers could both pass this.
    if home and home_runs_started_today(conn) > settings.max_local_runs_per_day:
        limit = f"daily limit of {settings.max_local_runs_per_day} local runs reached"
    elif not home and runs_started_today(conn) > settings.max_runs_per_day:
        limit = f"daily limit of {settings.max_runs_per_day} runs reached"
    else:
        limit = None
    if limit is not None:
        logger.warning(
            "refusing run %s: %s", run_id, limit,
            extra={"run_id": run_id, "worker_id": settings.worker_id},
        )  # fmt: skip
        refuse_run(conn, run_id, limit)
        return None
```

keep the `_RUNNABLE_TYPES` refusal next as it is, then the budget check and `model_builder` call as they are (drop the now duplicated `task_type = TASK_TYPES[task_type_name]` and provider lines), and replace the `_with_fallback` line with:

```python
    if not home:
        # A run on a home provider never falls back (decision 26).
        model = _with_fallback(conn, run_id, model, task_type, settings, model_builder, provider)
```

`test_the_daily_limit_refuses_the_run_and_closes_its_stream` must still pass with its reason text unchanged.

- [ ] **Step 6: No daily token cap at home.** In `app/budget.py` `check_budget`, wrap the daily check:

```python
    config = PROVIDERS.get(provider)
    # A home provider costs nothing and has no quota to protect (decision 25).
    if not (config and config.home):
        today = conn.execute(_TODAY, (provider,)).fetchone()[0]
        if today >= daily_tokens:
            return BudgetTrip(
                cap="daily_tokens",
                message=f"{provider} has used {today:,} of its {daily_tokens:,} tokens today.",
            )
```

- [ ] **Step 7: Run both files, then the full suite.** Expected: all pass, including every test in `tests/test_fallback.py` unchanged.

- [ ] **Step 8: Commit.** `Give local runs their own daily limit, no daily token cap and no fallback to a cloud rung`.

### Task 22: Every model call of a chore is recorded

**Files:**
- Create: `migrations/015_model_calls.sql`
- Modify: `app/repo_chore.py` (`run_repo_chore`'s `ask`), `app/cleanup.py` (`run_cleanup`)
- Test: `tests/test_repo_chore.py`, `tests/test_cleanup.py`

**Interfaces:**
- Produces: table `model_calls (id, run_id, seq, provider, system, prompt, reply, tokens, created_at)`. `seq` is the step the reply led to; `provider` is the rung that answered. Part 5b's example export reads it.

- [ ] **Step 1: Write the failing tests.** In `tests/test_repo_chore.py`, importing `SYSTEM` from `app.repo_chore`:

```python
def test_every_model_call_is_recorded_with_its_prompt_and_reply(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET provider = 'local' WHERE id = %s", (run_id,))
    replies = [pick("calc.py"), change(GOOD_CALC)]

    run_repo_chore(
        migrated_db, run_id, StubModel(replies=replies), setup(tmp_path, github), worker_id=WORKER
    )

    rows = migrated_db.execute(
        "SELECT seq, provider, system, prompt, reply, tokens FROM model_calls "
        "WHERE run_id = %s ORDER BY id",
        (run_id,),
    ).fetchall()
    assert [row[0] for row in rows] == [2, 3]  # the read step, then the first edit
    assert {row[1] for row in rows} == {"local"}
    assert {row[2] for row in rows} == {SYSTEM}
    assert "Instruction:\nAdd subtract to calc.py" in rows[0][3]
    assert "=== calc.py ===" in rows[1][3]
    assert [row[4] for row in rows] == replies
    assert [row[5] for row in rows] == [100, 100]
```

In `tests/test_cleanup.py`:

```python
def _chore_with_a_call(conn, source: str, *, age_days: int) -> str:
    run_id = conn.execute(
        "INSERT INTO runs (task, type, source) VALUES ('x', 'repo_chore', %s) RETURNING id::text",
        (source,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO model_calls (run_id, seq, provider, system, prompt, reply, tokens) "
        "VALUES (%s, 2, 'local', 's', 'p', 'r', 10)",
        (run_id,),
    )
    finish_run(conn, run_id, "succeeded", 10)
    _age(conn, run_id, age_days)
    return run_id


def test_model_calls_go_with_the_bodies_except_a_bank_runs(migrated_db):
    _chore_with_a_call(migrated_db, "api", age_days=31)
    bank = _chore_with_a_call(migrated_db, "bank", age_days=31)
    fresh = _chore_with_a_call(migrated_db, "api", age_days=1)

    run_cleanup(migrated_db)

    left = {row[0] for row in migrated_db.execute("SELECT run_id::text FROM model_calls")}
    assert left == {bank, fresh}
```

- [ ] **Step 2: Run them and see them fail.** Expected: `relation "model_calls" does not exist`.

- [ ] **Step 3: The table.** `migrations/015_model_calls.sql`:

```sql
-- Phase 5 (decision 28 of docs/build-brief-evals.md). Every model call a
-- repo_chore makes, as the model saw it and as it answered, so training
-- examples are built from the prompt the model is served. seq is the step
-- the reply led to; provider is the rung that answered. A bank run's calls
-- outlive the 30 day cleanup (app/cleanup.py); the rest go then.
CREATE TABLE model_calls (
    id         bigserial PRIMARY KEY,
    run_id     uuid NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq        integer NOT NULL,
    provider   text,
    system     text NOT NULL,
    prompt     text NOT NULL,
    reply      text NOT NULL,
    tokens     integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX model_calls_run_idx ON model_calls (run_id, seq);
```

Check the type of `runs.id` in `migrations/001_*.sql` first; if it is not `uuid`, use the same type it has.

- [ ] **Step 4: Record in `ask`.** In `app/repo_chore.py` add beside the other constants:

```python
# The rung that answered is the run's provider by now: a fallback rewrites it
# before the retry that reaches the next rung (app/worker.py _with_fallback).
_RECORD_CALL = """
INSERT INTO model_calls (run_id, seq, provider, system, prompt, reply, tokens)
SELECT id, %s, provider, %s, %s, %s, %s FROM runs WHERE id = %s
"""
```

and in `run_repo_chore`'s `ask`, after the token lines:

```python
        conn.execute(
            _RECORD_CALL,
            (state["seq"] + 1, SYSTEM, prompt, reply.text, reply.tokens, run_id),
        )
```

- [ ] **Step 5: Clean them up.** In `app/cleanup.py` add:

```python
# A chore's model calls go when its bodies do, except a bank run's, which are
# Phase 5's training data (decision 28 of docs/build-brief-evals.md). A bank
# run's calls go with the run itself after a year, by the cascade.
_DROP_CALLS = """
DELETE FROM model_calls c USING runs r
WHERE c.run_id = r.id
  AND r.source <> 'bank'
  AND r.finished_at < now() - make_interval(days => %s)
"""
```

call `conn.execute(_DROP_CALLS, (event_bodies_days,))` inside the transaction in `run_cleanup`, after the strip statements, and add one sentence about model calls to the module docstring.

- [ ] **Step 6: Run both files, then the full suite.** Expected: all pass.

- [ ] **Step 7: Commit.** `Record every model call a chore makes, and keep a bank run's calls past the 30 day cleanup`.

### Task 23: A chore can start from a given commit

**Files:**
- Create: `migrations/016_run_base.sql`, `tests/test_run_base.py`
- Modify: `app/run_request.py`, `app/run_api.py` (`_request_chore`), `app/chores.py` (`_CREATE`, `_CREATE_STARTED`, `start_chore`, `request_chore`), `app/advice.py` (`_RUN`, `_CREATE`, `advise`), `app/outage.py` (`_RETRY`), `app/repo_chore.py` (`run_repo_chore`, `_run`)
- Test: `tests/test_run_base.py`, `tests/test_repo_chore.py`, `tests/test_outage.py`

**Interfaces:**
- Produces: `inputs.base` on a `repo_chore` (a full 40 character sha), stored as `runs.base_sha`. `start_chore(..., base: str | None = None)` and `request_chore(..., base: str | None = None)`. Advised reruns and outage retries keep the base.

- [ ] **Step 1: Write the failing tests.** `tests/test_run_base.py`:

```python
"""A repo chore may name the commit it starts from (decision 29 of
docs/build-brief-evals.md). The bank's chores each start from the parent of
a mined commit."""

import pytest
from pydantic import ValidationError

from app.advice import advise
from app.mercury_config import RepoConfig
from app.run_request import RunRequest

SHA = "a" * 40
REPOS = (RepoConfig(name="owner/fixture", test_command="true"),)


def test_a_chore_may_name_a_full_commit_as_its_base():
    run = RunRequest(type="repo_chore", inputs={"task": "x", "repo": "owner/fixture", "base": SHA})

    assert run.inputs["base"] == SHA


@pytest.mark.parametrize("base", ["abc1234", "g" * 40, "A" * 40, 7])
def test_a_base_that_is_not_a_full_lowercase_sha_is_refused(base):
    with pytest.raises(ValidationError):
        RunRequest(type="repo_chore", inputs={"task": "x", "repo": "owner/fixture", "base": base})


def test_only_a_chore_takes_a_base():
    with pytest.raises(ValidationError):
        RunRequest(type="pytest", inputs={"task": "x", "base": SHA})


def test_an_advised_rerun_starts_from_the_same_base(migrated_db):
    run_id = migrated_db.execute(
        "INSERT INTO runs (task, type, repo, status, base_sha) "
        "VALUES ('x', 'repo_chore', 'owner/fixture', 'escalated', %s) RETURNING id::text",
        (SHA,),
    ).fetchone()[0]

    new_id = advise(migrated_db, run_id, "try the other file", "mcp", REPOS)

    base = migrated_db.execute("SELECT base_sha FROM runs WHERE id = %s", (new_id,)).fetchone()
    assert base == (SHA,)
```

In `tests/test_repo_chore.py`:

```python
def push_commit(remote: Path, tmp_path: Path, name: str, body: str) -> str:
    """Add one commit to the bare remote's main and return its sha."""
    work = tmp_path / f"push-{name}"
    git("clone", "-q", str(remote), str(work), cwd=tmp_path)
    (work / name).write_text(body)
    git("add", name, cwd=work)
    git("-c", "user.name=seed", "-c", "user.email=seed@example.com", "commit", "-qm", name, cwd=work)
    git("push", "-q", "origin", "main", cwd=work)
    return git("rev-parse", "HEAD", cwd=work)


def test_a_chore_with_a_base_starts_from_that_commit(migrated_db, remote, github, tmp_path):
    base = git("rev-parse", "main", cwd=remote)
    push_commit(remote, tmp_path, "later.py", "X = 1\n")
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET base_sha = %s WHERE id = %s", (base, run_id))
    model = StubModel(replies=[pick("calc.py"), change(GOOD_CALC)])

    result = run_repo_chore(migrated_db, run_id, model, setup(tmp_path, github), worker_id=WORKER)

    assert result.status == "succeeded"
    assert "later.py" not in model.prompts[0]
    assert git("rev-parse", f"agent/{run_id}~1", cwd=remote) == base


def test_a_base_that_is_not_in_the_repo_ends_the_chore_in_error(
    migrated_db, remote, github, tmp_path
):
    run_id = chore_run(migrated_db)
    migrated_db.execute("UPDATE runs SET base_sha = %s WHERE id = %s", ("0" * 40, run_id))

    result = run_repo_chore(
        migrated_db, run_id, StubModel(replies=[pick("calc.py")]), setup(tmp_path, github),
        worker_id=WORKER,
    )  # fmt: skip

    assert result.status == "error"
    assert "git checkout failed" in done(migrated_db, run_id)["reason"]
    assert TOKEN not in json.dumps(done(migrated_db, run_id))
```

In `tests/test_outage.py`, in `test_an_outage_older_than_half_an_hour_is_retried_once`, set a base on the failed run and check the retry keeps it:

```python
    failed = outage_run(migrated_db, hint="use floats")
    migrated_db.execute("UPDATE runs SET base_sha = %s WHERE id = %s", ("b" * 40, failed))
    ...
    base = migrated_db.execute(
        "SELECT base_sha FROM runs WHERE source_run_id = %s", (failed,)
    ).fetchone()
    assert base == ("b" * 40,)
```

- [ ] **Step 2: Run them and see them fail.** Expected: `RunRequest` accepts anything in `base`, and `column "base_sha" does not exist`.

- [ ] **Step 3: The column.** `migrations/016_run_base.sql`:

```sql
-- Phase 5 (decision 29 of docs/build-brief-evals.md). The commit a repo
-- chore starts from, when it is not the tip of the default branch. NULL is
-- the tip, as every chore before this migration started.
ALTER TABLE runs ADD COLUMN base_sha text;
```

- [ ] **Step 4: Validate it.** In `app/run_request.py`, `import re`, add `_SHA = re.compile(r"[0-9a-f]{40}")` and:

```python
    @model_validator(mode="after")
    def only_a_chore_has_a_base(self) -> "RunRequest":
        base = self.inputs.get("base")
        if base is None:
            return self
        if self.type != "repo_chore":
            raise ValueError("inputs.base is only for repo_chore")
        if not isinstance(base, str) or not _SHA.fullmatch(base):
            raise ValueError("inputs.base must be a full 40 character commit sha")
        return self
```

- [ ] **Step 5: Store it.** In `app/chores.py` add `base_sha` to both inserts (`_CREATE` gains it after `source`, `_CREATE_STARTED` likewise), give `start_chore` and `request_chore` a keyword `base: str | None = None` and pass it as the last value. In `app/run_api.py` `_request_chore`, pass `base=run.inputs.get("base")` to both. In `app/advice.py` select `base_sha` in `_RUN`, insert it in `_CREATE`, and pass it through in `advise`. In `app/outage.py` `_RETRY`, add `base_sha` to the column list and to the `SELECT`.

- [ ] **Step 6: Check it out.** In `app/repo_chore.py` `run_repo_chore`, select `base_sha` with the rest (`SELECT task, tokens_used, source_run_id, hint, base_sha`), pass it to `_run` as a new last parameter `base_sha: str | None = None`, and in `_run` replace the fresh clone's checkout with:

```python
    git.run("clone", "-q", url, str(clone), cwd=workdir)
    if base_sha:
        # A bank chore starts from the parent of the commit it was mined from
        # (decision 29). The pull request still targets the default branch, and
        # shows only this chore's change, since base_sha is its merge base.
        git.run("checkout", "-q", base_sha, cwd=clone)
    git.run("checkout", "-q", "-b", branch, cwd=clone)
```

`_open_anyway` reapplies an earlier diff and is not given a base; leave it.

- [ ] **Step 7: Run the four files, then the full suite.** Expected: all pass.

- [ ] **Step 8: Commit.** `Let a repo chore start from a named commit, and keep it through advised reruns and outage retries`.

### Task 24: The eval counts unusable replies per column

**Files:**
- Modify: `app/run_list.py` (`_COLUMNS`, `serialize_run_row`), `evals/runner.py` (`EvalRow`, `run_one`, `summarise`)
- Test: `tests/test_run_list.py`, `tests/test_eval_runner.py`

**Interfaces:**
- Produces: `unusable_replies: int` on every run in `GET /runs` and `GET /runs/{id}`; `EvalRow.unusable: int | None = None`; a last column `Unusable replies` in the summary table.

- [ ] **Step 1: Write the failing tests.** In `tests/test_run_list.py` add `"unusable_replies"` to the expected key set, and:

```python
def test_a_run_counts_its_unusable_replies(migrated_db):
    run_id = migrated_db.execute(
        "INSERT INTO runs (task, type) VALUES ('x', 'repo_chore') RETURNING id::text"
    ).fetchone()[0]
    record_step(
        migrated_db, run_id, 1, "edit",
        output={"attempt": 1, "files": [], "problem": "Your reply was not the JSON asked for."},
    )  # fmt: skip
    record_step(migrated_db, run_id, 2, "edit", output={"attempt": 2, "files": ["calc.py"]})

    row = migrated_db.execute(ONE_RUN, (run_id,)).fetchone()

    assert serialize_run_row(row)["unusable_replies"] == 1
```

importing `ONE_RUN` and `serialize_run_row` from `app.run_list` and `record_step` from `app.runs`. In `tests/test_eval_runner.py`:

```python
def test_the_summary_counts_unusable_replies_per_column():
    unusable = EvalRow(
        "t", "local", "local", "id", "escalated", False, 900, 30.0, 0.0,
        "three unusable replies", unusable=3,
    )  # fmt: skip

    lines = summarise([unusable, _row("local", True)]).splitlines()

    assert lines[0].endswith("| Unusable replies |")
    assert lines[2].endswith("| 3 |")
```

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Count them in the run row.** In `app/run_list.py` make `_COLUMNS`:

```python
_COLUMNS = """
SELECT id, type, provider, executor, status, tokens_used,
       extract(epoch from (finished_at - created_at)) AS duration_seconds,
       created_at, source, escalation_reason,
       (SELECT count(*) FROM steps s
        WHERE s.run_id = runs.id AND s.kind = 'edit' AND s.output ? 'problem'
       ) AS unusable_replies
FROM runs
"""
```

and add `unusable_replies` to the unpacking and `"unusable_replies": unusable_replies` to the dict, with a comment that it counts chore replies that were not the JSON asked for or named a path outside the repo (`app/repo_chore.py`), and reads 0 for a run whose bodies the cleanup has stripped. `encode_cursor(rows[-1][7], ...)` in `app/run_api.py` still indexes `created_at`, which has not moved.

- [ ] **Step 4: Carry it into the eval.** In `evals/runner.py` add `unusable: int | None = None` as the last field of `EvalRow`, set `unusable=run.get("unusable_replies")` in `run_one`'s return, and in `summarise` append `"| Unusable replies |"` to the header line, one more `| --- ` to the rule, and to each column line:

```python
            f"| {sum(r.unusable or 0 for r in mine)} |"
```

replacing the closing `|"` of the weakened tests cell with `"`.

- [ ] **Step 5: Run both files, then the full suite.** Expected: all pass; the existing summary assertions match on prefixes and are unchanged.

- [ ] **Step 6: Commit.** `Report unusable replies per run and per eval column`.

### Task 25: Measure the home model through Mercury in compose (decision 21)

On the Windows desktop. Nothing here deploys.

**Files:**
- Create: `local/Modelfile.base`, `local/mercury.compose.yaml`
- Modify: `docker-compose.yml` (the `api` and `worker` services), `.gitignore` if needed
- Results: `evals/results/<stamp>.md` and `.json`

- [ ] **Step 1: The base tag.** `ollama pull qwen2.5-coder:7b`. Write `local/Modelfile.base`:

```
# Mercury's local rung before any training (decision 20 of
# docs/build-brief-evals.md). Ollama's default context window would cut a
# chore prompt short without an error, so it is set here.
FROM qwen2.5-coder:7b
PARAMETER num_ctx 16384
```

then `ollama create mercury-local:base -f local/Modelfile.base` and `ollama show mercury-local:base` (expect `num_ctx 16384`). Run `nvidia-smi` while the next step's request is answering; record the VRAM used in the handoff. If it does not fit in 8 GB, drop `num_ctx` to 12288 and note it.

- [ ] **Step 2: Check JSON mode on this Ollama.**

```bash
curl -s http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"mercury-local:base","response_format":{"type":"json_object"},"messages":[{"role":"system","content":"Answer with a single JSON object and nothing else."},{"role":"user","content":"Reply {\"files\": {\"a.py\": \"print(\\\"hi\\\")\\n\"}, \"summary\": \"one line\"}"}]}' | python -c "import json,sys; print(json.loads(json.load(sys.stdin)['choices'][0]['message']['content']))"
```

Expected: a dict prints. If Ollama rejects `response_format`, stop and hand back: decision 23 needs another route.

- [ ] **Step 3: Compose config.** Copy `config/mercury.sample.yaml` to `local/mercury.compose.yaml` and edit it so `portfolio.repos` holds only:

```yaml
    - name: thomas-whitley/mercury-fixture
      test_command: python -m unittest -v
      auto_approve: true
```

with no Telegram chat id, and the `tasks:` ladders as in the live config. It holds no secret and is committed. In `docker-compose.yml`, give the `api` service `MERCURY_CONFIG_PATH: /config/mercury.yaml` and the volume `./local/mercury.compose.yaml:/config/mercury.yaml:ro`. Give the `worker` service the same two, plus:

```yaml
      # The local rung (Phase 5): Ollama on this machine, reached from the
      # container through the host gateway. Ollama ignores the token.
      LOCAL_MODEL_URL: ${LOCAL_MODEL_URL:-http://host.docker.internal:11434/v1}
      LOCAL_MODEL_TOKEN: ${LOCAL_MODEL_TOKEN:-unused-by-ollama-but-required-32ch}
      LOCAL_MODEL: ${LOCAL_MODEL:-mercury-local:base}
      MAX_LOCAL_RUNS_PER_DAY: ${MAX_LOCAL_RUNS_PER_DAY:-200}
      MERCURY_GITHUB_TOKEN: ${MERCURY_GITHUB_TOKEN:-}
```

and `extra_hosts: ["host.docker.internal:host-gateway"]`. Check CI's compose job still passes with these defaults: the stub model never builds the `local` provider.

- [ ] **Step 4: Run the eleven.** With Docker Desktop started and the repo `.env` loaded (it holds `MERCURY_BEARER_TOKEN` and `MERCURY_GITHUB_TOKEN`; never print them): `MODEL=gemini-3.5-flash-lite docker compose up -d --build db api proxy worker`, then from the Windows checkout `MERCURY_URL=http://localhost:8000 uv run python -m evals.runner --columns local --repeats 1`. The runner closes every pull request and branch it causes on the fixture.

- [ ] **Step 5: Apply the gate.** Read the report. At 2 of 11 or better, `qwen2.5-coder:7b` stays. Below 2, write `local/Modelfile.qwen3` (`FROM qwen3:8b`, the same `num_ctx`), create `mercury-local:qwen3`, rerun Step 4 with `LOCAL_MODEL=mercury-local:qwen3` in the worker's environment, and keep whichever scores higher by retagging it `mercury-local:base`. If both are below 2 of 11, stop here and hand back to Thomas (decision 21). Record the unusable reply counts too: if most failures are unusable replies, say so in the handoff, since that is a format finding for decision 24 rather than a capability one.

- [ ] **Step 6: Commit.** `docker compose down`. Commit the Modelfiles, `local/mercury.compose.yaml`, the compose changes and the results: `Measure the home model through Mercury in compose: <model> <n> of 11, <u> unusable replies`.

### Task 26: The rung goes live through Tailscale Funnel and Caddy (replaced by decision 46)

Done in part on 2026-10-07: the Bicep and `deploy.sh` wiring in Step 6 and `local/README.md` landed, the token was generated and set as a secret, and Caddy was installed and its file validated. Then Thomas chose decision 46, so Steps 4, 5, 7 and 8 were not done: no Funnel, no `LOCAL_MODEL_URL`, no live smoke test of the rung. The Caddyfile and scripts are in `local/parked/`. The steps below are kept as the record of the parked route.

On the desktop. Thomas sets one secret and approves Funnel; everything else Claude runs, per the standing rule that Claude runs the `mercury-config` deploys itself.

**Files:**
- Create: `local/Caddyfile`, `local/start.ps1`, `local/stop.ps1`, `local/README.md`
- Modify: `infra/main.bicep`, `infra/deploy.sh`, and in `thomas-whitley/mercury-config`, `.github/workflows/deploy.yml`

- [ ] **Step 1: Caddy.** `winget install --id CaddyServer.Caddy -e` (if the id has changed, `winget search caddy`). `local/Caddyfile`:

```
# Mercury's local rung (decision 22 of docs/build-brief-evals.md). Tailscale
# Funnel sends https://<machine>.<tailnet>.ts.net to this port. Only a POST to
# chat completions carrying the bearer reaches Ollama; anything else is a 403.
# start.ps1 refuses to start with a short token, because an empty one would
# make the matcher accept the bare word Bearer.
:8080 {
	@allowed {
		method POST
		path /v1/chat/completions
		header Authorization "Bearer {$LOCAL_MODEL_TOKEN}"
	}
	handle @allowed {
		reverse_proxy 127.0.0.1:11434 {
			header_up Host 127.0.0.1:11434
			header_up -Authorization
		}
	}
	respond 403
}
```

- [ ] **Step 2: Start and stop scripts.** `local/start.ps1`:

```powershell
# Starts Mercury's local rung: Caddy in front of Ollama, then Tailscale
# Funnel to Caddy. The token never leaves this process's environment.
$ErrorActionPreference = 'Stop'
$tokenFile = Join-Path $HOME 'mercury-local-token.txt'
$token = (Get-Content $tokenFile -Raw).Trim()
if ($token.Length -lt 32) { throw "$tokenFile must hold LOCAL_MODEL_TOKEN, at least 32 characters" }
$env:LOCAL_MODEL_TOKEN = $token
Start-Process caddy -ArgumentList 'run', '--config', (Join-Path $PSScriptRoot 'Caddyfile'), '--adapter', 'caddyfile' -WindowStyle Hidden
tailscale funnel --bg 8080
tailscale funnel status
```

`local/stop.ps1`:

```powershell
# Stops Mercury's local rung. A local run queued while it is down ends in
# error with "providers unavailable" and never falls back to a cloud rung.
tailscale funnel reset
Get-Process caddy -ErrorAction SilentlyContinue | Stop-Process
```

- [ ] **Step 3: The token, Thomas's step.** Claude generates it straight into the file without printing it: `python -c "import secrets; print(secrets.token_urlsafe(32))" > ~/mercury-local-token.txt`. Thomas runs `! gh secret set LOCAL_MODEL_TOKEN -R thomas-whitley/mercury-config < ~/mercury-local-token.txt`, because the classifier refuses secret writes from Claude.

- [ ] **Step 4: Funnel, Thomas approves.** Run `local/start.ps1`. The first `tailscale funnel` prints a link to enable Funnel for the tailnet; Thomas opens it and approves, then the script is run again. Record the `https://<machine>.<tailnet>.ts.net` address it prints. `LOCAL_MODEL_URL` is that address plus `/v1`.

- [ ] **Step 5: Check the door by hand.** With `T` read from the token file inside the same command, never echoed:

```bash
U=https://<machine>.<tailnet>.ts.net
curl -s -o /dev/null -w "%{http_code}\n" -X POST $U/v1/chat/completions                      # 403
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $(cat ~/mercury-local-token.txt)" $U/api/tags   # 403
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Authorization: Bearer $(cat ~/mercury-local-token.txt)" -H "Content-Type: application/json" -d '{"model":"mercury-local:base","messages":[{"role":"user","content":"Say ok"}]}' $U/v1/chat/completions   # 200
```

Write the three results into `local/README.md`.

- [ ] **Step 6: Bicep and deploy script.** In `infra/main.bicep`, after the `ollamaApiKey` parameter:

```bicep
@description('The home GPU rung: Tailscale Funnel to Caddy to Ollama, ending in /v1 (decision 22). Empty refuses every local run.')
param localModelUrl string = ''

@description('Bearer Caddy checks in front of the home Ollama. Empty refuses every local run.')
@secure()
param localModelToken string = ''

@description('The Ollama tag the local rung serves.')
param localModel string = 'mercury-local:base'

@description('Daily cap on runs on a home provider, apart from maxRunsPerDay (decision 25).')
param maxLocalRunsPerDay int = 200
```

after the `ollamaEnvironment` variable:

```bicep
// The worker alone calls a model, so the local rung's settings go to it alone.
var localSecret = empty(localModelToken)
  ? []
  : [
      {
        name: 'local-model-token'
        value: localModelToken
      }
    ]

var localEnvironment = concat(
  empty(localModelToken)
    ? []
    : [
        {
          name: 'LOCAL_MODEL_TOKEN'
          secretRef: 'local-model-token'
        }
      ],
  [
    {
      name: 'LOCAL_MODEL_URL'
      value: localModelUrl
    }
    {
      name: 'LOCAL_MODEL'
      value: localModel
    }
    {
      name: 'MAX_LOCAL_RUNS_PER_DAY'
      value: string(maxLocalRunsPerDay)
    }
  ]
)
```

and add `localSecret` beside `ollamaSecret` in the worker's secret list (line 269) and `localEnvironment` beside `ollamaEnvironment` in the worker's environment `concat` (line 460). If `az` is installed, `az bicep build --file infra/main.bicep --stdout > /dev/null` must succeed. In `infra/deploy.sh` add after the `maxRunsPerDay` line:

```bash
      localModelUrl="${LOCAL_MODEL_URL:-}" \
      localModelToken="${LOCAL_MODEL_TOKEN:-}" \
      localModel="${LOCAL_MODEL:-mercury-local:base}" \
      maxLocalRunsPerDay="${MAX_LOCAL_RUNS_PER_DAY:-200}" \
```

Commit `Wire the local rung into the Bicep: its address, bearer, tag and daily cap reach the worker` and push. Wait for CI and Publish.

- [ ] **Step 7: The private config.** In a clone of `thomas-whitley/mercury-config`, add to the Deploy step's `env:` in `.github/workflows/deploy.yml`:

```yaml
          LOCAL_MODEL_URL: ${{ vars.LOCAL_MODEL_URL }}
          LOCAL_MODEL_TOKEN: ${{ secrets.LOCAL_MODEL_TOKEN }}
          LOCAL_MODEL: ${{ vars.LOCAL_MODEL || 'mercury-local:base' }}
          MAX_LOCAL_RUNS_PER_DAY: ${{ vars.MAX_LOCAL_RUNS_PER_DAY || '200' }}
```

Set the variable with `gh variable set LOCAL_MODEL_URL -R thomas-whitley/mercury-config --body "<address>/v1"` (if the classifier refuses it, hand Thomas the line). Bump `PUBLIC_SHA` to the Step 6 commit in the same push, and watch Deploy go green.

- [ ] **Step 8: Smoke test live.** With `local/start.ps1` running: `uv run python -m evals.runner --columns local --only clamp` against the live URL; expect a row answered by `local`. Then run `local/stop.ps1` and repeat; expect `error` with `providers unavailable` within a minute, answered by `local`, and no gemini call in the worker's logs (the Logs workflow, `ContainerAppConsoleLogs_CL | where Log_s has "<run id>"`). Run `local/start.ps1` again afterwards. Close anything left on the fixture.

- [ ] **Step 9: README for the folder.** `local/README.md` says what the rung is, the three scripts, where the token lives, the door checks from Step 5 with their results, what happens when the desktop is off, and that nothing here runs in CI. In the repo's writing rules.

- [ ] **Step 10: Commit.** `Put the local rung live through Tailscale Funnel and Caddy, with the door checked by hand`.

### Task 27: Hand over 5a

- [ ] **Step 1: Handoff.** A dated section at the top of `docs/handoff.md`: the live `PUBLIC_SHA`, the Task 25 numbers (model, pass count, unusable replies, VRAM used), the Funnel address's shape without the tailnet name, the Step 8 smoke results, and that Phase 3 is next with a `local` column, detailed into tasks in its own session on Opus. Mark part 5a done in this brief's header.

- [ ] **Step 2: Commit.** `Hand over part 5a: the home model is a live rung and measured at <n> of 11`.

## What not to do

Do not give any repo but the fixture and the Phase 5 bank forks `auto_approve`. Do not add a paid model or an Anthropic key. Do not tune an instruction after seeing a model fail on it unless triage found it ambiguous, and say so in the report. Do not merge any PR the eval opens. Do not add the eval to CI. Do not start Phase 2 in the Phase 1 session.
