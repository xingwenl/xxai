---
id: 2026-10-26-resume-citation-lookup
tier: B
risk: low
approval:
  required: true
  granted: true
  why: ["改动落在 apps/backend/app/modules/conversation/router.py（B 档契约级路径）", "确认-续跑链路是工具审批的收尾入口，取数方式变化需确认回归口径"]
---

## 目标与范围

**做成什么**

`_prepare_resume` 补全 assistant 消息 citations 时，不再把整段会话的消息实体读进内存再线性扫描，
改成按主键 + 会话归属读单条消息。

**不做**

- 不改 `POST /{agent_id}/runs/{loop_run_id}/resolve` 的请求字段、响应结构、错误码。
- 不改 citations 的来源与语义（仍是挂起那刻落库的 assistant 消息上的引用，续跑不重新检索）。
- 不改 `list_console_conversation_messages` 的全量消息读取 —— 那是接口契约本身，另案再议。
- 不给 `list_messages` 加分页（会牵动控制台时间线与 embed 快照的返回契约）。

**边界**

只动仓储层一个新增方法 + 路由层一处取数逻辑 + 对应测试，不碰 schema、模型、鉴权。

## 来源与方案比较

- SQLAlchemy 2.0 ORM Querying Guide（<https://docs.sqlalchemy.org/en/20/orm/queryguide/select.html>，
  工程内实际版本 2.0.51，2026-10-26 取用）：主键取单行的标准写法是带条件的 `select()` 或
  `Session.get()`；ORM 指南把「只取需要的行/列」列为避免多余 IO 的默认做法。
- 项目既有约定：`ConversationRepository.get_loop(loop_run_id, conversation_id)` 已经是「主键 + 归属」
  的单条读取写法，本次新增方法与它对齐，调用方不需要自己再比对归属。

**方案 A（选中）**：新增 `get_message(message_id, conversation_id)`，一条
`SELECT ... WHERE id = ? AND conversation_id = ?`；返回 None 时 citations 留空。

**方案 B**：`session.get(ConversationMessage, message_id)` 后由调用方比对 `conversation_id`。

**方案 C**：直接投影 `select(ConversationMessage.citations)`，少取其余列。

三者都是一次查询，差别在归属校验位置、仓储层一致性与返回形态，比较见下节。

## 被否决的选项

- **方案 B（`session.get` + 调用方比对会话）**：归属校验外移到调用方，后续新调用漏比对就会跨会话读到
  别人的消息；identity map 命中时还会跳过 SQL 层的归属条件。否决。
- **方案 C（只投影 citations 列）**：省下的只是列宽，却让该仓储方法返回标量而非 ORM 对象，与
  `repositories.py` 其余方法「返回实体」的形态不一致。否决。
- **保留现状（`list_messages` 全量 + 线性扫描）**：长会话下为了一条记录把整段消息实体读进内存，
  且扫描成本随消息数线性增长。否决。
- **给 `list_messages` 顺手加分页**：会改控制台消息时间线的返回契约（影响前端与 ai-sdk），
  超出本次范围。否决。
- **沿用 `loop.assistant_message_id` 直查但不带会话条件**：本函数里 `loop` 已按会话校验过，但仓储方法
  失去自带隔离，等于把正确性押在调用顺序上。否决。

## 停点判断

- **分档 B**：diff 命中 `apps/backend/app/modules/conversation/router.py`（`**/router.py`），
  按「命中即取最高档」定 B。
- **未命中 A**：不碰 `**/migrations/**`、`**/models.py`、`**/auth/**`、`**/security*.py`，不新建模块目录。
- **审批触发**：不涉及数据模型、API 契约、鉴权或权限语义；但 B 档流程要求在 spec 写完后由人工确认
  方案要点，故 `approval.required: true`。
- **需要用户确认的点**：目标与范围、被否决的选项、验收标准。
- **确认记录**：2026-10-26 用户确认「按方案 A 实施」，随后进入实现。

## 变更点

1. `apps/backend/app/modules/conversation/repositories.py`：新增 `get_message`。

```python
async def get_message(self, message_id: int, conversation_id: int):
    """按主键取一条消息，并限定会话归属，避免跨会话读取。"""
    return await self.session.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == message_id,
            ConversationMessage.conversation_id == conversation_id,
        )
    )
```

2. `apps/backend/app/modules/conversation/router.py`：`_prepare_resume` 的 citations 取数改为单条查询，
   删除 `list_messages` 全量循环；注释保留「续跑不重新检索」的原有意图说明。

```python
citations: list = []
if loop.assistant_message_id:
    message = await repo.get_message(loop.assistant_message_id, conversation.id)
    if message is not None:
        citations = list(message.citations or [])
```

3. `apps/backend/tests/conversation/test_run_confirmation_resume.py`：补两条断言 ——
   续跑后 citations 与挂起前落库内容一致；`get_message` 对别会话的消息 ID 返回 None。

4. 新增 `tools/harness/verify/2026-10-26-resume-citation-lookup.sh`。

## 验收标准

1. `grep -c 'list_messages' apps/backend/app/modules/conversation/router.py` 结果为 0。
2. 新增单测：`get_message` 对本会话消息返回该实体且只发 1 条 SQL；传其他会话的消息 ID 返回 None。
3. `tests/conversation/test_run_confirmation_resume.py` 全部通过，且续跑响应里的 citations 与挂起前
   落库的 assistant 消息逐字段相同。
4. `ruff check` 对改动文件通过。
5. `python3 tools/harness/audit.py` 退出码 0，`tools/harness/verify.sh <id>` 产出 verify.md。
