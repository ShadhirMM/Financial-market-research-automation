#!/usr/bin/env bash
# Install (or remove) the weekly launchd job on macOS.
#   ./scripts/macos/install-launchd.sh            install / update
#   ./scripts/macos/install-launchd.sh --remove   uninstall (rollback)
set -euo pipefail

LABEL="com.example.market-research"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$TARGET"
  echo "Removed $LABEL. Reports, logs and data are left in place."
  exit 0
fi

[[ -x "$PYTHON" ]] || { echo "Python not found at $PYTHON (create the venv first, see docs/INSTALL.md)"; exit 1; }
(cd "$PROJECT_DIR" && "$PYTHON" -m market_research check) || { echo "Pre-flight check failed; fix config/.env first."; exit 1; }

mkdir -p "$PROJECT_DIR/logs" "$HOME/Library/LaunchAgents"
sed -e "s#__PYTHON__#$PYTHON#g" -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" \
  "$PROJECT_DIR/scripts/macos/$LABEL.plist" > "$TARGET"
plutil -lint "$TARGET"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$TARGET"
echo "Installed $LABEL (Mondays 06:00). Run it now with: launchctl kickstart -k $DOMAIN/$LABEL"
