# 验证记录：智能体接入店铺运营项目（查询我的店铺）

## 执行命令

- `poetry run pytest tests/shop_agent tests/tools -q` → `11 passed in 2.76s`
- `poetry run pytest tests/builtin_tool -q` → `49 passed in 3.43s`
- `poetry run pytest tests/embed -q` → `15 passed in 4.20s`
- `poetry run pytest tests/gateway -q` → `71 passed, 1 skipped`
- `poetry run pytest tests/builtin_tool tests/embed tests/gateway tests/shop_agent tests/tools -q --import-mode=importlib` → `146 passed, 1 skipped`
- `poetry run ruff check app/modules/shop_agent app/modules/tools/business/store_ops_query.py app/modules/builtin_tool/services.py app/modules/tools/business/framework.py tests/shop_agent tests/tools` → `All checks passed!`
- `poetry run python -c "...config/shop_agent_router/list_business_tools..."` → 配置加载、`/shop-agent/session` 路由注册、`store_ops_query` 已注册
- `cd apps/shop && pnpm install && pnpm build` → 依赖安装成功，`vite build` 构建成功（40 modules，`dist/` 产物生成）
- `python3 tools/harness/audit.py` → 本 request 无 ERROR/WARN
- `poetry run ruff check app/modules/tools/business/store_ops_query.py tests/tools/test_store_ops_query.py` → `All checks passed!`
- `poetry run pytest -q --import-mode=importlib` → `472 passed, 1 skipped`
- `cd apps/shop && pnpm build` → `vite build` 成功（40 modules，`dist/` 产物生成，ShopList 移动端卡片编译通过）
- `poetry run ruff check app/modules/tools/shop app/modules/tools/business/registry.py tests/tools/test_store_ops_query.py tests/tools/test_show_shop_list.py tests/conversation/test_custom_content.py` → `All checks passed!`
- `poetry run pytest tests/tools/test_store_ops_query.py tests/tools/test_show_shop_list.py tests/conversation/test_custom_content.py -q` → `18 passed`
- `poetry run pytest -q --import-mode=importlib` → `472 passed, 1 skipped`（分层重构后全量无回归）
- `poetry run ruff check app/modules/tools/shop tests/tools/test_order_query.py` → `All checks passed!`
- `poetry run pytest tests/tools/test_order_query.py tests/tools/test_store_ops_query.py tests/tools/test_show_shop_list.py tests/conversation/test_custom_content.py -q` → `24 passed`
- `poetry run pytest -q --import-mode=importlib` → `480 passed, 1 skipped`（接入 order_query 后全量无回归）
- `poetry run pytest tests/tools/test_store_ops_query.py tests/tools/test_show_shop_list.py tests/tools/test_order_query.py -q` → `16 passed`（店铺筛选参数透传后单测通过）
- `poetry run pytest -q --import-mode=importlib` → `481 passed, 1 skipped`（筛选参数透传后全量无回归）

## 预期结果

- 新增后端配置项（`STORE_OPS_BASE_URL` 等）可加载；
- `POST /api/v1/shop-agent/session` 路由注册；`store_ops_query` 进入业务工具注册表；
- 工具 mock 测试覆盖：店铺列表成功、401（token 过期）错误透传、未登录、网关不可达；
- 会话接口测试覆盖：路由契约、店铺 token 校验（成功/用户不匹配/无效/不可达）、Redis 写入（TTL=43200）；
- 既有 builtin_tool / embed / gateway 测试无回归；
- `apps/shop` 前端可构建，登录页 + embedded 聊天页可本地联调。

## 实际结果

- 全部符合预期：后端 146 项测试通过（含新增 11 项）、ruff 无错误、前端构建成功。
- 已知既有问题：`tests/builtin_tool tests/embed tests/gateway` 三目录合并收集冲突（同名 `test_models.py` 模块冲突），与本次改动无关，按仓库惯例使用 `--import-mode=importlib` 规避（146 passed）；单目录分别执行均全绿。
- 代码核对：`store_ops_query` 返回店铺字段白名单（不含 hua8 响应中的敏感字段）；工具错误经 `BusinessToolError.message` 透传（`builtin_tool/services.py` 已在错误 dict 中包含 `message`，模型可见）。
- 渲染对齐：`store_ops_query.list_my_shops` 单测断言输出 `kind=custom` + `component_name=ShopList`，`props.shops` 条目含 hua8 原字段（`platformStoreName`/`principalUserName`/`platformStoreId`/`tagList`），`tagList` 名称数组透传、`secret` 字段被白名单剔除、`fallback` 自动生成；`ShopList.vue` 展示字段与白名单一致，构建通过。
- 分层与解耦：`store_ops_query`（`tools/shop/data/`）返回纯数据 `kind=store_ops_shop_list`；`show_shop_list`（`tools/shop/ui/`）返回 `kind=custom` ShopList 渲染块并复用 `data/client.fetch_my_shops`；注册表同时含两个工具，旧 demo `shop_list.py` 已删除；`list_business_tools()` 冒烟验证通过。
- 订单接入：`order_query` 单测覆盖注册契约、未登录、成功白名单（剔除 `recipient_phone`/`op_desc`/`secret`，`goods` 裁剪为 `product_name/quantity/price`，total 字符串转 int）、日期转 epoch（Asia/Shanghai，end 为当日 23:59:59）、非法日期稳定错误码、401 错误透传。

## 失败项与例外

- 真实 hua8 联调未执行：依赖店铺系统环境、验证码登录与 `EMBED_CLIENT_ID/SECRET/AGENT_ID` 配置，待用户配置后人工联调（记录步骤见 `apps/shop/README.md`）。
- 浏览器→hua8 登录接口联调未执行（本地由 vite 代理 `/hua8-api` 规避跨域，生产需部署层反向代理）。
- 智能体启用：目标 Agent 需在管理后台启用内置工具 `store_ops_query` 绑定（与 `knowledge_search` 相同机制），待用户配置 Embed 时一并处理。
