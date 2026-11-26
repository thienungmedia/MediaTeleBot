# MediaTeleBot

Quản lý file sản xuất, Google Drive và lịch qua Telegram. Bot chạy bằng tài khoản của bạn trên máy cần quản lý. Mỗi người cài đặt cần một bot token riêng từ [@BotFather](https://t.me/BotFather).

## Cài đặt

| Máy chủ | Cách cài |
| --- | --- |
| macOS 12 trở lên, Intel và Apple Silicon | Cài Python 3.10+ có Tkinter từ [Python.org](https://www.python.org/downloads/macos/). Dùng gói được ký trong [GitHub Releases](https://github.com/thienungmedia/MediaTeleBot/releases) khi có, hoặc chạy `bash CaiDat.command` từ bản sao mã nguồn. |
| Windows 10/11 | Cài Python 3.10+ có Tkinter từ [Python.org](https://www.python.org/downloads/windows/). Giải nén bản Windows hoặc tải mã nguồn rồi mở `CaiDat-Windows.cmd`. |
| Chạy thủ công | `python3 install_core.py --no-start` để cấu hình, sau đó `python3 bot.py`. Trên Windows, dùng `py -3` thay cho `python3`. |

1. Mở MediaTeleBot, dán bot token vào tab **Cài đặt & ghép cặp**, rồi chọn **Lưu và chạy bot**.
2. Mở chat riêng với bot và gửi lệnh `/pair` kèm mã hiện trên máy trong vòng 15 phút. Nếu mã hết hạn, chọn **Mã ghép cặp mới**.
3. Nhắn `/start` để mở bảng điều khiển. Cài lại bằng cùng token giữ nguyên Telegram ID của chủ. Dùng **Đặt lại chủ** trên máy khi cần đổi chủ.

Bot chạy với LaunchAgent theo người dùng trên Mac và có thể tự chạy khi tài khoản Windows đăng nhập. Máy cần hoạt động và kết nối mạng. Cài đặt ghi vào thư mục riêng của người dùng. Trên macOS, dữ liệu được giữ tại `~/Library/Application Support/MacFileBot` để đọc lại cấu hình cũ. Trên Windows, dữ liệu nằm tại `%LOCALAPPDATA%\MediaTeleBot`. Nút **Dừng bot** cũng tắt chức năng tự chạy khi đăng nhập.

## Tính năng

| Tính năng | macOS | Windows |
| --- | --- | --- |
| Duyệt ổ, tìm file, sao chép và dời | Có | Có |
| Chép vào thư mục đồng bộ Google Drive | Có | Có |
| Phát hiện link Drive từ metadata, kiểm tra và gỡ bản đã tải cục bộ | Tùy phiên bản Drive/File Provider | Lấy link và quản lý cache trong Google Drive trên Windows |
| Lịch bot, Âm lịch Việt Nam, Google Calendar qua Apps Script có khóa | Có | Có |
| Ghi và đọc qua Calendar.app đã chọn | Có | — |
| Gemini để trò chuyện và gợi ý câu lệnh | Có | Có |
| Chụp màn hình, click theo lưới, Vision, chuột/phím, Finder Trash và mở ứng dụng | Có, theo quyền và phiên đăng nhập | — |
| Soạn nội dung Zalo từ link Drive | Có nếu bot tìm được link | Dùng link lấy từ Drive và tự gửi trong Zalo |

- **File:** `/drives`, `/ls <thư mục>`, `/find <từ khóa>`, `/cp <nguồn> -> <đích>`, `/mv <nguồn> -> <đích>`. Bot tạo tên mới khi đích đã tồn tại. Lệnh dời giữa hai ổ sao chép trước rồi mới dọn nguồn.
- **Drive:** Cài và đăng nhập Google Drive for Desktop. Ở tab **Drive, lịch & Gemini**, chọn đúng thư mục Drive khi có nhiều tài khoản. Thêm các thư mục footage cần ưu tiên. Khi bot báo đã chép vào vùng đồng bộ, kiểm tra trạng thái upload và quyền truy cập trên Drive. Trên macOS, bot chỉ tự lấy link khi thấy được cloud ID của chính bản sao.
- **Cộng tác viên:** Từ chat riêng của chủ, dùng `/allow <Telegram ID>` hoặc `/revoke <Telegram ID>`. Chọn rõ các thư mục chia sẻ trong ứng dụng. Cộng tác viên chỉ dùng được `/find <từ khóa>` trong các thư mục đó.
- **Quyền trên Mac:** Cấp Ghi màn hình và Trợ năng cho tiến trình Python mà MediaTeleBot sử dụng. Finder và Calendar có thể cần thêm quyền Automation. Chụp lưới dùng màn hình chính. AI Vision gửi ảnh đến Gemini khi bạn bật tùy chọn tương ứng.
- **Zalo:** Bot soạn sẵn nội dung cho người nhận. Kiểm tra cuộc trò chuyện và gửi trong Zalo.
- **Gemini:** Nhập API key tại máy chủ. Bot hiện gợi ý câu lệnh để bạn kiểm tra trước khi gửi lại. Dùng lệnh trực tiếp nếu không muốn nội dung gửi tới Gemini.

## Lịch

Mặc định, bot lưu sự kiện cục bộ. Trên macOS, nhập đúng tên lịch trong MediaTeleBot để dùng Calendar.app đã cấu hình. Nếu dùng Google Calendar hai chiều trên Mac hoặc Windows, mở `/gcal` và lấy mã Apps Script.

1. Tạo dự án Apps Script mới. Dán mã mà bot cung cấp. Đặt múi giờ dự án giống lịch Google của bạn.
2. Trong MediaTeleBot, chọn **Tạo và sao chép khóa Apps Script**. Lưu khóa đó trong **Project Settings → Script Properties** dưới tên `MEDIATELEBOT_SECRET`.
3. Triển khai Web App với **Execute as Me** và quyền gọi Web App phù hợp để máy chạy bot kết nối. Khóa trong yêu cầu POST bảo vệ thao tác đọc và ghi. Nếu Workspace chặn triển khai, dùng Calendar.app hoặc lịch bot.
4. Nhập URL `/exec` và khóa trong ứng dụng MediaTeleBot. Bấm **Kết nối Apps Script**. Nếu đã từng triển khai mẫu cũ của v1.7.2, tắt deployment cũ trong Google Apps Script.

## Build và kiểm thử

```sh
python3 -m unittest discover -s tests -v
python3 build_pkg.py --unsigned
python3 build_windows.py
```

Gói macOS `--unsigned` dành cho kiểm thử. Phát hành macOS dùng `build_pkg.py --app-identity ... --installer-identity ... --notary-profile ...` trên máy có Developer ID và quyền notarize. Build Windows tạo ZIP có trình cài đặt dùng Python hệ thống. Các gói nằm trong `dist/`.

Cập nhật được phân phối qua [GitHub Releases](https://github.com/thienungmedia/MediaTeleBot/releases). `/update` chỉ kiểm tra phiên bản và mở trang phát hành.
