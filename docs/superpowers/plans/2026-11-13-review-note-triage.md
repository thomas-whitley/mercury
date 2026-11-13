# Review Note Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every new review note is sorted by the model first. A note that isn't a website change goes straight to Thomas as a card showing what it is, how old it is and a suggestion, with Dismiss and Treat as a change buttons. Escalated note chores get the same card header and a Dismiss button.

**Architecture:**
- **Sorting:** the scheduler records each new note and queues a `note_sort` run. The worker runs it like `chat`: one model call, then either queue the note for a chore (`capped`) or send the card (`asked`).
- **Buttons:** handled by the webhook. Dismiss only sets state `dismiss`, and the next scheduler tick writes the D1 "done" (the same query a merged PR uses) and sets `dismissed`.
- **Digest:** waiting notes are listed in code.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, Postgres, uv, pytest with the stub model.

**Spec:** `docs/superpowers/specs/2026-11-13-review-note-triage-design.md`.

## Global Constraints

- `uv` for everything: `uv run pytest`, `uv run ruff check`. CI uses the stub model only, never a real key.
- One task, one green test run, one commit. Failing test first (repo CLAUDE.md).
- The note's words reach the model only inside fences (`fenced_text`). They never become a button or a link. The suggestion is plain text, at most 150 characters.
- Mercury never dismisses, closes or changes a note by itself. Only a button press does.
- A model failure messages no one. The note is sorted again on a later tick.
- Sorting doesn't count toward `review_notes.daily_cap`. Treat as a change and every chore respect `daily_cap`, the day's run limit and the token cap (`_advance_note`).
- Log ids and class names only, never note text (existing rule in `app/review_notes.py`).
- README banned words list applies to all copy. Fill a README claims row only when its test passes.
- Model config lives in two copies: change `local/mercury.home.yaml` and the `mercury-config` repo together (push the latter with `[skip ci]`).

## Review Focus

1. **A button pressed twice, or on an old card after the note moved on:** it must change nothing the second time. Lock the row (`FOR UPDATE`) and check its state, as approvals do. Covered in Task 5.
2. **Luke edits the note after the card went out:** Dismiss must not act. It tells Thomas the note changed, and the next tick re-sorts it and sends a new card. Covered in Task 5.
3. **The model returns junk** (no JSON, unknown kind, a 2,000-character suggestion): treat it as `other` with no suggestion, rather than crashing or starting a chore. Covered in Task 3.
4. **The note is deleted on the site** while it's `asked` or `sorting`: the row becomes `gone`, and any later press says so. Covered in Task 6.
5. **D1 is down when Dismiss is pressed:** the row stays `dismiss` and the next tick retries. Thomas's tap is never lost. Covered in Task 6.

---

### Task 1: Migration for the new states and columns

**Files:**
- Create: `migrations/021_review_note_triage.sql`
- Test: `tests/test_review_notes.py`

**Interfaces:**
- **Produces:**
  - `review_notes.state` also allows `'sorting'`, `'asked'`, `'dismiss'` and `'dismissed'`.
  - New columns:
    - `card_message_id bigint`: the Telegram card or escalation message that carries the note's buttons
    - `card_updated_at text`: `note_updated_at` when that message was sent
    - `suggestion text`
    - `held_by_page boolean NOT NULL DEFAULT false`

- [ ] **Step 1:** Write `test_review_notes_accepts_triage_states`. It inserts one row per new state and asserts all four commit, then asserts an insert with state `'bogus'` raises `psycopg.errors.CheckViolation`.
- [ ] **Step 2:** Run `uv run pytest tests/test_review_notes.py -k triage_states -q`. Expect a FAIL with CheckViolation on `'sorting'`.
- [ ] **Step 3:** Write the migration. Drop and re-add the `state` CHECK (copy the list from `017_review_notes.sql` and add the four), then `ALTER TABLE review_notes ADD COLUMN` for the four columns.
- [ ] **Step 4:** Run the test again. Expect a PASS.
- [ ] **Step 5:** Commit: `Add review note triage states and card columns`.

