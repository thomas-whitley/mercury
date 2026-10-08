# Queues a batch of bank chores on the home GPU (decisions 36 and 58 of
# docs/build-brief-evals.md), runs them through the compose Mercury on port
# 8001, exports the training examples, and unloads the model so the GPU is
# free again. Start the compose stack first (local/README.md).
#
#   local\queue-bank.ps1 -Count 10 [-Library <name>]
#
# The tokens come from the repo's .env inside WSL and are never printed.
param(
    [Parameter(Mandatory)][int]$Count,
    [string]$Library = "",
    [string]$Model = "mercury-local:base"
)
$ErrorActionPreference = "Stop"

try {
    Invoke-WebRequest -UseBasicParsing http://localhost:8001/health | Out-Null
} catch {
    Write-Error "The compose Mercury is not up on port 8001. See local/README.md."
}
$pick = if ($Library) { "--library $Library" } else { "" }
# .env may have Windows line endings, which bash would keep in each value.
$inner = "cd /mnt/c/Projects/agent-runs && set -a && . <(tr -d '\r' < .env) && set +a && " +
    "export MERCURY_URL=http://localhost:8001 UV_PROJECT_ENVIRONMENT=`$HOME/.venvs/agent-runs-win && " +
    "uv run python -m bank.run --count $Count $pick; code=`$?; " +
    "uv run python -m bank.export; exit `$code"
wsl -d Ubuntu-24.04 -- bash -lc $inner
$code = $LASTEXITCODE
$body = @{ model = $Model; keep_alive = 0 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:11434/api/generate -Body $body | Out-Null
exit $code
