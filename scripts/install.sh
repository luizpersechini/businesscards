#!/usr/bin/env bash
#
# Install (or update) the Outlook contact-dedupe AppleScript so it
# appears in Outlook's Script menu.
#
# What it does:
#   1. Compiles scripts/dedupe_outlook_contacts.applescript with osacompile.
#   2. Installs the .scpt into Outlook's user-scripts directory:
#        ~/Library/Application Scripts/com.microsoft.Outlook/
#   3. Enables the AppleScript "Show Script menu in menu bar" toggle so
#      the scroll icon appears next to the clock when Outlook is frontmost.
#      (Done via /usr/bin/defaults; equivalent to ticking the checkbox in
#      Script Editor → Preferences → General → "Show Script menu in menu bar".)
#
# Re-run any time the source .applescript changes — it overwrites in place.
#
# Usage:
#   bash scripts/install.sh

set -euo pipefail

# Resolve the directory the script lives in, so it works regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/dedupe_outlook_contacts.applescript"
OUTLOOK_DIR="$HOME/Library/Application Scripts/com.microsoft.Outlook"
DEST="$OUTLOOK_DIR/Dedupe Contacts.scpt"

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: source not found: $SRC" >&2
  exit 1
fi

echo "Source:      $SRC"
echo "Destination: $DEST"
echo

mkdir -p "$OUTLOOK_DIR"

echo "Compiling..."
/usr/bin/osacompile -o "$DEST" "$SRC"

echo "Enabling Script menu in menu bar..."
# This is the macOS-wide "Show Script menu" toggle. When ON, the scroll
# icon appears in the menu bar and shows scripts for the frontmost app
# from its ~/Library/Application Scripts/<bundle-id>/ folder.
/usr/bin/defaults write com.apple.scriptmenu ScriptMenuEnabled -bool true
# Some macOS versions read the toggle from a different key — set both.
/usr/bin/defaults write com.apple.systemuiserver "NSStatusItem Visible com.apple.menuextra.script-menu" -bool true 2>/dev/null || true

echo
echo "Installed."
echo
echo "To run from inside Outlook:"
echo "  1. Switch to Outlook (make it the foreground app)."
echo "  2. Click the scroll icon in the menu bar (top right) — you may need"
echo "     to log out + back in once for the icon to appear after first install."
echo "  3. Choose 'Dedupe Contacts'."
echo
echo "Or run from Terminal any time:"
echo "  osascript \"$DEST\""
echo
echo "Audit log of each run goes to:"
echo "  ~/Desktop/outlook_dedupe_<timestamp>.log"