### Task 2: The card text and its buttons

**Files:**
- Create: `app/note_card.py`
- Test: `tests/test_note_card.py`

**Interfaces:**
- **Produces:**
  - `age_line(written: str, picked_up: datetime, now: datetime, held_by_page: bool) -> str`
  - `card_text(reviewer: str, page: str, body: str, anchor: str | None, quote: str | None, age: str, suggestion: str | None) -> str`
  - `card_buttons(note_id: int, can_change: bool) -> list[tuple[str, str]]`
  - `BUTTON = re.compile(r"^note:(\d+):(dismiss|change)$")`
  - `SUGGESTION_LIMIT = 150`

- [ ] **Step 1: Write the failing tests.**
  - `test_age_line_plain`: written `"2026-10-28 09:48:42"`, picked up at the same time, now `2026-11-13 10:00 UTC`. Asserts `"Written 28 Oct, 16 days ago."`
  - `test_age_line_late_unknown`: picked up `2026-11-12 23:16 UTC`. Asserts the line ends `" Picked up late."`
  - `test_age_line_held`: the same with `held_by_page=True`. Asserts it ends `" Held up behind another note on the same page."`
  - `test_age_line_today`: written 2 hours before now. Asserts `"Written today."`
  - `test_card_text_shape`: asserts the first line is `"Luke left a note on /:"`, followed by the body inside a fence, then the age line, then `"Suggestion: Looks personal."` A `None` suggestion has no Suggestion line. A 4,000-character body is cut so the whole text stays under `escalation.MESSAGE_LIMIT`.
  - `test_card_buttons`: `card_buttons(5, True) == [("Dismiss", "note:5:dismiss"), ("Treat as a change", "note:5:change")]`, and `card_buttons(5, False)` has Dismiss only.
- [ ] **Step 2:** Run `uv run pytest tests/test_note_card.py -q`. Expect a FAIL (module not found).
- [ ] **Step 3:** Implement in `app/note_card.py`.
  - `written` is D1's `updated_at` text, read as UTC.
  - Late means `picked_up - written > 1 day`.
  - Put the body, anchor and quote in `fenced_text` blocks, each capped as `instruction_for` caps them, and use `escalation._fit` on the body when space runs short.
  - Cut the suggestion to `SUGGESTION_LIMIT` and put it on a single line.
- [ ] **Step 4:** Run the tests. Expect a PASS.
- [ ] **Step 5:** Commit: `Add the review note card`.

### Task 3: The `note_sort` run

**Files:**
- Create: `app/note_sort.py`
- Modify: `app/tasks.py` (add `TaskType(name="note_sort", tools=(), ladder=("gemini",), budget_tokens=5_000)`), `app/worker.py` (`_RUNNABLE_TYPES` and a dispatch next to the `chat` one at line 341), `local/mercury.home.yaml` and the `mercury-config` repo (`tasks.note_sort.ladder: [gemini]`, if the loader lists task types there)
- Test: `tests/test_note_sort.py`

**Interfaces:**
- **Consumes:** `card_text`, `card_buttons` and `age_line` (Task 2); the `review_notes` columns (Task 1).
- **Produces:** `run_note_sort(conn, run_id: str, model: Model, telegram: TelegramClient | None, chat_id: int | None, reviewer_name: str, worker_id: str | None = None) -> int` (tokens used). It finds its note with `review_notes.run_id = run_id`.

