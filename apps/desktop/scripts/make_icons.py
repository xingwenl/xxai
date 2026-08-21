"""从 assets/icon.png 生成 macOS .icns 与 Windows .ico 图标。

用法：python scripts/make_icons.py
换 Logo 时只需替换 assets/icon.png（建议 1024x1024 透明底），再运行本脚本即可。
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
SOURCE = ASSETS_DIR / "icon.png"

# macOS icns 分块类型 → 像素尺寸
ICNS_SIZES: list[tuple[str, int]] = [
    ("icp4", 16),
    ("icp5", 32),
    ("icp6", 64),
    ("ic07", 128),
    ("ic08", 256),
    ("ic09", 512),
    ("ic10", 1024),
]

# Windows ico 常用尺寸
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def _strip_png(payload: bytes) -> bytes:
    """移除 PNG 的附加分块（sRGB / eXIf / pHYs 等），只保留 IHDR + IDAT + IEND。

    sips 缩放输出会带上 eXIf 元数据，部分 macOS 图标渲染路径会因此显示空白；
    剥离后与 iconutil 产物的分块一致，兼容性最好。
    """
    assert payload[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    kept = bytearray(payload[:8])
    while pos < len(payload):
        ln, typ = struct.unpack(">I4s", payload[pos : pos + 8])
        if typ in (b"IHDR", b"IDAT", b"IEND"):
            kept += payload[pos : pos + 12 + ln]
        pos += 12 + ln
    return bytes(kept)


def _resize_png(src: Path, size: int, out: Path) -> None:
    """用 macOS 自带 sips 等比缩放 PNG。"""
    subprocess.run(
        ["sips", "-s", "format", "png", "-z", str(size), str(size), str(src), "--out", str(out)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def build_icns(sizes: dict[int, bytes]) -> bytes:
    """把 PNG 字节打包为 icns 容器（PNG 分块，macOS 10.7+ 支持）。"""
    chunks = b"".join(
        type_code.encode("ascii") + struct.pack(">I", len(png) + 8) + png
        for type_code, size in ICNS_SIZES
        for png in [sizes[size]]
    )
    return b"icns" + struct.pack(">I", len(chunks) + 8) + chunks


def build_ico(sizes: dict[int, bytes]) -> bytes:
    """把多尺寸 PNG 打包为 ico（PNG 压缩条目，Windows Vista+ 支持）。"""
    count = len(ICO_SIZES)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries: list[bytes] = []
    payload = b""
    for size in ICO_SIZES:
        png = sizes[size]
        w = 0 if size >= 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                w,
                w,
                0,
                0,
                1,
                32,
                len(png),
                offset,
            )
        )
        payload += png
        offset += len(png)
    return header + b"".join(entries) + payload


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"缺少源图标: {SOURCE}（请先放入 1024x1024 的 icon.png）")
    if shutil.which("sips") is None:
        raise SystemExit("需要 macOS 自带的 sips 进行等比缩放")

    with tempfile.TemporaryDirectory(prefix="ww-icons-") as tmp:
        tmp_dir = Path(tmp)
        resized: dict[int, bytes] = {}
        for size in sorted({s for _, s in ICNS_SIZES} | set(ICO_SIZES)):
            out = tmp_dir / f"{size}.png"
            _resize_png(SOURCE, size, out)
            resized[size] = _strip_png(out.read_bytes())

        (ASSETS_DIR / "icon.icns").write_bytes(build_icns(resized))
        (ASSETS_DIR / "icon.ico").write_bytes(build_ico(resized))

    print(f"已生成:\n  {ASSETS_DIR / 'icon.icns'}\n  {ASSETS_DIR / 'icon.ico'}")


if __name__ == "__main__":
    main()
