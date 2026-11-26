#!/bin/bash
set -e
cd "$(dirname "$0")"
for py in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3)"; do
    if [[ -n "$py" ]] && "$py" -c 'import sys, tkinter; assert sys.version_info >= (3, 10)' 2>/dev/null; then
        exec "$py" install_core.py --gui
    fi
done
echo 'Cài Python từ https://www.python.org/downloads/macos/ rồi chạy lại bộ cài.'
exit 1
