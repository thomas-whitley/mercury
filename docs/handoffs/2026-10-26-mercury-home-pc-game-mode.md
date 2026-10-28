# Handoff: Mercury moved to the home PC, game mode built (2026-10-26)

## What this session was and where it stands

A long multi-project session that ended on **Mercury** (`C:\Projects\agent-runs`, repo thomas-whitley/mercury). Azure was stopped on 2026-10-26 because of cost. Mercury now **runs on the home PC** in Docker inside WSL (Ubuntu-24.04), against the same Supabase database. Telegram works by polling, and `/status` from the bot was confirmed. Game mode is built: desktop shortcuts free WSL's memory for gaming. **The user has not yet clicked the game-mode shortcuts.** That's the immediate open item. The work is on branch `home-compose` (latest `5356f22`, pushed, **not merged to main**).

## In progress / next

1. The user tries "Game mode on", then "Game mode off" (desktop). Both show MessageBox popups, so they can't be tested headless. `Game-Mode-On.ps1` was **edited after I wrote it** (by the user or another session): it now also unloads Windows Ollama models through `localhost:11434`. That's intentional; keep it.
2. After about a day of stable running, merge `home-compose` to main. Merges are blocked for Claude by auto mode, so hand the user a `gh pr merge` command or open a PR.
3. Known follow-up: the scheduler's start can race the api. When the stack restarted at 09:04 UTC, one pass logged "could not create a run … counted as a failure" for each check. Make the scheduler wait for the api to be ready (`local/compose.home.yml` depends on `proxy: service_healthy`, which didn't stop it when proxy wasn't recreated).
4. The flight worker's `API_BASE_URL` and `n8n/issue-to-chore.json` still point at the Azure URL.
5. Review notes Task 9 (the supervised trial) needs a rerun on the home stack. The note from today's trial was closed by hand: PRs #5 and #6 on ludo-electrical were merged, and the scheduler logged "review note 3 merged and marked done".

## Artifacts (open these)

- `C:\Projects\agent-runs\NEXT.md`: current next steps (git-ignored, Project Dashboard note).
- `C:\Projects\agent-runs\docs\handoff.md`, "Cost position": the **real** Azure cost cause, found by another session. Each deploy's first api replica never scaled in, and `GET /mcp` holds a replica. Don't run mercury-config's deploy; it would restart Azure.
- `C:\Projects\agent-runs\local\README.md`, "Running Mercury at home", and `local/compose.home.yml`: the home stack, the `telegram` poller service, and game mode.
- `app/telegram_poll.py` and `tests/test_telegram_poll.py`: the getUpdates-to-`/telegram` forwarder (commit `29fc93f`).
- `local/env-from-azure.sh`: filled `.env` from the stopped Azure apps' secrets. It has been run, and `.env` is complete with 11 keys.
- `local/mercury.home.yaml` (git-ignored): a copy of mercury-config's `mercury.yaml` minus the dead Azure `/health` site.
- `C:\Users\thoma\Scripts\Game-Mode-On.ps1`, `Game-Mode-Off.ps1`, `wsl-nightly-shutdown.ps1` (now skips while Mercury is up).
- `docs/superpowers/plans/2026-10-19-review-notes-chores.md`: Tasks 1–8 done (Task 2 rerun today; results recorded).
- Mercury commits today on main: `6b3f202` (worker no longer wakes for chores awaiting approval), `309f495` (`/resume` takes any schedule name), `5b0dc8c` (uptime User-Agent plus SSRF hardening in `app/checks.py`), `4130d1a` (flight watch, from another session).

## Things you won't infer from the files

- **Docker is in WSL, not Docker Desktop.** `~/.wslconfig` has `vmIdleTimeout=60000`, so WSL and every container die a minute after the last WSL process. The scheduled task **"Mercury keep WSL awake"** (sign-in trigger, `conhost --headless wsl.exe -d Ubuntu-24.04 --exec sleep infinity`) holds it open. Verified healthy 100 s after the last command.
- The old task "WSL keep-alive" (boot, S4U) fails with result 1 and needs admin to change or delete. Left alone.
- Running `wsl.exe ...` from Claude's Bash also starts WSL. If you need to check health without starting WSL, `curl http://localhost:8000/health` from Git Bash works (mirrored networking).
- The API needs `Authorization: Bearer <MERCURY_BEARER_TOKEN>` from `.env`. Never print it. The Mercury MCP server in `~/.claude.json` still points at the dead Azure URL.
- Tests run in WSL: `wsl.exe -e bash -lc 'cd /mnt/c/Projects/agent-runs && docker compose up -d db --wait; UV_PROJECT_ENVIRONMENT=$HOME/.cache/mercury-deps-venv uv run pytest -q -p no:cacheprovider'`. The repo `.venv` is a Linux venv; don't recreate it from Windows.
- Auto mode blocks Claude from merging PRs, bumping deploy pins and closing PRs. The user runs those with `!` commands.
- The user games on this PC. Rejected: the local 4060 model rung (too weak, 2/11 evals, and it uses about 5.75 GB of VRAM). The model searcher session confirmed Ollama cloud `gpt-oss:120b` is still the best free fallback.
- The user wants NEXT.md kept current **without asking** (memory `keep-next-md-current`).
- Peer sessions: "merc dashboard" is designing a Mercury dashboard. I briefed it and asked it not to touch the scheduled tasks or game-mode scripts. "model searcher" is done.

## Other projects touched today (all done)

- ludo-electrical: dependency patch; copy pass PR #6 live (tagline "Melbourne electrician. Licensed, insured, on time."). NEXT.md: test the quote form and Resend delivery.
- job-hunt: RCH offer accepted (start 9 Nov). HR still needs the police check and **2026 flu vaccine evidence**; see `C:\Projects\job-hunt\NEXT.md`. `applications.md` is updated but uncommitted (PLAYBOOK.md has another session's uncommitted edits).

## Suggested skills

- `superpowers:systematic-debugging` if game mode or the home stack misbehaves.
- `superpowers:test-driven-development` for the scheduler startup race fix.
- `superpowers:finishing-a-development-branch` when merging `home-compose`.
