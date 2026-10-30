#!/bin/bash
cd "$(dirname "$0")"

clear
echo "=================================================================="
echo "🔍 CÔNG CỤ CHẨN ĐOÁN LỖI & CHẠY TRỰC TIẾP BOT (DEBUG MODE)"
echo "=================================================================="
echo "Công cụ này sẽ kiểm tra toàn bộ hệ thống, tìm nguyên nhân bot không"
echo "trả lời, và chạy bot trực tiếp trên màn hình để bạn thử gửi /start."
echo "=================================================================="
echo ""

CURRENT_DIR="$(pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.macfilebot.telegrambot.plist"

# 0. Gỡ bỏ cờ kiểm duyệt bảo mật của macOS
xattr -dr com.apple.quarantine "$CURRENT_DIR" 2>/dev/null
chmod +x *.command 2>/dev/null

# 1. Tìm Python 3
echo "1️⃣ Đang kiểm tra môi trường Python 3..."
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

if [ -z "$PYTHON_PATH" ]; then
    echo "❌ NGUYÊN NHÂN: Máy Mac của bạn CHƯA CÀI PYTHON 3!"
    echo "👉 Đây là lý do bot không chạy được ngầm."
    echo "👉 Vui lòng tải và cài đặt Python 3 miễn phí tại:"
    echo "   https://www.python.org/downloads/"
    echo ""
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

PY_VER=$("$PYTHON_PATH" --version 2>&1)
echo "✅ Đã tìm thấy Python 3: $PYTHON_PATH ($PY_VER)"
echo ""

# 2. Kiểm tra file config.json
echo "2️⃣ Đang kiểm tra cấu hình config.json..."
if [ ! -f "config.json" ]; then
    echo "❌ NGUYÊN NHÂN CHÍNH XÁC: Máy này CHƯA TỪNG CÀI ĐẶT BOT (chưa có file config.json)!"
    echo "👉 Đó là lý do vì sao gửi /start mà bot không trả lời: Vì bot chưa được kết nối với Telegram!"
    echo ""
    read -p "👉 Bạn có muốn TIẾN HÀNH CÀI ĐẶT NGAY BÂY GIỜ không? (Y/n): " RUN_INSTALL
    if [[ ! "$RUN_INSTALL" =~ ^[Nn]$ ]]; then
        echo "🚀 Đang mở trình cài đặt CaiDat.command..."
        sleep 1
        exec ./CaiDat.command
    fi
    echo ""
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

echo "✅ File config.json đã tồn tại."
echo ""

