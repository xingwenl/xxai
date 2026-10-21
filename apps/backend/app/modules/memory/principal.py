"""记忆主体：一条记忆究竟属于谁。

同一张 ``user_memories`` 表要容纳两种完全不同的身份域：

- **后台用户**（``sys_users.id``）：控制台、REST 对话与受信任入口的浮动助手，
  用户能登录、能在「我的记忆」页面看到并删除；
- **嵌入终端用户**（``platform_embed_clients.client_id`` +
  ``platform_end_users.id``）：第三方站点带来的访客，没有后台账号，只能按
  「哪个 Client 的哪个访客」隔离。

两种主体**不合并**：``external_user_id`` 由接入方自己赋值，两个 Client 的
``"1"`` 未必是同一个人；跨主体合并需要可信身份，当前没有。因此主体在落库时
就必须定死，读侧也按同一口径过滤——把这个判断散落在各个查询里迟早会漏一处，
那漏掉的一处就是串号。

本类刻意不是多态 ``(principal_type, principal_id)`` 单列：类型化列才能建外键，
删用户、删 Client 时数据库会级联清理，不会留下查不到也删不掉的孤儿记忆
（取舍见 docs/adr/0016-end-user-memory.md）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryPrincipal:
    """一条记忆的归属主体；``user_id`` 与 ``(client_id, end_user_id)`` 恰好一种。"""

    platform_id: int
    user_id: int | None = None
    client_id: str | None = None
    end_user_id: int | None = None

    def __post_init__(self) -> None:
        if self.platform_id < 1:
            raise ValueError("memory principal requires a platform")
        has_user = self.user_id is not None
        has_end_user = self.client_id is not None and self.end_user_id is not None
        if has_user and has_end_user:
            raise ValueError("memory principal must be exactly one subject")
        if not has_user and not has_end_user:
            raise ValueError("memory principal must have a subject")
        if (self.client_id is None) != (self.end_user_id is None):
            # 端用户主体必须同时有 Client 与终端用户：只有 one 列时无法表达归属，
            # 也无法与「后台用户主体」区分（CHECK 约束与这里保持同一规则）。
            raise ValueError(
                "end-user principal requires both client_id and end_user_id"
            )

    @property
    def kind(self) -> str:
        """主体类型，只用于日志与排障，不落库。"""

        return "user" if self.user_id is not None else "end_user"

    def owns(self, row) -> bool:
        """判断一行记忆是否属于本主体；删除、修改前用它做归属校验。"""

        if row.platform_id != self.platform_id:
            return False
        if self.user_id is not None:
            return row.user_id == self.user_id
        return row.client_id == self.client_id and row.end_user_id == self.end_user_id


def user_principal(platform_id: int, user_id: int) -> MemoryPrincipal:
    """后台用户主体（``sys_users.id``）。"""

    return MemoryPrincipal(platform_id=platform_id, user_id=user_id)


def end_user_principal(
    *, platform_id: int, client_id: str, end_user_id: int
) -> MemoryPrincipal:
    """嵌入终端用户主体（Client + 终端用户）。"""

    return MemoryPrincipal(
        platform_id=platform_id, client_id=client_id, end_user_id=end_user_id
    )
