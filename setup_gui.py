"""Local configuration and status UI. Credentials never pass through Telegram."""
from __future__ import annotations

import secrets
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import gcal_bridge
import install_core
from runtime import IS_MAC, edit_config, read_config
import updater


def run() -> None:
    root = tk.Tk()
    root.title("MediaTeleBot")
    root.minsize(560, 510)
    notebook = ttk.Notebook(root)
    notebook.pack(expand=True, fill="both", padx=14, pady=12)
    setup = ttk.Frame(notebook, padding=15)
    integrations = ttk.Frame(notebook, padding=15)
    notebook.add(setup, text="Cài đặt & ghép cặp")
    notebook.add(integrations, text="Drive, lịch & Gemini")
    cfg = read_config()
    status = tk.StringVar(value=f"MediaTeleBot {updater.CURRENT_VERSION}")
    pair_text = tk.StringVar()

    def field(parent, label, row, default="", secret=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        var = tk.StringVar(value=default)
        ttk.Entry(parent, width=35, textvariable=var, show="•" if secret else "").grid(row=row, column=1, sticky="ew", padx=(10, 0))
        parent.columnconfigure(1, weight=1)
        return var

    token = field(setup, "Telegram Bot Token", 0, secret=True)
    gemini = field(setup, "Gemini API Key", 1, secret=True)
    folder = field(setup, "Thư mục upload", 2, cfg.get("default_gdrive_folder") or "MacFileBot Uploads")
    ttk.Label(setup, text="Để trống token hoặc key để giữ giá trị đã lưu.").grid(row=3, columnspan=2, sticky="w")
    ttk.Label(setup, textvariable=status, wraplength=480).grid(row=5, columnspan=2, sticky="w", pady=(16, 6))
    ttk.Entry(setup, textvariable=pair_text, state="readonly").grid(row=6, columnspan=2, sticky="ew")
    ttk.Label(setup, text="Gửi lệnh hiện ở trên trong chat riêng với bot trong vòng 15 phút.", wraplength=470).grid(row=7, columnspan=2, sticky="w")
    buttons = ttk.Frame(setup)
    buttons.grid(row=8, columnspan=2, sticky="w", pady=10)
    tasks_running = False

    def on_success(result, callback):
        nonlocal tasks_running
        tasks_running = False
        status.set("Hoàn tất.")
        if callback:
            callback(result)

    def on_error(message):
        nonlocal tasks_running
        tasks_running = False
        status.set("Thao tác gặp lỗi.")
        messagebox.showerror("MediaTeleBot", message, parent=root)

    def async_action(action, success=None):
        nonlocal tasks_running
        if tasks_running:
            return
        tasks_running = True
        status.set("Đang xử lý…")

        def worker():
            try:
                result = action()
            except Exception as exc:
                message = str(exc) if type(exc) is ValueError else f"Không hoàn tất được thao tác ({type(exc).__name__})."
                root.after(0, on_error, message)
            else:
                root.after(0, on_success, result, success)

        threading.Thread(target=worker, daemon=True).start()

    bot_name = ""

    def show_result(result):
        nonlocal bot_name
        bot_name = result["username"]
        code = result["code"]
        pair_text.set("/pair " + code if code else "")
        status.set(f"Bot @{bot_name}. " + ("Đang chờ ghép cặp." if code else "Đã giữ tài khoản Telegram chủ."))
        token.set("")
        gemini.set("")

    def save(reset=False):
        if reset and not messagebox.askyesno("Đặt lại chủ", "Gỡ quyền Telegram hiện tại và tạo mã ghép cặp mới?", parent=root):
            return
        current = read_config()
        name = folder.get().strip()
        values = (token.get(), gemini.get(), name if name != current.get("default_gdrive_folder") else "")
        async_action(lambda: install_core.install(*values, reset_owner=reset), show_result)

    ttk.Button(setup, text="Lưu và chạy bot", command=save).grid(row=4, column=0, sticky="w", pady=9)
    ttk.Button(setup, text="Mở chat Telegram", command=lambda: webbrowser.open("https://t.me/" + bot_name) if bot_name else None).grid(row=4, column=1, sticky="w")
    ttk.Button(buttons, text="Mã ghép cặp mới", command=lambda: async_action(install_core.new_pairing_code, lambda code: pair_text.set("/pair " + code))).pack(side="left")
    ttk.Button(buttons, text="Đặt lại chủ", command=lambda: save(True)).pack(side="left", padx=6)
    ttk.Button(buttons, text="Dừng bot", command=lambda: async_action(install_core.disable_service)).pack(side="left")
    ttk.Button(setup, text="Trang phát hành", command=lambda: webbrowser.open(updater.RELEASES_URL)).grid(row=9, columnspan=2, sticky="w")
    ttk.Label(setup, text=f"Dữ liệu: {install_core.BASE_DIR}", wraplength=480).grid(row=10, columnspan=2, sticky="w", pady=10)

    drive = field(integrations, "Ổ / thư mục Google Drive", 0, cfg.get("google_drive_root", ""))
    media = field(integrations, "Thư mục footage", 1, "; ".join(cfg.get("media_roots") or []))
    shared = field(integrations, "Thư mục chia sẻ cho thợ", 2, "; ".join(cfg.get("shared_roots") or []))
    def choose(target, many=False):
        path = filedialog.askdirectory(parent=root)
        if path:
            target.set(target.get() + "; " + path if many and target.get() else path)
    ttk.Button(integrations, text="Chọn Drive", command=lambda: choose(drive)).grid(row=3, column=0, sticky="w")
    other = ttk.Frame(integrations)
    other.grid(row=3, column=1, sticky="w")
    ttk.Button(other, text="Thêm footage", command=lambda: choose(media, True)).pack(side="left")
    ttk.Button(other, text="Thêm thư mục chia sẻ", command=lambda: choose(shared, True)).pack(side="left")
    cal_name = field(integrations, "Tên lịch trên Mac", 4, cfg.get("macos_calendar", "")) if IS_MAC else None
    url = field(integrations, "URL Apps Script /exec", 5, cfg.get("gcal_webhook_url", ""))
    secret = field(integrations, "Khóa Apps Script", 6, secret=True)
    vision = tk.BooleanVar(value=bool(cfg.get("gemini_vision_enabled")))
    if IS_MAC:
        ttk.Checkbutton(integrations, text="Cho phép gửi ảnh màn hình sang Gemini khi dùng AI Vision", variable=vision).grid(row=7, columnspan=2, sticky="w")
    def save_integrations():
        drive_val, media_val, shared_val, cal_val, vision_val = drive.get().strip(), media.get(), shared.get(), cal_name.get().strip() if cal_name else "", vision.get()
        def work():
            edit_config(lambda c: c.update(google_drive_root=install_core.validate_local_root(drive_val) if drive_val else "",
                        media_roots=[install_core.validate_local_root(p.strip()) for p in media_val.split(";") if p.strip()],
                        shared_roots=[install_core.validate_local_root(p.strip()) for p in shared_val.split(";") if p.strip()],
                        macos_calendar=cal_val, gemini_vision_enabled=vision_val))
        async_action(work, lambda _: messagebox.showinfo("MediaTeleBot", "Đã lưu cấu hình trên máy.", parent=root))

    def connect_calendar():
        endpoint, key = url.get(), secret.get()
        def done(calendar):
            secret.set("")
            messagebox.showinfo("MediaTeleBot", f"Đã kết nối lịch {calendar}.", parent=root)
        async_action(lambda: gcal_bridge.configure_webhook(endpoint, key), done)

    def copy_calendar_key():
        value = secrets.token_urlsafe(32)
        secret.set(value)
        root.clipboard_clear()
        root.clipboard_append(value)

    ttk.Button(integrations, text="Lưu cấu hình", command=save_integrations).grid(row=8, column=0, sticky="w", pady=10)
    ttk.Button(integrations, text="Kết nối Apps Script", command=connect_calendar).grid(row=8, column=1, sticky="w")
    ttk.Button(integrations, text="Tạo và sao chép khóa Apps Script", command=copy_calendar_key).grid(row=9, column=1, sticky="w")
    ttk.Button(integrations, text="Ngắt Apps Script", command=lambda: async_action(
        lambda: edit_config(lambda c: c.update(gcal_webhook_url="", gcal_webhook_secret="")),
        lambda _: (url.set(""), secret.set(""), messagebox.showinfo("MediaTeleBot", "Đã ngắt trên máy. Tắt deployment cũ trong Google Apps Script nếu còn hoạt động.", parent=root))
    )).grid(row=9, column=0, sticky="w")
    def close():
        if not tasks_running:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
