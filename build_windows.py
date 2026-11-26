"""Package the Windows setup and Python source into a portable ZIP."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from install_core import FILES
from updater import CURRENT_VERSION

root = Path(__file__).resolve().parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
archive = dist / f"MediaTeleBot-{CURRENT_VERSION}-Windows.zip"
with ZipFile(archive, "w", ZIP_DEFLATED) as package:
    for file in (*FILES, "CaiDat-Windows.cmd", "README.md"):
        package.write(root / file, f"MediaTeleBot/{file}")
print(archive)
