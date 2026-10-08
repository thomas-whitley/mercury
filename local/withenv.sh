#!/usr/bin/env bash
# Runs a command in WSL from the repo with its .env loaded and the repo's WSL
# virtualenv, for the bank's tools (decision 58 of docs/build-brief-evals.md).
# .env has Windows line endings, which bash would keep in each value. Call it
# with wsl --exec, so no shell expands the command's own $ first:
#
#   wsl -d Ubuntu-24.04 --exec bash /mnt/c/Projects/agent-runs/local/withenv.sh uv run ...
cd /mnt/c/Projects/agent-runs || exit 1
set -a
. <(tr -d '\r' < .env)
set +a
export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/agent-runs-win
# --exec starts no login shell, so uv is not on PATH yet.
export PATH="$HOME/.local/bin:$PATH"
exec "$@"
