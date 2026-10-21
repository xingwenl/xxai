"""跨平台打包脚本：调用 PyInstaller 按 desktop.spec 产出桌面应用，并做一次启动冒烟检查。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = Path(__file__).resolve().parent / "desktop.spec"
DIST_DIR = PROJECT_ROOT / "dist"
WORK_DIR = PROJECT_ROOT / "build" / "pyinstaller"

# 启动冒烟：跑起来后观察这么久，进程还活着才算打包成功
SMOKE_SECONDS = 3.0
# 没有图形会话的环境（CI / 远程）可用它跳过冒烟
SMOKE_SKIP_ENV = "DESKTOP_SKIP_SMOKE"

sys.path.insert(0, str(PROJECT_ROOT))
from desktop_app.app_config import APP_NAME  # noqa: E402


def built_binary(dist_dir: Path) -> Path | None:
    """返回刚打出来的可执行文件（macOS 在 .app 包内，其余平台在 onedir 目录里）。"""
    mac_binary = dist_dir / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    if mac_binary.is_file():
        return mac_binary
    name = f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME
    one_dir_binary = dist_dir / APP_NAME / name
    return one_dir_binary if one_dir_binary.is_file() else None


def smoke_check(binary: Path, dist_dir: Path) -> None:
    """启动刚打出的可执行文件几秒，确认不是「启动即崩」。

    打包漏了动态库（例如 `_struct`）时，双击应用只会闪一下或毫无反应；
    这里在发版前直接跑一遍并打印启动日志，把这类问题拦在打包阶段。
    """
    if os.environ.get(SMOKE_SKIP_ENV):
        print(f"⏭ 跳过启动冒烟（{SMOKE_SKIP_ENV} 已设置）")
        return
    log_path = dist_dir / "smoke.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [str(binary)],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        try:
            time.sleep(SMOKE_SECONDS)
            exit_code = process.poll()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    if exit_code is not None:
        lines = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        print("✗ 启动冒烟失败：应用启动后立即退出（双击会表现为「没反应」）")
        print("  启动日志（末尾 15 行）：")
        for line in lines[-15:]:
            print(f"    {line}")
        print(f"  完整日志：{log_path}")
        raise SystemExit(1)
    print(f"✓ 启动冒烟通过：进程存活 {SMOKE_SECONDS:.0f}s 后被结束，启动日志：{log_path.name}")


def main() -> None:
    """执行打包、清理临时产物并做启动冒烟检查。"""
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
    # PyInstaller 默认把 bincache 写到 ~/Library/Application Support/pyinstaller；
    # 在没有该目录写权限的环境（CI、沙箱）里 --clean 会直接失败，这里固定放到构建目录下。
    env = dict(os.environ)
    env.setdefault("PYINSTALLER_CONFIG_DIR", str(work_dir / "config"))

    print("打包命令:", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)

    # 清理 spec 的临时产物目录（PyInstaller 会在 spec 同目录生成 build/ 目录）
    spec_build = SPEC_FILE.parent / "build"
    if spec_build.is_dir():
        shutil.rmtree(spec_build)

    binary = built_binary(dist_dir)
    if binary is None:
        raise SystemExit(f"✗ 打包目录里找不到可执行文件：{dist_dir}")
    smoke_check(binary, dist_dir)

    print("\n打包完成，产物位于:")
    for child in sorted(dist_dir.glob(f"{APP_NAME}*")):
        print(f"  - {child}")
    print("\n运行方式（macOS/Windows/Linux 通用）:")
    print(f"  {dist_dir / APP_NAME / APP_NAME}")
    print(f"  # macOS 应用包: {dist_dir / f'{APP_NAME}.app'}")


if __name__ == "__main__":
    main()
