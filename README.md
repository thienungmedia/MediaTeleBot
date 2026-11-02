<p align="center">
  <img src="assets/logo.jpg" width="160" style="border-radius: 32px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);" alt="MacFileBot Logo">
</p>

<h1 align="center">🎬 MAC FILE BOT - TRỢ LÝ ĐIỀU KHIỂN MAC QUA TELEGRAM</h1>

<p align="center">
  <b>Trợ lý cá nhân thông minh dành cho Creators, Editors & Filmmakers</b><br>
  Điều khiển máy Mac từ xa bằng tiếng Việt tự nhiên qua Telegram: Quản lý footage ổ cứng ngoài, kiểm tra dung lượng, tải lên Google Drive tự lấy link gửi khách, đặt lịch âm/dương công việc, và tự động gửi link qua Zalo.
</p>

<p align="center">
  <a href="https://github.com/thienungmedia/MediaTeleBot/raw/main/MacFileBot_Installer.pkg">
    <img src="https://img.shields.io/badge/📦%20TẢI%20GÓI%20CÀI%20ĐẶT-MacFileBot__Installer.pkg%20(1--Click)-007AFF?style=for-the-badge&logo=apple&logoColor=white" alt="Download PKG">
  </a>
</p>

---

## 🌟 TÍNH NĂNG NỔI BẬT

1. 🔒 **An toàn tuyệt đối (100% NO DELETE):**  
   Hệ thống khóa cứng vĩnh viễn các lệnh xoá (`rm`, `trash`, `unlink`). Bot tuyệt đối không bao giờ xoá file của bạn dưới bất kỳ hình thức nào.
2. 🛡️ **Không bao giờ ghi đè (No Overwrite):**  
   Khi sao chép/dời file trùng tên, bot tự động đổi tên thành `(copy 1)`, `(copy 2)` để bảo toàn 100% dữ liệu gốc.
3. 🔍 **Tìm kiếm thông minh:**  
   Ưu tiên quét nhanh các thư mục làm việc như `Desktop/SOURCE`, ổ cứng ngoài `FILM DATA`, và quét trực tiếp kho lưu trữ Google Drive.
4. ☁️ **Upload Google Drive & Tự động lấy Link chia sẻ:**  
   Chỉ cần nhắn *"Up file X lên drive"*, bot sẽ chép vào thư mục Drive, chờ đồng bộ xong và tự động gửi link chia sẻ trực tiếp về Telegram.
5. 💬 **Tự động gửi Link Drive qua Zalo:**  
   Chỉ cần nhắn *"gửi link X qua cho Hoàng Dựng"*, bot tìm đúng link trên Drive, soạn sẵn tin và hiện nút bấm trên Telegram để bạn duyệt gửi qua Zalo trong 1 giây.
6. 🤖 **Tích hợp Trí tuệ nhân tạo (Gemini AI):**  
   Hiểu ngôn ngữ giao tiếp tiếng Việt tự nhiên, không bắt buộc bạn phải nhớ cú pháp lệnh máy móc.
7. 🔐 **Bảo mật chủ nhân duy nhất (Owner Lock):**  
   Chỉ một mình tài khoản Telegram của bạn có quyền điều khiển. Bất kỳ người lạ nào nhắn vào bot đều bị từ chối 100%.

---

## 📋 MỤC LỤC HƯỚNG DẪN

