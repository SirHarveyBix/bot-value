#!/usr/bin/env bash
# Génère et charge le LaunchAgent macOS pour démarrer supervisord au boot.
# Usage: bash scripts/install-launchd.sh [-n]
#   -n  Dry-run : affiche le plist sans l'installer

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST=~/Library/LaunchAgents/com.valuemomentum.plist
DRY_RUN=0

while getopts "n" opt; do
    case $opt in
        n) DRY_RUN=1 ;;
        *) echo "Usage: $0 [-n]"; exit 1 ;;
    esac
done

mkdir -p ~/Library/LaunchAgents
mkdir -p "${PROJECT_DIR}/data/logs"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.valuemomentum</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PROJECT_DIR}/venv/bin/supervisord</string>
        <string>-c</string>
        <string>${PROJECT_DIR}/supervisord.conf</string>
        <string>-n</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/data/logs/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/data/logs/launchd_stderr.log</string>
</dict>
</plist>
EOF

echo "Plist généré : $PLIST"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] Plist non chargé."
    cat "$PLIST"
    exit 0
fi

launchctl load "$PLIST"
echo "Service installé. Le scanner démarrera à chaque boot."
echo "Pour désinstaller : launchctl unload $PLIST && rm $PLIST"
