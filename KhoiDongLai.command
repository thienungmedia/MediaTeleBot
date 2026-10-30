#!/bin/bash
cd "$(dirname "$0")"

PLIST_NAME="com.macfilebot.telegrambot"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "🔄 Đang khởi động lại dịch vụ Mac File Bot..."
launchctl kickstart -k "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null
if [ $? -ne 0 ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null
    launchctl load "$PLIST_PATH" 2>/dev/null
fi

echo "✅ Đã khởi động lại thành công!"
sleep 2
