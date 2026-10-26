# Review Notes Become Chores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mercury reads open review notes from a site's D1 database each hourly tick, turns each into a repo chore that opens a pull request, reports the change with CI and Lighthouse scores on Telegram, and marks the note done after Thomas merges.

**Architecture:** A new `review_notes:` section in `mercury.yaml` names the repo, live hosts, preview pattern, D1 ids and path rules. The scheduler gains one step, `advance_review_notes`, that moves every tracked note one state on per tick and never waits. The chore itself is the existing `repo_chore` with source `review_note`, which turns on a path guard, a question reply and a different pull request layout. Luke's site gets its own CI workflow.

**Tech Stack:** Python 3.12, FastAPI, psycopg, PostgreSQL, pytest, uv; Node 24 in the image; Cloudflare D1 REST API; GitHub REST API; Azure Container Apps (Bicep); GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-19-review-notes-chores-design.md`. Read it first. Where this plan and the spec disagree, the spec's "Settled with Thomas in the second pass" section wins, and the plan is wrong.

## Global Constraints

- Test first. Each task ends green on `uv run pytest` and `uv run ruff check`, then one commit with a plain message saying what now works, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. No emoji, no `feat:` prefix.
- CI uses the stub model and fakes for Cloudflare, GitHub and Telegram. No real key in any test.
- Nothing Luke specific in this public repo: no account id, database id, hostname, path list or note text. `config/mercury.sample.yaml` carries placeholders only.
- Note text never appears in a log line or on an unauthenticated endpoint. `GET /runs` and `GET /runs/{id}` stay status fields only.
- Writing rules from `CLAUDE.md` for README, docs and commit messages: no em or en dashes, the banned word list, numbers over adjectives, no claim ahead of its test.
- $0 a month idle. The worker still scales to zero.
- Values the spec pins: daily cap 10 note chores in a rolling 24 hours; size flag over 3 files or over 60 changed lines; Lighthouse warning when the preview's performance score is more than 5 points below the live page's; preview given up on at the second tick after the pull request opened; two advised reruns, then a Claude session; worker 1 vCPU and 2 GiB; Node 24.

## Review Focus

- **D1 unreachable or the token wrong.** The tick logs it, counts it against a `review_notes` schedule entry (`record_failure`, which suspends after `SUSPEND_AFTER` and sends the Resume button), and runs the rest of the scheduler as normal. Tested in Task 4.
- **Two ticks overlap, or a tick dies after creating the chore.** A note never gets two chores: the tracking row and the run are created in one transaction, and `review_notes.note_id` is the primary key. Tested in Task 4.
- **A hostile or huge note.** Luke's text is capped at 2,000 characters in the instruction, fenced as data, and the path guard holds whatever the model is told. Tested in Tasks 4 and 5.
- **A page path that is not a page** (a 404 on the live site, a path with a query string). The Lighthouse step records the error and the message says the check failed, without a score. Tested in Task 6.
- **Luke deletes or edits a note mid flight.** Deleted means `gone` and the pull request is left alone. Edited means one line in the message or the report, never a rerun. Tested in Task 7.

---

### Task 1: Node in the image, a bigger worker, and a timeout per repo

**Files:**
- Modify: `Dockerfile` (the `python:3.12-slim` stage)
- Modify: `infra/main.bicep` (worker container resources, about line 498)
- Modify: `app/mercury_config.py` (`RepoConfig`, `_repo`)
- Modify: `app/worker.py:387-394` (`_run_chore` builds `ChoreSetup`)
- Modify: `config/mercury.sample.yaml`
- Test: `tests/test_mercury_config.py`, `tests/test_worker.py` (or the existing chore wiring test file; use the one that already builds `ChoreSetup`)

**Interfaces:**
- Produces: `RepoConfig.test_timeout_seconds: float | None = None`. `None` means `settings.repo_test_timeout_seconds`.

- [ ] **Step 1: Write the failing tests.** `test_a_repo_may_set_its_own_test_timeout`: a config with `test_timeout_seconds: 900` under a repo loads as `900.0`, and a repo without it loads as `None`. `test_a_chore_uses_its_repos_timeout_over_the_default`: `_run_chore` hands `ChoreSetup` the repo's value when set and `settings.repo_test_timeout_seconds` when not (patch `run_repo_chore` to capture the setup).
- [ ] **Step 2: Run them.** `uv run pytest tests/test_mercury_config.py -k timeout -v` fails on the unknown field.
- [ ] **Step 3: Implement** the field, its parsing (`float(entry["test_timeout_seconds"])` when present), and the fallback in `_run_chore`. Add a commented `test_timeout_seconds:` line to the sample config.
- [ ] **Step 4: Node 24 in the Python stage.** Copy the Node 24 binaries from the official `node:24-slim` image into `python:3.12-slim` (`COPY --from=node:24-slim /usr/local/bin/node /usr/local/bin/` and the `npm` and `npx` modules under `/usr/local/lib/node_modules`, with their links), pinned to an exact `node:24.x.y-slim` tag. Raise the web stage to the same tag. Run `docker build -t mercury-local .` then `docker run --rm --entrypoint sh mercury-local -c "node --version && npm --version"`. Expected: `v24.` and an npm version. Record the image size from `docker images mercury-local` before and after in the commit message.
- [ ] **Step 5: The worker size.** Set the worker container to `cpu: json('1.0')` and `memory: '2Gi'`. Leave every other app and the scheduler Job as they are. Check with `az bicep build --file infra/main.bicep`.
- [ ] **Step 6: Run** `uv run pytest` and `uv run ruff check`. All pass.
- [ ] **Step 7: Commit.** "Give the worker Node 24, 1 vCPU and 2 GiB, and let a repo set its own test timeout".

### Task 2: Prove a Node chore on the site repo

Thomas's steps are marked. This task changes no Mercury code unless the trial finds a bug, which then gets its own failing test first.

- [x] **Step 1 (Thomas): give the GitHub token the site repo.** The fine grained `MERCURY_GITHUB_TOKEN` needs Contents and Pull requests read and write on `thomas-whitley/ludo-electrical`.
- [x] **Step 2: Add the site repo to the private config.** In `mercury-config`'s `mercury.yaml`, under `portfolio.repos`, add the repo with `test_command: npm ci && npm run check && npm test && npm run build` and `test_timeout_seconds: 900`. Bump `PUBLIC_SHA` to Task 1's commit once its Publish workflow is green. Pushing `mercury-config` deploys, so ask Thomas first.
- [x] **Step 3: Queue one chore by hand** through MCP `create_run` on the site repo, with an instruction that changes one word of copy in `src/pages/about.astro`. Approve it on Telegram.
- [x] **Step 4: Check the result.** Expected: a pull request whose diff is that one word, and a done step with all of `npm ci`, `astro check`, vitest and `astro build` green. Read the worker's peak memory and the test step's duration from the Logs workflow (`gh workflow run logs.yml -R thomas-whitley/mercury-config -f query='<KQL>'`) and write them down for the README in Task 8. Close the pull request and delete its branch.
- [x] **Step 5: If it ran out of memory or time,** stop and bring the numbers to Thomas before any further task. The spec's worker size is his decision.

**First done 2026-10-21 (run `f96c092b`, in the README). Repeated 2026-10-26 (run 54ef4b79, ludo-electrical PR #4, closed), with the same outcome.** The test command passed on the first attempt: `npm ci`, `astro check`, vitest and `astro build`. Worker peak memory 1,053 MiB of 2 GiB; the test step about 2.5 minutes of the 900 s timeout; the run 219 s end to end on gemini. The diff carried the one word plus a reformat of the `.map(...)` block in the At a glance panel, because a hand queued chore rewrites whole files; note chores use search and replace edits (Task 5), so this is not a bug in the note path.

### Task 3: CI on the site repo

**Files (in `C:\Projects\ludo-electrical`):**
- Create: `.github/workflows/ci.yml`

Follow that repo's `CLAUDE.md` and `AGENTS.md`.

- [ ] **Step 1: Write the workflow.** On `pull_request` and on `push` to `main`. One job on `ubuntu-latest` with `actions/setup-node` at Node 24 and the npm cache, running `npm ci`, `npm run check`, `npm run check:worker`, `npm test` and `npm run build` as separate steps. Name the workflow `CI`.
- [ ] **Step 2: Prove it.** Push it on a branch, open a pull request, and wait with `gh pr checks <n> --watch`. Expected: every step green. Merge only with Thomas's yes, since `main` deploys Luke's site.
- [ ] **Step 3: Commit** in the site repo: "Run the site's checks, tests and build on every pull request and push to main".

### Task 4: Read notes and start chores

**Files:**
- Create: `app/review_notes.py`, `app/d1.py`, `migrations/017_review_notes.sql`, `tests/cloudflare_fake.py`, `tests/test_review_notes.py`
- Modify: `app/mercury_config.py`, `app/config.py` (`Settings`), `app/scheduler.py` (`main`), `config/mercury.sample.yaml`, `tests/test_mercury_config.py`

**Interfaces:**
- Produces, in `app/mercury_config.py`:
  `ReviewNotesConfig(enabled: bool, repo: str, live_hosts: tuple[str, ...], preview_pattern: str, account_id: str, database_id: str, allowed_paths: tuple[str, ...], shared_paths: tuple[str, ...], sensitive_files: tuple[str, ...], daily_cap: int = 10)`, and `MercuryConfig.review_notes: ReviewNotesConfig | None = None`. `preview_pattern` contains `{alias}`, as in `https://{alias}-worker.sub.workers.dev`. `enabled` is true only for a YAML boolean `true`. A `repo` that is not in `portfolio.repos` with a `test_command` is refused at load.
