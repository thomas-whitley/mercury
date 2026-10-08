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
$pick = if ($Library) { @("--library", $Library) } else { @() }
# withenv.sh loads .env in WSL; --exec keeps any shell from expanding the
# command first. MERCURY_URL is the compose Mercury, not the live one.
$withenv = @("-d", "Ubuntu-24.04", "--exec", "env", "MERCURY_URL=http://localhost:8001",
    "bash", "/mnt/c/Projects/agent-runs/local/withenv.sh", "uv", "run", "python", "-m")
wsl @withenv bank.run --count $Count @pick
$code = $LASTEXITCODE
wsl @withenv bank.export
$body = @{ model = $Model; keep_alive = 0 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:11434/api/generate -Body $body | Out-Null
exit $code
