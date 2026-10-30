#!/bin/bash
cd "$(dirname "$0")"

clear
echo "=================================================================="
echo "🎬 CÀI ĐẶT TRỢ LÝ QUẢN LÝ FILE MAC QUA TELEGRAM (MAC FILE BOT) 🎬"
echo "=================================================================="
echo "Tính năng nổi bật:"
echo "• 🔒 An toàn tuyệt đối: CẤM XOÁ FILE 100% (bảo vệ footage/source quay)."
echo "• 🔍 Tìm kiếm file/thư mục thông minh khắp ổ cứng ngoài & Google Drive."
echo "• ☁️ Upload lên Google Drive và tự động lấy link chia sẻ gửi khách."
echo "• 💬 Soạn và gửi link qua Zalo tự động (chỉ cần bấm xác nhận)."
echo "• 🤖 Tích hợp AI Gemini hiểu câu nói tiếng Việt tự nhiên."
echo "=================================================================="
echo ""

# 1. Tự động kiểm tra và xử lý nếu chạy trong thư mục Downloads
CURRENT_DIR="$(pwd)"
if [[ "$CURRENT_DIR" == *"/Downloads"* ]]; then
    SAFE_DIR="$HOME/MacFileBot_Assistant"
    echo "⚠️ PHÁT HIỆN: Thư mục đang nằm trong mục 'Downloads' (Tải về)!"
    echo "Hệ điều hành macOS sẽ CHẶN quyền chạy ngầm của các file trong Downloads."
    echo "👉 Đang tự động chuyển sang thư mục an toàn: $SAFE_DIR ..."
    mkdir -p "$SAFE_DIR"
    cp -R "$CURRENT_DIR/"* "$SAFE_DIR/"
    cd "$SAFE_DIR"
    CURRENT_DIR="$SAFE_DIR"
    echo "✅ Đã chuyển vị trí cài đặt thành công: $CURRENT_DIR"
    echo ""
fi

# Xoá cờ kiểm duyệt bảo mật com.apple.quarantine của macOS
xattr -dr com.apple.quarantine "$CURRENT_DIR" 2>/dev/null
chmod +x *.command 2>/dev/null

# 2. Tìm Python 3
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
    echo "❌ Lỗi: Máy Mac của bạn chưa cài Python 3!"
    echo "👉 Vui lòng vào https://www.python.org/downloads/ để tải và cài đặt Python 3 miễn phí."
    echo ""
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

echo "✅ Đã tìm thấy Python: $PYTHON_PATH"
echo ""

# 3. Nhập cấu hình
PLIST_NAME="com.macfilebot.telegrambot"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "------------------------------------------------------------------"
echo "📋 BƯỚC 1: CẤU HÌNH BOT TELEGRAM"
echo "⚠️ LƯU Ý QUAN TRỌNG: Mỗi người/máy Mac PHẢI dùng 1 con Bot riêng!"
echo "   (Tạo miễn phí trong 30 giây bằng cách chat /newbot với @BotFather)"
echo "   KHÔNG dùng chung Token của người khác vì sẽ bị khoá bảo mật."
echo "------------------------------------------------------------------"

EXISTING_TOKEN=""
EXISTING_KEY=""
EXISTING_FOLDER="PRODUCTION"

if [ -f "config.json" ]; then
    EXISTING_TOKEN=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('config.json')); print(cfg.get('bot_token',''))" 2>/dev/null)
    EXISTING_KEY=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('config.json')); print(cfg.get('gemini_api_key',''))" 2>/dev/null)
    EXISTING_FOLDER=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('config.json')); print(cfg.get('default_gdrive_folder','PRODUCTION'))" 2>/dev/null)
fi