- Produces, in `app/config.py`: `Settings.cloudflare_d1_token: str | None` (env `CLOUDFLARE_D1_TOKEN`) and `Settings.cloudflare_api_url: str` (env `CLOUDFLARE_API_URL`, default `https://api.cloudflare.com/client/v4`).
- Produces, in `app/d1.py`: `class D1Error(Exception)`, and `D1Client(token: str, account_id: str, database_id: str, api_url: str)` with `query(sql: str, params: list) -> list[dict]`, a POST to `/accounts/{account_id}/d1/database/{database_id}/query` with `{"sql", "params"}`. It raises `D1Error` on any HTTP error, a timeout or `"success": false`, and the message never carries the token.
- Produces, in `app/review_notes.py`: `@dataclass(frozen=True) class Note(id: int, host: str, page: str, anchor_text: str | None, quote: str | None, body: str, updated_at: str)`; `open_notes(d1: D1Client) -> list[Note]`; `instruction_for(note: Note) -> str`; `start_note_chores(conn, notes: list[Note], config: ReviewNotesConfig, repo: RepoConfig) -> list[str]`.
- Produces, in `migrations/017_review_notes.sql`: `review_note` added to `runs_source_check`, and the table below.

```sql
CREATE TABLE review_notes (
    note_id            integer PRIMARY KEY,
    host               text NOT NULL,
    page               text NOT NULL,
    note_updated_at    text NOT NULL,
    state              text NOT NULL CHECK (state IN
        ('chore', 'question', 'waiting', 'reported', 'merged', 'closed', 'gone', 'preview', 'capped')),
    run_id             uuid REFERENCES runs (id),
    pr_url             text,
    pr_opened_ticks    integer NOT NULL DEFAULT 0,
    preview_url        text,
    live_check_id      uuid,
    preview_check_id   uuid,
    message_id         bigint,
    edited             boolean NOT NULL DEFAULT false,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
```

