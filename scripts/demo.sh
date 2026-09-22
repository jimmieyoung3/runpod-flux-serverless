#!/usr/bin/env bash
# One-command live demo. Takes the prompt as an argument so you can use whatever
# the room suggests - that is the point, it proves the endpoint is really running.
#
#   ./scripts/demo.sh "a brass diving helmet on a workbench, morning light"
#
# Requires RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID in the environment.
set -euo pipefail

PROMPT="${*:-a brass diving helmet on a workbench, morning light}"
: "${RUNPOD_API_KEY:?export RUNPOD_API_KEY first}"
: "${RUNPOD_ENDPOINT_ID:?export RUNPOD_ENDPOINT_ID first}"

cd "$(dirname "$0")/.."
PY=".venv/bin/python"; [[ -x "$PY" ]] || PY="python3"

echo "── worker state ────────────────────────────────────────"
curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" \
  "https://api.runpod.ai/v2/${RUNPOD_ENDPOINT_ID}/health" \
  | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print("  workers:", d["workers"]); print("  jobs   :", d["jobs"])'

echo
echo "── generating ──────────────────────────────────────────"
echo "  prompt: ${PROMPT}"
echo
"$PY" client/call_endpoint.py "$PROMPT" --out demo-output

echo
echo "── open the image from demo-output/ ────────────────────"
