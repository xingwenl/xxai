#!/usr/bin/env bash
# Harness v2 验证脚本：后台会话记录（request 2026-10-13-admin-conversation-history）。
#
# 覆盖 spec.md 的 7 条验收标准：
#   1 鉴权/隔离       → pytest tests/conversation + 真实后端联调
#   2 会话主体聚合    → 同上
#   3 消息投影逐字段一致 → 同上（pytest 与真实 Postgres 各比一次）
#   4 软删除语义      → 同上
#   5 四个筛选维度    → 同上
#   6 ai-sdk 产物未破坏 → npm run type-check / build + dist 断言（含图表引擎保持可选懒加载）
#   7 apps/front 可用  → tsc -b / lint（按存量基线判定）/ vite build / 真实浏览器三层页面交互
#
# 退出码：0 全通过无未执行项 / 3 其余通过但有未执行项 / 1 有失败 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2
REPO_ROOT="$(pwd)"

FAIL=0
UNEXECUTED=0
MOUNTED_API_PID=""

# 执行一条验证命令并打印结果。
# 用法：verify_step "<人类可读名称>" <命令> [参数...]
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

# —— ai-sdk 产物断言：唯一 CSS 产物、既有导出仍在、.xxai- 规则只增不减 ——
# 用子 shell 切目录，避免改变脚本自身的工作目录（后续步骤依赖仓库根相对路径）。
assert_ai_sdk_dist() (
  cd "$REPO_ROOT/apps/ai-sdk" || exit 1
  local css_count selectors baseline=141 ok=0
  css_count="$(ls dist/*.css 2>/dev/null | wc -l | tr -d ' ')"
  selectors="$(grep -o '\.xxai-[a-z0-9-]*' dist/style.css | sort -u | wc -l | tr -d ' ')"
  echo "dist 内 CSS 产物数量：${css_count}（期望 1）"
  echo "dist/style.css 内唯一 .xxai- 选择器数：${selectors}（基线 ${baseline}，只增不减）"
  echo "dist 内 xxai-history 选择器数：$(grep -o '\.xxai-history-[a-z0-9-]*' dist/style.css | sort -u | wc -l | tr -d ' ')"
  echo "index.d.ts 中的新增导出："
  grep -n "history" dist/index.d.ts || true
  [[ "$css_count" == "1" ]] || ok=1
  [[ "$selectors" -ge "$baseline" ]] || ok=1
  grep -q "ConversationList" dist/index.d.ts || ok=1
  grep -q "ConversationHistory" dist/index.d.ts || ok=1
  grep -q "createAgentClient" dist/index.d.ts || ok=1
  grep -q "registerCustomComponent" dist/index.d.ts || ok=1
  grep -q "xxai-chat-window" dist/style.css || ok=1
  grep -q "xxai-history-list" dist/xxai-agent.es.js || ok=1
  # 图表引擎必须保持「可选 + 运行时懒加载」：一旦说明符被折叠成字面量，宿主打包器
  # 会把未安装的 mermaid/echarts 当作硬依赖，dev server 与生产构建都会直接失败。
  local mermaid_static echarts_static
  mermaid_static="$(grep -c 'import("mermaid")' dist/xxai-agent.es.js || true)"
  echarts_static="$(grep -c 'import("echarts")' dist/xxai-agent.es.js || true)"
  echo "dist 内静态 import(\"mermaid\") 次数：${mermaid_static}（期望 0）"
  echo "dist 内静态 import(\"echarts\") 次数：${echarts_static}（期望 0）"
  [[ "$mermaid_static" == "0" ]] || ok=1
  [[ "$echarts_static" == "0" ]] || ok=1
  exit "$ok"
)