- [ ] **Step 1: Write the failing tests**, using a stub model that returns fixed text.
  - `test_sort_change_queues_chore`: the reply is `{"kind": "change", "suggestion": "x"}`. Asserts the row is `capped`, `run_id IS NULL`, and no Telegram message was sent.
  - `test_sort_other_sends_card`: the reply is `{"kind": "other", "suggestion": "Looks personal."}`. Asserts the row is `asked`, `card_message_id` is the sent id, `card_updated_at` equals `note_updated_at`, and the sent text contains `"Suggestion: Looks personal."` with both buttons.
  - `test_sort_unsure_sends_card`: `{"kind": "unsure"}` is handled like other.
  - `test_sort_junk_is_other`: the reply is `"no json here"`. Asserts the row is `asked`, with no Suggestion line.
  - `test_sort_long_suggestion_cut`: a 2,000-character suggestion. Asserts the stored `suggestion` is at most 150 characters.
  - `test_sort_model_down_leaves_sorting`: the model raises `RuntimeError`. Asserts the run ends `error`, the row is still `sorting`, and nothing was sent.
  - `test_sort_prompt_fences_note`: asserts the user prompt the model got has the note body only inside a fence (use `fenced_text`).
- [ ] **Step 2:** Run `uv run pytest tests/test_note_sort.py -q`. Expect a FAIL.
- [ ] **Step 3:** Implement `run_note_sort`.
  - **The model call:** a system prompt asking for a single JSON object, `{"kind": "change"|"other"|"unsure", "suggestion": "<one line for the site owner>"}`. Call it through `_complete_with_retry`, as `app/chat.py` does.
  - **The note:** its words come from `review_notes.note_body`, `note_anchor` and `note_quote`.
  - **On change:** `UPDATE ... SET state='capped', run_id=NULL`.
  - **Otherwise:** send the card and set `asked`, `suggestion`, `card_message_id` and `card_updated_at`. Use one transaction, so a failed send leaves the row `sorting`.
  - **On model failure:** finish the run `error` and leave the row alone.
- [ ] **Step 4:** Run the tests, then `uv run pytest tests/test_worker.py -q`. Expect a PASS.
- [ ] **Step 5:** Commit: `Add the note_sort run`.

### Task 4: Sort every new note first

**Files:**
- Modify: `app/review_notes.py` (`start_note_chores`, `_advance_note`)
- Test: `tests/test_review_notes.py`

**Interfaces:**
- **Consumes:** the `note_sort` run type (Task 3).
- **Produces:** `queue_sort(conn, note: Note) -> str`. It records or reuses the row as `sorting`, stores the note's words (as `_SET_RUN` does, capped), creates a pending `note_sort` run with `source='review_note'`, and returns its id.

- [ ] **Step 1: Write the failing tests.**
  - `test_new_note_is_sorted_not_chored`: asserts a new note on a live host gets a `sorting` row and a `note_sort` run, and no `repo_chore`.
  - `test_new_note_sorted_while_page_busy`: another note on the same page is `waiting`. Asserts the new note is still `sorting`.
  - `test_new_note_sorted_over_daily_cap`: the cap is full. Asserts it's still `sorting`.
  - `test_failed_sort_is_requeued`: a `sorting` row whose run ended `error` or `refused` gets a new `note_sort` run on the next call. A row whose run is still pending gets none.
  - `test_capped_from_sort_starts_chore_when_free`: a `capped` row with `run_id NULL` starts a chore through the existing path.
  - `test_capped_waiting_for_page_sets_held`: a `capped` row blocked by `_PAGE_BUSY` gets `held_by_page = true`.
  - `test_preview_host_unchanged`: notes on preview hosts still become `preview` with no sort.
- [ ] **Step 2:** Run `uv run pytest tests/test_review_notes.py -q`. Expect the new tests to FAIL.
- [ ] **Step 3:** In `_advance_note`:
  - A new live note (`state is None`) calls `queue_sort` before the page-busy and cap checks.
  - A `sorting` row requeues when its run has finished but not succeeded.
  - `capped` keeps today's path, plus the `held_by_page` update where it logs "waits for another note on its page".
  - The `capped` row's `run_id` is NULL after sorting, so `_UNCAP` returns NULL and `start_chore` runs, as today.
- [ ] **Step 4:** Run all of `tests/test_review_notes.py`. Expect a PASS, with old tests updated only where a new note used to go straight to `chore`.
- [ ] **Step 5:** Commit: `Sort each new review note before any chore`.

