# Review notes become chores

Date: 2026-10-19. Status: design written, waiting for Thomas to read it.

## Why

Luke's site (the `ludo-electrical` repo, an Astro site deployed as a Cloudflare Worker) has a review mode. Luke opens
a link on his phone, taps part of a page and writes a note. Each note lands in the site's D1 database (`ludo-review`,
table `review_comments`), with the host and page, the text of the element he tapped, any text he highlighted, his
words and a status of `open` or `done`. Today nothing happens until Thomas remembers to ask a Claude session to read
the notes. Thomas wants Mercury to notice each new note and do the work itself, then stop so he can check it before it
goes live.

## What happens to one note

1. An hourly scheduler tick reads the open notes from D1 and finds any Mercury has not seen.
2. Each new note on a live host becomes one `repo_chore` on the site's repo, with source `review_note`. It starts
   without the Telegram Approve tap (decided with Thomas).
3. The free model ladder makes the smallest change that does what the note asks. The site's checks run on the worker
   between attempts, and only a passing change is pushed. A pull request opens, with Luke's exact words at the top of
   its body.
4. The site repo's own GitHub Actions workflow runs the full checks on the pull request. Cloudflare builds a preview
   URL for the branch. Mercury runs Lighthouse on the noted page, on the preview and on the live site.
5. Thomas gets one Telegram message with Luke's note, a short summary of the change, the CI result, the two scores,
   any warnings and the pull request link.
6. Thomas merges, and Cloudflare deploys `main`. On a later tick Mercury sees the merge and marks the note `done` in
   D1, so Luke sees a tick on it. Luke sees nothing else while the work is in progress (decided with Thomas).

A note that is a question, or too vague to act on, changes no code. The model may answer with a question for Thomas
in place of files. The run then ends `escalated` with the reason `the note needs Thomas`, and Telegram carries Luke's
note and the model's question. Thomas answers through the hint path (a Telegram reply or `advise`), which reruns the
chore with his answer. The rerun keeps the source `review_note`, so it gets the same guard, checks, scores and
done marking.

## Goals

- Every open note on a live host becomes a pull request or a question for Thomas with no action from him, and the
  Telegram message arrives within about 3 hours of the note (one to three hourly ticks, the Lighthouse claim window
  and the preview build).
- Nothing reaches the live site without Thomas merging.
- Each pull request changes only what its note asks for.
- The site does not get slower, and does not break, without Thomas being told.

## Anti-goals

Thomas named two ways this fails even when it technically works.

- **Changing things Luke did not ask for.** One note is one chore. The instruction tells the model to make the
  smallest change that does what the note says and to change nothing else. The diff guard refuses changes outside the
  parts of the site a note can be about, and Telegram flags a diff larger than a note should need.
- **Poor performance, of the site and of the work.** The Lighthouse comparison covers the site. The work is covered by
  the checks on the worker gating the push, CI on the pull request, the escalation ladder, and a question in place of
  a guess.

## Non-goals

- Merging automatically, or deploying anything.
- Replying to Luke, or showing him progress beyond the tick at the end.
- Grouping several notes into one chore.
- Any other site, or more than one reviewer.
- Changes to the site's review mode itself.

## Constraints

- The repo rules in `CLAUDE.md` hold. Test first, CI on the stub model, $0 a month idle, secrets only in Actions and
  Container Apps secrets, and no claim in the README ahead of its test.
- The Mercury repo is public. Luke's note text, the Cloudflare account id, the database id, the live hosts and the
  preview hostname pattern live in the private `mercury-config` (its `mercury.yaml` and secrets), never in this repo,
  in a log line or on an unauthenticated endpoint. `GET /runs` and `GET /runs/{id}` show only status fields today
  (`app/run_list.py`), and that must stay true for these runs.
- Note text is untrusted input. Anyone holding Luke's link can write a note. The instruction presents the note as
  quoted data to act on, not as instructions to the model, and the diff guard and Thomas's merge are the real
  controls.
- Free models only, through the chore ladder in `mercury.yaml`, within the 50k tokens per chore and
  `MAX_RUNS_PER_DAY`.

## Decided with Thomas

- Build it inside Mercury, not as a separate tool or a scheduled Claude session.
- The task does the work and opens a pull request. Thomas merging is the only step that changes the live site.
- Chores from notes skip the Approve tap. This is done by their source, not by turning on `auto_approve` for the
  site's repo, so any other chore on that repo still asks.
- The tick on the note is all Luke sees.
- **The worker grows to 1 vCPU and 2 GiB** (from 0.25 vCPU and 0.5 GiB in `infra/main.bicep`), so it can install,
  check, test and build the site. It still scales to zero, so idle cost stays $0. The first trial note measures the
  run time and peak memory, and the README records them with the free grant arithmetic.
- **The site repo gets a GitHub Actions CI workflow** that runs `npm ci`, `npm run check`, `npm run check:worker`,
  `npm test` and `npm run build` on every pull request and every push to `main`. The worker's checks are the gate
  inside the chore. CI is the second check on the pull request, and it also covers pull requests Thomas opens himself.
- **A recorded exception to the phase order.** `docs/build-brief-evals.md` says self started chores wait on Phase 3's
  numbers and on Phase 5, that every self started chore other than dependency bumps and red CI asks for Approve, and
  that Node repos, `ludo-electrical` by name, wait until a Python repo has proven self started chores. Review notes go
  ahead of all three. The reasons are a volume of a few notes a week, Thomas's merge gating every change, and gemini's
  33 of 33 in Phase 3. Phase 4's own findings and its Python first order are unchanged. The first note Mercury handles
  is a supervised trial, watched end to end before the feature is trusted.

## Decided by Claude (Thomas can overrule any of these)