0. [Yêu cầu quan trọng trước khi sử dụng (Google Drive & Chống Sleep)](#-2-yêu-cầu-quan-trọng-trước-khi-sử-dụng)
1. [Hướng dẫn 1: Cách lấy Telegram Bot Token (1 phút)](#1-cách-lấy-telegram-bot-token-trong-1-phút)
2. [Hướng dẫn 2: Cách lấy Google Gemini API Key miễn phí (1 phút)](#2-cách-lấy-gemini-api-key-miễn-phí)
3. [Hướng dẫn 3: Cài đặt 1-Click trên máy Mac](#3-cài-đặt-1-click-trên-máy-mac)
4. [Hướng dẫn 4: Cấp quyền gửi tin Zalo trên macOS](#4-cấp-quyền-gửi-tin-nhắn-zalo-trên-macos)
5. [Cẩm nang câu lệnh mẫu thường dùng](#5-cẩm-nang-câu-lệnh-mẫu-thường-dùng)
6. [Quản lý và Gỡ cài đặt](#6-quản-lý-và-gỡ-cài-đặt)
7. [Cơ chế tự động cập nhật khi có bản mới](#7-cơ-chế-tự-động-cập-nhật-khi-có-bản-mới)

---

## ⚠️ 2 YÊU CẦU QUAN TRỌNG TRƯỚC KHI SỬ DỤNG

Để bot có thể hoạt động trơn tru 24/7 từ xa và thực hiện đầy đủ các tính năng tải file / lấy link Google Drive, máy Mac của bạn cần đáp ứng 2 điều kiện sau:

### 1. ☁️ Bắt buộc cài đặt ứng dụng Google Drive trên máy Mac
Bot quản lý và đồng bộ file trực tiếp thông qua ứng dụng Google Drive chính thức dành cho macOS (để lưu file vào đám mây và tự động lấy link chia sẻ cho khách).

* **Link tải chính thức từ Google:**  
  👉 **[Tải Google Drive cho máy tính (macOS)](https://www.google.com/drive/download/)**  
  *(Tải về file `.dmg`, mở lên và kéo biểu tượng Google Drive vào Applications để cài đặt)*.
* **Sau khi cài đặt:**
  * Mở ứng dụng **Google Drive** và đăng nhập tài khoản Gmail/Google Workspace của bạn.
  * Chọn chế độ đồng bộ (Stream files hoặc Mirror files). Ổ đĩa Google Drive sẽ xuất hiện trên máy Mac của bạn.
  * **Mẹo mục "Được chia sẻ với tôi":** Khi thợ, đối tác hoặc khách hàng gửi link Google Drive cho bạn, bạn chỉ cần bấm mở link đó trên trình duyệt 1 lần là bot sẽ tự động quét và lấy link được bất kỳ lúc nào!

---

### 2. ⚡ Cài đặt máy Mac luôn thức (Chống Sleep 24/7)
Bot hoạt động như một máy chủ dịch vụ cá nhân chạy ngầm trên Mac. **Nếu máy Mac rơi vào trạng thái ngủ (Sleep), CPU và kết nối WiFi sẽ tạm ngắt**, dẫn đến việc khi bạn ở ngoài nhắn tin qua Telegram thì bot sẽ không nhận được lệnh ngay.

Bạn chỉ cần thiết lập để **màn hình vẫn tắt/khoá để tiết kiệm điện và bảo vệ màn hình, nhưng máy Mac vẫn chạy ngầm kết nối mạng**:

#### Cách 1: Thiết lập trực tiếp trong Cài đặt hệ thống (Khuyên dùng - Không cần cài thêm app)
* **Bước 1:** Mở **Cài đặt hệ thống (System Settings)** trên máy Mac.
* **Bước 2:** Vào mục **Màn hình (Displays)** ➔ Bấm vào nút **Nâng cao... (Advanced...)** (nằm ở góc dưới cùng bên phải cửa sổ).
* **Bước 3:** Bật công tắc: **"Ngăn chặn tự động chuyển sang chế độ ngủ khi màn hình tắt"** (*Prevent automatic sleeping when the display is off*).
* **Bước 4 (Tiết kiệm điện/màn hình):** Vào mục **Màn hình khoá (Lock Screen)**:
  * Mục *"Tắt màn hình khi không hoạt động"* (*Turn display off when inactive*): Đặt thời gian tuỳ ý (ví dụ: `15 phút` hoặc `30 phút`).
  * 👉 **Kết quả:** Sau 15-30 phút không dùng, màn hình Mac sẽ tắt đen để nghỉ ngơi và bảo mật, nhưng bot Telegram và WiFi vẫn chạy ngầm 24/7 để bạn điều khiển từ xa bất kỳ lúc nào!
* **Dành riêng cho MacBook:**
  * Cắm dây sạc nguồn nếu muốn máy chạy liên tục khi bạn ra ngoài.
  * Vào mục **Pin (Battery)** ➔ **Tuỳ chọn (Options)** ➔ Bật: **"Đánh thức khi có truy cập mạng"** (*Wake for network access*).

#### Cách 2: Dùng ứng dụng giữ thức máy miễn phí 1-Click
Nếu bạn thích có 1 nút bấm bật/tắt nhanh trên thanh Menu Bar:
* Cài ứng dụng **Amphetamine** (Hoàn toàn miễn phí trên Mac App Store): Giúp giữ máy luôn thức theo ý muốn chỉ với 1 click.
* Hoặc khi cần giữ thức nhanh từ dòng lệnh, bạn chỉ cần mở Terminal gõ: `caffeinate -d` là máy sẽ không bao giờ ngủ.

---

---

## 1. CÁCH LẤY TELEGRAM BOT TOKEN (Trong 1 phút)

Bot Token là "chìa khoá" để kết nối máy Mac với tài khoản Telegram riêng của bạn.

* **Bước 1:** Mở ứng dụng **Telegram** trên điện thoại hoặc máy tính.
* **Bước 2:** Tìm kiếm tài khoản chính thức của Telegram có tên là: `@BotFather` (có dấu tích xanh ✅).
* **Bước 3:** Bấm nút **Start** (hoặc gửi tin nhắn `/start`).
* **Bước 4:** Gửi lệnh:  
  ```text
  /newbot
  ```
* **Bước 5:** BotFather sẽ hỏi tên hiển thị cho bot (Name):  
  * Bạn nhập tên tuỳ thích, ví dụ: `Trợ Lý Mac Của Tôi` hoặc `Mac File Bot`.
* **Bước 6:** BotFather sẽ hỏi Username cho bot (Username):  
  * Username phải là chữ không dấu và **bắt buộc phải kết thúc bằng chữ `bot`**.  
  * Ví dụ: `my_mac_studio_bot` hoặc `thienung_file_bot`.
* **Bước 7:** BotFather sẽ gửi cho bạn một đoạn mã Token có dạng:  
  ```text
  1234567890:ABCdefGhIJKlmNoPQRstuVWXyz123456789
  ```
  👉 **Sao chép (Copy) toàn bộ chuỗi mã này** để dán vào trình cài đặt ở Bước 3.

> ⚠️ **Lưu ý bảo mật:** Giữ kín mã Token này, không gửi cho người lạ.

---

## 2. CÁCH LẤY GEMINI API KEY MIỄN PHÍ

Gemini AI giúp bot hiểu ngôn ngữ tự nhiên hàng ngày (dù bạn nói lẹo từ, dùng tiếng lóng hay trật tự từ đảo lộn). Google cung cấp gói miễn phí hoàn toàn.

* **Bước 1:** Mở trình duyệt web và truy cập vào:  
  👉 **https://aistudio.google.com/apikey**
* **Bước 2:** Đăng nhập bằng tài khoản Google (Gmail) của bạn.
* **Bước 3:** Bấm vào nút màu xanh: **Create API key** (hoặc *Tạo khoá API*).
* **Bước 4:** Chọn project có sẵn hoặc bấm tạo project mới ➔ Bấm **Create key in new project**.
* **Bước 5:** Bấm nút **Copy** để sao chép chuỗi mã API Key (thường bắt đầu bằng `AIzaSy...` hoặc `AQ...`).

---

## 3. CÀI ĐẶT 1-CLICK BẰNG GÓI CHUẨN MACOS (.PKG)

Sau khi đã có **Bot Token** (và Gemini API Key):

1. Tải gói cài đặt:  
   👉 [**MacFileBot_Installer.pkg** (Tải trực tiếp)](https://github.com/thienungmedia/MediaTeleBot/raw/main/MacFileBot_Installer.pkg)
2. Bấm đúp chuột vào file **`MacFileBot_Installer.pkg`** ➔ Chọn **Tiếp tục** ➔ **Cài đặt** (nhập mật khẩu máy Mac nếu được hỏi).
3. Sau khi cài đặt hoàn tất, hộp thoại cấu hình giao diện Apple sẽ tự động bật lên:
   * **Dán Bot Token** bạn vừa lấy ở Bước 1 (có kèm nút *[Xem Hướng Dẫn]* trực quan) ➔ Bấm **Tiếp tục**.
   * **Dán Gemini API Key** ở Bước 2 (hoặc bấm *Bỏ qua* nếu chưa có).
   * **Dán LINK hoặc Nhập tên thư mục Google Drive mặc định** (Hỗ trợ cả link thư mục do chủ dự án chia sẻ quyền chỉnh sửa, ví dụ: `https://drive.google.com/drive/folders/...` hoặc `PRODUCTION`) ➔ Bấm **Tiếp tục**.
4. Hệ thống sẽ tự động cài sâu vào macOS và đăng ký dịch vụ chạy ngầm (`com.macfilebot.telegrambot`).  
   **Từ nay, mỗi khi máy Mac khởi động, bot sẽ tự động chạy ngầm 24/7 mà bạn không cần mở Terminal hay giữ cửa sổ nào!**
5. **KÍCH HOẠT CHỦ NHÂN DUY NHẤT:**
   * Bấm nút **"Mở Telegram Ngay"** trên màn hình cài đặt.
   * Gửi tin nhắn:  
     ```text
     /start
     ```
   * Bot sẽ lập tức phản hồi: `✅ ĐÃ KẾT NỐI VỚI MÁY MAC CỦA BẠN!` và tự động khoá quyền điều khiển cho riêng tài khoản Telegram này.
6. **Ứng dụng quản lý đi kèm:**
   * Trong thư mục **Applications** (Launchpad) của máy sẽ có sẵn **`MacFileBot Manager.app`** để bạn kiểm tra trạng thái đang chạy, đổi thư mục Drive hoặc khởi động lại bot bất cứ lúc nào.

---

## 4. CẤP QUYỀN GỬI TIN NHẮN ZALO TRÊN MACOS

Tính năng gửi Zalo hoạt động bằng cách điều khiển ứng dụng [Zalo.app](file:///Applications/Zalo.app) chính chủ trên Mac (mô phỏng thao tác dán tin nhắn như người thật để bảo vệ an toàn 100% cho tài khoản Zalo của bạn, tránh bị khoá nick như các API lậu).

Để Mac cho phép bot gửi tin:
1. Mở **Cài đặt hệ thống (System Settings)** trên máy Mac.
2. Chọn **Quyền riêng tư & Bảo mật (Privacy & Security)** ➔ **Trợ năng (Accessibility)**.
3. Bấm bật công tắc cho **Python** (hoặc `Terminal`).
4. **Lưu ý:** Ứng dụng Zalo trên máy Mac cần đang mở và đã đăng nhập tài khoản của bạn.

---

## 5. CẨM NANG CÂU LỆNH MẪU THƯỜNG DÙNG

Bạn có thể nhắn tin cho Bot bằng tiếng Việt tự nhiên bất cứ lúc nào:

### 🔍 1. Tìm kiếm file / thư mục
* `tìm thư mục 2510`
* `tìm file test.mp4 trong ổ FILM DATA`
* `tìm clip ofi ngoài desktop`
* `tìm thư mục 2510 trong google drive` *(quét thẳng kho lưu trữ Drive)*

### 📊 2. Kiểm tra dung lượng
* `thư mục 2510 nặng bao nhiêu gb`
* `kiểm tra dung lượng thư mục SOURCE`
* `kiểm tra ổ đĩa` *(xem dung lượng trống các ổ cứng ngoài)*

### ☁️ 3. Upload lên Google Drive
* `up file test.mp4 lên drive`
* `up thư mục 2810 lên google drive cho tôi`  
*(Bot sẽ tự động tải lên thư mục mặc định đã cài đặt, sau khi Drive đồng bộ xong sẽ tự động gửi link chia sẻ về Telegram cho bạn!)*

### 📁 4. Cài đặt & Đổi thư mục upload mặc định (Hỗ trợ DÁN LINK Drive)
* **Dán trực tiếp link Google Drive:**
  * `/setfolder https://drive.google.com/drive/folders/1xRaK_aEWV1D6H3YhalfzQ...`
  * *(Hỗ trợ cả link thư mục được chia sẻ quyền chỉnh sửa từ chủ dự án/thợ)*.
* **Hoặc nhập tên thư mục:**
  * `/setfolder THIEN UNG PRODUCTION`
  * Hoặc nhắn tự nhiên: *"đổi thư mục mặc định thành Fly Cam Ofi"*
* **Xem thư mục đang cài đặt:**
  * `/getfolder` hoặc nhắn: *"thư mục mặc định hiện tại là gì"*
* **Hoặc bấm đúp chuột** vào file `DoiThuMucDrive.command` trong thư mục trợ lý để xem/đổi nhanh chỉ với 1 click!

### 🔗 5. Lấy link Google Drive có sẵn
* `lấy link 2510 huynh trung hiep`
* `xin link thư mục 2810`
* `lấy link flycam ofi` *(tự động tìm cả trong mục "Được chia sẻ với tôi")*

### 💬 6. Gửi link Drive qua Zalo
* `gửi link 2510 huynh trung hiep qua cho Hoàng Dựng`
* `gửi link 2810 cho Hoàng Dựng qua zalo`
* `chia sẻ link 2510 huynh trung hiep qua cho anh Thăng`
* `up file test.mp4 lên drive rồi gửi cho chị Hà qua zalo`  
*(Bot sẽ soạn sẵn tin nhắn, hiện bản xem trước kèm nút bấm `[✅ Gửi Zalo cho ...]`. Bạn chỉ cần bấm nút xác nhận trên Telegram là máy Mac sẽ tự động gửi!)*

### 📂 7. Copy / Dời file trên máy Mac
* `copy thư mục 2510 trong film data ra source ngoài desktop`
* `chuyển clip ofi qua film data`

---

## 6. QUẢN LÝ VÀ GỠ CÀI ĐẶT

Mọi thao tác quản lý đều có sẵn file bấm đúp chuột trong thư mục:

* 🔄 **Khởi động lại bot:** Bấm đúp vào file `KhoiDongLai.command`
* 📁 **Đổi thư mục Drive:** Bấm đúp vào file `DoiThuMucDrive.command`
* 🗑️ **Gỡ bỏ dịch vụ:** Bấm đúp vào file `GoCaiDat.command` (Dừng chạy ngầm và xoá dịch vụ sạch sẽ).

---

## 7. CƠ CHẾ TỰ ĐỘNG CẬP NHẬT KHI CÓ BẢN MỚI

Hệ thống đã tích hợp sẵn cơ chế **Auto-Update** thông minh:

### 👤 Dành cho người sử dụng:
1. **Tự động thông báo qua Telegram:** Mỗi khi tác giả phát hành bản nâng cấp mới, bot sẽ tự động gửi tin nhắn về Telegram:  
   `🔔 PHÁT HIỆN BẢN CẬP NHẬT MỚI: v1.1.0!`  
   kèm nút bấm: `[🚀 Cập nhật lên v1.1.0]`. Bạn chỉ cần **bấm nút**, bot sẽ tự tải code mới và khởi động lại trong 2 giây!
2. **Cập nhật chủ động:** Bạn có thể nhắn tin cho bot bất cứ lúc nào:  
   * `/update` hoặc nhắn: *"cập nhật bot"*, *"kiểm tra cập nhật"*.
3. **Hoặc bấm đúp chuột** vào file: `CapNhat.command` trong thư mục.
4. **An toàn 100%:** Quá trình cập nhật chỉ thay thế các file mã nguồn, **tuyệt đối không chạm vào `config.json`** (giữ nguyên Bot Token, API Key và cấu hình của bạn).

---

### 👨‍💻 Dành cho Tác giả (Khi muốn phát hành bản mới cho tất cả người dùng):
1. Đẩy mã nguồn mới lên repository GitHub (`https://github.com/thienungmedia/MediaTeleBot`).
2. Trong file `version.json`, tăng số phiên bản (ví dụ từ `1.0.0` lên `1.1.0`) và viết ghi chú tính năng mới vào mục `release_notes`.
3. Toàn bộ máy Mac của người dùng đang chạy bot sẽ tự động nhận được thông báo nâng cấp chỉ sau vài phút!

---

Chúc bạn có trải nghiệm làm việc nhẹ nhàng, nhanh chóng và chuyên nghiệp cùng **Mac File Bot**!