### Task 5: The card buttons and replies

**Files:**
- Modify: `app/telegram_webhook.py` (`_on_button` routes `note:` data; a reply to a `card_message_id` is a hint)
- Create: `app/note_buttons.py` (database logic, so the webhook stays thin)
- Test: `tests/test_note_buttons.py`, `tests/test_telegram_webhook.py`

**Interfaces:**
- **Consumes:** `BUTTON` and `card_text` (Task 2); `_advance_note` (Task 4).
- **Produces:**
  - `press(conn, note_id: int, action: str, mercury: MercuryConfig, settings: Settings) -> str`. It returns the short answer shown to Thomas.
  - `hint_on_card(conn, message_id: int, hint: str, mercury, settings) -> str | None`. It returns None when no card has that id.

- [ ] **Step 1: Write the failing tests** in `test_note_buttons.py`.
  - `test_dismiss_asked`: asserts state becomes `dismiss` and the answer is `"Dismissed."`
  - `test_dismiss_question`: an escalated note with no PR. Same result.
  - `test_dismiss_refused_while_running`: the newest chain run is still running. Asserts state is unchanged and the answer is `"A rerun is going; close its pull request to drop the note."`
  - `test_dismiss_refused_with_pr`: `pr_url` is set. The same refusal.
  - `test_press_after_edit`: `note_updated_at != card_updated_at`. Asserts state is unchanged, the row is reset to `sorting` with a new `note_sort` run, and the answer is `"Luke changed this note since. I'll send the new version."`
  - `test_press_twice`: the second press of Dismiss answers `"Already dismissed."` and changes nothing.
  - `test_press_gone`: the row is `gone`. Asserts the answer is `"Luke deleted this note."`
  - `test_change_starts_chore`: `asked` plus change. Asserts `_advance_note` ran: a `repo_chore` run exists or the row is `capped` when the day is full, and the answer says which.
  - `test_change_on_question_refused`: change isn't offered on escalations. The answer is `"This one already ran. Reply with a hint instead."`
  - `test_hint_on_asked_card`: a reply to an `asked` card starts the chore with the hint. Follow how `app/advice.py` stores `runs.hint`. If `repo_chore` reads the hint only for reruns, append it to the instruction inside a `fenced_text("Thomas's hint:", hint)` block instead.

  In `test_telegram_webhook.py`, add `test_note_button_routes`: a `callback_query` with data `note:5:dismiss` from the allowed chat reaches `press`, and a press from another chat is ignored.
- [ ] **Step 2:** Run both test files. Expect a FAIL.
- [ ] **Step 3:** Implement.
  - Lock the row with `SELECT ... FOR UPDATE`.
  - Answer Telegram's callback, and on success edit the card to add the answer line, as the approval button handler does.
  - Treat a reply to `card_message_id` like `_advise_on_escalation`. For a `question` row, keep today's advice path.
- [ ] **Step 4:** Run the tests. Expect a PASS.
- [ ] **Step 5:** Commit: `Handle Dismiss and Treat as a change on note cards`.

### Task 6: Scheduler follow-up: D1 done, legacy questions, edits and deletions

**Files:**
- Modify: `app/review_notes.py` (`settle_notes`, `_TRACKED_BY_PR`, and a new `finish_dismissals`), `app/scheduler.py` (`advance_review_notes` calls it before `start_note_chores`)
- Test: `tests/test_review_notes.py`

**Interfaces:**
- **Consumes:** `card_text`, `card_buttons` and `age_line` (Task 2).
- **Produces:**
  - `finish_dismissals(conn, d1: D1Client) -> int`
  - `card_for_old_questions(conn, telegram, chat_id, reviewer_name: str) -> int`

