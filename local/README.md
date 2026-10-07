# The local rung

Phase 5 of `docs/build-brief-evals.md` gives Mercury a provider called `local`: a 7B model, `qwen2.5-coder:7b`, served by Ollama on a desktop with an RTX 4060 (8 GB). A run on `local` never falls back to a cloud provider, has its own cap of 200 runs a day (`MAX_LOCAL_RUNS_PER_DAY`), and asks Ollama for JSON mode, so every reply parses.

The rung runs only in the local compose stack on that desktop (decision 46). Nothing on the internet points at the machine, and the live deploy on Azure has no `LOCAL_MODEL_URL`, so it refuses any run that names `local`.

## Files

- `Modelfile.base` builds the tag `mercury-local:base` from `qwen2.5-coder:7b` with a 16,384 token context window. Ollama's default window is smaller than a chore prompt and would cut it short without an error. On the 4060 the tag loads 100% on the GPU and uses about 5.75 GB.
- `mercury.compose.yaml` is the Mercury config for the compose stack: the fixture repo only, `auto_approve: true`, no Telegram chat. It holds no secret.
- `compose.local.yml` layers over `docker-compose.yml`, so CI's compose file is unchanged. It mounts that config, points the worker at Ollama through the host gateway, and moves the proxy to port 8001.
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
