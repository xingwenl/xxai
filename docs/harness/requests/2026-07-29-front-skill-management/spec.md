# 技能管理规格

## 目标

- 为当前登录用户提供平台内技能配置和智能体绑定管理。
- 支持技能创建、编辑、启用/停用、硬删除。
- 支持查看某智能体已绑定技能，并执行绑定和解绑。
- 复用现有 Jinja2 沙箱模板渲染和会话 runtime 启用规则。

## 范围

### 后端

- `GET /api/v1/platforms/{platform_id}/skills`：分页返回技能列表。
- 保留 `POST /api/v1/platforms/{platform_id}/skills`。
- `PATCH /api/v1/platforms/{platform_id}/skills/{skill_id}`：修改名称、描述、模板、schema、hooks 和 `is_active`。
- `DELETE /api/v1/platforms/{platform_id}/skills/{skill_id}`：硬删除技能并级联删除绑定。
- `GET /api/v1/platforms/{platform_id}/agents/{agent_id}/skills`：查询智能体绑定。
- 保留 `PUT /api/v1/platforms/{platform_id}/agents/{agent_id}/skills`，新增 `DELETE /.../skills/{skill_id}` 解绑。
- 所有管理接口复用当前用户的平台管理员校验。

### 前端

- 新增 `/ai/skills` 路由和技能管理页面。
- 平台选择、技能列表、创建/编辑表单、状态开关和硬删除确认。
- 编辑 `instruction_template`、`parameter_schema`、`lifecycle_hooks`，JSON 字段提供格式校验提示。
- 绑定面板选择平台内智能体，显示已绑定技能并支持绑定/解绑。
- 使用真实 `/platforms/{platform_id}/...` 接口，不再调用旧 `/api/skills`。

## 非目标

- 不新增技能表字段或迁移。
- 不实现技能包上传、安装、资源文件浏览；旧前端类型中的 Skill Package 不属于当前后端模型。
- 不修改 Jinja2 runtime、会话 prompt 拼装和技能执行权限模型。
- 不实现平台管理。

## 风险

- 硬删除技能不可恢复，必须二次确认。
- 停用技能不会解除绑定，但会立即阻止运行时加载。
- JSON 配置可能格式正确但业务语义不完整，页面需要明确错误提示。

## 停点判断

- 架构边界变化：否。
- 数据模型变化：否。
- API 契约变化：是，新增管理和解绑接口，进入实现前需人工确认。
- 鉴权或权限行为变化：否，复用平台管理员校验。
- 人工确认：是。

## 验收标准

- OpenAPI 暴露技能列表、更新、删除、绑定列表和解绑接口。
- 非平台管理员不能访问技能管理和绑定接口。
- 技能停用后不进入会话 runtime；重新启用后恢复。
- 硬删除技能后绑定记录一并删除。
- 前端能完成技能 CRUD、启停、硬删除、绑定和解绑。
- 前端变更文件 ESLint/Prettier、后端定向测试/Ruff 通过。

## 变更记录

### 2026-07-29 初始版本

- 变更原因：继续实现 AI 管理模块，建立技能管理独立闭环。
- 变更内容：确定平台级技能 CRUD 和智能体绑定管理范围。
- 影响章节：全部。
- 是否触发人工确认：是。
