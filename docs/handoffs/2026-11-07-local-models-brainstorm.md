# Handoff: move Mercury to local models, then fine-tune on chore history (brainstorm in progress)

## What this is and where it stands

Thomas wants Mercury off cloud models and onto models running on his PC (RTX 4060 8 GB, 32 GB RAM, WSL 8 GB). He wants an ongoing loop: pull models from Hugging Face, fine-tune and improve them on Mercury's own history, and keep cloud only for certain tasks. He picked **chores (`repo_chore`) as the first job** and **Mercury history as the training data**. He asked for the work to be on a branch (he typed `/branch`). No branch has been created and no code has been written. This is still the **superpowers:brainstorming** stage, so nothing gets built until he approves a written design.

**Open question to him (unanswered when the session ended):** wait for real chores to build up the history over time, or use cloud models once, on purpose, to create a starting set of training examples (a strong model solving a batch of made-up chores for the small one to learn from)?

## Findings so far (live DB, 2026-11-07)

- 125 `repo_chore` runs, 2026-10-02 to 10-28, none since. 107 succeeded, 13 escalated (10 "tests still failing after 3 attempts", 3 "three unusable replies").
- By source: eval 76, api 27, mcp 15, telegram 4, review_note 2, n8n 1. By repo: mercury-fixture 110, claude-run-cost 11, ludo-electrical 4. Only 14 distinct task texts.
- By provider: gemini 71, ollama (cloud, `gpt-oss:120b`) 54. **The `local` provider has never run a chore.**
- `model_calls` (system, prompt, reply) exists for only 15 chores / 40 calls; recording started late. `steps` and `events` hold the rest. 12 chores have a `hint`, 0 have `needs_claude`, and no saved corrected fixes exist.
- Conclusion given to Thomas: too little and too narrow to fine-tune yet (a few hundred varied examples is the usual bar). Suggested order: (1) move chores to local, (2) score each model against a fixed chore set, (3) save every chore as a training example, including the corrected version when one fails and gets fixed, (4) fine-tune later. QLoRA on the 4060 tops out at roughly 7 to 8B.
- Query scripts used: `C:\Users\thoma\AppData\Local\Temp\claude\eeff386faf75659c\189ed2c0-faaa-481a-bf29-43b37fe7bbf2\scratchpad\q.py` and `q2.py`, run with `docker compose -f docker-compose.yml -f local/compose.home.yml exec -T api python - < <file>` from `/mnt/c/Projects/agent-runs` in WSL. The scratchpad may be gone; they are short and easy to rewrite.

## Things the next agent won't infer

- **The home stack isn't connected to local Ollama.** `PROVIDERS["local"]` in `app/config.py` reads `LOCAL_MODEL_URL`, `LOCAL_MODEL_TOKEN` and `LOCAL_MODEL`. None is set in `.env`, `local/compose.home.yml` or `docker-compose.yml`. Ollama runs on Windows (not in WSL), so containers need a host address to reach it.
- **Installed Ollama models:** `qwen3-coder:30b`, `flint:40b-a2b` (22 GB), `qwen2.5-coder:7b`, `mercury-local:base` (7b with 16K ctx, `local/Modelfile.base`) and `mercury-local:qwen3-30b`. No chat UI is installed (Thomas asked about one; Open WebUI was offered and not decided).
- **Telegram free-text chat** is the `chat` task type, with ladder `[ollama, gemini]` in `local/mercury.home.yaml` and a 20-turn memory (`app/chat.py`). Thomas showed interest in it going local too, but chores come first.
- **Two config copies:** `local/mercury.home.yaml` (gitignored, what the home stack mounts) and the private repo `thomas-whitley/mercury-config` `mercury.yaml`. **A push to mercury-config main triggers an Azure deploy** (Azure is stopped). Use `[skip ci]` in the commit message, as was done today for `deals: enabled: true`.
- **The Ollama cloud free tier** hit its monthly limit on 2026-10-30. Gemini is the remaining cloud rung. The Cheap AI worker shares the same Ollama account.
- **Game mode** shuts WSL down (and with it, all of Mercury). The GPU is shared between gaming, Mercury `local` and any chat use.
- **Tests** need the `mercury-test-db` container. See `docs/handoffs/2026-10-31-deal-finder-next.md`, "Things the next agent won't infer".

## Also done this session (context only, all finished)

- Merged mercury#10 (OzBargain deal finder), rebased local main, enabled deals, rebuilt the stack, and sent a manual roundup. The state is in `NEXT.md` (untracked by convention).
- Pulled all of `C:\Projects`, merged and pushed street-plots, and committed and pushed job-hunt. Leftover: `stash@{0}` in job-hunt, which is redundant (a hook blocks dropping it, so Thomas has to run it himself).
- Local main is 2 commits ahead of origin (the deal-finder handoff, and "NEXT: park research task type") plus this handoff. Not pushed.

## Pointers

- `NEXT.md` (Mercury state and open items), `CLAUDE.md` (providers and ladders: "Models: free providers only")
- `app/config.py` (`PROVIDERS`), `app/chat.py`, `config/mercury.sample.yaml`, `local/compose.home.yml`, `local/Modelfile.base`
- Eval material: `docs/build-brief-evals.md`, plus the `mercury-eval-*` containers (stopped) and the fixture repo `thomas-whitley/mercury-fixture`
- `C:\Projects\Cheap AI\NEXT.md` (model search, cloud budget decision, local qwen3-coder quality notes)

## Next step

Get Thomas's answer to the open question. Carry on the brainstorm until scope is clear (likely sized as a project), then write `docs/superpowers/specs/2026-11-0X-local-models-design.md`, run the builder check, and get his approval. Only after that, create a branch and invoke superpowers:writing-plans.

## Suggested skills

- `superpowers:brainstorming` (resume it; one question per message)
- `superpowers:writing-plans` (after the design is approved)
- `superpowers:using-git-worktrees` (for the branch)
- `claude-api` is not relevant here, since the work is local and Ollama-based
