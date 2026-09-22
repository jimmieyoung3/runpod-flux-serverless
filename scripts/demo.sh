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
echo "── opening ─────────────────────────────────────────────"
NEWEST="$(ls -t demo-output/*.png 2>/dev/null | head -1 || true)"
if [[ -n "$NEWEST" ]]; then
  # On WSL, hand the image to the Windows default viewer. explorer.exe always
  # returns a non-zero exit code even on success, hence the `|| true`.
  if command -v explorer.exe >/dev/null && command -v wslpath >/dev/null; then
    explorer.exe "$(wslpath -w "$NEWEST")" >/dev/null 2>&1 || true
    echo "  opened $NEWEST in the Windows viewer"
  else
    echo "  saved $NEWEST"
  fi
else
  echo "  no image produced - check the output above"
fi
