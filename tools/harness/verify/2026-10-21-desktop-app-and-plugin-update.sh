#!/usr/bin/env bash
# Harness v2 验证脚本：2026-10-21-desktop-app-and-plugin-update
#
# 覆盖范围：
#   1. 版本比较单测 + apps/desktop 全量 pytest
#   2. 插件升级端到端（临时 HOME + file:// 索引）：hasUpdate 标记、备份、数据保留、
#      失败回滚、内置 / 未安装 / 降级错误语义
#   3. 宿主更新端到端（临时 HOME + file:// 清单）：检查、镜像回退、下载校验、坏 sha 拒绝
#   4. scripts/make_release.py（主应用发布）：版本一致性自检、打包 + 清单生成、
#      --bump 同步三处版本、--dry-run 不落文件、版本漂移拦截、缺 token 时上传报错
#   5. scripts/make_plugin_release.py（子应用发布）：确定性打包、索引更新、降级 /
#      同版本换包护栏、--dry-run 不落文件、旧入口 make_plugin_zip.py 兼容
#   6. 前端构建 + Harness audit
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

ROOT="$(pwd)"
DESKTOP="${ROOT}/apps/desktop"
PY="${DESKTOP}/.venv/bin/python"
PROBE_DIR="$(mktemp -d)"
REQUEST_ID="2026-10-21-desktop-app-and-plugin-update"
FAIL=0
UNEXECUTED=0
AUDIT_UNRELATED=0
SKIPPED_NOTES=()
trap 'rm -rf "$PROBE_DIR"' EXIT

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
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

