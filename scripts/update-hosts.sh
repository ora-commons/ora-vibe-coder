#!/bin/zsh
# Update every installed Ora host from this repository's current state.
#   Vibe bodies : every host through the shared installer; claude via its own
#                 plugin CLI
#   Loop        : managed loop installer per installed host, except a tool
#                 whose standalone ora-programming-loop entry (public-release
#                 provenance naming the public Loop repository) is already at
#                 the bundled version or newer — that entry is preserved
#                 untouched
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
# The plugin name must be marketplace-qualified or claude reports it not found.
# A failure here is reported but never skips the Loop install and verify steps.
if ! claude plugin update ora-vibe-coder@ora-vibe-coder; then
  echo "WARNING: the Claude plugin update failed; continuing with the remaining steps."
fi

echo "== Programming Loop -> installed hosts =="
python3 - <<'PY'
import subprocess, sys
from pathlib import Path
from ora_vibe_coder.installer import (bundled_loop_version, release_version,
                                      standalone_loop_release)
plugin = Path("plugins/ora-vibe-coder")
loop = plugin / "resources/programming-loop"
bundled = bundled_loop_version(plugin)
for host in ("zcode", "codex", "claude", "minimax", "hermes", "qwen"):
    marker = standalone_loop_release(Path.home(), host)
    found = release_version(marker.get("version")) if marker else None
    if marker and found and bundled and found >= bundled:
        print(f"keep standalone loop @ {host} ({marker.get('version')})")
        continue
    subprocess.run([sys.executable, str(loop / "scripts" / "install.py"), "install", "--host", host],
                   check=True)
PY

echo "== Verify loop installations =="
# The install step's standalone-preservation predicate decides here too: a
# qualifying standalone entry counts as current and preserved even when its
# recorded digests differ (personal edits are the point of preservation).
# Everything else — bundle-installed entries included — keeps the digest
# integrity check.
python3 - <<'PY'
import json, subprocess, sys
from pathlib import Path
from ora_vibe_coder.installer import (bundled_loop_version, release_version,
                                      standalone_loop_release)
plugin = Path("plugins/ora-vibe-coder")
status = plugin / "resources/programming-loop/scripts/install.py"
bundled = bundled_loop_version(plugin)
for host in ("zcode", "codex", "claude", "minimax", "hermes", "qwen"):
    marker = standalone_loop_release(Path.home(), host)
    found = release_version(marker.get("version")) if marker else None
    if marker and found and bundled and found >= bundled:
        print(f"OK   loop @ {host} (preserved standalone {marker.get('version')})")
        continue
    result = subprocess.run([sys.executable, str(status), "status", "--host", host],
                            capture_output=True, text=True)
    try:
        current = json.loads(result.stdout)
    except ValueError:
        current = None
    if isinstance(current, dict) and current.get("mismatches") == []:
        print(f"OK   loop @ {host}")
    else:
        print(f"CHECK loop @ {host}")
PY
echo "Done. Restart each host (and Claude Code) to load refreshed skills."
