#!/bin/bash
cd "$(dirname "$0")"

clear
echo "=================================================================="
echo "🚀 ĐẨY BẢN CẬP NHẬT LÊN GITHUB (MediaTeleBot)"
echo "Repo: https://github.com/thienungmedia/MediaTeleBot"
echo "=================================================================="
echo ""

git add .
read -p "Nhập nội dung cập nhật (Enter để lấy mặc định 'Update MediaTeleBot'): " MSG
if [ -z "$MSG" ]; then
    MSG="Update MediaTeleBot"
fi
git commit -m "$MSG" 2>/dev/null

echo ""
echo "⏳ Đang đẩy code lên GitHub (nhập tài khoản / token GitHub nếu được hỏi)..."
git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "=================================================================="
    echo "🎉 ĐÃ ĐẨY LÊN GITHUB THÀNH CÔNG!"
    echo "Link xem: https://github.com/thienungmedia/MediaTeleBot"
    echo "=================================================================="
else
    echo ""
    echo "⚠️ Nếu GitHub yêu cầu đăng nhập, bạn có thể chạy lệnh sau trong Terminal:"
    echo "   gh auth login"
    echo "(chọn GitHub.com -> HTTPS -> Login with a web browser)"
fi

echo ""
read -p "Nhấn Enter để đóng..."
