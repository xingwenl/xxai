"""宿主自更新安装：把校验通过的更新包替换到当前应用并重启。

早期版本的取舍是「不替换宿主自身，下载完由用户自己覆盖安装」（见 ``app_update.py``
模块说明），理由是未签名产物在 Gatekeeper / 文件占用上容易把应用搞坏。但每次升级
都要用户手动解压、替换、清隔离属性，成本明显高于收益，因此改成**自动安装**：

* 替换动作由**脱离宿主进程的安装脚本**执行：脚本先让宿主退出，再把旧包改名成
  ``<app>.ww-old`` 备份，替换成功并重新拉起后才删备份；
* 换包失败、``open`` 起不来都会立刻回滚到旧包并重新打开，避免「更新失败就再也
  打不开」；
* 更新包在下载阶段已按清单校验过 sha256/size，这里落盘后再校验一次，防止
  ``~/.desktop-app/updates/`` 被别的文件替换；
* 解包用 macOS 自带的 ``ditto``（与 ``build/build.py`` 打 zip 的工具一致），能保留
  .app 里的符号链接与可执行权限；
* 目前只支持 macOS，其他平台直接抛中文错误让用户手动覆盖安装。
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from desktop_app import paths

# 安装脚本里「等宿主进程退出」的宽限时间：秒。太短会截断前端响应，太长用户会以为卡住。
EXIT_GRACE_SECONDS = 2
# 收到 SIGTERM 后再等若干轮，仍然活着就 SIGKILL（避免残留进程占着旧包）
TERM_WAIT_ROUNDS = 30
TERM_WAIT_INTERVAL = 0.5

_SAFE_VERSION = re.compile(r"[^0-9A-Za-z._+-]")


class AppInstallError(Exception):
    """自动安装不可用或失败：消息直接面向用户，保持中文可读。"""


def bundle_path(executable: Path | None = None) -> Path:
    """从可执行文件路径反推当前 ``.app`` 包路径。

    打包后 ``sys.executable`` 形如 ``/Applications/WW.app/Contents/MacOS/WW``，
    往上三层就是 .app 包；开发模式（未打包）没有 .app，直接报错。
    """
    if executable is None:
        if not getattr(sys, "frozen", False):
            raise AppInstallError("开发模式（未打包）不支持自动安装，请用打包后的 WW.app 验证")
        executable = Path(sys.executable)
    exe = Path(executable)
    if exe.parent.name != "MacOS" or exe.parent.parent.name != "Contents":
        raise AppInstallError(f"当前可执行文件不在 .app 包内（{exe}），无法自动安装")
    bundle = exe.parents[2]
    if not bundle.name.endswith(".app"):
        raise AppInstallError(f"当前可执行文件的上一级不是 .app 包（{bundle}），无法自动安装")
    return bundle


def _sha256_file(path: Path) -> str:
    """流式算文件 sha256（安装包接近 20 MB，不整块读进内存）。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(package: Path, *, expected_sha256: str, expected_size: int) -> None:
    """安装前再校验一次更新包：大小与清单一致、sha256 一致。"""
    if not package.is_file():
        raise AppInstallError(f"更新包不存在：{package}，请先下载并校验")
    size = package.stat().st_size
    if size != expected_size:
        raise AppInstallError(f"更新包大小与清单不一致（清单 {expected_size}，实际 {size}），请重新下载")
    digest = _sha256_file(package)
    if digest != expected_sha256.lower():
        raise AppInstallError("更新包 sha256 与清单不一致，请重新下载")


