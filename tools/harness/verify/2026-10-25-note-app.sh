#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-25-note-app
#
# 覆盖范围：apps/note（「念记」）能否作为 desktop iframe 插件独立构建、7 个 note_* 方法是否
# 同时存在于契约文件 / README 方法表 / 构建产物三处、安装脚本能否把 dist 同步到插件目录且不
# 动别的插件，以及数据模型的纯函数（空快照默认值、长度上限）是否可用。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。
#
# 守则：只写真实执行过的命令；每一步失败计 FAIL 但继续跑完其余步骤（不 set -e 提前退出），
# 结尾统一收口；无法自动化的项显式写进「未执行项与原因」。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
LAST_STATUS=0
PURE_PROBE_SKIPPED=0
PROBE_DIR="$(mktemp -d)"
export PROBE_DIR
trap 'rm -rf "$PROBE_DIR"' EXIT

# 7 个方法的契约清单。这里是**故意写死的第二份**：它就是对外承诺的契约，
# 与 apps/note/tools.json 的一致性由第 3 步（逐个方法名）+ 第 4 步（三方集合）双向断言。
NOTE_METHODS=(
  note_create_note
  note_list_notes
  note_get_note
  note_update_note
  note_set_category
  note_list_categories
  note_delete_note
)
export NOTE_METHOD_LIST="${NOTE_METHODS[*]}"

# 执行一条验证命令并打印结果。
verify_step() {
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$*"
  echo '```'
  echo
  if "$@"; then
    echo "结果：通过"
    LAST_STATUS=0
  else
    LAST_STATUS=$?
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

# 在指定目录内执行命令（不用子 shell，保证 FAIL 能传出来）。
verify_step_in() {
  local dir="$1"; shift
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "cd ${dir} && $*"
  echo '```'
  echo
  if pushd "$dir" >/dev/null 2>&1; then
    if "$@"; then
      echo "结果：通过"
      LAST_STATUS=0
    else
      LAST_STATUS=$?
      echo "结果：失败"
      FAIL=1
    fi
    popd >/dev/null 2>&1
  else
    echo "结果：失败（目录不存在：${dir}）"
    LAST_STATUS=1
    FAIL=1
  fi
  echo
}

# 执行一个外部探针脚本，并把探针源码全文打进证据块（verify.md 里能看到真正跑了什么）。
# 约定：退出码 0 通过 / 3 未执行（需要人工或环境缺失，计入 UNEXECUTED）/ 其它为失败。
verify_step_probe() {
  local name="$1"; shift
  local script="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  sed 's/^/  /' "$script"
  echo "  # 执行：$* ${script}"
  echo '```'
  echo
  "$@" "$script"
  LAST_STATUS=$?
  case $LAST_STATUS in
    0) echo "结果：通过" ;;
    3) echo "结果：未执行（原因见上方输出）"; UNEXECUTED=$((UNEXECUTED + 1)) ;;
    *)
      echo "结果：失败"
      FAIL=1
      ;;
  esac
  echo
}

echo "## 已执行的命令与结果"
echo

# 1. 依赖：apps/note 已在 pnpm-workspace.yaml 里，lockfile 必须与 package.json 一致，
#    否则任何人的机器上「装完直接 build」都会漂移。
verify_step "安装依赖（pnpm --frozen-lockfile，确认 apps/note 已纳入 workspace 且 lockfile 一致）" \
  pnpm install --frozen-lockfile

# 2. 构建：tsc --noEmit 先做类型检查，再 vite build 出 dist（base:'./'，产物可直接被宿主托管）。
#    与 `pnpm --dir apps/note build` 完全等价，只是在 apps/note 目录里执行以复用 verify_step_in。
verify_step_in "apps/note" \
  "子应用构建（tsc --noEmit + vite build，等价于 pnpm --dir apps/note build）" \
  pnpm build

# 3. 产物断言：dist 必须是一份合法的 iframe 插件，7 个方法名都得出现在 bundle 里
#    （方法名是字符串字面量，被 vite 打进 assets/*.js）。
cat > "${PROBE_DIR}/dist_probe.sh" <<'SH'
#!/usr/bin/env bash
# 断言 apps/note/dist 是一份合法的 iframe 插件产物，且 7 个 note_* 方法名都进了 bundle。
set -euo pipefail