# —— 前端 lint：只允许存量基线里的 error，本次改动不得新增 ——
assert_frontend_lint_baseline() (
  cd "$REPO_ROOT/apps/front" || exit 1
  pnpm exec eslint . -f json > /tmp/conv-history-lint.json 2>/dev/null
  python3 - <<'PY'
import json

BASELINE = {
    "src/components/sign-out-dialog.tsx:19:5:no-console",
    "src/lib/auth.ts:6:20:react-hooks/rules-of-hooks",
    "src/lib/http.ts:19:44:@typescript-eslint/no-explicit-any",
    "src/lib/http.ts:23:5:no-console",
}
with open("/tmp/conv-history-lint.json", encoding="utf-8") as handle:
    report = json.load(handle)
found = set()
for entry in report:
    rel = entry["filePath"].split("apps/front/")[-1]
    for message in entry["messages"]:
        if message["severity"] == 2:
            key = f"{rel}:{message['line']}:{message['column']}:{message['ruleId']}"
            found.add(key)
            print(f"ERROR {rel}:{message['line']}:{message['column']} {message['ruleId']}")
print()
print(f"存量基线 error（本次改动前已存在，文件未被本 request 修改）：{len(BASELINE)} 条")
for item in sorted(BASELINE):
    print(f"  - {item}")
new = sorted(found - BASELINE)
print(f"本 request 新增 error：{len(new)} 条")
for item in new:
    print(f"  ! {item}")
raise SystemExit(1 if new else 0)
PY
)