- **Polling, not a push from the site.** The hourly tick reads D1 through the Cloudflare REST API (the D1 query
  endpoint). A push would put Mercury's bearer token on Luke's Cloudflare account.
- **Which notes count.** Only notes whose `host` is in the private config's list of live hosts become chores (today
  the production `workers.dev` host, and `ludoelectrical.com` once it serves the site). A note left on a branch preview
  is listed in the report and never becomes a chore, because it may be about code that is not on `main`. The first of
  the live hosts is the live side of the Lighthouse comparison.
- **Mercury records what it has seen** in its own table, keyed by note id: the note's `updated_at` at the time it was
  read, the run id, the pull request, and a state of `chore`, `question`, `waiting`, `merged`, `closed`, `gone` or
  `preview`. A note already in the table never starts a second chore by itself.
- **The scheduler never waits.** The scheduler Job has a 300 second timeout and the worker has one replica, so each
  hourly tick moves each note one step on (start the chore, look for the preview, queue Lighthouse, read the scores,
  send the message, look for the merge) and returns.
- **The Cloudflare token** is a new secret in `mercury-config`, held by the scheduler alone, with D1 edit permission on
  Luke's account and nothing else. Cloudflare scopes D1 permission to an account, not to one database, so the token
  can reach every D1 database on that account. Today `ludo-review` is the only one. The README says so in those
  words.
- **Node in the image.** The Python stage gains Node 24, the version the site's Cloudflare build uses. The README
  records the image size and the cold start before and after, measured. The site's `test_command` in `mercury.yaml`
  is `npm ci && npm run check && npm test && npm run build`. `check:worker` is left to CI, since the diff guard keeps
  `worker/` out of every note chore. The test timeout becomes a per repo setting in `mercury.yaml`, beside
  `test_command`, defaulting to today's `REPO_TEST_TIMEOUT_SECONDS`.
- **The diff guard.** A chore from a note may change files under `src/pages`, `src/content`, `src/components`,
  `src/layouts`, `src/styles`, `src/assets` and `public/`, and the one file `src/site.config.ts`, which holds the
  phone number, email, ABN and licence number. Anything else (`src/scripts/`, which is review mode, `src/content.config.ts`,
  `worker/`, `migrations/`, `scripts/`, `wrangler.jsonc`, `package.json`, the lock file, `.github/`) is refused as an
  attempt and counts toward the three, so a model that keeps trying escalates with that reason. An escalated note
  chore gets no "Open it anyway" button, because that would open the refused diff without the guard or the checks.
- **The flags in the message.** A diff over 3 files or over 60 changed lines still opens its pull request, but the
  Telegram message leads with a line saying it is larger than a note usually needs. A diff that touches
  `src/site.config.ts` gets its own line naming the fields that changed, because a wrong phone number or licence
  number costs Luke real jobs.
- **The pull request.** Its title is `Luke's note on <page>: <the note's first words>`. Its body starts with Luke's
  note quoted exactly, then the anchor text and quote, then the summary, then the instruction Mercury sent. This
  changes `_open_pull`, which today puts the whole instruction first and takes its first line as the title.
- **The preview URL** is built from a hostname pattern in the private config and the branch name, the way Cloudflare
  names branch previews. Mercury checks the URL answers before it queues Lighthouse. This needs no new GitHub token
  permission. The supervised trial proves the pattern. If no preview answers by the second tick after the pull
  request opened, the message is sent without scores and says so.
- **The Lighthouse comparison.** The page is the note's `page` path. Both checks are queued on the same tick through
  the existing `lighthouse` site check. The two scores are compared only when the same executor ran both, because a
  home score and a PageSpeed score are not comparable. When they ran on different executors, both scores are shown
  with that said. A preview performance score more than 5 points below the live page's is a warning in the message
  and in the pull request body.
- **The CI result** in the message is the site repo's workflow on the pull request's head, read through the existing
  CI watch: green, red with the failing job, or still running.
- **One Telegram message per note.** It is sent when the pull request, its CI result and its scores are ready, or when
  the run asks a question or escalates. Later changes do not send a second message.
- **A daily cap for notes.** At most 10 note chores start in a day, separate from Phase 4's three self started chores.
  Notes over the cap wait for the next day and are listed in the report.
- **Hints.** A note's rerun keeps the source `review_note` (this changes `app/advice.py`, which today keeps the source
  only for `eval` and `bank`). The existing limit of two advised reruns stays, after which the note goes to a Claude
  session as any chore does.
- **After the pull request.** Merged means Mercury sets the note `done` in D1, guarded by `status = 'open'`. Closed
  without merging leaves the note `open` in D1 and marks it `closed` in Mercury, so it is not retried, and the report
  lists it. A note Luke edits after its chore started is not rerun. If its `updated_at` changed before the merge, the
  Telegram message (or, if that was already sent, the report) says Luke edited it. A note that disappears from D1
  (Luke deleted it) is marked `gone`, and any open pull request for it is left for Thomas.
- **The report and the digest.** `report` gains a section for review notes, with each note's state and pull request,
  and the notes left on previews or over the cap. The daily digest gets one line when a note is waiting on Thomas.

## Left to the builder

- The instruction template: how the page path maps to source files (pages under `src/pages`, service copy under
  `src/content/services`), and how the anchor text and quote help the model find the right place.
- How the model's question comes back within the existing full file JSON reply format.
- The migration for the seen notes table, and where the Cloudflare client lives.
- How the scheduler finds the merge (GitHub's pull request state on each tick is enough).
- The CI workflow file in the site repo, following the site's Node 24 build.
- Test structure, with the Cloudflare API and GitHub faked in CI. One end to end trial on the live deploy with a real
  note, which is the supervised trial above, and its numbers in the README.
