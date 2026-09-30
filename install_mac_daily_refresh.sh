#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.gakpuh.classavail.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/class_avail_refresh.log"
UID_NUM="$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
chmod +x "$REPO_DIR/refresh_and_publish_mac.sh"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>$REPO_DIR/refresh_and_publish_mac.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>15</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>

    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID_NUM" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL"

echo "Installed daily class-availability refresh."
echo "Schedule: 7:15 AM local Mac time"
echo "LaunchAgent: $PLIST"
echo "Log: $LOG_FILE"
echo
echo "To test the LaunchAgent manually:"
echo "  launchctl kickstart -k gui/$UID_NUM/$LABEL"
