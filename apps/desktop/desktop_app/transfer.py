"""远程资源读取：地址白名单、限字节下载、按镜像顺序回退。

插件市场与宿主应用更新都需要「从静态地址取 JSON / zip」，并且都要求：
生产只走 https、本机调试允许回环 http 与 file://、超时与大小有上限、主源失败时
能按顺序退到 Gitee 等镜像。这层不掺业务语义，业务模块（market / app_update）把
这里的异常翻译成各自领域的错误类型。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_USER_AGENT = "WW-Desktop/1.0"


class TransferError(Exception):
    """远程资源读取失败。"""


class TransferValidationError(TransferError):
    """地址或内容不合法（用户可修正）。"""


class TransferDownloadError(TransferError):
    """网络、HTTP 状态或大小超限等下载失败。"""


def validate_url(url: str, *, what: str) -> str:
    """校验地址：生产只接受 https，本机开发额外允许 file:// 与回环 http://。"""
    parsed = urlparse(url)
    scheme = parsed.scheme
    if scheme == "https" and parsed.netloc:
        return url
    if scheme == "http" and (parsed.hostname or "") in LOOPBACK_HOSTS:
        return url
    if scheme == "file" and parsed.path:
        return url
    raise TransferValidationError(
        f"{what} 只支持 https:// 地址（本机开发可用 127.0.0.1 的 http:// 或 file://）：{url}"
    )


def read_url(
    url: str,
    limit: int,
    *,
    what: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> bytes:
    """读取 URL 内容并限制字节数；超限、网络异常统一转成中文错误。"""
    parsed = urlparse(url)
    try:
        if parsed.scheme == "file":
            data = Path(unquote(parsed.path)).read_bytes()
            if len(data) > limit:
                raise TransferDownloadError(f"{what}超过大小限制（{len(data)} > {limit} 字节）")
            return data
        request = Request(url, headers={"User-Agent": user_agent})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 地址已校验
            data = response.read(limit + 1)
    except TransferError:
        raise
    except OSError as exc:  # URLError / HTTPError / 文件不存在都落在这里
        raise TransferDownloadError(f"下载{what}失败：{exc}") from exc
    if len(data) > limit:
        raise TransferDownloadError(f"{what}超过大小限制（{len(data)} > {limit} 字节）")
    return data


def read_first(
    primary: str,
    mirrors: Sequence[str] = (),
    limit: int = 0,
    *,
    what: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str, bytes]:
    """按「主源 → 镜像」顺序读取，返回 (命中的地址, 内容)。

    主源与所有镜像都失败时抛 ``TransferDownloadError``，并在消息里带上每个地址的
    失败原因；这样前端能看出是「网络不通」而不是误报「已是最新」。
    """
    candidates = [primary, *mirrors]
    failures: list[str] = []
    for url in candidates:
        try:
            validate_url(url, what=what)
            return url, read_url(url, limit, what=what, user_agent=user_agent, timeout=timeout)
        except TransferError as exc:
            failures.append(f"{url}（{exc}）")
            continue
    raise TransferDownloadError(f"主源与镜像都不可用：{'；'.join(failures)}")


def sha256_bytes(data: bytes) -> str:
    """返回字节内容的 sha256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def _copy_stream(source, part: Path, limit: int, *, what: str, digest):
    """把二进制流写到 part 文件并同步算 sha256；超限立即中断。"""
    total = 0
    with part.open("wb") as out:
        while True:
            chunk = source.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise TransferDownloadError(
                    f"{what}超过大小限制（{total} > {limit} 字节）"
                )
            digest.update(chunk)
            out.write(chunk)
    return total, digest


def download_to(
    url: str,
    dest: Path,
    limit: int,
    *,
    what: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[int, str]:
    """把 URL 内容流式下载到 ``dest``，返回 (字节数, sha256)。

    先写 ``<dest>.part`` 并在**替换正式文件之前**校验清单给的 size / sha256：
    校验不过就删掉 ``.part``，既不会留下半成品，也不会把上一次已校验通过的
    安装包覆盖成坏包。
    """
    validate_url(url, what=what)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f"{dest.name}.part")
    part.unlink(missing_ok=True)
    digest = hashlib.sha256()
    try:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            source_path = Path(unquote(parsed.path))
            if source_path.stat().st_size > limit:
                raise TransferDownloadError(f"{what}超过大小限制（{limit} 字节）")
            with source_path.open("rb") as source:
                total, digest = _copy_stream(source, part, limit, what=what, digest=digest)
        else:
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 地址已校验
                total, digest = _copy_stream(response, part, limit, what=what, digest=digest)
        size, hexdigest = total, digest.hexdigest()
        if expected_size is not None and size != expected_size:
            raise TransferValidationError(
                f"{what}校验失败（清单 size={expected_size}，实际 {size}）"
            )
        if expected_sha256 is not None and hexdigest != expected_sha256:
            raise TransferValidationError(
                f"{what}校验失败（清单 sha256={expected_sha256}，实际 {hexdigest}）"
            )
        os.replace(part, dest)
    except TransferError:
        part.unlink(missing_ok=True)
        raise
    except OSError as exc:  # URLError / HTTPError / 文件不存在都落在这里
        part.unlink(missing_ok=True)
        raise TransferDownloadError(f"下载{what}失败：{exc}") from exc
    return total, digest.hexdigest()


def download_first(
    primary: str,
    mirrors: Sequence[str],
    dest: Path,
    limit: int,
    *,
    what: str,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[str, int, str]:
    """按「主源 → 镜像」顺序下载到 ``dest``，返回 (命中地址, 字节数, sha256)。

    校验失败也会继续试下一个镜像（镜像可能比主源内容更新）；全部失败时，
    若失败原因全是校验问题则抛 ``TransferValidationError``，否则抛下载错误，
    便于调用方区分「网络不可达」与「清单与内容对不上」。
    """
    candidates = [primary, *mirrors]
    failures: list[str] = []
    saw_download_error = False
    for url in candidates:
        try:
            total, digest = download_to(
                url,
                dest,
                limit,
                what=what,
                user_agent=user_agent,
                timeout=timeout,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )
            return url, total, digest
        except TransferValidationError as exc:
            failures.append(f"{url}（{exc}）")
        except TransferDownloadError as exc:
            failures.append(f"{url}（{exc}）")
            saw_download_error = True
    message = f"主源与镜像都不可用：{'；'.join(failures)}"
    if saw_download_error:
        raise TransferDownloadError(message)
    raise TransferValidationError(message)
