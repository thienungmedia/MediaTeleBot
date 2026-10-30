#!/bin/bash
cd "$(dirname "$0")"

clear
echo "=================================================================="
echo "🔄 KIỂM TRA & CẬP NHẬT PHIÊN BẢN MỚI (MAC FILE BOT)"
echo "=================================================================="
echo ""

PYTHON_PATH=""
if [ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PYTHON_PATH="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PYTHON_PATH="/usr/local/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_PATH=$(command -v python3)
fi

"$PYTHON_PATH" updater.py

echo ""
read -p "Nhấn Enter để đóng..."