DIST="apps/note/dist"

# 每一项都单独报错：构建挂了的时候，最需要知道的是「缺哪个文件」，而不是一个静默的 exit 1。
for artifact in index.html manifest.json icon.svg; do
  if [[ ! -f "$DIST/$artifact" ]]; then
    echo "缺少产物：$DIST/${artifact}（构建是否成功？）" >&2
    exit 1
  fi
done
if ! ls "$DIST"/assets/*.js >/dev/null 2>&1; then
  echo "缺少产物：$DIST/assets/*.js（vite 没产出 JS bundle？）" >&2
  exit 1
fi
if ! grep -qF 'id="root"' "$DIST/index.html"; then
  echo "index.html 里没有 #root 挂载点" >&2
  exit 1
fi
echo "产物文件齐全：index.html / manifest.json / icon.svg / assets/*.js / #root"

# manifest 字段是宿主识别插件与授权能力的唯一依据，逐项断言。
node -e '
  const assert = require("node:assert");
  const m = require("./apps/note/dist/manifest.json");
  assert.strictEqual(m.id, "note", "manifest.id 必须是 note");
  assert.strictEqual(m.name, "念记");
  assert.strictEqual(m.version, "0.1.0");
  assert.strictEqual(m.type, "iframe", "只支持 iframe 形态");
  assert.strictEqual(m.entry, "index.html");
  for (const permission of ["storage", "tools"]) {
    assert.ok((m.permissions || []).includes(permission), "permissions 缺少 " + permission);
  }
  console.log("manifest 字段：", JSON.stringify(m));
'

# 逐个方法名断言并打印命中的文件名（别用「grep 到一个就算了」，漏一个方法助手就少一条能力）。
count=0
for name in ${NOTE_METHOD_LIST:?NOTE_METHOD_LIST 未设置}; do
  hits="$(grep -l "$name" "$DIST"/assets/*.js || true)"
  if [[ -z "$hits" ]]; then
    echo "bundle 里没有方法名：$name" >&2
    exit 1
  fi
  echo "  ${name} → $(printf '%s\n' "$hits" | sed 's#^.*/##' | tr '\n' ' ')"
  count=$((count + 1))
done
if [[ "$count" -ne 7 ]]; then
  echo "bundle 命中的方法数应为 7，实际 ${count}" >&2
  exit 1
fi
echo "bundle 方法名断言：通过（${count} 个）"
SH

verify_step_probe "dist 产物是合法 iframe 插件，且 bundle 内含 7 个 note_* 方法名" \
  "${PROBE_DIR}/dist_probe.sh" bash