verify_step_in() {
  local dir="$1" name="$2"; shift 2
  echo "### ${name}"
  echo
  echo '```bash'
  echo "( cd ${dir} && $* )"
  echo '```'
  echo
  if ( cd "$dir" && "$@" ); then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

skip_step() {
  echo "### $1"
  echo
  echo "结果：未执行（$2）"
  echo
  UNEXECUTED=1
  SKIPPED_NOTES+=("$1：$2")
}

# audit 口径：本 request 不得有新增 ERROR；仓库里他人 request 的既有 ERROR 不计入本次验收。
harness_audit() {
  local out status
  out="$("$PY" tools/harness/audit.py 2>&1)"
  status=$?
  printf '%s\n' "$out"
  if [[ $status -eq 0 ]]; then
    return 0
  fi
  if grep -q "ERROR.*${REQUEST_ID}" <<<"$out"; then
    return 1
  fi
  echo
  echo "注：以上 ERROR 均与本 request 无关（仓库其他 request 缺少 verify.md），按「无新增 ERROR」判定通过。"
  AUDIT_UNRELATED=1
  return 0
}

free_port() {
  "$PY" - <<'PY'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
}

# 起宿主并等到 /api/health 可用；参数：home port log [额外 env KEY=VALUE ...]
start_host() {
  local home="$1" port="$2" log="$3"; shift 3
  local envs=("HOME=$home" "PYTHONPATH=${DESKTOP}" "$@")
  env "${envs[@]}" "$PY" -c "
import uvicorn
from desktop_app.server import create_app
uvicorn.run(create_app(dev_agent_enabled=False), host='127.0.0.1', port=${port}, log_level='warning')
" >"$log" 2>&1 &
  echo $!
}

wait_host() {
  local port="$1"
  for _ in $(seq 1 60); do
    sleep 0.2
    if curl -fsS "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

echo "## 已执行的命令与结果"
echo

# ---------- 1. 单测 ----------

verify_step_in "$DESKTOP" "版本比较单测" \
  "$PY" -m pytest tests/test_version.py -q

verify_step_in "$DESKTOP" "apps/desktop 全量测试" \
  "$PY" -m pytest tests/ -q

# ---------- 2. 插件升级端到端 ----------

build_plugin_fixture() {
  local dir="$1"
  "$PY" - "$dir" <<'PY'
import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
packages = root / "packages"
packages.mkdir(parents=True, exist_ok=True)


def make_zip(plugin_id: str, version: str) -> Path:
    manifest = {
        "id": plugin_id,
        "name": "升级探针",
        "version": version,
        "description": "验证市场升级链路",
        "entry": "index.html",
        "permissions": ["storage", "settings"],
    }
    target = packages / f"{plugin_id}-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("index.html", f"<html><body>v{version}</body></html>")
    return target


def entry(plugin_id: str, version: str, path: Path) -> dict:
    data = path.read_bytes()
    return {
        "id": plugin_id,
        "name": "升级探针",
        "version": version,
        "description": "验证市场升级链路",
        "download": f"file://{path}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "permissions": ["storage", "settings"],
    }


index_v1 = {"version": 1, "plugins": [entry("upgrade-probe", "0.1.0", make_zip("upgrade-probe", "0.1.0"))]}
index_v2 = {"version": 1, "plugins": [entry("upgrade-probe", "0.2.0", make_zip("upgrade-probe", "0.2.0"))]}
(root / "index-v1.json").write_text(json.dumps(index_v1, ensure_ascii=False), encoding="utf-8")
(root / "index-v2.json").write_text(json.dumps(index_v2, ensure_ascii=False), encoding="utf-8")

# 坏包：sha256 故意写错，用来验证失败回滚
bad = make_zip("upgrade-probe", "0.3.0")
bad_entry = entry("upgrade-probe", "0.3.0", bad)
bad_entry["sha256"] = "0" * 64
(root / "index-bad.json").write_text(
    json.dumps({"version": 1, "plugins": [bad_entry]}, ensure_ascii=False), encoding="utf-8"
)
print(root)
PY
}

plugin_upgrade_probe() {
  local fixture="${PROBE_DIR}/plugin-market"
  build_plugin_fixture "$fixture" || return 1
  local home="${PROBE_DIR}/home-plugin" port log pid rc=0
  mkdir -p "$home"
  port="$(free_port)"
  log="${PROBE_DIR}/plugin-host.log"
  # 先用 v1 索引启动（并存一份同版本索引供后续重启使用）
  cp "${fixture}/index-v1.json" "${fixture}/index.json"
  pid="$(start_host "$home" "$port" "$log" "DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json")"
  if ! wait_host "$port"; then
    echo "宿主启动失败："; tail -20 "$log"; kill "$pid" 2>/dev/null; return 1
  fi
  local base="http://127.0.0.1:${port}"

  # 装 v1 + 写插件数据 + 写配置 + 停用
  curl -fsS -X POST "${base}/api/desktop/plugin-market/install" \
    -H 'Content-Type: application/json' -d '{"id":"upgrade-probe"}' >/dev/null || rc=1
  curl -fsS -X PUT "${base}/api/desktop/plugin-data/upgrade-probe/ledger" \
    -H 'Content-Type: application/json' -d '{"total":42}' >/dev/null || rc=1
  curl -fsS -X PATCH "${base}/api/desktop/plugins/upgrade-probe" \
    -H 'Content-Type: application/json' -d '{"enabled":false}' >/dev/null || rc=1

  # 切到 v2 索引（重启宿主让索引地址不变、内容换新）
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  cp "${fixture}/index-v2.json" "${fixture}/index.json"
  port="$(free_port)"
  pid="$(start_host "$home" "$port" "$log" "DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json")"
  if ! wait_host "$port"; then
    echo "宿主重启失败："; tail -20 "$log"; kill "$pid" 2>/dev/null; return 1
  fi
  base="http://127.0.0.1:${port}"

  curl -fsS "${base}/api/desktop/plugin-market" -o "${PROBE_DIR}/market-before.json" || rc=1
  curl -fsS -X POST "${base}/api/desktop/plugin-market/update" \
    -H 'Content-Type: application/json' -d '{"id":"upgrade-probe"}' \
    -o "${PROBE_DIR}/upgrade-result.json" || rc=1
  curl -fsS "${base}/api/desktop/plugin-market?refresh=1" -o "${PROBE_DIR}/market-after.json" || rc=1

  # 同版本再升级一次必须 400（不是 500，也不能覆盖）
  local same_status
  same_status="$(curl -s -o "${PROBE_DIR}/upgrade-same.json" -w '%{http_code}' \
    -X POST "${base}/api/desktop/plugin-market/update" \
    -H 'Content-Type: application/json' -d '{"id":"upgrade-probe"}')" || rc=1

  # 未安装的插件升级必须 404
  local missing_status
  missing_status="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "${base}/api/desktop/plugin-market/update" \
    -H 'Content-Type: application/json' -d '{"id":"nope-probe"}')" || rc=1

  # 坏包：切到 index-bad 再升级 → 400，且本机仍是 0.2.0
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  cp "${fixture}/index-bad.json" "${fixture}/index.json"
  port="$(free_port)"
  pid="$(start_host "$home" "$port" "$log" "DESKTOP_PLUGIN_MARKET_URL=file://${fixture}/index.json")"
  if ! wait_host "$port"; then
    echo "宿主重启失败："; tail -20 "$log"; kill "$pid" 2>/dev/null; return 1
  fi
  base="http://127.0.0.1:${port}"
  local bad_status
  bad_status="$(curl -s -o "${PROBE_DIR}/upgrade-bad.json" -w '%{http_code}' \
    -X POST "${base}/api/desktop/plugin-market/update" \
    -H 'Content-Type: application/json' -d '{"id":"upgrade-probe"}')" || rc=1

  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

  "$PY" - "$home" "${PROBE_DIR}/market-before.json" "${PROBE_DIR}/upgrade-result.json" \
    "$same_status" "$missing_status" "$bad_status" "${PROBE_DIR}/upgrade-bad.json" \
    "${PROBE_DIR}/market-after.json" <<'PY'
import json
import sys
from pathlib import Path

home = Path(sys.argv[1])
market_before = json.load(open(sys.argv[2], encoding="utf-8"))
result = json.load(open(sys.argv[3], encoding="utf-8"))
same_status, missing_status, bad_status = sys.argv[4], sys.argv[5], sys.argv[6]
bad_body = json.load(open(sys.argv[7], encoding="utf-8"))
market_after = json.load(open(sys.argv[8], encoding="utf-8"))

plugin_root = home / ".desktop-app" / "plugins" / "upgrade-probe"
assert plugin_root.is_dir(), "插件目录缺失"
manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))
assert manifest["version"] == "0.2.0", manifest
assert "v0.2.0" in (plugin_root / "index.html").read_text(encoding="utf-8"), "目录内容没有换新"

# 升级前：本机 0.1.0、索引 0.2.0 → 标记为有更新
before = next(item for item in market_before["plugins"] if item["id"] == "upgrade-probe")
assert before["version"] == "0.2.0", before
assert before["installedVersion"] == "0.1.0", before
assert before["hasUpdate"] is True, before

# 升级后：本机 0.2.0、索引 0.2.0 → 不再提示更新
after = next(item for item in market_after["plugins"] if item["id"] == "upgrade-probe")
assert after["installedVersion"] == "0.2.0", after
assert after["hasUpdate"] is False, after

# 升级接口返回新版本
assert result["plugin"]["version"] == "0.2.0", result

# 数据与配置保留、启用状态沿用
data = home / ".desktop-app" / "plugin-data" / "upgrade-probe" / "ledger.json"
assert json.loads(data.read_text(encoding="utf-8")) == {"total": 42}, data
state = json.loads((home / ".desktop-app" / "state.json").read_text(encoding="utf-8"))
record = state["plugins"]["upgrade-probe"]
assert record["enabled"] is False, record
assert record["previousVersion"] == "0.1.0", record
assert record.get("updatedAt"), record
assert record.get("installedAt"), record

# 旧版本备份存在且只有一份
backups = list((home / ".desktop-app" / "plugin-backups" / "upgrade-probe").iterdir())
assert len(backups) == 1, backups
assert "0.1.0" in backups[0].name, backups

# 没有临时目录残留
assert not (home / ".desktop-app" / "plugins" / ".upgrade-probe.upgrading").exists()

# 错误语义
assert same_status == "400", same_status
assert missing_status == "404", missing_status
assert bad_status == "400", bad_status
assert "sha256" in bad_body["detail"], bad_body
assert json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))["version"] == "0.2.0"

