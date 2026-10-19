#!/bin/zsh
# Update every installed Ora host from this repository's current state.
#   Vibe bodies : every host through the shared installer; claude via its own
#                 plugin CLI
#   Loop        : managed loop installer per installed host
# Usage: scripts/update-hosts.sh [installer-hosts...]   (default: codex zcode minimax hermes qwen)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Vibe bodies -> ${*:-(codex zcode minimax hermes qwen)} =="
python3 - "$@" <<'PY'
import sys
from ora_vibe_coder.installer import install
install(hosts=tuple(sys.argv[1:]) or ("codex", "zcode", "minimax", "hermes", "qwen"))
PY

echo "== Claude plugin (Claude Code updates only through its own CLI) =="
claude plugin update ora-vibe-coder

LOOP=plugins/ora-vibe-coder/resources/programming-loop/scripts/install.py
echo "== Programming Loop -> installed hosts =="
for h in zcode codex claude minimax hermes qwen; do
  python3 "$LOOP" install --host "$h"
done

echo "== Verify loop installations =="
for h in zcode codex claude minimax hermes qwen; do
  if python3 "$LOOP" status --host "$h" 2>/dev/null | grep -q '"mismatches": \[\]'; then
    echo "OK   loop @ $h"
  else
    echo "CHECK loop @ $h"
  fi
done
echo "Done. Restart each host (and Claude Code) to load refreshed skills."
