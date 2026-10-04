#!/usr/bin/env bash
# Runs inside the agent container. Inputs come from env: ZX_PROMPT, ZX_MODEL, ZX_BUDGET_USD,
# ZX_TIMEOUT_S, and either ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN (Claude subscription).
# Everything is written to /out (the only host mount).
set -u
cd /work

# --bare accepts only an API key. With a subscription token, run without it; the container starts
# empty (no CLAUDE.md, hooks, memory or settings), so the run is just as clean.
BARE=()
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then BARE=(--bare); fi

timeout --kill-after=30 "${ZX_TIMEOUT_S:-900}" \
  claude -p "$ZX_PROMPT" \
    "${BARE[@]}" \
    --model "$ZX_MODEL" \
    --output-format stream-json --verbose \
    --dangerously-skip-permissions \
    --no-session-persistence \
    --max-budget-usd "${ZX_BUDGET_USD:-1.50}" \
  > /out/transcript.jsonl 2> /out/stderr.txt
echo $? > /out/exit_code

tar -czf /out/workspace.tar.gz \
  --exclude=node_modules --exclude=.venv --exclude=venv --exclude=__pycache__ \
  --exclude=dist --exclude=build --exclude=.git \
  -C /work .