- [ ] **Step 1: Write the failing tests.**
  - `test_dismiss_marks_d1_done`: asserts a `dismiss` row runs `_MARK_DONE_IN_D1` with its id and becomes `dismissed`.
  - `test_dismiss_d1_down_retries`: `D1Error` leaves the row `dismiss`.
  - `test_asked_edit_flagged`: a changed `updated_at` on an `asked` note updates `note_updated_at`.
  - `test_asked_gone`: an `asked` or `sorting` note missing from D1 becomes `gone`.
  - `test_old_question_gets_one_card`: a `question` row with `card_message_id NULL` gets one card with Dismiss only, and `card_message_id` is set. A second call sends nothing.
- [ ] **Step 2:** Run the tests. Expect a FAIL.
- [ ] **Step 3:** Implement.
  - Add `'asked'` and `'sorting'` to the states that settle checks for edits and deletions.
  - `card_for_old_questions` covers note 5, the live beer note, and any question escalated before this ships. New escalations set `card_message_id` in Task 7, so they never get a second card.
- [ ] **Step 4:** Run the tests. Expect a PASS.
- [ ] **Step 5:** Commit: `Finish dismissals in D1 and card old questions`.

### Task 7: Escalated note chores carry the card header and Dismiss

**Files:**
- Modify: `app/escalation.py` (`announce_escalation` when `source == 'review_note'`)
- Test: `tests/test_escalation.py`

**Interfaces:**
- **Consumes:** `card_text`, `card_buttons(note_id, can_change=False)` and `age_line` (Task 2).

- [ ] **Step 1:** Write `test_note_escalation_has_card_and_dismiss`. Asserts the text starts with the card header (`"Luke left a note on /:"`, with the fenced body and the age line). It still contains `"The model asks:"`, the run link and the reply-with-a-hint line, and has no Suggestion line. The message is sent with `[("Dismiss", "note:<id>:dismiss")]`, and the `review_notes` row gets `card_message_id` and `card_updated_at`. Also assert that non-note escalations are unchanged (the existing tests stay green).
- [ ] **Step 2:** Run `uv run pytest tests/test_escalation.py -q`. Expect a FAIL.
- [ ] **Step 3:** Implement. Find the note row through the run's chain (`chain_ids`, then `review_notes.run_id`). The card header replaces the raw task text in the message for note chores. Keep the length under `MESSAGE_LIMIT`.
- [ ] **Step 4:** Run the tests. Expect a PASS.
- [ ] **Step 5:** Commit: `Give note escalations the card header and Dismiss`.

### Task 8: The digest names each waiting note, and the README

**Files:**
- Modify: `app/report.py` (a new `notes_waiting_lines`), `app/digest.py:306` (use it), `README.md` (claims table rows for triage, Dismiss and the card)
- Test: `tests/test_digest.py`

**Interfaces:**
- **Produces:** `notes_waiting_lines(conn, reviewer_name: str, now: datetime) -> list[str]`, one line per note in `asked`, `question` or `reported`.

- [ ] **Step 1:** Write `test_digest_lists_waiting_notes`. An `asked` row whose body is "Should we get a beer this weekend", entered 2 days ago, gives exactly `Luke's note on / ("Should we get a beer this w…"), waiting 2 days`. The digest text holds that line. The facts the digest model sees keep only the count, never the words.
- [ ] **Step 2:** Run `uv run pytest tests/test_digest.py -q`. Expect a FAIL.
- [ ] **Step 3:** Implement.
  - The quote is the first 27 characters with whitespace collapsed, plus `…` when cut.
  - "Waiting" is counted from `review_notes.updated_at`.
  - Use `1 day` and `N days`, and `today` for under a day.
- [ ] **Step 4:** Run the whole suite: `uv run pytest -q` and `uv run ruff check`. Expect a PASS with no errors. Then fill in the README claims rows.
- [ ] **Step 5:** Commit: `List waiting review notes by name in the digest`.

---

After Task 8: push the branch, open a PR, and have Thomas merge it. Merging runs Deploy, and the PC's compose stack needs a rebuild to pick it up. On the first scheduler tick after the rebuild, note 5 gets its card (Task 6), and Thomas taps Dismiss as the first real test.
