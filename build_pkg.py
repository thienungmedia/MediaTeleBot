import os, sys, shutil, subprocess

scratch_dir = '/Users/thienung/.gemini/antigravity/scratch/MacFileBot_Assistant'
pkg_root = '/tmp/macfilebot_pkg_root'
pkg_scripts = '/tmp/macfilebot_pkg_scripts'
pkg_component = '/tmp/macfilebot_component.pkg'
final_pkg = f'{scratch_dir}/MacFileBot_Installer.pkg'

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
    'config.example.json', 'AppIcon.icns',
    'KiemTraLoi.command', 'KhoiDongLai.command', 'DoiThuMucDrive.command',
    'CapNhat.command', 'GoCaiDat.command'
]
for f in core_files:
    src = f'{scratch_dir}/{f}'
    if os.path.exists(src):
        shutil.copy2(src, f'{pkg_root}/Library/Application Support/MacFileBot/{f}')

# 4. Tạo script postinstall
postinstall_code = '''#!/bin/bash
CONSOLE_USER=$(stat -f "%Su" /dev/console 2>/dev/null || echo "$USER")
CONSOLE_UID=$(id -u "$CONSOLE_USER" 2>/dev/null || echo "501")
CONSOLE_HOME=$(dscl . -read /Users/"$CONSOLE_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')
if [ -z "$CONSOLE_HOME" ]; then
    CONSOLE_HOME="/Users/$CONSOLE_USER"
fi

USER_TARGET_DIR="$CONSOLE_HOME/Library/Application Support/MacFileBot"
mkdir -p "$USER_TARGET_DIR"
cp -R "/Library/Application Support/MacFileBot/"* "$USER_TARGET_DIR/" 2>/dev/null || true
chown -R "$CONSOLE_USER":staff "$USER_TARGET_DIR"
chmod -R 755 "$USER_TARGET_DIR"

# Xoá quarantine và cấp quyền sở hữu cho user trên /Applications
chown -R "$CONSOLE_USER":staff "/Applications/Cài Đặt MacFileBot.app" "/Applications/MacFileBot Manager.app" 2>/dev/null || true
chmod -R 755 "/Applications/Cài Đặt MacFileBot.app" "/Applications/MacFileBot Manager.app" 2>/dev/null || true
xattr -dr com.apple.quarantine "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null || true
xattr -dr com.apple.quarantine "/Applications/MacFileBot Manager.app" 2>/dev/null || true
xattr -dr com.apple.quarantine "$USER_TARGET_DIR" 2>/dev/null || true

# Nhập config cũ nếu có
if [ -f "$CONSOLE_HOME/.gemini/antigravity/scratch/telegram-file-manager/config.json" ] && [ ! -f "$USER_TARGET_DIR/config.json" ]; then
    cp "$CONSOLE_HOME/.gemini/antigravity/scratch/telegram-file-manager/config.json" "$USER_TARGET_DIR/config.json"
    chown "$CONSOLE_USER":staff "$USER_TARGET_DIR/config.json"
    chmod 600 "$USER_TARGET_DIR/config.json"
fi

# Tạo biểu tượng ngoài Desktop bằng ditto (ghi đè sạch bundle không lồng thư mục)
if [ -d "$CONSOLE_HOME/Desktop" ]; then
    /usr/bin/ditto "/Applications/Cài Đặt MacFileBot.app" "$CONSOLE_HOME/Desktop/Cài Đặt MacFileBot.app" 2>/dev/null || true
    /usr/bin/ditto "/Applications/MacFileBot Manager.app" "$CONSOLE_HOME/Desktop/MacFileBot Manager.app" 2>/dev/null || true
    cp "$USER_TARGET_DIR/KiemTraLoi.command" "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
    chmod +x "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
    chown -R "$CONSOLE_USER":staff "$CONSOLE_HOME/Desktop/Cài Đặt MacFileBot.app" "$CONSOLE_HOME/Desktop/MacFileBot Manager.app" "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$CONSOLE_HOME/Desktop/Cài Đặt MacFileBot.app" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$CONSOLE_HOME/Desktop/MacFileBot Manager.app" 2>/dev/null || true
    xattr -dr com.apple.quarantine "$CONSOLE_HOME/Desktop/Kiểm Tra Lỗi Bot.command" 2>/dev/null || true
fi

# Mở ứng dụng Cài Đặt MacFileBot ngay sau khi trình cài đặt hoàn tất
(sleep 1; launchctl asuser "$CONSOLE_UID" sudo -u "$CONSOLE_USER" open "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null || sudo -u "$CONSOLE_USER" open "/Applications/Cài Đặt MacFileBot.app" 2>/dev/null) >/dev/null 2>&1 &

exit 0
'''
with open(f'{pkg_scripts}/postinstall', 'w') as f:
    f.write(postinstall_code)
os.chmod(f'{pkg_scripts}/postinstall', 0o755)

# 5. Build component package (with BundleIsRelocatable=False so Apps always go to /Applications)
os.environ['TMPDIR'] = '/tmp'
comp_plist = '/tmp/macfilebot_components.plist'
subprocess.run(['pkgbuild', '--analyze', '--root', pkg_root, comp_plist], check=True)
import plistlib
with open(comp_plist, 'rb') as fp:
    bundles = plistlib.load(fp)
for b in bundles:
    b['BundleIsRelocatable'] = False
    b['BundleHasStrictIdentifier'] = False
with open(comp_plist, 'wb') as fp:
    plistlib.dump(bundles, fp)

print("Building component package with pkgbuild...")
subprocess.run([
    'pkgbuild',
    '--root', pkg_root,
    '--component-plist', comp_plist,
    '--scripts', pkg_scripts,
    '--identifier', 'com.macfilebot.pkg',
    '--version', '1.3.0',
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