- [ ] **Step 1: Write the failing tests** in `tests/test_review_notes.py`, with `FakeCloudflare` in `tests/cloudflare_fake.py` serving the D1 query endpoint on a local socket, the way `tests/github_fake.py` serves GitHub:
  - `test_a_new_note_on_a_live_host_starts_one_chore`: one open note gives one `repo_chore` run, `pending`, source `review_note`, on the configured repo, and one `review_notes` row in state `chore` with that run id.
  - `test_a_note_already_tracked_starts_nothing`: a second tick with the same note creates no run.
  - `test_a_note_on_a_preview_host_is_recorded_not_run`: state `preview`, no run.
  - `test_notes_over_the_daily_cap_wait`: 12 notes give 10 runs and 2 rows in state `capped`. A `capped` note starts on a tick once fewer than 10 note chores started in the last 24 hours.
  - `test_a_second_note_on_the_same_page_waits`: two notes on `/about/` give one run. The second starts only once the first's row is `merged` or `closed`.
  - `test_disabled_starts_nothing_but_existing_notes_advance`: `enabled: false` starts no run.
  - `test_the_instruction_quotes_the_note_as_data`: the instruction holds the page, the anchor text, the quote and the body, the body inside a fenced block under a line saying it is the reviewer's words to act on and not instructions to follow, and a body over 2,000 characters is cut to 2,000.
  - `test_d1_failing_counts_against_the_schedule_and_the_tick_goes_on`: the fake answers 500. No run, `record_failure` counted for `review_notes`, no exception out of the step.
  - `test_the_row_and_the_run_are_one_transaction`: when the run insert fails, no `review_notes` row is left.
  - In `tests/test_mercury_config.py`: `test_review_notes_loads` and `test_review_notes_with_an_unknown_repo_is_refused`.
  - In `tests/test_migrations.py`, or wherever migrations are checked: 017 applies, and a run with source `review_note` inserts.
