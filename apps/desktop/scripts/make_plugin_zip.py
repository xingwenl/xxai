"""兼容入口：把内置 hello-world 插件打成 zip 放到 dist/（用于测试与演示安装流程）。

真正的发布脚本是 `make_plugin_release.py`（打包 + 更新 market/index.json），
这里保留旧命令，等价于「只打包、不动市场索引」。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_plugin_release import main  # noqa: E402  (依赖上面的 sys.path 调整)

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

if __name__ == "__main__":
    raise SystemExit(main(["hello-world", "--no-index", "--out-dir", str(DIST_DIR), *sys.argv[1:]]))