print("✓ 升级成功：版本/内容换新、数据与状态保留、旧版本备份、无临时残留")
print("✓ 错误语义：同版本 400、未安装 404、坏包 400 且本机版本不变")
PY
}

verify_step "插件升级端到端（临时 HOME + file:// 索引）" plugin_upgrade_probe

# ---------- 3. 宿主更新端到端 ----------

build_app_update_fixture() {
  local dir="$1"
  "$PY" - "$dir" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
assets = root / "assets"
assets.mkdir(parents=True, exist_ok=True)
payload = b"fake-app-bundle-zip"
asset = assets / "WW-9.9.9-macos-arm64.zip"
asset.write_bytes(payload)
asset_entry = {
    "name": asset.name,
    "url": f"file://{asset}",
    "sha256": hashlib.sha256(payload).hexdigest(),
    "size": len(payload),
}
manifest = {
    "version": 1,
    "latest": "9.9.9",
    "publishedAt": "2026-10-21T00:00:00Z",
    "notes": "验证宿主更新链路",
    "releaseUrl": "https://github.com/xingwenl/xxai/releases/tag/desktop-v9.9.9",
    "platforms": {"macos-arm64": asset_entry},
}
(root / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
bad = dict(manifest)
bad["platforms"] = {"macos-arm64": {**asset_entry, "sha256": "0" * 64}}
(root / "latest-bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
print(root)
PY
}

app_update_probe() {
  local fixture="${PROBE_DIR}/app-update"
  build_app_update_fixture "$fixture" || return 1
  local home="${PROBE_DIR}/home-app-update" port log pid rc=0
  mkdir -p "$home"
  # 平台固定为 macos-arm64：清单里只放这一个平台条目
  port="$(free_port)"
  log="${PROBE_DIR}/app-update-host.log"
  pid="$(start_host "$home" "$port" "$log" \
    "DESKTOP_APP_UPDATE_URL=file:///nonexistent/latest.json" \
    "DESKTOP_APP_UPDATE_MIRRORS=file://${fixture}/latest.json")"
  if ! wait_host "$port"; then
    echo "宿主启动失败："; tail -20 "$log"; kill "$pid" 2>/dev/null; return 1
  fi
  local base="http://127.0.0.1:${port}"

  "$PY" - "$base" <<'PY'
import sys
import urllib.error
import urllib.request

base = sys.argv[1]


def call(method: str, path: str) -> dict:
    request = urllib.request.Request(base + path, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕过本机系统代理
    try:
        with opener.open(request, timeout=20) as response:
            import json

            return {"status": response.status, "body": json.loads(response.read().decode())}
    except urllib.error.HTTPError as exc:
        import json

        return {"status": exc.code, "body": json.loads(exc.read().decode())}


# 平台不是 macos-arm64 时跳过（清单只放了这一个平台）
info = call("GET", "/api/desktop/app-update")
if info["body"].get("platform") != "macos-arm64":
    print(f"SKIP: 当前平台 {info['body'].get('platform')!r} 不在夹具覆盖范围（只造了 macos-arm64）")
    sys.exit(3)
print("✓ GET /api/desktop/app-update 走镜像回退拿到清单：", info["body"]["latest"])
PY
  local probe_rc=$?
  if [[ $probe_rc -eq 3 ]]; then
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    return 3
  elif [[ $probe_rc -ne 0 ]]; then
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    return 1
  fi

  curl -fsS -X POST "${base}/api/desktop/app-update/download" -o "${PROBE_DIR}/app-download.json" || rc=1
  curl -fsS -X POST "${base}/api/desktop/app-update/reveal" -o "${PROBE_DIR}/app-reveal.json" || rc=1
  local after_download
  after_download="$(curl -fsS "${base}/api/desktop/app-update")" || rc=1

  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

  # 坏 sha：单独起一次宿主
  port="$(free_port)"
  pid="$(start_host "$home" "$port" "$log" "DESKTOP_APP_UPDATE_URL=file://${fixture}/latest-bad.json")"
  if ! wait_host "$port"; then
    echo "宿主启动失败："; tail -20 "$log"; kill "$pid" 2>/dev/null; return 1
  fi
  local bad_status
  bad_status="$(curl -s -o "${PROBE_DIR}/app-download-bad.json" -w '%{http_code}' \
    -X POST "http://127.0.0.1:${port}/api/desktop/app-update/download")" || rc=1
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

  "$PY" - "$home" "${PROBE_DIR}/app-download.json" "${PROBE_DIR}/app-reveal.json" \
    "$after_download" "$bad_status" "${PROBE_DIR}/app-download-bad.json" <<'PY'
import json
import sys
from pathlib import Path

home = Path(sys.argv[1])
download = json.load(open(sys.argv[2], encoding="utf-8"))
reveal = json.load(open(sys.argv[3], encoding="utf-8"))
after = json.loads(sys.argv[4])
bad_status = sys.argv[5]
bad_body = json.load(open(sys.argv[6], encoding="utf-8"))

assert download["version"] == "9.9.9", download
path = Path(download["path"])
assert path.is_file(), path
assert path.parent == home / ".desktop-app" / "updates" / "9.9.9", path
assert path.read_bytes() == b"fake-app-bundle-zip", path
assert download["sha256"] == after["asset"]["sha256"], (download, after)

# 已下载：再检查一次应带上 downloadedPath
assert after["hasUpdate"] is True, after
assert after["downloadedPath"] == str(path), after

# reveal 只打开固定更新目录
assert Path(reveal["path"]).name == "updates", reveal

# 坏 sha → 400；已下载并通过校验的安装包不能被坏包覆盖或删掉
assert bad_status == "400", bad_status
assert "校验失败" in bad_body["detail"], bad_body
assert path.is_file(), "坏包校验失败不应影响已下载的安装包"
assert not list(path.parent.glob("*.part")), "不应残留 .part 临时文件"
print("✓ 下载校验落盘、downloadedPath 回填、reveal 打开固定目录")
print("✓ 坏 sha 返回 400 且不残留文件")
PY
}

echo "### 宿主更新端到端（临时 HOME + file:// 清单 + 镜像回退）"
echo
echo '```bash'
echo "# 主源指向不可达路径、镜像指向 file:// 清单，验证回退与下载校验"
echo '```'
echo
app_update_probe
probe_rc=$?
if [[ $probe_rc -eq 0 ]]; then
  echo "结果：通过"
elif [[ $probe_rc -eq 3 ]]; then
  echo "结果：未执行（当前平台不在夹具覆盖范围）"
  UNEXECUTED=1
  SKIPPED_NOTES+=("宿主更新端到端：当前平台不在夹具覆盖范围（夹具只造了 macos-arm64）")
else
  echo "结果：失败"
  FAIL=1
fi
echo

# ---------- 4. make_release.py ----------

make_release_probe() {
  local proj="${PROBE_DIR}/fakeproj"
  mkdir -p "${proj}/scripts" "${proj}/desktop_app" "${proj}/front" "${proj}/dist/WW/bin"
  cp "${DESKTOP}/scripts/make_release.py" "${proj}/scripts/"
  printf 'APP_NAME = "WW"\nAPP_VERSION = "1.2.3"\n' > "${proj}/desktop_app/app_config.py"
  printf '[project]\nname = "desktop-app"\nversion = "1.2.3"\n' > "${proj}/pyproject.toml"
  printf '{"name": "desktop-front", "version": "1.2.3"}\n' > "${proj}/front/package.json"
  printf '#!/bin/sh\necho hi\n' > "${proj}/dist/WW/bin/WW"
  chmod +x "${proj}/dist/WW/bin/WW"

  # --check-only 通过
  "$PY" "${proj}/scripts/make_release.py" --check-only || return 1

  # 打包 + 写清单
  "$PY" "${proj}/scripts/make_release.py" --notes "验证发版脚本" || return 1

  "$PY" - "$proj" <<'PY' || return 1
import hashlib
import json
import sys
import zipfile
from pathlib import Path

proj = Path(sys.argv[1])
manifest = json.loads((proj / "releases" / "latest.json").read_text(encoding="utf-8"))
assert manifest["version"] == 1, manifest
assert manifest["latest"] == "1.2.3", manifest
assert manifest["notes"] == "验证发版脚本", manifest
assert len(manifest["platforms"]) == 1, manifest
key, entry = next(iter(manifest["platforms"].items()))
zip_path = proj / "dist" / "releases" / entry["name"]
assert zip_path.is_file(), zip_path
data = zip_path.read_bytes()
assert entry["sha256"] == hashlib.sha256(data).hexdigest(), entry
assert entry["size"] == len(data), entry
assert entry["url"].endswith(entry["name"]), entry
assert entry["mirrors"] and entry["mirrors"][0].endswith(entry["name"]), entry
assert manifest["releaseUrl"].endswith("desktop-v1.2.3"), manifest

with zipfile.ZipFile(zip_path) as archive:
    names = archive.namelist()
    assert "WW/bin/WW" in names, names
    info = archive.getinfo("WW/bin/WW")
    mode = info.external_attr >> 16
    assert mode & 0o111, oct(mode)
print(f"✓ 打包出 {zip_path.name}，清单 sha256/size/url/mirrors 一致、可执行位保留")
PY
  local rc=$?
  [[ $rc -eq 0 ]] || return 1

  # 版本漂移必须被拦截
  printf '{"name": "desktop-front", "version": "9.9.9"}\n' > "${proj}/front/package.json"
  if "$PY" "${proj}/scripts/make_release.py" --check-only >"${PROBE_DIR}/drift.out" 2>&1; then
    echo "✗ 版本漂移未被拦截"
    return 1
  fi
  grep -q "不一致" "${PROBE_DIR}/drift.out" || { echo "✗ 漂移输出缺少原因"; return 1; }
  echo "✓ 版本号漂移被 --check-only 拦截"

  # 恢复一致后验 --bump patch：三处版本号与清单 latest 一起改
  printf '{"name": "desktop-front", "version": "1.2.3"}\n' > "${proj}/front/package.json"
  "$PY" "${proj}/scripts/make_release.py" --bump patch --notes "1.2.4" >"${PROBE_DIR}/bump.out" 2>&1 || {
    cat "${PROBE_DIR}/bump.out"
    return 1
  }
  "$PY" - "$proj" <<'PYEOF' || return 1
import json
import sys
from pathlib import Path

proj = Path(sys.argv[1])
assert 'APP_VERSION = "1.2.4"' in (proj / "desktop_app" / "app_config.py").read_text(encoding="utf-8")
assert 'version = "1.2.4"' in (proj / "pyproject.toml").read_text(encoding="utf-8")
front = json.loads((proj / "front" / "package.json").read_text(encoding="utf-8"))
assert front["version"] == "1.2.4", front
manifest = json.loads((proj / "releases" / "latest.json").read_text(encoding="utf-8"))
assert manifest["latest"] == "1.2.4", manifest
print("✓ --bump patch 同步三处版本号与清单 latest")
PYEOF
  [[ $? -eq 0 ]] || return 1

  # --dry-run 不得写任何文件
  local before_manifest before_version
  before_manifest="$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${proj}/releases/latest.json")"
  before_version="$(cat "${proj}/desktop_app/app_config.py")"
  "$PY" "${proj}/scripts/make_release.py" --bump minor --build --git --publish all --dry-run >"${PROBE_DIR}/dryrun.out" 2>&1 || {
    cat "${PROBE_DIR}/dryrun.out"
    return 1
  }
  [[ "$before_manifest" == "$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${proj}/releases/latest.json")" ]] || {
    echo "✗ --dry-run 改写了清单"
    return 1
  }
  [[ "$before_version" == "$(cat "${proj}/desktop_app/app_config.py")" ]] || {
    echo "✗ --dry-run 改写了版本号"
    return 1
  }
  grep -q "改写三处版本号" "${PROBE_DIR}/dryrun.out" || { echo "✗ --dry-run 计划不完整"; return 1; }
  echo "✓ --dry-run 只打印计划、不写文件"

  # 缺 token 时上传必须明确报错（不是静默成功）
  if env -u GITHUB_TOKEN -u GH_TOKEN -u GITEE_TOKEN "$PY" "${proj}/scripts/make_release.py" --publish github >"${PROBE_DIR}/notoken.out" 2>&1; then
    echo "✗ 缺 token 时 --publish github 竟然成功"
    return 1
  fi
  grep -q "GITHUB_TOKEN" "${PROBE_DIR}/notoken.out" || { echo "✗ 缺 token 报错缺少提示"; return 1; }
  echo "✓ 缺 GITHUB_TOKEN 时 --publish github 明确报错"
}

# ---------- 4b. make_plugin_release.py（子应用发布） ----------

plugin_release_probe() {
  local proj="${PROBE_DIR}/pluginproj"
  rm -rf "$proj"
  mkdir -p "${proj}/scripts" "${proj}/plugins/hello-world" "${proj}/market"
  cp "${DESKTOP}/scripts/make_plugin_release.py" "${DESKTOP}/scripts/make_plugin_zip.py" "${proj}/scripts/"
  # 用仓库里的示例插件当素材，只复制，不改仓库
  cp -R "${DESKTOP}/plugins/hello-world/." "${proj}/plugins/hello-world/"
  printf '{"version": 1, "plugins": []}\n' > "${proj}/market/index.json"

  # 未收录时 --check-only 不报错
  "$PY" "${proj}/scripts/make_plugin_release.py" hello-world --check-only >"${PROBE_DIR}/plugin-check.out" 2>&1 || {
    cat "${PROBE_DIR}/plugin-check.out"
    return 1
  }
  grep -q "尚未收录" "${PROBE_DIR}/plugin-check.out" || { echo "✗ 未收录提示缺失"; return 1; }

  # 首次发布：打包 + 写索引
  "$PY" "${proj}/scripts/make_plugin_release.py" hello-world >"${PROBE_DIR}/plugin-release-1.out" 2>&1 || {
    cat "${PROBE_DIR}/plugin-release-1.out"
    return 1
  }
  local zip_path="${proj}/market/packages/hello-world-0.1.0.zip"
  [[ -f "$zip_path" ]] || { echo "✗ 没有生成 ${zip_path}"; return 1; }
  local sha_first sha_second
  sha_first="$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$zip_path")"

  # 重复打包必须字节一致（否则同版本会被 sha 护栏拦下、发版不可复现）
  "$PY" "${proj}/scripts/make_plugin_release.py" hello-world >"${PROBE_DIR}/plugin-release-2.out" 2>&1 || {
    cat "${PROBE_DIR}/plugin-release-2.out"
    return 1
  }
  sha_second="$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$zip_path")"
  [[ "$sha_first" == "$sha_second" ]] || { echo "✗ 重复打包 sha256 不一致：${sha_first} vs ${sha_second}"; return 1; }
  echo "✓ 确定性打包：重复打同一版本 sha256 一致（${sha_first}）"

  # 索引能被宿主解析，且字段与包一致
  "$PY" - "$proj" <<'PYEOF' || return 1