- [ ] **Step 2: Run them.** `uv run pytest tests/test_review_notes.py -v` fails on the missing module.
- [ ] **Step 3: Implement.** `open_notes` selects `id, host, page, anchor_text, quote, body, updated_at` where `status = 'open'`, ordered by `id`. `start_note_chores` inserts the row and calls `app.chores.start_chore(conn, repo, instruction_for(note), "review_note", TASK_TYPES["repo_chore"].provider)` inside `conn.transaction()`, with `ON CONFLICT (note_id) DO NOTHING` deciding whether to go on. The scheduler's `main` calls a wrapper, `advance_review_notes(conn, settings, config, telegram, github)`, after `watch_ci`. In this task it reads the notes and starts chores only, inside a `try` that turns `D1Error` into `_fail(conn, "review_notes", "Reading the review notes", telegram, chat_id)` and `record_success` otherwise. Skip the whole step when `config.review_notes` is `None` or `settings.cloudflare_d1_token` is unset.
- [ ] **Step 4: Run** `uv run pytest` and `uv run ruff check`. All pass.
- [ ] **Step 5: Commit.** "Start one chore for each new review note on a live host, within a daily cap and one per page".

### Task 5: What a note chore may do, and how its pull request reads

**Files:**
- Modify: `app/repo_chore.py` (`run_repo_chore` reads `source`; `_run`; `_open_pull`; `_title`), `app/chore_prompts.py` (the edit prompt gains the question option for note chores), `app/escalation.py` (`announce_escalation`), `app/advice.py` (`advise`)
- Test: `tests/test_repo_chore.py`, `tests/test_escalation.py`, `tests/test_advice.py`

**Interfaces:**
- Consumes: `ReviewNotesConfig.allowed_paths` from Task 4, passed in through `ChoreSetup`.
- Produces: `ChoreSetup.allowed_paths: tuple[str, ...] | None = None`. `None` means no guard, as today. `_run_chore` in `app/worker.py` sets it from `config.review_notes.allowed_paths` when the run's source is `review_note`. A path is allowed when it equals an entry or starts with an entry that ends in `/`.
- Produces: the reason constants `OUTSIDE_PATHS = "changes outside the paths a note may touch"` and `NEEDS_THOMAS = "the note needs Thomas"` in `app/repo_chore.py`. The `done` output of a question carries `{"reason": NEEDS_THOMAS, "question": "<the model's question>"}`.
- Produces: `note_title(page: str, body: str) -> str` in `app/review_notes.py`, giving `Luke's note on <page>: <first words of body>`, cut to 72 characters. The reviewer's name comes from a `reviewer_name` field on `ReviewNotesConfig` (add it in this task, required), not a literal, so the public repo stays general.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_note_chore_outside_its_paths_is_refused_and_escalates`: with `allowed_paths=("src/pages/",)`, three replies writing `package.json` end `escalated` with reason `OUTSIDE_PATHS`, nothing pushed, and each attempt's prompt names the refused paths.
  - `test_a_note_chore_inside_its_paths_opens_its_pull_request`: a reply writing `src/pages/about.astro` passes the tests and opens a PR.
  - `test_a_chore_without_allowed_paths_keeps_todays_rules`: an ordinary chore writing `package.json` is not refused.
  - `test_a_question_ends_the_chore_with_no_push`: a reply `{"question": "Which number?"}` ends `escalated` with reason `NEEDS_THOMAS`, the question in the done output, and no branch on the remote.
  - `test_a_note_pull_request_puts_the_note_first`: the PR title is `note_title(...)`, and the body starts with the note's body quoted, then the anchor text and quote, then the summary, then the instruction. Read the note from the `review_notes` row joined on `run_id`.
  - `test_a_note_escalation_has_no_open_anyway_button`: `announce_escalation` on a `review_note` run with a diff sends a plain message, with no approval row.
  - `test_each_question_in_a_note_chain_is_announced`: a rerun that asks again is announced, though its chain already sent one.
  - `test_advice_on_a_note_chore_keeps_its_source`: `advise` on a `review_note` run creates a rerun with source `review_note`, and the third refuses as today.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement.** Keep `_refused_paths` and add the allowed path check beside it, so the existing escaping rules still apply. The question reply is accepted only when the run's source is `review_note`. For any other chore it stays an unusable reply. The note prompt says that a question in place of files is the right answer when the note is a question, or too vague to act on.
