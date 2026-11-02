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

echo "⚠️ BẠN CÓ CHẮC MUỐN DỪNG VÀ GỠ BỎ DỊCH VỤ MAC FILE BOT?"
read -p "Nhập 'y' để xác nhận gỡ bỏ (hoặc Enter để huỷ): " CONFIRM

if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
    if [ -f "install_core.py" ]; then
        "$PYTHON_PATH" install_core.py --uninstall >/dev/null 2>&1
    elif [ -f "$HOME/Library/Application Support/MacFileBot/install_core.py" ]; then
        "$PYTHON_PATH" "$HOME/Library/Application Support/MacFileBot/install_core.py" --uninstall >/dev/null 2>&1
    else
        launchctl bootout "gui/$(id -u)/com.macfilebot.telegrambot" 2>/dev/null
        launchctl unload -w "$HOME/Library/LaunchAgents/com.macfilebot.telegrambot.plist" 2>/dev/null
        rm -f "$HOME/Library/LaunchAgents/com.macfilebot.telegrambot.plist"
    fi
    echo "✅ Đã gỡ bỏ dịch vụ chạy ngầm thành công."
else
    echo "❌ Đã huỷ thao tác."
fi

sleep 2