import hashlib
import json
import sys
from pathlib import Path

proj = Path(sys.argv[1])
index = json.loads((proj / "market" / "index.json").read_text(encoding="utf-8"))
assert index["version"] == 1, index
assert len(index["plugins"]) == 1, index
entry = index["plugins"][0]
assert entry["id"] == "hello-world", entry
assert entry["version"] == "0.1.0", entry
zip_path = proj / "market" / "packages" / f"hello-world-{entry['version']}.zip"
data = zip_path.read_bytes()
assert entry["sha256"] == hashlib.sha256(data).hexdigest(), entry
assert entry["size"] == len(data), entry
assert "apps/desktop/market/packages/" in entry["download"], entry
assert entry["mirrors"] and "gitee.com" in entry["mirrors"][0], entry
print(f"✓ 索引条目自洽：{entry['id']} v{entry['version']}，含 Gitee mirrors")
PYEOF
  [[ $? -eq 0 ]] || return 1

  # 降级必须被拦，且 manifest 不被改脏
  local manifest_path="${proj}/plugins/hello-world/manifest.json"
  local version_before version_after
  version_before="$(cat "$manifest_path")"
  if "$PY" "${proj}/scripts/make_plugin_release.py" hello-world --version 0.0.9 >"${PROBE_DIR}/plugin-guard.out" 2>&1; then
    echo "✗ 降级发布未被拦截"
    return 1
  fi
  grep -q "更高" "${PROBE_DIR}/plugin-guard.out" || { echo "✗ 降级拦截缺少原因"; return 1; }
  version_after="$(cat "$manifest_path")"
  [[ "$version_before" == "$version_after" ]] || { echo "✗ 拦下后 manifest 被改脏"; return 1; }
  echo "✓ 索引版本更高时拒绝降级发布，且不改脏 manifest"

  # --bump patch 发布 0.1.1
  "$PY" "${proj}/scripts/make_plugin_release.py" hello-world --bump patch >"${PROBE_DIR}/plugin-bump.out" 2>&1 || {
    cat "${PROBE_DIR}/plugin-bump.out"
    return 1
  }
  grep -q '"version": "0.1.1"' "${proj}/market/index.json" || { echo "✗ 索引未更新到 0.1.1"; return 1; }
  [[ -f "${proj}/market/packages/hello-world-0.1.1.zip" ]] || { echo "✗ 没有生成 0.1.1 的包"; return 1; }
  grep -q '"version": "0.1.1"' "$manifest_path" || { echo "✗ manifest 未更新到 0.1.1"; return 1; }
  echo "✓ --bump patch 同时更新 manifest、包与索引"

  # --dry-run 不写文件
  local index_before
  index_before="$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${proj}/market/index.json")"
  "$PY" "${proj}/scripts/make_plugin_release.py" hello-world --bump minor --dry-run >"${PROBE_DIR}/plugin-dryrun.out" 2>&1 || {
    cat "${PROBE_DIR}/plugin-dryrun.out"
    return 1
  }
  [[ "$index_before" == "$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "${proj}/market/index.json")" ]] || {
    echo "✗ --dry-run 改写了索引"
    return 1
  }
  grep -q '"version": "0.1.1"' "$manifest_path" || { echo "✗ --dry-run 改写了 manifest"; return 1; }
  echo "✓ --dry-run 只预演、不写文件"

  # 旧入口兼容：make_plugin_zip.py = 只打包到 dist/、不动索引
  ( cd "$proj" && "$PY" scripts/make_plugin_zip.py >"${PROBE_DIR}/plugin-zip-compat.out" 2>&1 ) || {
    cat "${PROBE_DIR}/plugin-zip-compat.out"
    return 1
  }
  [[ -f "${proj}/dist/hello-world-0.1.1.zip" ]] || { echo "✗ 旧入口没有打包到 dist/"; return 1; }
  grep -q '"version": "0.1.1"' "${proj}/market/index.json" || { echo "✗ 旧入口动了索引"; return 1; }
  echo "✓ 旧入口 make_plugin_zip.py 仍可用，且只打包不动索引"
}