# —— 前端生产构建 + 产物含会话历史组件 ——
assert_frontend_bundle() (
  cd "$REPO_ROOT/apps/front" || exit 1
  local ok=0
  pnpm exec vite build || ok=1
  echo
  echo "产物中的会话历史组件与样式："
  grep -l "xxai-history-list" dist/assets/*.js || ok=1
  grep -l "xxai-history" dist/assets/*.css || ok=1
  exit "$ok"
)

# —— 真实后端联调：Postgres 实数据 + 本地 uvicorn 启动本次新增接口 ——
run_live_smoke() {
  echo "### 真实后端联调：Postgres 实数据 + 本地 uvicorn 验证平台级只读接口"
  echo
  echo '```bash'
  echo 'cd apps/backend && DATABASE_URL=postgresql+asyncpg://root:***@127.0.0.1:5432/ai_db poetry run uvicorn main:app --host 127.0.0.1 --port 8011 &'
  echo 'python3 <联调脚本：mint admin token → 鉴权/主体/列表/详情/消息/软删除>'
  echo '```'
  echo

  if ! (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null; then
    echo "跳过：本机 127.0.0.1:5432 不可达（docker 数据库未启动），无法执行真实数据联调。"
    echo
    UNEXECUTED=1
    return
  fi

  if curl -s -o /dev/null --max-time 3 http://127.0.0.1:8011/api/v1/platforms/1/conversations; then
    echo "跳过：127.0.0.1:8011 已被占用，无法保证联调打到本次改动的代码。"
    echo
    UNEXECUTED=1
    return
  fi

  local db_url="postgresql+asyncpg://${DB_USER:-root}:${DB_PASSWORD:-Dd123456}@127.0.0.1:5432/${DB_NAME:-ai_db}"
  local smoke_py api_log
  smoke_py="$(mktemp /tmp/conv-history-smoke-XXXXXX.py)"
  api_log="$(mktemp /tmp/conv-history-api-XXXXXX.log)"

  (
    cd "$REPO_ROOT/apps/backend" || exit 1
    DATABASE_URL="$db_url" DB_HOST=127.0.0.1 poetry run uvicorn main:app \
      --host 127.0.0.1 --port 8011 >"$api_log" 2>&1 &
    echo $! > /tmp/conv-history-api.pid
  )
  MOUNTED_API_PID="$(cat /tmp/conv-history-api.pid 2>/dev/null || true)"

  local ready=0
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8011/api/v1/platforms/1/conversations; then
      ready=1
      break
    fi
    sleep 1
  done

  if [[ "$ready" != "1" ]]; then
    echo "跳过：本地 uvicorn 启动失败，日志见下。"
    tail -20 "$api_log" || true
    echo
    UNEXECUTED=1
    [[ -n "$MOUNTED_API_PID" ]] && kill "$MOUNTED_API_PID" 2>/dev/null
    rm -f "$smoke_py" "$api_log" /tmp/conv-history-api.pid
    return
  fi

  cat > "$smoke_py" <<'PY'
"""本次新增后台会话读接口的真实数据联调。

跑在真实 Postgres 上：鉴权/隔离、会话主体聚合、列表筛选、详情用量、消息投影与
embed 逐字段比对、软删除语义。临时会话在结束时物理删除，不留测试残留。
"""

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request

from sqlalchemy import delete

from app.core.database import dispose_database, get_session_factory
from app.core.security import create_access_token
from app.modules.conversation.models import Conversation, ConversationMessage
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.services import list_console_conversation_messages
from app.modules.embed.services import get_embed_message_snapshot

BASE = "http://127.0.0.1:8011/api/v1"
ADMIN_USER_ID = 7
OTHER_USER_ID = 6
PLATFORM_ID = 1
SAMPLE_CONVERSATION_ID = 293
SAMPLE_END_USER_ID = 1

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'  [OK]  ' if ok else '  [FAIL]'} {name}{f'  {detail}' if detail else ''}")
    if not ok:
        failures.append(name)


def call(method: str, path: str, token: str | None = None):
    request = urllib.request.Request(BASE + path, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, None


async def create_scratch_conversation() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        conversation = Conversation(
            platform_id=PLATFORM_ID,
            agent_id=1,
            user_id=ADMIN_USER_ID,
            title="[verify] admin-conversation-history smoke",
            status="active",
        )
        session.add(conversation)
        await session.flush()
        session.add(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content="联调用的临时消息",
                status="completed",
                message_metadata={},
            )
        )
        await session.commit()
        return conversation.id


async def drop_scratch_conversation(conversation_id: int) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id
            )
        )
        await session.execute(
            delete(Conversation).where(Conversation.id == conversation_id)
        )
        await session.commit()


async def compare_message_projections() -> None:
    """验收 3：后台接口与 embed 接口在同一会话上逐字段一致（含 loop.steps）。"""
    session_factory = get_session_factory()
    async with session_factory() as session:
        console = await list_console_conversation_messages(
            session, PLATFORM_ID, SAMPLE_CONVERSATION_ID
        )
        embed = await get_embed_message_snapshot(
            ConversationRepository(session),
            conversation_id=SAMPLE_CONVERSATION_ID,
            claims={"platform_id": PLATFORM_ID, "sub": SAMPLE_END_USER_ID},
        )
    check(
        "后台与 embed 消息投影逐字段一致（真实 Postgres）",
        console == embed,
        f"条数={len(console)}",
    )
    check(
        "消息含 agent loop 步骤投影",
        any((item.get("loop") or {}).get("steps") for item in console),
        f"含 loop 的消息={sum(1 for i in console if i.get('loop'))}",
    )
    if console != embed:
        for index, (left, right) in enumerate(zip(console, embed)):
            if left != right:
                print(f"    首个差异 #{index}: console={left!r} embed={right!r}")
                break


async def main() -> None:
    admin_token = create_access_token(str(ADMIN_USER_ID))
    other_token = create_access_token(str(OTHER_USER_ID))

    print("  鉴权与隔离（验收 1）")
    check(
        "无 token 访问 401",
        call("GET", f"/platforms/{PLATFORM_ID}/conversation-principals")[0] == 401,
    )
    for path in (
        "/conversation-principals",
        "/conversations",
        f"/conversations/{SAMPLE_CONVERSATION_ID}",
        f"/conversations/{SAMPLE_CONVERSATION_ID}/messages",
    ):
        check(
            f"非平台成员访问 {path} → 404",
            call("GET", f"/platforms/{PLATFORM_ID}{path}", other_token)[0] == 404,
        )
    check(
        "管理员访问无权限平台 → 404",
        call("GET", "/platforms/999/conversation-principals", admin_token)[0] == 404,
    )

    print("  会话主体列表（验收 2）")
    status, body = call(
        "GET", f"/platforms/{PLATFORM_ID}/conversation-principals?page=1&page_size=100", admin_token
    )
    check("主体列表 200", status == 200, f"status={status}")
    principals = (body or {}).get("data", {}).get("items", [])
    check("主体列表非空", bool(principals), f"返回 {len(principals)} 个主体")
    check("每个主体都有会话数 > 0", all(p["conversation_count"] > 0 for p in principals))
    check("每个主体都有显示名", all(p["display_name"] for p in principals))
    check(
        "主体类型只有 user / end_user",
        {p["principal_type"] for p in principals} <= {"user", "end_user"},
    )

    print("  会话列表与筛选（验收 5）")
    status, body = call(
        "GET",
        f"/platforms/{PLATFORM_ID}/conversations?page=1&page_size=5&agent_id=1",
        admin_token,
    )
    data = (body or {}).get("data", {})
    check("按 agent_id 筛选 200", status == 200, f"total={data.get('total')}")
    check("分页字段完整", {"items", "total", "page", "page_size"} <= set(data))
    check("分页条数不超过 page_size", len(data.get("items", [])) <= 5)
    first = (data.get("items") or [{}])[0]
    check(
        "列表项字段完整",
        {
            "id",
            "agent_name",
            "principal_type",
            "principal_name",
            "title",
            "status",
            "message_count",
            "last_message_preview",
        }
        <= set(first),
    )
    check(
        "默认不含已删除会话",
        all(item["status"] != "deleted" for item in data.get("items", [])),
    )
    keyword = (first.get("title") or "")[:4]
    if keyword:
        status, body = call(
            "GET",
            f"/platforms/{PLATFORM_ID}/conversations?page=1&page_size=5&keyword={urllib.parse.quote(keyword)}",
            admin_token,
        )
        check(
            f"按关键字 {keyword!r} 筛选有结果",
            status == 200 and (body or {}).get("data", {}).get("total", 0) > 0,
        )
    status, body = call(
        "GET",
        f"/platforms/{PLATFORM_ID}/conversations?page=1&page_size=5&principal_type=end_user&principal_id={first.get('principal_id', 1)}",
        admin_token,
    )
    check(
        "按会话主体筛选，返回项主体一致",
        status == 200
        and all(
            item["principal_type"] == "end_user"
            and item["principal_id"] == first.get("principal_id", 1)
            for item in (body or {}).get("data", {}).get("items", [])
        ),
    )

    print("  详情与用量（验收 2/5）")
    status, body = call(
        "GET", f"/platforms/{PLATFORM_ID}/conversations/{SAMPLE_CONVERSATION_ID}", admin_token
    )
    detail = (body or {}).get("data", {})
    check("会话详情 200", status == 200)
    check(
        "详情含会话级用量汇总",
        {"prompt_tokens", "completion_tokens", "total_tokens", "record_count"}
        <= set(detail.get("usage") or {}),
        f"message_count={detail.get('message_count')} usage={detail.get('usage')}",
    )
    status, body = call(
        "GET",
        f"/platforms/{PLATFORM_ID}/conversations/{SAMPLE_CONVERSATION_ID}/messages",
        admin_token,
    )
    messages = (body or {}).get("data", [])
    check(
        "消息接口返回裸数组且条数与详情一致",
        status == 200
        and isinstance(messages, list)
        and len(messages) == detail.get("message_count"),
        f"messages={len(messages)} detail.message_count={detail.get('message_count')}",
    )

    await compare_message_projections()

    print("  软删除语义（验收 4）")
    scratch_id = await create_scratch_conversation()
    try:
        status, body = call(
            "GET",
            f"/platforms/{PLATFORM_ID}/conversations?page=1&page_size=100&keyword=%5Bverify%5D",
            admin_token,
        )
        check(
            "临时会话出现在默认列表",
            any(item["id"] == scratch_id for item in (body or {}).get("data", {}).get("items", [])),
        )
        status, _ = call(
            "DELETE", f"/platforms/{PLATFORM_ID}/conversations/{scratch_id}", admin_token
        )
        check("软删除返回 200", status == 200, f"status={status}")
        _, body = call(
            "GET",
            f"/platforms/{PLATFORM_ID}/conversations?page=1&page_size=100&keyword=%5Bverify%5D",
            admin_token,
        )
        check(
            "软删除后从默认列表消失",
            all(item["id"] != scratch_id for item in (body or {}).get("data", {}).get("items", [])),
        )
        _, body = call(
            "GET",
            f"/platforms/{PLATFORM_ID}/conversations?page=1&page_size=100&status=deleted&keyword=%5Bverify%5D",
            admin_token,
        )
        check(
            "status=deleted 时可见",
            any(item["id"] == scratch_id for item in (body or {}).get("data", {}).get("items", [])),
        )
        status, body = call(
            "GET", f"/platforms/{PLATFORM_ID}/conversations/{scratch_id}/messages", admin_token
        )
        check(
            "软删除后消息仍可查",
            status == 200 and len((body or {}).get("data", [])) == 1,
        )
    finally:
        await drop_scratch_conversation(scratch_id)
        print(f"  已清理临时会话 #{scratch_id}")

    await dispose_database()


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if failures:
        print(f"联调失败项：{len(failures)}")
        for item in failures:
            print(f"  - {item}")
        raise SystemExit(1)
    print("联调全部通过：真实 Postgres + 真实登录态 + 本次新增接口。")
PY

  if (cd "$REPO_ROOT/apps/backend" && DATABASE_URL="$db_url" DB_HOST=127.0.0.1 poetry run python "$smoke_py"); then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo

  [[ -n "$MOUNTED_API_PID" ]] && kill "$MOUNTED_API_PID" 2>/dev/null
  sleep 1
  [[ -n "$MOUNTED_API_PID" ]] && kill -9 "$MOUNTED_API_PID" 2>/dev/null
  # poetry run 可能留下 uvicorn 子进程，按端口兜底清理，避免下次运行撞端口。
  lsof -ti tcp:8011 2>/dev/null | xargs -r kill -9 2>/dev/null
  rm -f "$smoke_py" "$api_log" /tmp/conv-history-api.pid
  MOUNTED_API_PID=""
}

# —— 真实浏览器验证：三层页面（Vue 岛）在真实后端数据下的交互 ——
# 需要 node + playwright-core + 已下载的 Chromium；缺任一项则记为未执行项。
run_browser_e2e() {
  echo "### 真实浏览器验证：三层页面（会话主体 → 会话列表 → 会话详情）"
  echo
  echo '```bash'
  echo 'cd apps/front && VITE_PROXY_TARGET=http://127.0.0.1:8012 pnpm exec vite --port 5310 --strictPort &'
  echo 'node tools/harness/verify/2026-10-13-admin-conversation-history.browser.mjs'
  echo '```'
  echo

  if ! command -v node >/dev/null 2>&1; then
    echo "跳过：本机没有 node，无法执行浏览器验证。"
    echo
    UNEXECUTED=1
    return
  fi

  local playwright_module="${PLAYWRIGHT_MODULE:-}"
  if [[ -z "$playwright_module" && -f /tmp/e2e/node_modules/playwright-core/index.mjs ]]; then
    playwright_module=/tmp/e2e/node_modules/playwright-core/index.mjs
  fi
  if [[ -z "$playwright_module" ]]; then
    echo "跳过：未找到 playwright-core。安装后可用 PLAYWRIGHT_MODULE=<路径或包名> 重跑本步骤。"
    echo
    UNEXECUTED=1
    return
  fi

  if ! (exec 3<>/dev/tcp/127.0.0.1/5432) 2>/dev/null; then
    echo "跳过：本机 127.0.0.1:5432 不可达（docker 数据库未启动），页面没有真实数据可验证。"
    echo
    UNEXECUTED=1
    return
  fi

  if curl -s -o /dev/null --max-time 3 http://127.0.0.1:8012/api/v1/platforms/1/conversations; then
    echo "跳过：127.0.0.1:8012 已被占用，无法保证前端代理打到本次改动的代码。"
    echo
    UNEXECUTED=1
    return
  fi

  local db_url="postgresql+asyncpg://${DB_USER:-root}:${DB_PASSWORD:-Dd123456}@127.0.0.1:5432/${DB_NAME:-ai_db}"
  local api_log vite_log token
  api_log="$(mktemp /tmp/conv-history-browser-api-XXXXXX.log)"
  vite_log="$(mktemp /tmp/conv-history-browser-vite-XXXXXX.log)"

  (
    cd "$REPO_ROOT/apps/backend" || exit 1
    DATABASE_URL="$db_url" DB_HOST=127.0.0.1 poetry run uvicorn main:app \
      --host 127.0.0.1 --port 8012 >"$api_log" 2>&1 &
    echo $! > /tmp/conv-history-browser-api.pid
  )
  (
    cd "$REPO_ROOT/apps/front" || exit 1
    VITE_PROXY_TARGET=http://127.0.0.1:8012 pnpm exec vite --port 5310 --strictPort --force \
      >"$vite_log" 2>&1 &
    echo $! > /tmp/conv-history-browser-vite.pid
  )
  local api_pid vite_pid
  api_pid="$(cat /tmp/conv-history-browser-api.pid 2>/dev/null || true)"
  vite_pid="$(cat /tmp/conv-history-browser-vite.pid 2>/dev/null || true)"

  # vite dev 只监听 IPv6 的 localhost，必须用 localhost 而不是 127.0.0.1 探测。
  local ready=0
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8012/api/v1/platforms/1/conversations &&
      curl -s -o /dev/null --max-time 2 http://localhost:5310/; then
      ready=1
      break
    fi
    sleep 1
  done

  if [[ "$ready" != "1" ]]; then
    echo "跳过：本地 uvicorn 或 vite dev server 启动失败，日志见下。"
    echo "--- uvicorn ---"
    tail -15 "$api_log" || true
    echo "--- vite ---"
    tail -15 "$vite_log" || true
    echo
    UNEXECUTED=1
  else
    token="$(cd "$REPO_ROOT/apps/backend" && DATABASE_URL="$db_url" DB_HOST=127.0.0.1 poetry run python -c \
      "from app.core.security import create_access_token; print(create_access_token('${ADMIN_USER_ID:-7}'))" 2>/dev/null | tail -1)"
    if [[ -z "$token" ]]; then
      echo "跳过：无法 mint 管理员 token。"
      echo
      UNEXECUTED=1
    elif E2E_BASE=http://localhost:5310 E2E_TOKEN="$token" PLAYWRIGHT_MODULE="$playwright_module" \
      node "$REPO_ROOT/tools/harness/verify/2026-10-13-admin-conversation-history.browser.mjs"; then
      echo "结果：通过"
    else
      echo "结果：失败"
      FAIL=1
    fi
  fi
  echo

  [[ -n "$vite_pid" ]] && kill "$vite_pid" 2>/dev/null
  [[ -n "$api_pid" ]] && kill "$api_pid" 2>/dev/null
  sleep 1
  lsof -ti tcp:5310 2>/dev/null | xargs -r kill -9 2>/dev/null
  lsof -ti tcp:8012 2>/dev/null | xargs -r kill -9 2>/dev/null
  rm -f "$api_log" "$vite_log" /tmp/conv-history-browser-api.pid /tmp/conv-history-browser-vite.pid
}

echo "## 已执行的命令与结果"
echo

verify_step "后端会话读接口测试（验收 1-5：鉴权、主体聚合、投影一致、软删除、筛选）" \
  bash -c 'cd apps/backend && poetry run pytest tests/conversation -q'

verify_step "后端回归：共享投影重构未破坏 embed 与 gateway（132 passed, 1 skipped 基线）" \
  bash -c 'cd apps/backend && poetry run pytest tests/embed tests/gateway -q'

verify_step "后端 ruff" \
  bash -c 'cd apps/backend && poetry run ruff check app/modules/conversation/ app/modules/embed/services.py app/__init__.py tests/conversation/test_admin_conversation_read.py'

verify_step "ai-sdk 类型检查（验收 6）" \
  bash -c 'cd apps/ai-sdk && npm run type-check'

verify_step "ai-sdk 构建（验收 6：单入口打包，样式仍汇成单文件）" \
  bash -c 'cd apps/ai-sdk && npm run build'

verify_step "ai-sdk 产物断言（验收 6）" assert_ai_sdk_dist

verify_step "apps/front 类型检查（验收 7）" \
  bash -c 'cd apps/front && pnpm exec tsc -b --force'

verify_step "apps/front lint：本次改动未新增 error（验收 7，按存量基线判定）" \
  assert_frontend_lint_baseline

verify_step "apps/front 生产构建（验收 7：图表引擎保持可选懒加载后仍可构建）" \
  assert_frontend_bundle

run_live_smoke

run_browser_e2e

echo "## 未执行项与原因"
echo
if [[ $UNEXECUTED -ne 0 ]]; then
  echo "- 真实浏览器验证被跳过（本机缺 node / playwright-core / Chromium，或 Postgres 不可达），三层页面在真实 DOM 中的挂载与交互只有构建产物层面的证据；上面已打印具体跳过原因。"
else
  echo "- 无未执行项。"
fi
echo
echo "### 明确排除在本次范围外（不计为未执行项）"
echo
echo "- \`xxai-agent\` 发布到 registry 并用版本号安装：本 request 采用 \`file:../ai-sdk\` 本地接入（与 apps/shop 一致），发布链路不在本次范围内。"
echo "- ai-sdk 在非 React 宿主（Vue/原生页面）里的手工回归：本次只验证主入口导出与产物结构未破坏（导出项、唯一 CSS 产物、\`.xxai-\` 选择器数只增不减、图表引擎保持非字面量动态导入），未跑其它宿主的交互用例。"

echo "## 验收结论"
echo
echo "- 自动化部分覆盖 spec.md 验收标准 1-7 中可脚本化的全部内容：后端鉴权/隔离（1）、会话主体聚合（2）、后台与 embed 投影逐字段一致（3）、软删除语义（4）、四个筛选维度（5）、ai-sdk 产物未破坏（6）、apps/front 类型检查/构建/无新增 lint error（7）。"
echo "- 真实浏览器步骤（若未跳过）覆盖验收 7 的交互面：侧栏入口、会话主体表格与跳转、Vue 岛 ConversationList / ConversationHistory 挂载、消息时间线与 Agent 执行过程开关、用量汇总、「全部会话」Tab。"
echo "- 已发现的既有缺陷（非本 request 引入，浏览器步骤中做了隔离）：后台悬浮 Agent 桥接请求 \`GET /api/v1/embed/agent-token\` 在本机返回 401，而 http 拦截器把 401 视为登出，会让后台页面跳回登录页。"
echo "- 接入方式与剩余风险：\`apps/front\` 通过 \`file:../ai-sdk\` 依赖本地 SDK，而 pnpm 对 \`file:\` 依赖是复制且不执行 SDK 的 \`prepare\` 脚本，因此干净克隆后需先在 \`apps/ai-sdk\` 执行 \`npm run build\` 再装 \`apps/front\`（已写入两个 README）；改动 ai-sdk 源码后同样需要重建 dist 并在 apps/front 重跑 \`pnpm install\`。"
echo "- 是否可归档：可归档（退出码 0 = 全部通过且无未执行项；3 = 其余通过但存在未执行项）。"

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
