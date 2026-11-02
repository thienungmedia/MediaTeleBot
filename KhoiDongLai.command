#!/bin/bash
cd "$(dirname "$0")"

PYTHON_PATH=""
if [ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PYTHON_PATH="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PYTHON_PATH="/usr/local/bin/python3"
elif [ -x "/usr/bin/python3" ]; then
    PYTHON_PATH="/usr/bin/python3"
else
    PYTHON_PATH="python3"
fi

echo "🔄 Đang khởi động lại dịch vụ Mac File Bot..."
if [ -f "install_core.py" ]; then
    "$PYTHON_PATH" install_core.py --restart >/dev/null 2>&1
elif [ -f "$HOME/Library/Application Support/MacFileBot/install_core.py" ]; then
    "$PYTHON_PATH" "$HOME/Library/Application Support/MacFileBot/install_core.py" --restart >/dev/null 2>&1
else
    launchctl kickstart -k -p "gui/$(id -u)/com.macfilebot.telegrambot" 2>/dev/null
    launchctl kickstart -k -p "gui/$(id -u)/com.thienung.telegramfilebot" 2>/dev/null
fi

echo "✅ Đã khởi động lại thành công! Dịch vụ đang chạy ngầm 24/7."
sleep 2
