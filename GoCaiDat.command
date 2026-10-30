#!/bin/bash
cd "$(dirname "$0")"

PLIST_NAME="com.macfilebot.telegrambot"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

echo "⚠️ BẠN CÓ CHẮC MUỐN DỪNG VÀ GỠ BỎ DỊCH VỤ MAC FILE BOT?"
read -p "Nhập 'y' để xác nhận gỡ bỏ (hoặc Enter để huỷ): " CONFIRM

if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null
    rm -f "$PLIST_PATH"
    echo "✅ Đã gỡ bỏ dịch vụ chạy ngầm thành công."
    echo "Các file code và config vẫn nằm trong thư mục này nếu bạn muốn cài đặt lại sau."
else
    echo "❌ Đã huỷ thao tác."
fi

sleep 2