- [ ] **Step 4: Run** `uv run pytest` and `uv run ruff check`. All pass.
- [ ] **Step 5: Commit.** "Keep note chores inside their paths, let them ask a question, and lead their pull requests with the note".

### Task 6: Preview, Lighthouse, CI and the one message

**Files:**
- Modify: `app/review_notes.py`, `app/github.py`, `tests/github_fake.py`, `app/scheduler.py`
- Test: `tests/test_review_notes.py`

**Interfaces:**
- Consumes: `_create_run(api_base_url, bearer_token, url, kind="lighthouse")` in `app/scheduler.py`; Lighthouse results as the run's step 1 output `scores.performance` (0 to 1) and `runs.executor`; `GitHubClient.completed_workflow_runs(repo, branch)`.
- Produces: `preview_alias(branch: str) -> str` (lower case, every run of characters outside `a-z0-9` becomes `-`, trimmed of `-`). `diff_flags(diff: str, config: ReviewNotesConfig) -> list[str]`. `note_message(note: Note, row: dict, flags: list[str], ci: str, scores: dict) -> str`. `advance_waiting(conn, config, github, telegram, chat_id, api_base_url, bearer_token, http_get) -> None`. `http_get(url) -> int` is injected, so tests need no network.

State moves, one per tick, all in `advance_waiting`:
1. `chore`: the run finished `succeeded` with a `pr_url`, so set `pr_url`, then state `waiting`. Finished `escalated` with `NEEDS_THOMAS` or any other reason, so state `question` (the escalation message already went out from the worker). A rerun from advice is followed through `source_run_id`, so the row's `run_id` moves to the newest run of the chain.
2. `waiting` with no `preview_url`: build it from `preview_pattern` and `preview_alias("agent/<run id>")`, plus the page. If `http_get` gives 200, store it and queue the two Lighthouse checks (live, `https://{live_hosts[0]}{page}`, and preview) on this tick. Otherwise increment `pr_opened_ticks`. At 2, go straight to the message without scores.
3. `waiting` with both checks finished: send `note_message` and store `message_id`. State `reported`.

- [ ] **Step 1: Write the failing tests.**
  - `test_preview_alias_of_an_agent_branch`: `preview_alias("agent/0bd71e3b-27f2-4926-9694-9db194075188")` is `agent-0bd71e3b-27f2-4926-9694-9db194075188`.
  - `test_diff_flags`: 4 files gives the size line. 61 changed lines gives the size line. A file under a `shared_paths` entry gives the every page line. A change to a `sensitive_files` file gives a line naming each changed `key:` (for `phone: '0419...'` the line names `phone`). A one line change to a page gives no flags.
  - `test_the_message_compares_scores_from_one_executor`: both `self_hosted`, live 0.92 and preview 0.85, gives a warning line (7 points). Live 0.92 and preview 0.88 gives none (4 points). Different executors show both scores, with a line saying they ran on different machines, and no comparison.
  - `test_the_message_without_a_preview`: after 2 ticks with `http_get` returning 404, one message with no scores and a line saying no preview answered.
  - `test_a_lighthouse_error_is_said_not_scored`: a check that ended in error puts the error in the message, not a score.
  - `test_ci_states_in_the_message`: green, red with the workflow name, and still running when no completed run exists on the branch.
  - `test_one_message_per_note`: a later tick after `reported` sends nothing.
  - `test_the_message_holds_the_note_and_the_link`: the note's body, the summary from the done output, and the PR URL.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement.** Call `advance_waiting` from `advance_review_notes` before starting new chores. Put the message's flags first, then the note, then the summary, the CI line, the scores and the link.
- [ ] **Step 4: Run** `uv run pytest` and `uv run ruff check`. All pass.
- [ ] **Step 5: Commit.** "Report each note's pull request on Telegram with its CI result and Lighthouse scores".

### Task 7: The tick on merge, the report and the digest

**Files:**
- Modify: `app/review_notes.py`, `app/github.py` (`pull_state`), `tests/github_fake.py`, `app/report.py`, `app/digest.py`
- Test: `tests/test_review_notes.py`, `tests/test_report.py`, `tests/test_digest.py`

