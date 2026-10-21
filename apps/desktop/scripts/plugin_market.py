"""插件市场命令行工具：查看索引、按 id 安装、生成索引条目、校验 sha256。

与宿主共用 `desktop_app/market.py`，因此「宿主里能装的包」和「CLI 能装的包」走同一套
校验（大小上限、sha256、包内 manifest 与索引一致）。

用法：
    python scripts/plugin_market.py list
    python scripts/plugin_market.py install hello-world
    python scripts/plugin_market.py entry dist/hello-world-0.1.0.zip --download https://example.com/x.zip
    python scripts/plugin_market.py verify dist/hello-world-0.1.0.zip --sha256 <64 位十六进制>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# 允许从仓库里直接运行：把 apps/desktop 加进 import 路径
APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from desktop_app import market, paths  # noqa: E402  (依赖上面的 sys.path 调整)
from desktop_app.manager import PluginError, PluginManager  # noqa: E402


def _make_manager() -> PluginManager:
    """构造与宿主一致的插件管理器（用户插件目录 + state.json）。"""
    return PluginManager(
        builtin_dir=paths.builtin_plugins_dir(),
        user_dir=paths.user_plugins_dir(),
        state_file=paths.state_file(),
    )


def _find_entry(entries: list[market.MarketEntry], plugin_id: str) -> market.MarketEntry:
    for entry in entries:
        if entry.id == plugin_id:
            return entry
    raise SystemExit(f"市场里没有插件：{plugin_id}（可用 list 查看全部 id）")


def cmd_list(args: argparse.Namespace) -> int:
    entries = market.fetch_index(args.index or None, refresh=args.refresh)
    installed = {plugin.id: plugin.version for plugin in _make_manager().list_plugins()}
    if args.json:
        print(json.dumps([entry.to_dict() for entry in entries], ensure_ascii=False, indent=2))
        return 0
    if not entries:
        print(f"索引为空：{args.index or market.index_url()}")
        return 0
    print(f"市场源：{args.index or market.index_url()}")
    for entry in entries:
        version = installed.get(entry.id)
        state = f"已安装 v{version}" if version else "未安装"
        size = f"{entry.size / 1024:.0f} KB" if entry.size else "大小未知"
        print(f"- {entry.id}  v{entry.version}  [{state}]  {size}  {entry.name}")
        if entry.description:
            print(f"    {entry.description}")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    entries = market.fetch_index(args.index or None, refresh=True)
    entry = _find_entry(entries, args.plugin_id)
    try:
        plugin = market.install_entry(_make_manager(), entry)
    except market.MarketError as exc:
        print(f"安装失败：{exc}", file=sys.stderr)
        return 1
    except PluginError as exc:
        print(f"安装失败：{exc}", file=sys.stderr)
        return 1
    print(f"已安装：{plugin.id} v{plugin.version} → {plugin.dir}")
    return 0


def cmd_entry(args: argparse.Namespace) -> int:
    zip_path = Path(args.zip)
    if not zip_path.is_file():
        print(f"找不到文件：{zip_path}", file=sys.stderr)
        return 1
    try:
        manifest = market.read_archive_manifest(zip_path.read_bytes())
    except market.MarketError as exc:
        print(f"读取插件包失败：{exc}", file=sys.stderr)
        return 1
    data = zip_path.read_bytes()
    entry = {
        "id": manifest.get("id"),
        "name": manifest.get("name"),
        "version": manifest.get("version"),
        "description": manifest.get("description", ""),
        "download": args.download or "<上传后的下载地址>",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "permissions": manifest.get("permissions", []),
    }
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    zip_path = Path(args.zip)
    if not zip_path.is_file():
        print(f"找不到文件：{zip_path}", file=sys.stderr)
        return 1
    data = zip_path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    expected = args.sha256.lower()
    if actual != expected:
        print(f"sha256 不匹配：期望 {expected}，实际 {actual}", file=sys.stderr)
        return 1
    try:
        manifest = market.read_archive_manifest(data)
    except market.MarketError as exc:
        print(f"插件包校验失败：{exc}", file=sys.stderr)
        return 1
    print(f"校验通过：{manifest.get('id')} v{manifest.get('version')}（{len(data)} 字节）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="插件市场命令行工具（索引 / 安装 / 生成条目 / 校验）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="列出市场索引里的插件")
    list_parser.add_argument("--index", default="", help="索引地址（默认取 DESKTOP_PLUGIN_MARKET_URL）")
    list_parser.add_argument("--refresh", action="store_true", help="跳过缓存强制重取索引")
    list_parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    list_parser.set_defaults(func=cmd_list)

    install_parser = subparsers.add_parser("install", help="按 id 安装市场插件")
    install_parser.add_argument("plugin_id", help="插件 id")
    install_parser.add_argument("--index", default="", help="索引地址（默认取 DESKTOP_PLUGIN_MARKET_URL）")
    install_parser.set_defaults(func=cmd_install)

    entry_parser = subparsers.add_parser("entry", help="为打包好的 zip 生成索引条目")
    entry_parser.add_argument("zip", help="插件包路径")
    entry_parser.add_argument("--download", default="", help="上传后的下载地址")
    entry_parser.set_defaults(func=cmd_entry)

    verify_parser = subparsers.add_parser("verify", help="校验插件包的 sha256 与 manifest")
    verify_parser.add_argument("zip", help="插件包路径")
    verify_parser.add_argument("--sha256", required=True, help="期望的 sha256")
    verify_parser.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
