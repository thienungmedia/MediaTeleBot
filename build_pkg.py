import os, sys, shutil, subprocess

scratch_dir = '/Users/thienung/.gemini/antigravity/scratch/MacFileBot_Assistant'
pkg_root = '/tmp/macfilebot_pkg_root'
pkg_scripts = '/tmp/macfilebot_pkg_scripts'
pkg_component = '/tmp/macfilebot_component.pkg'
final_pkg = '/Users/thienung/Desktop/MacFileBot_Installer.pkg'

if os.path.exists(pkg_root):
    shutil.rmtree(pkg_root)
if os.path.exists(pkg_scripts):
    shutil.rmtree(pkg_scripts)
if os.path.exists(pkg_component):
    os.remove(pkg_component)
if os.path.exists(final_pkg):
    os.remove(final_pkg)

# 1. Cấu trúc thư mục
os.makedirs(f'{pkg_root}/Applications', exist_ok=True)
os.makedirs(f'{pkg_root}/Library/Application Support/MacFileBot', exist_ok=True)
os.makedirs(pkg_scripts, exist_ok=True)

# 2. Copy Apps vào /Applications
shutil.copytree(f'{scratch_dir}/Cài Đặt MacFileBot.app', f'{pkg_root}/Applications/Cài Đặt MacFileBot.app')
shutil.copytree(f'{scratch_dir}/MacFileBot Manager.app', f'{pkg_root}/Applications/MacFileBot Manager.app')

# 3. Copy engine files
core_files = [
    'bot.py', 'safe_fs.py', 'nl_engine.py', 'lunar_calendar.py', 'llm_intent.py',
    'updater.py', 'version.json', 'install_core.py', 'HuongDanLayMa.html',
    'no_delete_guard.py', 'zalo_sender.py', 'HUONG_DAN_NHANH.txt', 'README.md',
    'config.example.json', 'AppIcon.icns'
]
for f in core_files:
    src = f'{scratch_dir}/{f}'
    if os.path.exists(src):
        shutil.copy2(src, f'{pkg_root}/Library/Application Support/MacFileBot/{f}')

