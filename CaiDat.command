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
echo "• ⚙️ Cài sâu vào hệ thống: Chạy ngầm Native 24/7 (kể cả khi khởi động lại máy)."
echo "=================================================================="
echo ""

# Xoá cờ kiểm duyệt bảo mật com.apple.quarantine của macOS
xattr -dr com.apple.quarantine "$(pwd)" 2>/dev/null
chmod +x *.command *.py 2>/dev/null

# 1. Tìm Python 3
PYTHON_PATH=""
if [ -x "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
elif [ -x "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
elif [ -x "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
elif [ -x "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" ]; then
    PYTHON_PATH="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
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
    echo "❌ Lỗi: Máy Mac của bạn chưa cài Python 3!"
    echo "👉 Vui lòng vào https://www.python.org/downloads/ để tải và cài đặt Python 3 miễn phí."
    echo ""
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

echo "✅ Đã tìm thấy Python: $PYTHON_PATH"
echo ""

# 2. Nhập cấu hình
echo "------------------------------------------------------------------"
echo "📋 BƯỚC 1: CẤU HÌNH BOT TELEGRAM"
echo "⚠️ LƯU Ý QUAN TRỌNG: Mỗi người/máy Mac PHẢI dùng 1 con Bot riêng!"
echo "   (Tạo miễn phí trong 30 giây bằng cách chat /newbot với @BotFather)"
echo "   KHÔNG dùng chung Token của người khác vì sẽ bị khoá bảo mật."
echo "------------------------------------------------------------------"

EXISTING_TOKEN=""
EXISTING_KEY=""
EXISTING_FOLDER="PRODUCTION"

TARGET_CONFIG="$HOME/Library/Application Support/MacFileBot/config.json"
if [ -f "$TARGET_CONFIG" ]; then
    EXISTING_TOKEN=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('$TARGET_CONFIG')); print(cfg.get('bot_token',''))" 2>/dev/null)
    EXISTING_KEY=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('$TARGET_CONFIG')); print(cfg.get('gemini_api_key',''))" 2>/dev/null)
    EXISTING_FOLDER=$("$PYTHON_PATH" -c "import json; cfg=json.load(open('$TARGET_CONFIG')); print(cfg.get('default_gdrive_folder','PRODUCTION'))" 2>/dev/null)
elif [ -f "config.json" ]; then
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
    BOT_CHECK=$("$PYTHON_PATH" install_core.py --verify-token "$BOT_TOKEN" 2>/dev/null)
    IS_OK=$("$PYTHON_PATH" -c "import json; data=json.loads('''$BOT_CHECK'''); print('1' if data.get('ok') else '0')" 2>/dev/null)
    
    if [ "$IS_OK" = "1" ]; then
        BOT_USERNAME=$("$PYTHON_PATH" -c "import json; data=json.loads('''$BOT_CHECK'''); print(data['result'].get('username',''))" 2>/dev/null)
        echo "✅ KẾT NỐI THÀNH CÔNG với Bot: @$BOT_USERNAME"
    else
        ERR_MSG=$("$PYTHON_PATH" -c "import json; data=json.loads('''$BOT_CHECK'''); print(data.get('error','Lỗi không xác định'))" 2>/dev/null)
        echo "❌ Lỗi: $ERR_MSG"
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

echo ""
echo "⚙️ Đang cài đặt sâu vào hệ thống (~/Library/Application Support/MacFileBot)..."
INSTALL_OUTPUT=$("$PYTHON_PATH" install_core.py "$BOT_TOKEN" "$GEMINI_KEY" "$GDRIVE_FOLDER")

IS_SUCCESS=$("$PYTHON_PATH" -c "import json; data=json.loads('''$INSTALL_OUTPUT'''); print('1' if data.get('ok') else '0')" 2>/dev/null)

if [ "$IS_SUCCESS" != "1" ]; then
    ERR_DETAIL=$("$PYTHON_PATH" -c "import json; data=json.loads('''$INSTALL_OUTPUT'''); print(data.get('error','Lỗi không xác định'))" 2>/dev/null)
    echo "❌ LỖI CÀI ĐẶT: $ERR_DETAIL"
    read -p "Nhấn Enter để thoát..."
    exit 1
fi

TARGET_DIR=$("$PYTHON_PATH" -c "import json; data=json.loads('''$INSTALL_OUTPUT'''); print(data.get('target_dir',''))" 2>/dev/null)
FOLDER_NAME=$("$PYTHON_PATH" -c "import json; data=json.loads('''$INSTALL_OUTPUT'''); print(data.get('folder',''))" 2>/dev/null)

echo ""
echo "=================================================================="
echo "🎉 CHÚC MỪNG! ĐÃ CÀI ĐẶT THÀNH CÔNG TRỢ LÝ QUẢN LÝ FILE MAC! 🎉"
echo "=================================================================="
echo "📍 Vị trí cài đặt an toàn: $TARGET_DIR"
echo "📁 Thư mục upload Google Drive: $FOLDER_NAME"
echo "⚙️ Dịch vụ đang CHẠY NGẦM NATIVE 24/7 (Kể cả khi tắt máy khởi động lại)."
echo ""
echo "👉 BƯỚC KÍCH HOẠT (DUY NHẤT 1 LẦN):"
echo "1. Mở ứng dụng Telegram trên điện thoại hoặc máy tính."
echo "2. Tìm kiếm đúng con Bot của bạn: @$BOT_USERNAME"
echo "3. Bấm START (hoặc gửi tin nhắn: /start)"
echo "4. Bot sẽ tự động NHẬN DIỆN BẠN LÀ CHỦ NHÂN DUY NHẤT và khoá bảo mật."
echo "=================================================================="
echo ""
read -p "Nhấn Enter để hoàn tất..."