**Interfaces:**
- Produces: `GitHubClient.pull_state(repo: str, branch: str) -> str`, returning `open`, `merged` or `closed` (from `GET /repos/{repo}/pulls?head={owner}:{branch}&state=all`; merged when `merged_at` is set). `settle_notes(conn, d1: D1Client, config: ReviewNotesConfig, github: GitHubClient, notes: list[Note]) -> None`. `notes_section(conn) -> list[str]` for the report. `notes_waiting(conn) -> int` for the digest.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_merged_note_is_marked_done_in_d1`: a `reported` row whose PR is merged sends `UPDATE review_comments SET status = 'done', updated_at = datetime('now') WHERE id = ? AND status = 'open'` with the note id, and the row becomes `merged`.
  - `test_a_closed_pull_request_leaves_the_note_open`: the row becomes `closed`, with no D1 write and no new chore for that note.
  - `test_a_deleted_note_is_gone_and_its_pull_request_left`: a tracked note missing from `open_notes` while its row is not `merged` becomes `gone`, with no GitHub write.
  - `test_an_edited_note_is_flagged_not_rerun`: a changed `updated_at` sets `edited`, starts no run, and adds a line to the message if it is not yet sent.
  - `test_the_report_lists_notes`: a `## Review notes` section with each row's note id, page, state and PR, and the `preview` and `capped` rows. Never the note's body: the report goes to Claude sessions, but its section stays as plain as the rest of the file.
  - `test_the_digest_says_when_notes_wait`: one line, `Review notes: 2 waiting on you.`, when rows are in `question` or `reported`, and none when there are none.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement.** Wire `settle_notes` into `advance_review_notes` after `advance_waiting`. A D1 write that fails is a `D1Error`, counted on the same schedule entry, and it leaves the row as it was, so the next tick tries again.
- [ ] **Step 4: Run** `uv run pytest` and `uv run ruff check`. All pass.
- [ ] **Step 5: Commit.** "Mark a review note done once its pull request merges, and list notes in the report and digest".

### Task 8: Configure, deploy, and document

- [ ] **Step 1 (Thomas): the Cloudflare token.** In Luke's Cloudflare account, create an API token with Account, D1, Edit on that account only. Store it as `CLOUDFLARE_D1_TOKEN` in `mercury-config` with the clipboard script pattern used for the PageSpeed key (it checks and stores the token without printing it).
- [ ] **Step 2: Pass the secret to the scheduler alone.** Add a `cloudflareD1Token` Bicep parameter, a scheduler only secret and its env var in `infra/main.bicep`, following `pagespeedApiKey`. Add the `CLOUDFLARE_D1_TOKEN` line to `config/private-repo/deploy.yml` and to the private repo's copy.
- [ ] **Step 3: The private config.** In `mercury-config`'s `mercury.yaml`, add `review_notes:` with `enabled: true`, the site repo, `live_hosts: [ludoelectrical.com, <the production workers.dev host>]`, the preview pattern, the account and database ids, `reviewer_name: Luke`, and the paths: `allowed_paths` (`src/pages/`, `src/content/`, `src/components/`, `src/layouts/`, `src/styles/`, `src/assets/`, `public/`, `src/site.config.ts`), `shared_paths` (`src/components/`, `src/layouts/`, `src/styles/`) and `sensitive_files` (`src/site.config.ts`). Bump `PUBLIC_SHA`. Ask Thomas before pushing, since it deploys.
- [ ] **Step 4: README.** Add a section, "Review notes become chores", in the README's voice: what happens to a note, the token's account wide D1 reach in those words, and the image size, cold start, peak memory and chore duration measured in Tasks 1 and 2. Add a claims row only in Task 9, once the trial passes.
- [ ] **Step 5: Commit** (public repo). "Pass the Cloudflare token to the scheduler and document review notes".

### Task 9: The supervised trial

- [ ] **Step 1 (Thomas):** open Luke's review link on his own phone and leave one note on a page asking for a harmless copy change.
- [ ] **Step 2: Watch it through.** Note the times of the note, the chore start, the PR, the message, the merge and the tick. The trial passes only if all of these hold:
  - the PR changes only what the note asked;
  - the worker checks and CI are green;
  - one Telegram message arrives, with both scores from the same executor;
  - after Thomas merges, the change is on `ludoelectrical.com` and the note shows its tick.
- [ ] **Step 3: Record it.** Each step's time, the worker's peak memory and the tokens go in the README section. Add the claims row with that evidence.
- [ ] **Step 4: Commit.** "Record the first review note handled end to end".
- [ ] **Step 5:** A failed criterion gets a failing test and a fix before Luke's link is used for real.