# 4. Tạo script postinstall
postinstall_code = '''#!/bin/bash
CONSOLE_USER=$(stat -f "%Su" /dev/console 2>/dev/null || echo "$USER")
CONSOLE_UID=$(id -u "$CONSOLE_USER" 2>/dev/null || echo "501")
CONSOLE_HOME=$(eval echo "~$CONSOLE_USER")

# 1. Tự động kiểm tra và cài đặt Python 3.12 chính thức nếu máy chưa có Python Framework
HAS_OFFICIAL_PYTHON=0
for p in /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
         /opt/homebrew/bin/python3; do
    if [ -x "$p" ]; then
        HAS_OFFICIAL_PYTHON=1
        break
    fi
done

if [ "$HAS_OFFICIAL_PYTHON" -eq 0 ]; then
    echo "Đang tự động cài đặt Python 3.12 chính thức cho macOS..."
    PY_PKG="/tmp/python-3.12-macos.pkg"
    # Tải gói Python 3.12 chính thức từ python.org (Universal macOS 11+)
    curl -sL --connect-timeout 10 --max-time 180 "https://www.python.org/ftp/python/3.12.8/python-3.12.8-macos11.pkg" -o "$PY_PKG" 2>/dev/null || true
    if [ -s "$PY_PKG" ]; then
        installer -pkg "$PY_PKG" -target / >/dev/null 2>&1 || true
        rm -f "$PY_PKG"
        if [ -x "/Applications/Python 3.12/Install Certificates.command" ]; then
            "/Applications/Python 3.12/Install Certificates.command" >/dev/null 2>&1 || true
        fi
    fi
fi

USER_TARGET_DIR="$CONSOLE_HOME/Library/Application Support/MacFileBot"
mkdir -p "$USER_TARGET_DIR"
cp -R "/Library/Application Support/MacFileBot/"* "$USER_TARGET_DIR/" 2>/dev/null || true
chown -R "$CONSOLE_USER":staff "$USER_TARGET_DIR"
chmod -R 755 "$USER_TARGET_DIR"

# Xoá quarantine
xattr -dr com.apple.quarantine "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null || true
xattr -dr com.apple.quarantine "/Applications/MacFileBot Manager.app" 2>/dev/null || true
xattr -dr com.apple.quarantine "$USER_TARGET_DIR" 2>/dev/null || true

# Nhập config cũ nếu có
if [ -f "$CONSOLE_HOME/.gemini/antigravity/scratch/telegram-file-manager/config.json" ] && [ ! -f "$USER_TARGET_DIR/config.json" ]; then
    cp "$CONSOLE_HOME/.gemini/antigravity/scratch/telegram-file-manager/config.json" "$USER_TARGET_DIR/config.json"
    chown "$CONSOLE_USER":staff "$USER_TARGET_DIR/config.json"
    chmod 600 "$USER_TARGET_DIR/config.json"
fi

# Tạo biểu tượng ngoài Desktop để thợ dễ thấy và bấm mở
if [ -d "$CONSOLE_HOME/Desktop" ]; then
    cp -R "/Applications/Cài Đặt MacFileBot.app" "$CONSOLE_HOME/Desktop/" 2>/dev/null || true
    cp -R "/Applications/MacFileBot Manager.app" "$CONSOLE_HOME/Desktop/" 2>/dev/null || true
    cp "$USER_TARGET_DIR/KiemTraLoi.command" "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
    chmod +x "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
    chown -R "$CONSOLE_USER":staff "$CONSOLE_HOME/Desktop/Cài Đặt MacFileBot.app" "$CONSOLE_HOME/Desktop/MacFileBot Manager.app" "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$CONSOLE_HOME/Desktop/Cài Đặt MacFileBot.app" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$CONSOLE_HOME/Desktop/MacFileBot Manager.app" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
fi

# Tự động nạp dịch vụ nếu đã có config
PY_BIN=""
for p in /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$p" ]; then PY_BIN="$p"; break; fi
done

if [ -n "$PY_BIN" ] && [ -f "$USER_TARGET_DIR/config.json" ]; then
    sudo -u "$CONSOLE_USER" "$PY_BIN" "$USER_TARGET_DIR/install_core.py" --setup-service 2>/dev/null || true
fi

# Luôn luôn mở Cài Đặt MacFileBot để người dùng dán Token Bot & Gemini API Key
launchctl asuser "$CONSOLE_UID" sudo -u "$CONSOLE_USER" open "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null || \
sudo -u "$CONSOLE_USER" open "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null || \
open "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null || true

exit 0
'''
with open(f'{pkg_scripts}/postinstall', 'w') as f:
    f.write(postinstall_code)
os.chmod(f'{pkg_scripts}/postinstall', 0o755)

# 5. Build component package
print("Building component package with pkgbuild...")
subprocess.run([
    'pkgbuild',
    '--root', pkg_root,
    '--scripts', pkg_scripts,
    '--identifier', 'com.macfilebot.pkg',
    '--version', '1.2.0',
    '--install-location', '/',
    pkg_component
], check=True)

# 6. Tạo Distribution.xml cho productbuild
dist_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="1">
    <title>Cài Đặt Trợ Lý MacFileBot</title>
    <options customize="never" require-scripts="false" hostArchitectures="x86_64,arm64"/>
    <domains enable_anywhere="true" enable_currentUserHome="false" enable_localSystem="true"/>
    <choices-outline>
        <line choice="default"/>
    </choices-outline>
    <choice id="default" title="MacFileBot Core &amp; Apps">
        <pkg-ref id="com.macfilebot.pkg"/>
    </choice>
    <pkg-ref id="com.macfilebot.pkg" version="1.2.0" onConclusion="none">macfilebot_component.pkg</pkg-ref>
</installer-gui-script>
'''
dist_path = '/tmp/Distribution.xml'
with open(dist_path, 'w', encoding='utf-8') as f:
    f.write(dist_xml)

# 7. Build final installer product
print("Building final product installer with productbuild...")
subprocess.run([
    'productbuild',
    '--distribution', dist_path,
    '--package-path', '/tmp',
    final_pkg
], check=True)

print("SUCCESS: Package created at", final_pkg)
