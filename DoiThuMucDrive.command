#!/bin/bash
cd "$(dirname "$0")"

clear
echo "=================================================================="
echo "📁 ĐỔI THƯ MỤC UPLOAD GOOGLE DRIVE MẶC ĐỊNH (MAC FILE BOT)"
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

"$PYTHON_PATH" -c "
import safe_fs
info = safe_fs.get_default_gdrive_folder_info()
shared = ' (Được chia sẻ)' if info.get('is_shared') else ''
print('📌 Thư mục upload hiện tại: ' + str(info['folder_name']) + shared)
if info.get('folder_url'):
    print('🔗 Link Google Drive: ' + str(info['folder_url']))
if info.get('local_path'):
    print('📂 Vị trí trên Mac: ' + str(info['local_path']))
" 2>/dev/null

echo ""
echo "👉 Dán LINK thư mục Google Drive (kể cả link được thợ/chủ dự án chia sẻ)"
echo "   hoặc gõ TÊN thư mục mới:"
read -p "Nhập link hoặc tên thư mục (Enter để giữ nguyên): " NEW_INPUT

if [ -n "$NEW_INPUT" ]; then
    "$PYTHON_PATH" -c "
import safe_fs
res = safe_fs.set_default_gdrive_folder('''$NEW_INPUT''')
shared = ' (Được chia sẻ)' if res.get('is_shared') else ''
print('')
print('✅ ĐÃ CẬP NHẬT THÀNH CÔNG!')
print('📁 Thư mục mới: ' + str(res['folder_name']) + shared)
if res.get('folder_url'):
    print('🔗 Link: ' + str(res['folder_url']))
if res.get('local_path'):
    print('📂 Vị trí: ' + str(res['local_path']))
"
    PLIST_PATH="$HOME/Library/LaunchAgents/com.macfilebot.telegrambot.plist"
    if [ -f "$PLIST_PATH" ]; then
        launchctl kickstart -k "gui/$(id -u)/com.macfilebot.telegrambot" 2>/dev/null
    fi
    PLIST_PATH2="$HOME/Library/LaunchAgents/com.thienung.telegramfilebot.plist"
    if [ -f "$PLIST_PATH2" ]; then
        launchctl kickstart -k "gui/$(id -u)/com.thienung.telegramfilebot" 2>/dev/null
    fi
fi

echo ""
read -p "Bấm Enter để đóng cửa sổ..."
