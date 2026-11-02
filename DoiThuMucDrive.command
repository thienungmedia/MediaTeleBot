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

clear
echo "=================================================================="
echo "☁️ CẬP NHẬT THƯ MỤC GOOGLE DRIVE MẶC ĐỊNH ĐỂ UPLOAD"
echo "=================================================================="
echo "Bạn có thể dán LINK hoặc nhập TÊN thư mục Google Drive tại đây."
echo "Hỗ trợ cả thư mục được chia sẻ quyền chỉnh sửa từ chủ nhân/thợ!"
echo "=================================================================="
echo ""

APP_DIR="$HOME/Library/Application Support/MacFileBot"
if [ ! -d "$APP_DIR" ]; then
    APP_DIR="$(pwd)"
fi

CURRENT_INFO=$("$PYTHON_PATH" -c "
import sys
sys.path.insert(0, '$APP_DIR')
import safe_fs
safe_fs.CONFIG_PATH = safe_fs.BASE_DIR / 'config.json'
info = safe_fs.get_default_gdrive_folder_info()
print(info.get('folder_name', 'Chưa cấu hình'))
" 2>/dev/null)

echo "📁 Thư mục hiện tại: $CURRENT_INFO"
echo ""
read -p "👉 Dán LINK Google Drive hoặc nhập TÊN thư mục mới: " NEW_INPUT

if [ -z "$NEW_INPUT" ]; then
    echo "❌ Bạn chưa nhập gì. Giữ nguyên cài đặt cũ."
    read -p "Nhấn Enter để thoát..."
    exit 0
fi

echo ""
echo "⏳ Đang phân tích và kiểm tra thư mục..."
RESULT=$("$PYTHON_PATH" -c "
import sys
sys.path.insert(0, '$APP_DIR')
import safe_fs
safe_fs.CONFIG_PATH = safe_fs.BASE_DIR / 'config.json'
res = safe_fs.set_default_gdrive_folder('''$NEW_INPUT''')
print('NAME|' + str(res.get('folder_name', '')))
print('URL|' + str(res.get('folder_url', '')))
" 2>/dev/null)

NEW_NAME=$(echo "$RESULT" | grep "NAME|" | cut -d'|' -f2)
NEW_URL=$(echo "$RESULT" | grep "URL|" | cut -d'|' -f2)

if [ -n "$NEW_NAME" ]; then
    echo "✅ ĐÃ CẬP NHẬT THÀNH CÔNG!"
    echo "📁 Tên thư mục mới: $NEW_NAME"
    if [ -n "$NEW_URL" ]; then
        echo "🔗 Link Google Drive: $NEW_URL"
    fi
    
    echo ""
    echo "🔄 Đang khởi động lại dịch vụ..."
    if [ -f "$APP_DIR/install_core.py" ]; then
        "$PYTHON_PATH" "$APP_DIR/install_core.py" --restart >/dev/null 2>&1
    else
        launchctl kickstart -k -p "gui/$(id -u)/com.macfilebot.telegrambot" 2>/dev/null
        launchctl kickstart -k -p "gui/$(id -u)/com.thienung.telegramfilebot" 2>/dev/null
    fi
    echo "✅ Bot đã nhận thư mục mới và tiếp tục chạy ngầm!"
else
    echo "❌ Lỗi: Không thể cập nhật thư mục."
fi

echo ""
read -p "Nhấn Enter để hoàn tất..."