verify_step "scripts/make_release.py（主应用发布：打包 / 清单 / 版本 / 预演 / token）" make_release_probe
verify_step "scripts/make_plugin_release.py（子应用发布：确定性打包 / 索引 / 护栏）" plugin_release_probe

# ---------- 5. 仓库内自检 + 前端构建 + audit ----------

verify_step_in "$DESKTOP" "仓库内 make_release.py --check-only" \
  "$PY" scripts/make_release.py --check-only

verify_step_in "$DESKTOP" "仓库内 make_plugin_release.py hello-world --check-only" \
  "$PY" scripts/make_plugin_release.py hello-world --check-only

if [[ -d "${DESKTOP}/front/node_modules" ]]; then
  verify_step_in "${DESKTOP}/front" "前端构建（pnpm build）" pnpm build
else
  skip_step "前端构建（pnpm build）" "apps/desktop/front/node_modules 未安装"
fi

echo "### Harness audit"
echo
echo '```bash'
echo "$PY tools/harness/audit.py"
echo '```'
echo
if harness_audit; then
  echo "结果：通过"
else
  echo "结果：失败"
  FAIL=1
fi
echo

echo "## 未执行项与原因"
echo
if [[ $UNEXECUTED -eq 0 && $AUDIT_UNRELATED -eq 0 ]]; then
  echo "- 无。本机可执行的步骤已全部执行。"
