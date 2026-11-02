-- MacFileBot Manager.applescript
on run
    set myPath to POSIX path of (path to me)
    set parentDir to do shell script "dirname " & quoted form of myPath
    
    set pyPath to do shell script "
    if [ -x '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3' ]; then
        echo '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3'
    elif [ -x '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3' ]; then
        echo '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3'
    elif [ -x '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3' ]; then
        echo '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3'
    elif [ -x '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3' ]; then
        echo '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3'
    elif [ -x '/opt/homebrew/bin/python3' ]; then
        echo '/opt/homebrew/bin/python3'
    elif [ -x '/usr/local/bin/python3' ]; then
        echo '/usr/local/bin/python3'
    elif [ -x '/usr/bin/python3' ]; then
        echo '/usr/bin/python3'
    else
        which python3 2>/dev/null || echo ''
    fi
    "
    
    set coreScript to parentDir & "/install_core.py"
    -- Nếu không có trong parentDir thì kiểm tra trong ~/Library/Application Support/MacFileBot
    set testExist to do shell script "if [ -f " & quoted form of coreScript & " ]; then echo '1'; elif [ -f \"$HOME/Library/Application Support/MacFileBot/install_core.py\" ]; then echo '2'; else echo '0'; fi"
    if testExist is "2" then
        set coreScript to (do shell script "echo \"$HOME/Library/Application Support/MacFileBot/install_core.py\"")
    else if testExist is "0" then
        display alert "❌ Chưa tìm thấy MacFileBot!" message "Bạn hãy chạy ứng dụng 'Cài Đặt MacFileBot.app' trước." as critical
        return
    end if
    
    -- Lấy trạng thái hiện tại (gọi --status-simple, trả về chuỗi trực tiếp)
    set stParsed to do shell script quoted form of pyPath & " " & quoted form of coreScript & " --status-simple"
    set AppleScript's text item delimiters to "|"
    set stItems to text items of stParsed
    set isRunning to item 1 of stItems
    set pidVal to item 2 of stItems
    set folderVal to item 3 of stItems
    set ownerVal to item 4 of stItems
    set AppleScript's text item delimiters to ""
    
    set stText to "🔴 ĐANG DỪNG"
    if isRunning is "True" then
        set stText to "🟢 ĐANG CHẠY NGẦM 24/7 (PID: " & pidVal & ")"
    end if
    
    set menuMsg to "🤖 TRÌNH QUẢN LÝ TRỢ LÝ MAC FILE BOT

" & stText & "
📁 Thư mục Upload Drive: " & folderVal & "
🔒 Chủ nhân: Telegram ID " & ownerVal & "

Chọn thao tác bạn muốn thực hiện:"
    
    set btn1 to "Đổi Thư Mục"
    if isRunning is not "True" then
        set btn1 to "Mở Trợ Năng"
    end if
    
    set userChoice to button returned of (display dialog menuMsg with title "MacFileBot Manager" buttons {btn1, "Kiểm Tra Lỗi", "Khởi Động Lại"} default button "Khởi Động Lại" with icon note)
    
    if userChoice is "Mở Trợ Năng" then
        do shell script "open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
        do shell script "open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'"
    else if userChoice is "Khởi Động Lại" then
        do shell script quoted form of pyPath & " " & quoted form of coreScript & " --restart"
        display dialog "✅ ĐÃ KHỞI ĐỘNG LẠI THÀNH CÔNG!" & return & return & "Dịch vụ đã được nạp lại và đang chạy ngầm 24/7." with title "Khởi Động Lại" buttons {"OK"} default button "OK" with icon note
    else if userChoice is "Kiểm Tra Lỗi" then
        set kiemTraScript to do shell script "
        if [ -f " & quoted form of parentDir & "'/KiemTraLoi.command' ]; then
            echo " & quoted form of parentDir & "'/KiemTraLoi.command'
        elif [ -f \"$HOME/Library/Application Support/MacFileBot/KiemTraLoi.command\" ]; then
            echo \"$HOME/Library/Application Support/MacFileBot/KiemTraLoi.command\"
        elif [ -f \"$HOME/Desktop/Kiểm Tra Lỗi Bot.command\" ]; then
            echo \"$HOME/Desktop/Kiểm Tra Lỗi Bot.command\"
        else
            echo ''
        fi
        "
        if kiemTraScript is not "" then
            do shell script "open -a Terminal " & quoted form of kiemTraScript
        end if
    else if userChoice is "Đổi Thư Mục" then
        try
            set newFolderRes to (display dialog "☁️ ĐỔI THƯ MỤC GOOGLE DRIVE MẶC ĐỊNH
    
Dán LINK hoặc Nhập TÊN thư mục Google Drive:
(Hỗ trợ link thư mục được chia sẻ quyền chỉnh sửa)" default answer folderVal with title "Đổi Thư Mục Upload" buttons {"Huỷ", "Lưu"} default button "Lưu" cancel button "Huỷ" with icon note)
            set newFolder to text returned of newFolderRes
            if newFolder is not "" then
                set changedName to do shell script quoted form of pyPath & " " & quoted form of coreScript & " --set-folder " & quoted form of newFolder
                do shell script quoted form of pyPath & " " & quoted form of coreScript & " --restart"
                display dialog "✅ ĐÃ ĐỔI THƯ MỤC THÀNH CÔNG!" & return & return & "Thư mục upload mới: " & changedName with title "Thành Công" buttons {"OK"} default button "OK" with icon note
            end if
        on error number -128
            -- Người dùng bấm Huỷ: thoát êm ái không báo lỗi
            return
        end try
    end if
end run
