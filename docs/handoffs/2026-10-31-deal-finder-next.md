# Handoff: OzBargain deal finder, ready to plan (2026-10-31)

## Where things are

A long "workhorse" session across several repos ended with Thomas reviewing the OzBargain deal-finder design. It is
not approved yet. The last open question to him: is "a deal ignored for 7 days counts as a weak 👎" right for how often
he opens Telegram? Everything else in the draft he was happy to leave as is, and grilling it again was judged not worth it
(the main choices were made with him and a builder check followed).

**Next step:** get his yes, or his change to the silence rule. Then:
1. Fix two out-of-date parts of the spec. The "Prerequisite" section says Mercury is stopped on Azure, but it now runs on
   the home PC. The "Constraints" section calls the scheduler an Azure Container Apps Job that exits each tick; at home
   it is a long-running compose service. The "state lives in the database" rule still holds.
2. Commit the spec. It is **untracked** today.
3. Write the implementation plan.

## Artifacts

- Spec (untracked): `docs/superpowers/specs/2026-10-23-deal-finder-design.md`
- Mercury state, outage and fix, open items: `NEXT.md` (untracked by convention, like other repos' NEXT.md)
- Home stack setup and game mode: `C:\Users\thoma\Scripts\README.md`; overlay `local/compose.home.yml`
- Parent plan the feature belongs to: the `mercury-money` repo's plan (phase 2: shopping deals)
- Digest code to mirror for the local-time schedule: `schedule_digest` in `app/scheduler.py`; digest itself in
  `app/digest.py`. `age_days` was added this session in PR #9.

## Done this session (for context, all merged)

- mercury#8 (flights service), mercury#9 (digest result age), flight-finder#1, mercury-studio#1 (change loop v1 plus
  payment follow-ups and `sent_sha`), ludo-electrical#8 (copy-check sync).
- The stack was rebuilt from `main` in `C:\Projects\agent-runs` (WSL path `/mnt/c/Projects/agent-runs`), using
  `docker compose -f docker-compose.yml -f local/compose.home.yml up -d --build`.
- Outage 29–30 Oct: docker.service in WSL was disabled, so Docker only started when something touched its socket. Thomas
  enabled docker.service and containerd.service on 31 Oct. Not yet seen across a Windows restart.

## Things the next agent won't infer

- A plain `up` also starts the base file's local `db`, which the home stack does not use (all services use the Supabase
  pooler). Remove it after a rebuild: `docker compose -f docker-compose.yml -f local/compose.home.yml rm -sf db`.
- Mercury's tests need Linux and Postgres. Run them in WSL against the `mercury-test-db` container (port **55432**,
  user/password `agent`, database `agent_runs_test`):
  `TEST_DATABASE_URL=postgresql://agent:agent@localhost:55432/agent_runs_test UV_PROJECT_ENVIRONMENT=/tmp/<venv> uv run --frozen pytest`.
  Start the container first with `docker start mercury-test-db`, and stop it after.
- The Ollama **cloud free tier hit its monthly limit on 30 Oct**, so `delegate.ps1 -Model cloud` fails until it resets.
  Local qwen3-coder did poorly that day (it invented copy and skipped half a task), so do the work directly or keep
  delegation small. The deal finder makes no model calls, so the limit doesn't affect it.
- Privacy rule from the spec: no deal titles or ratings in the public repo, the public run list at `/`, `/runs`, the
  event stream or the MCP tools.
- Hooks block `git restore .`, `worktree remove --force` and `branch -D`; Thomas runs those himself. In his `!` bash
  commands, use forward slashes in Windows paths.
- Don't push or commit unless he asks; merging the PRs was his explicit call.

## Other projects touched (each has its own NEXT.md)

- `C:\Projects\mercury-studio`: florist (Elliott, Mornhaven Blooms) waits on his answers. One unpushed NEXT.md commit
  on main. Change loop Task 9 (Cloudflare deploy, migrations 0001–0003) is Thomas's.
- `C:\Projects\ludo-electrical`: local branch `copy-check-sync` was squash-merged and can be deleted.
- `C:\Projects\nextset`: parked by Thomas.
- `C:\Projects\Cheap AI`: decide what to do about the cloud budget.

## Suggested skills

- `superpowers:writing-plans` once the spec is approved.
- `superpowers:test-driven-development`: the repo requires a failing test first.
- `superpowers:verification-before-completion` before claiming anything works.