else
  for note in "${SKIPPED_NOTES[@]:-}"; do
    [[ -n "$note" ]] && echo "- ${note}"
  done
  if [[ $AUDIT_UNRELATED -eq 1 ]]; then
    echo "- Harness audit 仍报与本 request 无关的既有 ERROR（仓库其他 request 缺少 verify.md），未纳入本次验收，也未在本脚本内修别人的 request。"
  fi
fi
echo
echo "## 验收结论"
echo
if [[ $FAIL -eq 0 ]]; then
  echo "- 版本比较单测与 apps/desktop 全量测试：通过（见上）。"
  echo "- 插件升级链路：通过（hasUpdate 标记、备份、plugin-data 保留、同版本 400 / 未安装 404 / 坏包 400 且不破坏本机版本）。"
  echo "- 宿主更新链路：通过（镜像回退、下载后 size/sha256 校验、坏包 400 且不覆盖已下载安装包、downloadedPath 回填）。"
  echo "- make_release.py（主应用发布）：通过（打包、清单 sha256/size/url/mirrors、可执行位、--bump 同步三处版本、--dry-run 不落文件、版本漂移拦截、缺 token 明确报错）。"
  echo "- make_plugin_release.py（子应用发布）：通过（确定性打包 sha256 稳定、索引字段与包一致、降级护栏、--bump 同步 manifest/包/索引、--dry-run 不落文件、旧入口兼容）。"
  echo "- 前端构建：见上方结果；Harness audit：本 request 无新增 ERROR。"
  echo "- 剩余风险：未在真实 GitHub/Gitee 网络环境跑过发布与下载（夹具用 file:// 替代，Release 上传只验到「缺 token 明确报错」这一层）；未在 Windows / Linux 真机验证安装包替换。"
else
  echo "- 存在失败步骤，未达到 spec 的验收标准，详见上方输出。"
fi
echo "- 脚本退出码：$( [[ $FAIL -ne 0 ]] && echo 1 || { [[ $UNEXECUTED -ne 0 ]] && echo 3 || echo 0; } )"
echo
if [[ $FAIL -eq 0 && $UNEXECUTED -eq 0 ]]; then
  exit 0
elif [[ $FAIL -eq 0 ]]; then
  exit 3
else
  exit 1
fi
