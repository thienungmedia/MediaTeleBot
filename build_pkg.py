"""Build a universal macOS installer from the checkout, without root scripts."""
from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from install_core import FILES
from runtime import IS_MAC
from updater import CURRENT_VERSION

SOURCE = Path(__file__).resolve().parent
MIN_MAC = "12.0"


def run(*argv: str) -> None:
    subprocess.run(argv, check=True)


def build(output: Path, app_sign: str | None, installer_sign: str | None, notary_profile: str | None) -> Path:
    if not IS_MAC:
        raise ValueError("Build .pkg cần macOS với Xcode Command Line Tools.")
    if bool(app_sign) != bool(installer_sign) or (notary_profile and not installer_sign):
        raise ValueError("Bản ký cần Developer ID Application và Developer ID Installer.")
    output.mkdir(parents=True, exist_ok=True)
    pkg = output.resolve() / f"MediaTeleBot-{CURRENT_VERSION}-macOS-universal.pkg"
    with tempfile.TemporaryDirectory(prefix="mediatelebot-build-") as temporary:
        staging = Path(temporary)
        app = staging / "MediaTeleBot.app"
        resources = app / "Contents" / "Resources"
        executable = app / "Contents" / "MacOS" / "MediaTeleBot"
        resources.mkdir(parents=True)
        executable.parent.mkdir()
        slices = []
        for arch in ("arm64", "x86_64"):
            binary = staging / arch
            run("xcrun", "clang", "-arch", arch, f"-mmacosx-version-min={MIN_MAC}", "-fobjc-arc",
                "-framework", "Cocoa", str(SOURCE / "packaging" / "Launcher.m"), "-o", str(binary))
            slices.append(str(binary))
        run("xcrun", "lipo", "-create", *slices, "-output", str(executable))
        for file in FILES:
            shutil.copyfile(SOURCE / file, resources / file)
        shutil.copyfile(SOURCE / "AppIcon.icns", resources / "AppIcon.icns")
        with (app / "Contents" / "Info.plist").open("wb") as fp:
            plistlib.dump({
                "CFBundleIdentifier": "com.thienungmedia.mediatelebot",
                "CFBundleName": "MediaTeleBot",
                "CFBundleExecutable": "MediaTeleBot",
                "CFBundleIconFile": "AppIcon",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": CURRENT_VERSION,
                "CFBundleShortVersionString": CURRENT_VERSION,
                "LSMinimumSystemVersion": MIN_MAC,
            }, fp)
        if app_sign:
            run("codesign", "--force", "--options", "runtime", "--timestamp", "--sign", app_sign, str(app))
        else:
            run("codesign", "--force", "--sign", "-", str(app))
        run("codesign", "--verify", "--strict", str(app))

        component = staging / "component.pkg"
        run("pkgbuild", "--component", str(app), "--install-location", "/Applications",
            "--identifier", "com.thienungmedia.mediatelebot.installer", "--version", CURRENT_VERSION, str(component))
        dist = staging / "Distribution.xml"
        dist.write_text(f"""<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>MediaTeleBot {CURRENT_VERSION}</title>
  <options customize="never" hostArchitectures="arm64,x86_64"/>
  <allowed-os-versions><os-version min="{MIN_MAC}"/></allowed-os-versions>
  <choices-outline><line choice="app"/></choices-outline>
  <choice id="app" visible="false"><pkg-ref id="com.thienungmedia.mediatelebot.installer"/></choice>
  <pkg-ref id="com.thienungmedia.mediatelebot.installer" version="{CURRENT_VERSION}">component.pkg</pkg-ref>
</installer-gui-script>
""", encoding="utf-8")
        command = ["productbuild", "--distribution", str(dist), "--package-path", temporary]
        if installer_sign:
            command.extend(["--sign", installer_sign])
        run(*command, str(pkg))
    if notary_profile:
        run("xcrun", "notarytool", "submit", str(pkg), "--keychain-profile", notary_profile, "--wait")
        run("xcrun", "stapler", "staple", str(pkg))
        run("xcrun", "stapler", "validate", str(pkg))
        run("spctl", "-a", "-t", "install", str(pkg))
    return pkg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist", type=Path)
    parser.add_argument("--app-identity")
    parser.add_argument("--installer-identity")
    parser.add_argument("--notary-profile")
    parser.add_argument("--unsigned", action="store_true", help="Build a local test package, without Developer ID.")
    args = parser.parse_args()
    if not args.unsigned and not (args.app_identity and args.installer_identity and args.notary_profile):
        parser.error("Dùng --unsigned để kiểm thử hoặc cung cấp cả hai Developer ID và Notary profile để phát hành.")
    if args.unsigned and any((args.app_identity, args.installer_identity, args.notary_profile)):
        parser.error("--unsigned chỉ dành cho gói kiểm thử.")
    print(build(args.output, args.app_identity, args.installer_identity, args.notary_profile))
