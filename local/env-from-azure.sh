#!/usr/bin/env bash
# Copies the keys the stopped Azure apps held into the repo's .env for
# local/compose.home.yml. Prints names only, never values, and skips any key
# .env already has. Needs `az login` to the Mercury subscription.
#
#   bash local/env-from-azure.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1

env_file="$(cd "$(dirname "$0")/.." && pwd)/.env"
touch "$env_file"
# A last line with no newline would swallow the first key added below.
if [ -s "$env_file" ] && [ -n "$(tail -c1 "$env_file")" ]; then echo >> "$env_file"; fi

# KEY app secret-name
secrets="
DATABASE_URL agent-runs-api database-url
TELEGRAM_BOT_TOKEN agent-runs-api telegram-bot-token
TELEGRAM_WEBHOOK_SECRET agent-runs-api telegram-webhook-secret
MODEL_API_KEY agent-runs-worker model-api-key
PAGESPEED_API_KEY agent-runs-worker pagespeed-api-key
"

has() { grep -q "^$1=" "$env_file"; }

while read -r key app secret; do
  [ -n "$key" ] || continue
  if has "$key"; then echo "$key: already in .env"; continue; fi
  value="$(az containerapp secret show -g agent-runs -n "$app" --secret-name "$secret" --query value -o tsv)"
  printf '%s=%s\n' "$key" "$value" >> "$env_file"
  echo "$key: added"
done <<< "$secrets"

# The scheduler Job is the only holder of the Cloudflare token.
if has CLOUDFLARE_D1_TOKEN; then
  echo "CLOUDFLARE_D1_TOKEN: already in .env"
else
  value="$(az containerapp job secret show -g agent-runs -n agent-runs-scheduler --secret-name cloudflare-d1-token --query value -o tsv)"
  printf 'CLOUDFLARE_D1_TOKEN=%s\n' "$value" >> "$env_file"
  echo "CLOUDFLARE_D1_TOKEN: added"
fi

for pair in MODEL=gemini-3.5-flash-lite MAX_RUNS_PER_DAY=40; do
  if has "${pair%%=*}"; then echo "${pair%%=*}: already in .env"; else echo "$pair" >> "$env_file"; echo "${pair%%=*}: added"; fi
done
