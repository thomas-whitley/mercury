# The local rung

Phase 5 of `docs/build-brief-evals.md` gives Mercury a provider called `local`: a 7B model, `qwen2.5-coder:7b`, served by Ollama on a desktop with an RTX 4060 (8 GB). A run on `local` never falls back to a cloud provider, has its own cap of 200 runs a day (`MAX_LOCAL_RUNS_PER_DAY`), and asks Ollama for JSON mode, so every reply parses.

The rung runs only in the local compose stack on that desktop (decision 46). Nothing on the internet points at the machine, and the live deploy on Azure has no `LOCAL_MODEL_URL`, so it refuses any run that names `local`.

## Files

- `Modelfile.base` builds the tag `mercury-local:base` from `qwen2.5-coder:7b` with a 16,384 token context window. Ollama's default window is smaller than a chore prompt and would cut it short without an error. On the 4060 the tag loads 100% on the GPU and uses about 5.75 GB.
- `mercury.compose.yaml` is the Mercury config for the compose stack: the fixture repo only, `auto_approve: true`, no Telegram chat. It holds no secret.
- `compose.local.yml` layers over `docker-compose.yml`, so CI's compose file is unchanged. It mounts that config, points the worker at Ollama through the host gateway, and moves the proxy to port 8001.
- `compose.home.yml` runs the whole service on that desktop instead of Azure. See "Running Mercury at home" below.
- `parked/` holds a Caddyfile and two scripts for exposing the rung through Tailscale Funnel. They are not used. If the live deploy ever needs the home GPU, the preferred route is Tailscale inside the worker container, which gives the GPU no public address at all.

## Running it

```bash
ollama create mercury-local:base -f local/Modelfile.base
docker compose -f docker-compose.yml -f local/compose.local.yml up -d --build db api proxy worker
MERCURY_URL=http://localhost:8001 uv run python -m evals.runner --columns local --repeats 1
docker compose -f docker-compose.yml -f local/compose.local.yml down
```

The worker needs `MERCURY_GITHUB_TOKEN` and the api `MERCURY_BEARER_TOKEN` in the environment, from the repo's `.env`. The runner closes every pull request and branch it opens on the fixture.

## The first measurement

On 2026-10-07 `mercury-local:base` passed 2 of the 11 eval chores (`evals/results/2026-10-07T1019Z.md`), against 11 for Gemini and 10 for `qwen3-coder:30b`. No reply was unusable. Six chores stayed red after three attempts, one weakened the repo's tests, and three opened a pull request whose hidden grade could not import the name the instruction asked for.

## Running Mercury at home

On 2026-10-26 the Azure apps were stopped and the scheduler Job suspended, because a replica that each deploy started never scaled in and cost about A$1 a day on a pay as you go subscription (`docs/handoff.md`, "Cost position"). `compose.home.yml` is for running the same service on the desktop against the same Supabase database, so that it is up while the PC is on and costs nothing while it is off. It has not been run yet.

Copy the `mercury.yaml` the private config repo deploys to `local/mercury.home.yaml` before the first `up`. Without it Docker creates an empty directory at that path and the services fail to load their config.

```bash
docker compose -f docker-compose.yml -f local/compose.home.yml up -d --build api proxy worker scheduler telegram
docker compose -f docker-compose.yml -f local/compose.home.yml logs -f scheduler
```

The repo's `.env` needs `DATABASE_URL`, the Supabase session pooler string, and `MERCURY_BEARER_TOKEN`. It also needs the keys the Azure deploy held, which are `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `MODEL`, `MODEL_API_KEY`, `OLLAMA_API_KEY`, `MERCURY_GITHUB_TOKEN`, `CLOUDFLARE_D1_TOKEN` and `PAGESPEED_API_KEY`. Azure ran with `MODEL=gemini-3.5-flash-lite` and `MAX_RUNS_PER_DAY=40`. The file names `DATABASE_URL` as required, so that the stack does not quietly use an empty local database. Each service is set to restart with Docker. On this desktop Docker runs inside WSL (Ubuntu-24.04), not Docker Desktop, and `~/.wslconfig` shuts WSL down a minute after its last process exits, containers and all. The Windows scheduled task "Mercury keep WSL awake" holds WSL open from sign in (`conhost --headless wsl.exe -d Ubuntu-24.04 --exec sleep infinity`), which brings Docker and Mercury up with it. The "WSL nightly shutdown" task (03:00) skips the night while Mercury is up.

For gaming, the desktop shortcuts "Game mode on" and "Game mode off" run `Game-Mode-On.ps1` and `Game-Mode-Off.ps1` in `C:\Users\thoma\Scripts`. On asks first if a chore is running, then stops the task and runs `wsl --shutdown`, which frees all of WSL's memory. Off starts the task and waits for `/health`. A forgotten game mode ends at the next sign in.

The scheduler is set to run one pass on start and then one an hour. A pass decides what is due from the database, so the first pass after the PC was off should catch up. Nothing on the internet reaches in, so the `telegram` service pulls the bot's updates with `getUpdates` and posts each one to the api's own `/telegram` with the webhook secret (`app/telegram_poll.py`). Commands and buttons work as they did on Azure. Starting it deletes the Azure webhook, so register the webhook again (`scripts/register-telegram-webhook.sh`) before moving back. claude.ai and the runs page answer only on this PC, at `http://localhost:8000` or `MERCURY_HOME_PORT`. The flight worker runs here too, as the `flights` service, built from `thomas-whitley/flight-finder` cloned beside this repo (`C:\Projects\flight-finder`, or set `FLIGHT_FINDER_DIR`).

Supabase pauses a free project after a week with no activity, so a PC that stays off for more than a week will find the database paused and needs it restored from the Supabase dashboard.

The shared setup that Mercury and Cheap AI both lean on (Ollama on Windows, the GPU, the Ollama cloud free tier, game mode and the WSL tasks) is described once in `C:\Users\thoma\Scripts\README.md`.