# 3. Kiểm tra kết nối Telegram Bot API & Bot Token
echo "3️⃣ Đang kết nối tới máy chủ Telegram API..."
CHECK_RESULT=$("$PYTHON_PATH" -c "
import json, urllib.request, sys
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    token = cfg.get('bot_token', '').strip()
    if not token:
        print('EMPTY_TOKEN')
        sys.exit(0)
    
    url = f'https://api.telegram.org/bot{token}/getMe'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        if data.get('ok'):
            res = data.get('result', {})
            bot_user = res.get('username', '')
            bot_name = res.get('first_name', '')
            owner = cfg.get('owner_id')
            print(f'OK|{bot_user}|{bot_name}|{owner}')
        else:
            print('INVALID_TOKEN|' + str(data))
except Exception as e:
    print('NET_ERROR|' + str(e))
" 2>/dev/null)

STATUS=$(echo "$CHECK_RESULT" | cut -d'|' -f1)

if [ "$STATUS" = "EMPTY_TOKEN" ]; then
    echo "❌ NGUYÊN NHÂN: Mã Bot Token đang bị để trống trong config.json!"
    echo "👉 Vui lòng chạy lại file 'CaiDat.command' và nhập Bot Token."
    read -p "Nhấn Enter để thoát..."
    exit 1
elif [ "$STATUS" = "INVALID_TOKEN" ]; then
    echo "❌ NGUYÊN NHÂN: Mã Bot Token KHÔNG ĐÚNG hoặc đã bị thu hồi!"
    echo "👉 Hãy mở Telegram chat với @BotFather, tạo bot mới hoặc lấy lại token."
    echo "👉 Sau đó chạy lại file 'CaiDat.command' để nhập lại."
    read -p "Nhấn Enter để thoát..."
    exit 1
elif [ "$STATUS" = "NET_ERROR" ]; then
    echo "⚠️ CẢNH BÁO: Không thể kết nối tới api.telegram.org"
    echo "👉 Hãy kiểm tra kết nối Internet hoặc Wi-Fi trên máy Mac."
    read -p "Nhấn Enter để thoát..."
    exit 1
elif [ "$STATUS" = "OK" ]; then
    BOT_USER=$(echo "$CHECK_RESULT" | cut -d'|' -f2)
    BOT_NAME=$(echo "$CHECK_RESULT" | cut -d'|' -f3)
    BOT_OWNER=$(echo "$CHECK_RESULT" | cut -d'|' -f4)
    
    echo "✅ KẾT NỐI TELEGRAM THÀNH CÔNG!"
    echo "🤖 Tên Bot: $BOT_NAME"
    echo "🔗 Username Bot: @$BOT_USER"
    
    if [ "$BOT_OWNER" != "None" ] && [ -n "$BOT_OWNER" ]; then
        echo "🔒 Trạng thái chủ nhân: Đã khoá cho Telegram ID: $BOT_OWNER"
        echo ""
        echo "⚠️ NẾU BẠN GỬI /start MÀ BOT KHÔNG TRẢ LỜI:"
        echo "Có thể tài khoản Telegram hiện tại của bạn không khớp với ID $BOT_OWNER này!"
        read -p "👉 Bạn có muốn RESET (mở khoá) để bạn gửi /start là nhận luôn không? (y/N): " RESET_CHOICE
        if [[ "$RESET_CHOICE" =~ ^[Yy]$ ]]; then
            "$PYTHON_PATH" -c "
import json
with open('config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)
cfg['owner_id'] = None
cfg['chat_id'] = None
cfg['username'] = ''
with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
print('✅ Đã xoá khoá chủ nhân cũ. Người đầu tiên nhắn /start sẽ trở thành chủ nhân!')
"
        fi
    else
        echo "ℹ️ Trạng thái: Chưa có chủ nhân. Người đầu tiên gửi /start sẽ trở thành chủ nhân duy nhất!"
    fi
fi
echo ""

# 4. Kiểm tra vị trí thư mục (Downloads warning)
echo "4️⃣ Đang kiểm tra vị trí thư mục trên máy Mac..."
if [[ "$CURRENT_DIR" == *"/Downloads"* ]]; then
    echo "⚠️ PHÁT HIỆN LỖI: Thư mục đang nằm trong mục 'Downloads' (Tải về)!"
    echo "👉 Hệ điều hành macOS bảo mật TCC CHẶN các tiến trình chạy ngầm từ thư mục Downloads!"
    echo "👉 Đây là nguyên nhân số 1 khiến bot chạy nền bị tắt ngấm không trả lời."
    echo ""
    read -p "👉 Bạn có muốn tự động chuyển thư mục này sang '$HOME/MacFileBot_Assistant' không? (Y/n): " MOVE_CHOICE
    if [[ ! "$MOVE_CHOICE" =~ ^[Nn]$ ]]; then
        SAFE_DIR="$HOME/MacFileBot_Assistant"
        mkdir -p "$SAFE_DIR"
        cp -R "$CURRENT_DIR/"* "$SAFE_DIR/"
        cd "$SAFE_DIR"
        CURRENT_DIR="$SAFE_DIR"
        echo "✅ Đã chuyển xong sang $CURRENT_DIR!"
        echo "👉 Bạn hãy mở lại file 'KiemTraLoi.command' trong $CURRENT_DIR nhé!"
        read -p "Nhấn Enter để thoát..."
        exit 0
    fi
else
    echo "✅ Vị trí thư mục an toàn: $CURRENT_DIR"
fi
echo ""

# 5. Dừng các tiến trình ngầm cũ để tránh lỗi xung đột (409 Conflict)
echo "5️⃣ Đang dọn dẹp tiến trình cũ để tránh xung đột..."
launchctl unload "$PLIST_PATH" 2>/dev/null
pkill -f "bot.py" 2>/dev/null
sleep 1

# Thiết lập khôi phục chạy ngầm khi thoát
restore_background() {
    echo ""
    echo "------------------------------------------------------------------"
    echo "⚙️ Đang kích hoạt lại chế độ chạy ngầm LaunchAgent..."
    if [ -f "$PLIST_PATH" ]; then
        launchctl load "$PLIST_PATH" 2>/dev/null
        launchctl kickstart -k "gui/$(id -u)/com.macfilebot.telegrambot" 2>/dev/null
        echo "✅ Bot đã được đưa trở lại chế độ chạy ngầm liên tục 24/7!"
    fi
    echo "=================================================================="
}
trap restore_background EXIT

echo ""
echo "=================================================================="
echo "🚀 ĐANG KHỞI CHẠY BOT TRỰC TIẾP TRÊN MÀN HÌNH NÀY!"
echo "=================================================================="
echo "👉 BƯỚC THỬ NGHIỆM:"
echo "1. Mở ứng dụng Telegram trên điện thoại/máy tính."
echo "2. Tìm kiếm đúng Username: @$BOT_USER"
echo "3. Bấm START hoặc nhắn: /start"
echo ""
echo "👀 TOÀN BỘ HOẠT ĐỘNG VÀ PHẢN HỒI CỦA BOT SẼ IN TRỰC TIẾP BÊN DƯỚI:"
echo "(Nhấn Ctrl + C khi muốn dừng chạy thử)"
echo "------------------------------------------------------------------"
echo ""

"$PYTHON_PATH" bot.py
