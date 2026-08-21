"""把内置插件打成 zip 包，用于测试与演示设置页安装流程。"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    plugin_dir = project_root / "plugins" / "hello-world"
    if not (plugin_dir / "manifest.json").is_file():
        sys.exit("未找到内置插件: " + str(plugin_dir))
    manifest = json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))
    out_dir = project_root / "dist"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"hello-world-{manifest['version']}.zip"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(plugin_dir.rglob("*")):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(plugin_dir.parent))
    print(f"已生成: {out_path}")


if __name__ == "__main__":
    main()
