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

# 1. Tìm Python 3
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
    echo "❌ Lỗi: Máy của bạn chưa cài Python 3!"
    echo "👉 Vui lòng vào https://www.python.org/downloads/ để tải và cài đặt Python 3 (hoặc cài qua Homebrew: brew install python3)."
    echo ""
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

echo "✅ Đã tìm thấy Python: $PYTHON_PATH"
echo ""

# 2. Nhập cấu hình
CURRENT_DIR="$(pwd)"
PLIST_NAME="com.macfilebot.telegrambot"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "------------------------------------------------------------------"
echo "📋 BƯỚC 1: CẤU HÌNH BOT TELEGRAM"
echo "(Xem hướng dẫn chi tiết cách tạo bot trong file README.md)"
echo "------------------------------------------------------------------"

EXISTING_TOKEN=""
EXISTING_KEY=""
EXISTING_FOLDER="PRODUCTION"

if [ -f "config.json" ]; then
    EXISTING_TOKEN=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('config.json')); print(cfg.get('bot_token',''))" 2>/dev/null)
    EXISTING_KEY=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('config.json')); print(cfg.get('gemini_api_key',''))" 2>/dev/null)
    EXISTING_FOLDER=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('config.json')); print(cfg.get('default_gdrive_folder','PRODUCTION'))" 2>/dev/null)
fi

PROMPT_TOKEN="Nhập mã Bot Token Telegram"
if [ -n "$EXISTING_TOKEN" ]; then
    PROMPT_TOKEN="$PROMPT_TOKEN [Enter để giữ cũ: ${EXISTING_TOKEN:0:10}...]"
fi
read -p "$PROMPT_TOKEN: " INPUT_TOKEN
BOT_TOKEN="${INPUT_TOKEN:-$EXISTING_TOKEN}"

while [ -z "$BOT_TOKEN" ]; do
    echo "⚠️ Bot Token là bắt buộc để bot có thể hoạt động!"
    read -p "Vui lòng nhập Bot Token: " BOT_TOKEN
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

echo ""
echo "------------------------------------------------------------------"
echo "☁️ BƯỚC 3: THƯ MỤC GOOGLE DRIVE MẶC ĐỊNH ĐỂ TỰ ĐỘNG UPLOAD"
echo "------------------------------------------------------------------"
read -p "Tên thư mục trên Drive [Mặc định: $EXISTING_FOLDER]: " INPUT_FOLDER
GDRIVE_FOLDER="${INPUT_FOLDER:-$EXISTING_FOLDER}"

# Tạo config.json
"$PYTHON_PATH" -c "
import json
cfg = {}
try:
    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
except Exception:
    pass

cfg['bot_token'] = '''$BOT_TOKEN'''.strip()
cfg['gemini_api_key'] = '''$GEMINI_KEY'''.strip()
cfg['gemini_model'] = 'gemini-3.1-flash-lite'
cfg['default_gdrive_folder'] = '''$GDRIVE_FOLDER'''.strip()
if 'owner_id' not in cfg:
    cfg['owner_id'] = None
if 'chat_id' not in cfg:
    cfg['chat_id'] = None
if 'last_update_id' not in cfg:
    cfg['last_update_id'] = 0

with open('config.json', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
"

chmod 600 config.json
chmod +x bot.py safe_fs.py nl_engine.py llm_intent.py zalo_sender.py no_delete_guard.py 2>/dev/null

echo ""
echo "⚙️ Đang thiết lập dịch vụ chạy ngầm LaunchAgent cho máy Mac..."
mkdir -p "$HOME/Library/LaunchAgents"

# Dừng dịch vụ cũ nếu có
launchctl unload "$PLIST_PATH" 2>/dev/null

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

launchctl load "$PLIST_PATH"

echo ""
echo "=================================================================="
echo "🎉 CHÚC MỪNG! ĐÃ CÀI ĐẶT THÀNH CÔNG TRỢ LÝ QUẢN LÝ FILE MAC! 🎉"
echo "=================================================================="
echo "Bot đang chạy ngầm trên máy của bạn (kể cả khi khởi động lại máy)."
echo ""
echo "👉 BƯỚC TIẾP THEO (RẤT QUAN TRỌNG):"
echo "1. Mở ứng dụng Telegram trên điện thoại hoặc máy tính."
echo "2. Tìm con bot bạn vừa tạo và gửi tin nhắn: /start"
echo "3. Bot sẽ tự động NHẬN DIỆN BẠN LÀ CHỦ NHÂN DUY NHẤT và khoá bảo mật."
echo "   (Bất kỳ người lạ nào nhắn vào bot sẽ bị từ chối 100%)."
echo ""
echo "💡 NẾU BẠN DÙNG TÍNH NĂNG GỬI ZALO:"
echo "• Vào: Cài đặt hệ thống (System Settings) ➔ Quyền riêng tư & Bảo mật"
echo "  ➔ Trợ năng (Accessibility) ➔ Bật cho Python."
echo "=================================================================="
echo ""
read -p "Nhấn Enter để hoàn tất..."
