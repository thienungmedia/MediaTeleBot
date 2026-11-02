#!/bin/bash
cd "$(dirname "$0")"

clear
echo "=================================================================="
echo "🔍 CÔNG CỤ CHẨN ĐOÁN LỖI & KIỂM TRA TRẠNG THÁI MAC FILE BOT"
echo "=================================================================="
echo "Công cụ này sẽ kiểm tra dịch vụ chạy ngầm, kết nối Telegram,"
echo "và kiểm tra xem Bot có đang hoạt động 24/7 bình thường hay không."
echo "=================================================================="
echo ""

APP_DIR="$HOME/Library/Application Support/MacFileBot"
if [ ! -d "$APP_DIR" ] || [ ! -f "$APP_DIR/config.json" ]; then
    APP_DIR="$(pwd)"
fi

# 1. Tìm Python 3
echo "1️⃣ Đang kiểm tra môi trường Python 3..."
PYTHON_PATH=""
if [ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
elif [ -x "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
elif [ -x "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PYTHON_PATH="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PYTHON_PATH="/usr/local/bin/python3"
elif [ -x "/usr/bin/python3" ]; then
    PYTHON_PATH="/usr/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_PATH=$(command -v python3)
fi

if [ -z "$PYTHON_PATH" ]; then
    echo "❌ NGUYÊN NHÂN: Máy Mac của bạn CHƯA CÀI PYTHON 3!"
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
CONFIG_FILE="$APP_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ NGUYÊN NHÂN: Máy này CHƯA TỪNG CÀI ĐẶT BOT (chưa có config.json)!"
    echo "👉 Hãy chạy file 'Cài Đặt MacFileBot.app' hoặc 'CaiDat.command' trước."
    echo ""
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

echo "✅ File config.json đã tồn tại tại: $CONFIG_FILE"
echo ""

# 3. Kiểm tra kết nối Telegram Bot API
echo "3️⃣ Đang kiểm tra kết nối với máy chủ Telegram..."
CHECK_RESULT=$("$PYTHON_PATH" -c "
import json, sys
sys.path.insert(0, '$APP_DIR')
import install_core
try:
    with open('$CONFIG_FILE', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    token = cfg.get('bot_token', '').strip()
    res = install_core.verify_telegram_token(token)
    if res.get('ok'):
        b = res['result']
        owner = cfg.get('owner_id')
        print(f'OK|{b.get(\"username\", \"\")}|{b.get(\"first_name\", \"\")}|{owner}')
    else:
        print('ERR|' + str(res.get('error', 'Token không hợp lệ')))
except Exception as e:
    print('NET_ERROR|' + str(e))
" 2>/dev/null)

STATUS=$(echo "$CHECK_RESULT" | cut -d'|' -f1)

if [ "$STATUS" = "OK" ]; then
    BOT_USER=$(echo "$CHECK_RESULT" | cut -d'|' -f2)
    BOT_NAME=$(echo "$CHECK_RESULT" | cut -d'|' -f3)
    BOT_OWNER=$(echo "$CHECK_RESULT" | cut -d'|' -f4)
    echo "✅ KẾT NỐI TELEGRAM THÀNH CÔNG!"
    echo "🤖 Tên Bot: $BOT_NAME (@$BOT_USER)"
    if [ "$BOT_OWNER" != "None" ] && [ -n "$BOT_OWNER" ]; then
        echo "🔒 Trạng thái chủ nhân: Đã khoá cho Telegram ID: $BOT_OWNER"
    else
        echo "ℹ️ Trạng thái: Chưa có chủ nhân. Người đầu tiên gửi /start sẽ nhận làm chủ nhân!"
    fi
else
    ERR_INFO=$(echo "$CHECK_RESULT" | cut -d'|' -f2-)
    echo "⚠️ Lỗi kết nối Telegram: $ERR_INFO"
fi
echo ""

# 4. Kiểm tra dịch vụ chạy ngầm LaunchAgent
echo "4️⃣ Đang kiểm tra dịch vụ chạy ngầm 24/7 của máy Mac..."
UID_VAL=$(id -u)
SVC_CHECK=$(launchctl print "gui/${UID_VAL}/com.macfilebot.telegrambot" 2>&1)
SVC_CHECK2=$(launchctl print "gui/${UID_VAL}/com.thienung.telegramfilebot" 2>&1)

RUNNING=0
PID_VAL=""
if echo "$SVC_CHECK" | grep -q "state = running"; then
    RUNNING=1
    PID_VAL=$(echo "$SVC_CHECK" | grep "pid = " | awk '{print $3}')
elif echo "$SVC_CHECK2" | grep -q "state = running"; then
    RUNNING=1
    PID_VAL=$(echo "$SVC_CHECK2" | grep "pid = " | awk '{print $3}')
fi

if [ $RUNNING -eq 1 ]; then
    echo "🟢 DỊCH VỤ ĐANG CHẠY NGẦM BÌNH THƯỜNG 24/7! (PID: $PID_VAL)"
    echo "Bot đang tự động lắng nghe tin nhắn trên Telegram kể cả khi bạn đóng cửa sổ này."
else
    echo "🔴 Dịch vụ chạy ngầm hiện ĐANG DỪNG hoặc chưa được kích hoạt."
    echo "👉 Đang kích hoạt lại dịch vụ..."
    if [ -f "$APP_DIR/install_core.py" ]; then
        "$PYTHON_PATH" "$APP_DIR/install_core.py" --restart >/dev/null 2>&1
    else
        launchctl kickstart -k -p "gui/${UID_VAL}/com.macfilebot.telegrambot" 2>/dev/null
    fi
    sleep 1
    CHK_AGAIN=$(launchctl print "gui/${UID_VAL}/com.macfilebot.telegrambot" 2>&1)
    if echo "$CHK_AGAIN" | grep -q "state = running"; then
        echo "✅ ĐÃ KÍCH HOẠT THÀNH CÔNG! Bot hiện đang chạy ngầm 24/7."
    else
        echo "ℹ️ Bạn có thể chạy thử trực tiếp bot trên cửa sổ này để xem log."
    fi
fi

echo ""
echo "=================================================================="
read -p "Nhấn Enter để hoàn tất kiểm tra..."
