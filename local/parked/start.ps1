# Starts Mercury's local rung: Caddy in front of Ollama, then Tailscale
# Funnel to Caddy. The token never leaves this process's environment.
$ErrorActionPreference = 'Stop'
$tokenFile = Join-Path $HOME 'mercury-local-token.txt'
$token = (Get-Content $tokenFile -Raw).Trim()
if ($token.Length -lt 32) { throw "$tokenFile must hold LOCAL_MODEL_TOKEN, at least 32 characters" }
$env:LOCAL_MODEL_TOKEN = $token
Start-Process caddy -ArgumentList 'run', '--config', (Join-Path $PSScriptRoot 'Caddyfile'), '--adapter', 'caddyfile' -WindowStyle Hidden
tailscale funnel --bg 8080
tailscale funnel status
