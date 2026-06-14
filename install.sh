#!/bin/bash
# Install the daily job digest as a macOS launchd agent
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_NAME="com.jobdigest.daily"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
PLIST_SRC="$INSTALL_DIR/$PLIST_NAME.plist"

echo "==> Install directory: $INSTALL_DIR"

# 1. Check Python
if ! command -v python3 &>/dev/null; then
  echo "[ERROR] python3 not found. Install via: brew install python" >&2
  exit 1
fi
echo "==> Python: $(python3 --version)"

# 2. Create .env from example if missing
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  echo ""
  echo "  !! Created .env from .env.example"
  echo "  !! Open it and set your SMTP_PASS before the first run:"
  echo "     open '$INSTALL_DIR/.env'"
  echo ""
fi

# 3. Create logs dir
mkdir -p "$INSTALL_DIR/logs"

# 4. Make scripts executable
chmod +x "$INSTALL_DIR/run_digest.sh"

# 5. Patch INSTALL_DIR into plist
sed "s|INSTALL_DIR|$INSTALL_DIR|g" "$PLIST_SRC" > "$PLIST_DST"
echo "==> Plist written to: $PLIST_DST"

# 6. Unload if already registered, then load
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load -w "$PLIST_DST"
echo "==> Agent loaded. Will run daily at 08:00."

echo ""
echo "Useful commands:"
echo "  Test now:    bash '$INSTALL_DIR/run_digest.sh'"
echo "  View log:    tail -f '$INSTALL_DIR/logs/digest.log'"
echo "  Uninstall:   launchctl unload '$PLIST_DST' && rm '$PLIST_DST'"
echo ""
echo "Done."