BOT_TOKEN=""
BOT_USERNAME=""
while [ -z "$BOT_USERNAME" ]; do
    PROMPT_TOKEN="Nhập mã Bot Token Telegram"
    if [ -n "$EXISTING_TOKEN" ]; then
        PROMPT_TOKEN="$PROMPT_TOKEN [Enter để giữ cũ: ${EXISTING_TOKEN:0:10}...]"
    fi
    read -p "$PROMPT_TOKEN: " INPUT_TOKEN
    BOT_TOKEN="${INPUT_TOKEN:-$EXISTING_TOKEN}"
    BOT_TOKEN="$(echo "$BOT_TOKEN" | tr -d '[:space:]')"

    if [ -z "$BOT_TOKEN" ]; then
        echo "⚠️ Bot Token là bắt buộc để bot có thể hoạt động!"
        continue
    fi

    echo "📡 Đang kiểm tra mã Bot Token với Telegram..."
    BOT_CHECK=$("$PYTHON_PATH" -c "
import urllib.request, json, sys
token = '''$BOT_TOKEN'''.strip()
url = f'https://api.telegram.org/bot{token}/getMe'
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        if data.get('ok'):
            print(data['result'].get('username', ''))
        else:
            sys.exit(1)
except Exception:
    sys.exit(1)
" 2>/dev/null)

    if [ -n "$BOT_CHECK" ]; then
        BOT_USERNAME="$BOT_CHECK"
        echo "✅ KẾT NỐI THÀNH CÔNG với Bot: @$BOT_USERNAME"
    else
        echo "❌ Lỗi: Mã Bot Token không hợp lệ hoặc máy không có mạng!"
        echo "👉 Bạn hãy kiểm tra lại mã Token lấy từ @BotFather (ví dụ: 123456789:ABCdef...)"
        EXISTING_TOKEN=""
    fi
done

echo ""
echo "------------------------------------------------------------------"
echo "🤖 BƯỚC 2: CẤU HÌNH AI GEMINI (TÙY CHỌN)"
echo "(Giúp bot hiểu câu nói tiếng Việt tự nhiên không cần đúng cú pháp)"
echo "------------------------------------------------------------------"
PROMPT_KEY="Nhập Gemini API Key (Enter để bỏ qua nếu chưa có)"
if [ -n "$EXISTING_KEY" ]; then
    PROMPT_KEY="Nhập Gemini API Key [Enter để giữ cũ: ${EXISTING_KEY:0:10}...]"
fi
read -p "$PROMPT_KEY: " INPUT_KEY
GEMINI_KEY="${INPUT_KEY:-$EXISTING_KEY}"
GEMINI_KEY="$(echo "$GEMINI_KEY" | tr -d '[:space:]')"

echo ""
echo "------------------------------------------------------------------"
echo "☁️ BƯỚC 3: THƯ MỤC GOOGLE DRIVE MẶC ĐỊNH ĐỂ TỰ ĐỘNG UPLOAD"
echo "(Dán LINK thư mục Google Drive HOẶC gõ TÊN thư mục)"
echo "• Hỗ trợ cả thư mục được chia sẻ quyền chỉnh sửa từ chủ nhân/thợ!"
echo "• Bấm Enter để dùng mặc định: $EXISTING_FOLDER"
echo "------------------------------------------------------------------"
read -p "Dán Link hoặc Nhập Tên thư mục [Mặc định: $EXISTING_FOLDER]: " INPUT_FOLDER
GDRIVE_FOLDER="${INPUT_FOLDER:-$EXISTING_FOLDER}"

# Tạo config.json và giải phóng owner_id để người cài đặt nhắn /start là nhận làm chủ nhân ngay
"$PYTHON_PATH" -c "
import json, sys
sys.path.append('.')
import safe_fs

cfg = safe_fs._read_json(safe_fs.CONFIG_PATH)
cfg['bot_token'] = '''$BOT_TOKEN'''.strip()
cfg['gemini_api_key'] = '''$GEMINI_KEY'''.strip()
cfg['gemini_model'] = 'gemini-3.1-flash-lite'
cfg['owner_id'] = None
cfg['chat_id'] = None
cfg['username'] = ''
if 'last_update_id' not in cfg:
    cfg['last_update_id'] = 0

safe_fs._write_json(safe_fs.CONFIG_PATH, cfg)

# Cập nhật thư mục upload Google Drive qua hàm phân giải link/tên
res = safe_fs.set_default_gdrive_folder('''$GDRIVE_FOLDER''')
print('📁 Thư mục upload mặc định: ' + str(res.get('folder_name', '''$GDRIVE_FOLDER''')))
if res.get('folder_url'):
    print('🔗 Link Google Drive: ' + str(res['folder_url']))
"

chmod 600 config.json
chmod +x bot.py safe_fs.py nl_engine.py llm_intent.py zalo_sender.py no_delete_guard.py updater.py 2>/dev/null

echo ""
echo "⚙️ Đang thiết lập dịch vụ chạy ngầm LaunchAgent cho máy Mac..."
mkdir -p "$HOME/Library/LaunchAgents"

# Dừng dịch vụ cũ nếu đang chạy
launchctl unload "$PLIST_PATH" 2>/dev/null
pkill -f "${CURRENT_DIR}/bot.py" 2>/dev/null

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${CURRENT_DIR}/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${CURRENT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${CURRENT_DIR}/bot_service.log</string>
    <key>StandardErrorPath</key>
    <string>${CURRENT_DIR}/bot_service.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Library/Frameworks/Python.framework/Versions/3.14/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
        <key>HOME</key>
        <string>${HOME}</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH" 2>/dev/null
launchctl kickstart -k "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null

echo ""
echo "=================================================================="
echo "🎉 CHÚC MỪNG! ĐÃ CÀI ĐẶT THÀNH CÔNG TRỢ LÝ QUẢN LÝ FILE MAC! 🎉"
echo "=================================================================="
echo "Bot đang chạy ngầm trên máy Mac của bạn (kể cả khi khởi động lại máy)."
echo ""
echo "👉 BƯỚC KÍCH HOẠT (RẤT QUAN TRỌNG):"
echo "1. Mở ứng dụng Telegram trên điện thoại hoặc máy tính."
echo "2. Tìm kiếm đúng con Bot của bạn: @$BOT_USERNAME"
echo "3. Bấm START (hoặc gửi tin nhắn: /start)"
echo "4. Bot sẽ tự động NHẬN DIỆN BẠN LÀ CHỦ NHÂN DUY NHẤT và khoá bảo mật."
echo ""
echo "💡 NẾU BẠN GỬI /start MÀ KHÔNG THẤY TRẢ LỜI:"
echo "• Click đúp vào file 'KiemTraLoi.command' trong thư mục này để xem trực tiếp lỗi!"
echo "=================================================================="
echo ""
read -p "Nhấn Enter để hoàn tất..."