def extract_package(package: Path, dest_dir: Path) -> Path:
    """用 ``ditto`` 解包到 ``dest_dir``，返回解出来的唯一 ``.app`` 路径。"""
    if shutil.which("ditto") is None:
        raise AppInstallError("系统缺少 ditto 命令，无法自动解包，请手动安装")
    shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # noqa: S603 - 固定命令 + 本地路径
        ["ditto", "-x", "-k", str(package), str(dest_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise AppInstallError(f"解包失败：{detail or f'ditto 退出码 {result.returncode}'}")
    apps = sorted(item for item in dest_dir.iterdir() if item.is_dir() and item.name.endswith(".app"))
    if len(apps) != 1:
        raise AppInstallError(f"更新包结构异常：期望 1 个 .app，实际 {len(apps)} 个")
    return apps[0]


def script_text(
    bundle: Path,
    staged: Path,
    backup: Path,
    pid: int,
    log: Path,
    *,
    grace: int = EXIT_GRACE_SECONDS,
) -> str:
    """生成安装脚本：等宿主退出 → 备份旧包 → 换上新包 → 失败回滚 → 重启。

    脚本脱离宿主进程运行（``start_new_session=True``），所以宿主被杀掉也不会中断替换。
    """
    quote = shlex.quote
    rounds = TERM_WAIT_ROUNDS
    return f"""#!/bin/sh
# 由 WW 自更新生成：替换 {bundle.name} 并在成功后重新打开；任何一步失败都回滚。
set -u
APP={quote(str(bundle))}
NEW={quote(str(staged))}
BAK={quote(str(backup))}
LOG={quote(str(log))}
PID={pid}

exec >>"$LOG" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始安装：pid=$PID app=$APP"

# 给前端留出显示「正在安装」提示的时间，再让宿主退出
sleep {grace}
kill -TERM "$PID" 2>/dev/null || true
i=0
while [ $i -lt {rounds} ]; do
  kill -0 "$PID" 2>/dev/null || break
  sleep {TERM_WAIT_INTERVAL}
  i=$((i + 1))
done
if kill -0 "$PID" 2>/dev/null; then
  echo "宿主未按 SIGTERM 退出，改用 SIGKILL"
  kill -9 "$PID" 2>/dev/null || true
  sleep 1
fi

rm -rf "$BAK"
if ! mv "$APP" "$BAK"; then
  echo "备份旧包失败：$APP（可能没有写权限），未做任何替换"
  exit 1
fi

if mv "$NEW" "$APP"; then
  # 浏览器下载的包会带 quarantine，自更新下载的不带；统一清一次，避免 Gatekeeper 拦新包。
  # 用 find 逐文件清：macOS 自带的 xattr 没有 -r，`xattr -dr` 会直接报 option not recognized。
  find "$APP" -exec xattr -d com.apple.quarantine {{}} + 2>/dev/null || true
  rmdir "$(dirname "$NEW")" 2>/dev/null || true
  if open "$APP"; then
    echo "安装完成，已重新打开新版本"
    rm -rf "$BAK"
    exit 0
  fi
  echo "新版本启动失败，开始回滚"
fi

rm -rf "$APP"
rmdir "$(dirname "$NEW")" 2>/dev/null || true
mv "$BAK" "$APP" 2>/dev/null || echo "回滚失败：请手动把 $BAK 改回 $APP"
open "$APP" 2>/dev/null || true
echo "已回滚到原版本"
exit 1
"""


def _default_spawn(script: Path) -> None:
    """交给系统接管脚本：独立会话 + 脱离 stdin/stdout，宿主退出后继续执行。"""
    subprocess.Popen(  # noqa: S603 - 固定 /bin/sh + 本地脚本
        ["/bin/sh", str(script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def install_package(
    package: Path,
    version: str,
    *,
    expected_sha256: str,
    expected_size: int,
    pid: int | None = None,
    platform_name: str | None = None,
    bundle: Path | None = None,
    spawn: Callable[[Path], None] | None = None,
) -> dict[str, str]:
    """把已校验的更新包换到当前 .app 上，返回安装脚本与日志路径。

    调用方（HTTP 接口）拿到结果后立即返回；宿主会在 ``EXIT_GRACE_SECONDS`` 秒后
    被安装脚本结束，随后由脚本替换并重新打开新版本。
    """
    system = platform_name or sys.platform
    if system != "darwin":
        raise AppInstallError(f"自动安装目前只支持 macOS（当前 {system}），请手动覆盖安装")
    # 显式传 bundle 的场景（测试 / 迁移）跳过可执行文件推导，其余按真实 .app 推导
    resolved = Path(bundle or bundle_path()).resolve()
    if not resolved.is_dir():
        raise AppInstallError(f"当前应用包不存在：{resolved}")
    if not os.access(resolved.parent, os.W_OK):
        raise AppInstallError(f"应用所在目录不可写（{resolved.parent}），请手动覆盖安装")

    verify_package(package, expected_sha256=expected_sha256, expected_size=expected_size)

    safe_version = _SAFE_VERSION.sub("_", version) or "unknown"
    staging_dir = resolved.parent / f".{resolved.stem}-update-{safe_version}"
    staged_app = extract_package(package, staging_dir)
    if staged_app.name != resolved.name:
        # 包内 .app 名字必须与当前一致，否则替换后 .app 路径变了，Dock/别名全废
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise AppInstallError(f"更新包里的应用名是 {staged_app.name}，与当前 {resolved.name} 不一致，已放弃安装")

    updates_dir = paths.updates_dir()
    updates_dir.mkdir(parents=True, exist_ok=True)
    script = updates_dir / f"install-{safe_version}.sh"
    log = updates_dir / f"install-{safe_version}.log"
    backup = resolved.parent / f"{resolved.name}.ww-old"
    script.write_text(
        script_text(resolved, staged_app, backup, pid if pid is not None else os.getpid(), log),
        encoding="utf-8",
    )
    script.chmod(0o755)

    (spawn or _default_spawn)(script)
    return {
        "version": version,
        "bundle": str(resolved),
        "script": str(script),
        "log": str(log),
        "platform": platform.machine(),
    }
