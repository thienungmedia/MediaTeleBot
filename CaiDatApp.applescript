-- Cài Đặt MacFileBot.applescript
on run
    set myPath to POSIX path of (path to me)
    set parentDir to do shell script "dirname " & quoted form of myPath
    
    -- 1. Tìm Python 3 thực sự hoạt động (kiểm tra chạy thử import sys)
    set pyPath to do shell script "
    for p in '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3' '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3' '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3' '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3' '/Library/Frameworks/Python.framework/Versions/3.10/bin/python3' '/Library/Frameworks/Python.framework/Versions/3.9/bin/python3' '/opt/homebrew/bin/python3' '/usr/local/bin/python3' '/Library/Developer/CommandLineTools/usr/bin/python3' '/usr/bin/python3'; do
        if [ -x \"$p\" ] && \"$p\" -c 'import sys; assert sys.version_info >= (3, 8)' >/dev/null 2>&1; then
            echo \"$p\"
            exit 0
        fi
    done
    echo ''
    "
    
    if pyPath is "" then
        display alert "❌ Chưa tìm thấy Python 3!" message "Máy Mac của bạn cần cài Python 3 để chạy bot." buttons {"Tải Python 3", "Huỷ"} default button "Tải Python 3" as critical
        if button returned of result is "Tải Python 3" then
            open location "https://www.python.org/downloads/"
        end if
        return
    end if
    
    -- 2. Hộp thoại chào mừng
    set welcomeMsg to "🎬 CHÀO MỪNG BẠN ĐẾN VỚI TRỢ LÝ MAC FILE BOT!

Hệ thống sẽ được cài đặt sâu vào máy Mac để chạy ngầm native 24/7 (tự khởi động khi mở máy).

• 🔒 An toàn tuyệt đối: CẤM XOÁ FILE 100%.
• 🔍 Tìm kiếm file khắp ổ cứng ngoài & Google Drive.
• ☁️ Upload lên Google Drive và tự lấy link chia sẻ.
• 💬 Soạn và gửi link qua Zalo tự động.

Nhấn 'Tiếp tục' để bắt đầu thiết lập nhanh trong 1 phút."
    
    try
        display dialog welcomeMsg with title "Cài Đặt MacFileBot" buttons {"Huỷ", "Tiếp tục"} default button "Tiếp tục" cancel button "Huỷ" with icon note
    on error number -128
        return
    end try
    
    -- Tự động tìm thư mục chứa core scripts
    set coreDir to do shell script "
    if [ -f " & quoted form of (parentDir & "/install_core.py") & " ]; then
        echo " & quoted form of parentDir & "
    elif [ -f \"$HOME/Library/Application Support/MacFileBot/install_core.py\" ]; then
        echo \"$HOME/Library/Application Support/MacFileBot\"
    elif [ -f '/Library/Application Support/MacFileBot/install_core.py' ]; then
        echo '/Library/Application Support/MacFileBot'
    else
        echo " & quoted form of parentDir & "
    fi
    "
    
    set htmlGuide to coreDir & "/HuongDanLayMa.html"
    set htmlTokenUrl to "file://" & htmlGuide & "#telegram"
    set htmlGeminiUrl to "file://" & htmlGuide & "#gemini"
    set installerScript to coreDir & "/install_core.py"
    
    -- 2.5 Đọc thông tin cấu hình cũ nếu có (gọi --get-config-simple)
    set preToken to ""
    set preGemini to ""
    set preFolder to "PRODUCTION"
    try
        set cfgParsed to do shell script quoted form of pyPath & " " & quoted form of installerScript & " --get-config-simple"
        set AppleScript's text item delimiters to "|"
        set cfgItems to text items of cfgParsed
        set preToken to item 1 of cfgItems
        set preGemini to item 2 of cfgItems
        set preFolder to item 3 of cfgItems
        set AppleScript's text item delimiters to ""
        if preFolder is "" then set preFolder to "PRODUCTION"
    end try

    -- 3. Nhập Bot Token
    set botToken to ""
    repeat while botToken is ""
        set promptToken to "📋 BƯỚC 1/3: DÁN MÃ BOT TOKEN TELEGRAM

Hướng dẫn lấy token bot telegram:
👉 " & htmlTokenUrl & "

(Hoặc bấm nút [Xem Hướng Dẫn] bên dưới để mở ảnh & các bước chi tiết)

Dán mã Bot Token của bạn vào ô dưới:"
        try
            set diagRes to (display dialog promptToken default answer preToken with title "Cài Đặt MacFileBot (Bước 1/3)" buttons {"Xem Hướng Dẫn", "Huỷ", "Tiếp tục"} default button "Tiếp tục" cancel button "Huỷ" with icon note)
        on error number -128
            return
        end try
        set clickedBtn to button returned of diagRes
        if clickedBtn is "Xem Hướng Dẫn" then
            open location htmlTokenUrl
        else
            set botToken to text returned of diagRes
            set botToken to do shell script "echo " & quoted form of botToken & " | tr -d '[:space:]'"
            if botToken is "" then
                display alert "⚠️ Bạn chưa nhập mã Bot Token!" message "Bot Token là bắt buộc để kết nối với Telegram." as warning
            end if
        end if
    end repeat
    
    -- 4. Nhập Gemini API Key
    set geminiKey to ""
    repeat
        set promptGemini to "🤖 BƯỚC 2/3: DÁN MÃ GEMINI API KEY (TÙY CHỌN)

Hướng dẫn lấy mã API:
👉 " & htmlGeminiUrl & "

(Hoặc bấm nút [Xem Hướng Dẫn] bên dưới để mở trang lấy mã)

Dán mã Gemini Key vào ô dưới (hoặc bấm 'Bỏ qua'):"
        try
            set diagKey to (display dialog promptGemini default answer preGemini with title "Cài Đặt MacFileBot (Bước 2/3)" buttons {"Xem Hướng Dẫn", "Bỏ qua", "Tiếp tục"} default button "Tiếp tục" with icon note)
        on error number -128
            return
        end try
        set clickedKeyBtn to button returned of diagKey
        if clickedKeyBtn is "Xem Hướng Dẫn" then
            open location htmlGeminiUrl
        else if clickedKeyBtn is "Bỏ qua" then
            set geminiKey to ""
            exit repeat
        else
            set geminiKey to text returned of diagKey
            set geminiKey to do shell script "echo " & quoted form of geminiKey & " | tr -d '[:space:]'"
            exit repeat
        end if
    end repeat
    
    -- 5. Nhập Google Drive Folder
    try
        set diagFolder to (display dialog "☁️ BƯỚC 3/3: THƯ MỤC GOOGLE DRIVE MẶC ĐỊNH

Dán LINK hoặc Nhập TÊN thư mục Google Drive để tự động upload.
(Hỗ trợ cả link thư mục được chia sẻ quyền chỉnh sửa từ chủ nhân/thợ)

Bấm 'Mặc định' để dùng: PRODUCTION" default answer preFolder with title "Cài Đặt MacFileBot (Bước 3/3)" buttons {"Mặc định", "Tiếp tục"} default button "Tiếp tục" with icon note)
    on error number -128
        return
    end try
    set gdriveFolder to text returned of diagFolder
    if gdriveFolder is "" then
        set gdriveFolder to "PRODUCTION"
    end if
    
    -- 6. Thực hiện cài đặt sâu vào máy qua install_core.py (--install-simple)
    set cmd to quoted form of pyPath & " " & quoted form of installerScript & " --install-simple " & quoted form of botToken & " " & quoted form of geminiKey & " " & quoted form of gdriveFolder
    
    try
        set parsed to do shell script cmd
    on error errMsg
        display alert "❌ Cài đặt thất bại!" message errMsg as critical
        return
    end try
    
    if parsed starts with "ERR|" then
        set errText to text 5 thru -1 of parsed
        display alert "❌ Không thể cài đặt" message errText as critical
        return
    end if
    
    -- 7. Lấy các trường kết quả
    set AppleScript's text item delimiters to "|"
    set resItems to text items of parsed
    set botUser to item 2 of resItems
    set botName to item 3 of resItems
    set gdriveFolderDisplay to item 4 of resItems
    set AppleScript's text item delimiters to ""
    
    -- 7.5 Thông báo thành công (Bot đã chạy ngầm ngay lập tức, không bị chặn bởi bất kỳ bước nào)
    set successMsg to "🎉 CHÚC MỪNG! ĐÃ CÀI ĐẶT & KHỞI CHẠY THÀNH CÔNG!

Trợ lý MacFileBot đã được cài sâu vào hệ thống macOS.
⚙️ Dịch vụ đang CHẠY NGẦM 24/7 (tự chạy lại kể cả khi khởi động lại máy).
📁 Thư mục Google Drive: " & gdriveFolderDisplay & "

👉 BƯỚC KÍCH HOẠT TRÊN TELEGRAM:
1. Mở Telegram tìm con bot: @" & botUser & "
2. Nhắn lệnh: /start
(Bot sẽ phản hồi ngay lập tức!)"

    set finalDlg to (display dialog successMsg with title "Cài Đặt Thành Công" buttons {"Cấp Quyền Zalo (Tuỳ chọn)", "Hoàn tất", "Mở Telegram Ngay"} default button "Mở Telegram Ngay" with icon note)
    set finalBtn to button returned of finalDlg
    if finalBtn is "Mở Telegram Ngay" then
        open location "https://t.me/" & botUser
    else if finalBtn is "Cấp Quyền Zalo (Tuỳ chọn)" then
        do shell script "open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
        do shell script "
        if [ -d '/Library/Frameworks/Python.framework/Versions/Current/Resources/Python.app' ]; then
            open -R '/Library/Frameworks/Python.framework/Versions/Current/Resources/Python.app'
        elif [ -d '/System/Applications/Utilities/Terminal.app' ]; then
            open -R '/System/Applications/Utilities/Terminal.app'
        fi
        "
        open location "https://t.me/" & botUser
    end if
end run