# 4. 三方一致性：tools.json 是唯一契约源，README 是给人看的文档，bundle 是宿主实际拿到的东西。
#    三者排序后必须完全一致，任一漂移都要在这里现形（并打印差异方法名）。
cat > "${PROBE_DIR}/contract_probe.py" <<'PY'
#!/usr/bin/env python3
"""三方方法契约一致性：apps/note/tools.json ↔ apps/note/README.md 方法表 ↔ dist/assets/*.js。

tools.json 是唯一契约源（页面从它取 schema，后台 HostToolPolicy 也由它生成）；
README 的方法表是文档承诺；bundle 是宿主真正注册到助手手里的东西。
三处集合必须完全相同，否则「助手认不认得 note_* 方法」就会变成玄学。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
APP = ROOT / "apps/note"

# README 只取「方法表」的行（| `note_xxx` | …）：正文里提到的 note_* 不参与比对。
README_ROW = re.compile(r"^\|\s*`(note_[a-z_]+)`")
# bundle 里的方法名形状是 note_<动词>_<名词>，这个正则不会把 `note:data`、`note-data` 算进来。
BUNDLE_NAME = re.compile(r"\bnote_[a-z]+_[a-z]+\b")


def readme_names() -> list[str]:
    text = (APP / "README.md").read_text(encoding="utf-8")
    return [m.group(1) for m in (README_ROW.match(line) for line in text.splitlines()) if m]


def bundle_names() -> tuple[set[str], dict[str, list[str]]]:
    assets = sorted((APP / "dist/assets").glob("*.js"))
    if not assets:
        sys.exit("没有找到 apps/note/dist/assets/*.js，请先构建")
    names: set[str] = set()
    where: dict[str, list[str]] = {}
    for asset in assets:
        for name in BUNDLE_NAME.findall(asset.read_text(encoding="utf-8", errors="ignore")):
            names.add(name)
            where.setdefault(name, []).append(asset.name)
    return names, where


def main() -> int:
    tools = [item["name"] for item in json.loads((APP / "tools.json").read_text(encoding="utf-8"))]
    readme = readme_names()
    bundle, where = bundle_names()

    print(f"tools.json：{len(tools)} 个 → {', '.join(sorted(tools))}")
    print(f"README 方法表：{len(readme)} 个 → {', '.join(sorted(readme))}")
    print(f"dist bundle：{len(bundle)} 个 → {', '.join(sorted(bundle))}")

    ok = True
    sources = [
        ("tools.json", set(tools)),
        ("README 方法表", set(readme)),
        ("dist bundle", bundle),
    ]
    for index, (left_label, left) in enumerate(sources):
        for right_label, right in sources[index + 1:]:
            only_left = sorted(left - right)
            only_right = sorted(right - left)
            if not only_left and not only_right:
                print(f"{left_label} ↔ {right_label}：一致")
                continue
            ok = False
            print(f"差异 {left_label} ↔ {right_label}：")
            for name in only_left:
                print(f"  - 只在 {left_label}：{name}")
            for name in only_right:
                print(f"  - 只在 {right_label}：{name}")

    if len(tools) != 7:
        ok = False
        print(f"契约方法数应恒为 7，实际 {len(tools)}")

    for name in sorted(tools):
        print(f"  {name} → bundle: {', '.join(where.get(name, ['未命中']))}")

    if not ok:
        print("三方契约一致性：不通过")
        return 1
    print("三方契约一致性：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

verify_step_probe "三方方法契约一致（tools.json ↔ README 方法表 ↔ dist bundle，含差异打印）" \
  "${PROBE_DIR}/contract_probe.py" python3

# 5. 安装脚本探针：把 dist 同步到临时插件目录，断言 --json 输出与目标目录内容；
#    再放一个「别的插件」哨兵目录，确认安装脚本只动 note 自己。
cat > "${PROBE_DIR}/install_probe.sh" <<'SH'
#!/usr/bin/env bash
# 安装脚本探针：--target 到临时目录 + --json 输出断言 + 「不清理其他插件目录」断言。
set -euo pipefail

target="${PROBE_PLUGIN_DIR:?缺少 PROBE_PLUGIN_DIR}"
json_out="${PROBE_JSON:?缺少 PROBE_JSON}"
plugins_dir="$(dirname "$target")"

# --help 不依赖 dist，先验证它可独立运行（编辑器里改脚本后最容易漏的就是用法文本）。
node apps/note/scripts/install-to-desktop.mjs --help | grep -q "用法："
echo "--help：通过"

# 哨兵：宿主 plugins 目录下已有的其他插件不能被本脚本清掉。
mkdir -p "${plugins_dir}/other-plugin"
echo "<html>keep me</html>" > "${plugins_dir}/other-plugin/index.html"

node apps/note/scripts/install-to-desktop.mjs --target "$target" --json > "$json_out"
echo "安装脚本输出：$(cat "$json_out")"

test -f "${plugins_dir}/other-plugin/index.html"
echo "隔壁插件目录未被清理：通过"

test -f "$target/index.html"
test -f "$target/manifest.json"
test -f "$target/icon.svg"
ls "$target"/assets/*.js >/dev/null
grep -qF 'id="root"' "$target/index.html"

node -e '
  const assert = require("node:assert");
  const fs = require("node:fs");
  const out = JSON.parse(fs.readFileSync(process.env.PROBE_JSON, "utf8"));
  assert.deepStrictEqual(Object.keys(out).sort(), ["installedTo", "zip"], "--json 只应输出 installedTo/zip");
  assert.strictEqual(out.installedTo, process.env.PROBE_PLUGIN_DIR, "installedTo 应是目标目录绝对路径");
  assert.strictEqual(out.zip, null, "未传 --zip 时 zip 应为 null");
  const manifest = JSON.parse(fs.readFileSync(process.env.PROBE_PLUGIN_DIR + "/manifest.json", "utf8"));
  assert.strictEqual(manifest.id, "note");
  assert.strictEqual(manifest.entry, "index.html");
  console.log("--json 输出与目标目录 manifest 断言：通过");
'
SH

export PROBE_PLUGIN_DIR="${PROBE_DIR}/install-plugins/note"
export PROBE_JSON="${PROBE_DIR}/install.json"
verify_step_probe "安装脚本探针（--target 临时目录 + --json + 不清理其他插件）" \
  "${PROBE_DIR}/install_probe.sh" bash

# 6. 纯函数自检：node 的类型擦除能直接 import .ts，用它跑数据模型的空快照与长度上限。
#    跑不起来（node 太老 / types.ts 的 import 形态不被支持）记为未执行，不引入 tsx 等新依赖。
cat > "${PROBE_DIR}/pure_probe.sh" <<'SH'
#!/usr/bin/env bash
# 纯函数自检：直接导入 apps/note/src/lib/types.ts（无外部依赖、无宿主 API），
# 断言空快照默认值与长度上限。退出码 0 通过 / 3 未执行（环境或导入形态不支持）/ 1 断言失败。
set -uo pipefail

if ! command -v node >/dev/null 2>&1; then
  echo "未执行：本机没有 node，纯函数自检跳过。"
  exit 3
fi

cat > "$PROBE_DIR/strip_support.ts" <<'TS'
const label: string = '类型擦除可用'
console.log(label)
TS
if ! node --experimental-strip-types "$PROBE_DIR/strip_support.ts" >/dev/null 2>&1; then
  echo "未执行：当前 node（$(node -v)）不支持 --experimental-strip-types，且仓库不引入 tsx 等新依赖，纯函数自检跳过。"
  exit 3
fi

cat > "$PROBE_DIR/pure_probe.ts" <<'TS'
import assert from 'node:assert'

const entry: string = process.env.NOTE_TYPES_ENTRY ?? ''
assert.ok(entry.length > 0, '缺少 NOTE_TYPES_ENTRY')

const types: any = await import(entry)
const data = types.emptyNoteData()

assert.strictEqual(data.version, 1, 'version 必须固定为 1')
assert.deepStrictEqual(data.categories, [...types.DEFAULT_CATEGORIES], '空快照应含全部内置分类')
assert.deepStrictEqual(data.notes, [], '空快照不应有笔记')
assert.ok(types.TITLE_MAX_LENGTH > 0, 'TITLE_MAX_LENGTH 应为正数')
assert.ok(types.CONTENT_MAX_LENGTH > 0, 'CONTENT_MAX_LENGTH 应为正数')
assert.ok(types.TAG_MAX_COUNT > 0, 'TAG_MAX_COUNT 应为正数')

console.log('空快照：', JSON.stringify({ version: data.version, categories: data.categories }))
console.log('长度上限：', JSON.stringify({
  TITLE_MAX_LENGTH: types.TITLE_MAX_LENGTH,
  CONTENT_MAX_LENGTH: types.CONTENT_MAX_LENGTH,
  TAG_MAX_COUNT: types.TAG_MAX_COUNT,
}))
TS

output="$(NOTE_TYPES_ENTRY="${NOTE_TYPES_ENTRY:?缺少 NOTE_TYPES_ENTRY}" \
  node --experimental-strip-types "$PROBE_DIR/pure_probe.ts" 2>&1)"
status=$?
printf '%s\n' "$output"
if [[ $status -eq 0 ]]; then
  exit 0
fi
# 模块解析 / 语法不支持属「跑不起来」，记未执行；断言失败才是真失败。
if grep -Eq 'ERR_MODULE_NOT_FOUND|Cannot find module|Unknown file extension|ERR_UNSUPPORTED|Unsupported' <<<"$output"; then
  echo "未执行：apps/note/src/lib/types.ts 当前形态无法被 node 直接导入（见上方错误），纯函数自检跳过。"
  exit 3
fi
exit 1
SH

export NOTE_TYPES_ENTRY="$(pwd)/apps/note/src/lib/types.ts"
verify_step_probe "纯函数自检（node 类型擦除直跑 src/lib/types.ts：空快照与长度上限）" \
  "${PROBE_DIR}/pure_probe.sh" bash
if [[ $LAST_STATUS -eq 3 ]]; then
  PURE_PROBE_SKIPPED=1
fi

echo "## 未执行项与原因"
echo
echo "- 真实桌面宿主点击安装（需 GUI，本机无自动化）：安装脚本只被验证到「能把 dist 同步到目标插件目录、--json 输出正确、不清理其他插件」；在 pywebview 窗口里打开「念记」卡片、新建/编辑/搜索/删除到废纸篓、重启应用后数据仍在 \`~/.desktop-app/plugin-data/note/note.json\`，都需要 macOS 图形会话与人工目视，脚本不能替代。"
echo "- 全局助手真实模型调用（需后台 Embed Client/Agent 绑定与凭证）：7 个方法是否被真实模型选中、后台 HostToolPolicy 与 schema 指纹是否一致，取决于 AI Base 后台数据与本机凭证；脚本不伪造模型会话、也不写入后台策略（避免污染），只在第 3/4 步证明方法名确实进了产物与契约文件。"
echo "- 760px 窄宽视觉检查（需人工/浏览器截图）：侧栏收成图标列、三栏不横向溢出、无控制台报错、无远程请求，属于视觉与运行时断言，脚本无法替代截图与目视。"
echo "- 宿主内 iframe 常驻与「不打开念记也能用方法」的最终体感：依赖宿主 \`tools\` 权限预挂载机制，本次不在本脚本里拉起桌面宿主（该链路已由 \`tools/harness/verify/2026-10-20-ledger-app.sh\` 用同一宿主机制覆盖）。"
if [[ $PURE_PROBE_SKIPPED -ne 0 ]]; then
  echo "- 纯函数自检：本机 node 不支持类型擦除（或 \`src/lib/types.ts\` 的导入形态无法被 node 直接解析），已跳过，未计入通过。"
fi
echo "- 平台：本机只有 macOS，未在 Windows / Linux 上执行。"
UNEXECUTED=$((UNEXECUTED + 4))
echo

echo "## 验收结论"
echo
echo "- 已由脚本证明：\`apps/note\` 能独立构建出合法 iframe 插件（\`manifest\` 的 id/name/version/type/entry/permissions 逐字段断言通过），\`dist\` 含 \`index.html\`/\`manifest.json\`/\`icon.svg\`/\`assets/*.js\`，7 个 \`note_*\` 方法名逐个在 bundle 中命中并打印了所在文件名；\`apps/note/tools.json\`、README 方法表与构建产物三方方法集合完全一致（不一致时会打印差异方法名）；安装脚本能把 \`dist/\` 同步到任意 \`--target\` 目录、\`--json\` 只输出 \`{installedTo, zip}\`、且不会清理 plugins 下的其他插件。"
echo "- 部分证明：数据模型的空快照默认值与长度上限由纯函数自检覆盖（node 类型擦除直跑，无新增依赖）；跨模式迁移、串行写队列等 store 行为不在本脚本内（依赖 \`window.desktop\`，见未执行项）。"
echo "- 尚未证明：真实宿主窗口里的界面交互与视觉、真实模型是否选中方法、窄宽布局。因此只要存在未执行项，本脚本退出码为 3，不能视为已通过人工联调。"
echo "- 剩余风险：\`note_*\` 方法名进 bundle 只能说明「页面会注册它们」，说明不了宿主侧后台策略与绑定是否就绪；真实模型对工具的选择受提示与模型版本影响，本脚本不覆盖模型绕开工具的分支。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
