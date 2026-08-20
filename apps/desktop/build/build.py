"""跨平台打包脚本：调用 PyInstaller 按 desktop.spec 产出桌面应用。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = Path(__file__).resolve().parent / "desktop.spec"
DIST_DIR = PROJECT_ROOT / "dist"
WORK_DIR = PROJECT_ROOT / "build" / "pyinstaller"


def main() -> None:
    """执行打包并输出产物路径。"""
    dist_dir = DIST_DIR.resolve()
    work_dir = WORK_DIR.resolve()
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        str(SPEC_FILE),
    ]
    print("打包命令:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # 清理 spec 的临时产物目录（PyInstaller 会在 spec 同目录生成 build/ 目录）
    spec_build = SPEC_FILE.parent / "build"
    if spec_build.is_dir():
        shutil.rmtree(spec_build)

    print("\n打包完成，产物位于:")
    for child in sorted(dist_dir.glob("desktop-app*")):
        print(f"  - {child}")
    print("\n运行方式（macOS/Windows/Linux 通用）:")
    print(f"  {dist_dir / 'desktop-app' / 'desktop-app'}")
    print(f"  # macOS 应用包: {dist_dir / 'desktop-app.app'}")


if __name__ == "__main__":
    main()
