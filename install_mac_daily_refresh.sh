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

    <!-- Run once when this LaunchAgent is loaded at login. -->
    <key>RunAtLoad</key>
    <true/>

    <!-- Check every 30 minutes while the user session is running.
         The refresh script exits immediately after one successful update
         has already been recorded for the current Hawaiʻi calendar day. -->
    <key>StartInterval</key>
    <integer>1800</integer>

    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>

    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
</dict>
</plist>
EOF

# Replace any previously installed fixed-time version with the catch-up version.
launchctl bootout "gui/$UID_NUM" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST"
launchctl enable "gui/$UID_NUM/$LABEL"

echo "Installed catch-up class-availability refresh."
echo "Behavior:"
echo "  • checks immediately when the LaunchAgent loads at login"
echo "  • checks every 30 minutes while your Mac user session is running"
echo "  • performs at most one successful refresh per Hawaiʻi calendar day"
echo "  • retries later if an earlier attempt fails"
echo
echo "LaunchAgent: $PLIST"
echo "Log: $LOG_FILE"
echo
echo "To test the LaunchAgent manually:"
echo "  launchctl kickstart -k gui/$UID_NUM/$LABEL"
echo
echo "To force a refresh even if today already succeeded:"
echo "  zsh \"$REPO_DIR/refresh_and_publish_mac.sh\" --force"
