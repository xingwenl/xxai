---
name: backend-basic-crud-table
description: Use when adding or modifying a basic CRUD table/module in this repo's FastAPI backend with SQLAlchemy, Alembic, repository-service-router layering, and the established response and pagination conventions.
---

# Backend Basic CRUD Table

## Overview

本 skill 用于本仓库 `apps/backend` 下的基础资料型 CRUD 表开发。目标不是“随便把表跑起来”，而是严格复用当前 `user` 模块已经验证过的技术栈、目录结构、分页格式、异常语义和验证方式。

优先把它当成“新模块模板”使用，而不是一次性脚手架。

## When to Use

适用于：

- 新增一个资料型表，并提供基础 CRUD 接口
- 在已有 CRUD 模块上补齐 `list/detail/create/update/delete`
- 需要复用当前仓库已确定的 `FastAPI + SQLAlchemy 2.0 + Alembic` 分层写法
- 需要复用统一分页格式和共享仓储基类

不适用于：

- 登录、密码、JWT、权限、角色、组织关系
- 跨服务架构调整
- 明显超出“基础资料表”的复杂领域建模

## Required Process

必须遵守仓库 Harness 流程：

1. `research`
2. `spec`
3. `plan`
4. `implement`
5. `verify`
6. `acceptance`

若任务涉及以下任一项，在进入实现前必须等待人工确认：

- 数据模型变化
- API 契约变化
- 架构边界变化
- 鉴权或权限行为变化

相关规则先读：

- `AGENTS.md`
- `docs/harness/README.md`
- `docs/harness/policies/global.md`
- 当前 request 文档

## Tech Baseline

以当前 `user` 模块为标准模板：

- ORM：SQLAlchemy 2.0 typed declarative
- Web：FastAPI
- Migration：Alembic
- 分层：`models -> schemas -> repositories -> services -> router`
- 共享模型基类：`app/shared/base_model.py`
- 共享仓储基类：`app/shared/base_repository.py`
- 共享异常：`app/shared/exceptions.py`
- 分页基础：`app/shared/pagination.py`
- 通用响应：`app/shared/responses.py`

## File Layout

新增一个基础 CRUD 模块时，默认补齐这些文件：

- `apps/backend/app/modules/<module>/models.py`
- `apps/backend/app/modules/<module>/schemas.py`
- `apps/backend/app/modules/<module>/repositories.py`
- `apps/backend/app/modules/<module>/services.py`
- `apps/backend/app/modules/<module>/router.py`
- `apps/backend/tests/<module>/`
- `apps/backend/migrations/versions/*.py`（仅当表结构变化时）

## Model Rules

模型写法遵循 `user` 模块：

- 继承 `BaseModel`
- 默认混入 `TimeModel`，统一提供 `created_at` 和 `updated_at`
- 主键使用 typed `mapped_column`
- 唯一约束、索引、非空约束在 ORM 层明确声明
- 基础资料表必须显式声明 `__tablename__`
- 建表命名默认采用“模块前缀 + 资源复数名”规则，避免不同业务域后续碰撞：
  - 系统模块使用 `sys_` 前缀，例如 `sys_users`、`sys_roles`
  - 聊天模块使用 `chat_` 前缀，例如 `chat_messages`、`chat_conversations`
  - 其他模块按同样模式扩展，例如 `<module>_<resources>`
- 不再默认直接使用裸表名如 `users`、`roles`、`messages`；除非已有历史表需要兼容
- 若是已有旧表做增量开发，优先兼容现有表名，不要为了追求统一强改存量表名
- migration、schema、repository、router 中涉及资源命名时，应围绕同一个模块前缀保持一致

示例骨架：

```python
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class SysUser(BaseModel, TimeModel):
    __tablename__ = "sys_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
```

## Schema Rules

请求和响应模型必须分离：

- `Create` 只定义创建入参
- `Update` 使用可选字段，支持局部更新
- `Read` 用于详情和列表项输出
- 列表分页数据优先复用 `PageData[T]`

分页响应结构必须是：

```json
{
  "code": 200,
  "message": "操作成功",
  "data": {
    "page_no": 1,
    "page_size": 10,
    "items": [],
    "total": 0,
    "pages": 1
  }
}
```

非分页接口继续使用 `ApiResponse[T]`。

## Repository Rules

先复用 `BaseRepository`，不要重复发明 CRUD：

- `get_by_id()`
- `get_one_by()`
- `list()`
- `list_by()`
- `count()`
- `exists()`
- `create()`
- `update()`
- `delete()`

模块仓储只保留领域专属查询或轻量包装，例如：

- `get_by_email()`
- `list_<module>()`
- `count_<module>()`
- `create_<module>()`

如果一个逻辑已经能被共享基类表达，就不要在模块仓储里重新写 SQL。

## Service Rules

service 负责业务语义，不负责 HTTP 细节：

- 创建前做必要的唯一性检查
- 详情/更新/删除前先查对象，不存在时抛 `NotFoundException`
- 空 patch 抛 `BadRequestException`
- 业务冲突抛 `ConflictException`
- 列表服务返回已经组装好的分页 `data`

不要在 router 里写业务判断。

## Router Rules

router 只做 4 件事：

1. 收请求参数
2. 注入 `AsyncSession`
3. 调用 service
4. 返回标准响应模型

基础接口模板：

- `POST /api/v1/<resources>`
- `GET /api/v1/<resources>/{id}`
- `GET /api/v1/<resources>`
- `PATCH /api/v1/<resources>/{id}`
- `DELETE /api/v1/<resources>/{id}`

分页列表接口：

- 入参使用 `PaginationParams = Depends(pagination_dependency)`
- `response_model` 使用 `PageResponse[<ListDataSchema>]`

## Migration Rules

出现表结构变化时：

- 接通 `BaseModel.metadata`
- 生成 Alembic migration
- 人工审阅 migration 内容
- 在 request 文档中记录这次数据模型变化

如果只是 CRUD 逻辑、分页格式、异常语义变化，不要新增 migration。

## Verification Checklist

最小验证默认执行：

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
- `apps/backend/.venv/bin/ruff check apps/backend`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py apps/backend/migrations`

涉及列表接口时，再补：

- OpenAPI 检查分页 schema
- 核对 `data.page_no/page_size/items/total/pages`

涉及表结构变化时，再补：

- `alembic heads`
- `alembic upgrade head`
- 数据库内表和版本号核验

## Default Decision Rules

做基础 CRUD 表时，默认按下面的收敛原则执行：

- 先做资料型模块，不默认加入登录/密码/权限
- 先做最小字段闭环，不提前扩展复杂关系
- 优先复用共享基类和共享分页，不单模块自创协议
- 优先写最小可验证测试，不跳过验证记录

## References

优先参考这些已落地文件：

- `apps/backend/app/modules/user/models.py`
- `apps/backend/app/modules/user/schemas.py`
- `apps/backend/app/modules/user/repositories.py`
- `apps/backend/app/modules/user/services.py`
- `apps/backend/app/modules/user/router.py`
- `apps/backend/app/shared/base_model.py`
- `apps/backend/app/shared/base_repository.py`
- `apps/backend/app/shared/pagination.py`
- `apps/backend/app/shared/exceptions.py`
- `docs/harness/requests/2026-07-19-user-module-minimum/`
