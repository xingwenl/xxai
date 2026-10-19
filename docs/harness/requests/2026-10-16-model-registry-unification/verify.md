---
source: script
request: 2026-10-16-model-registry-unification
ranAt: "2026-10-17 08:30:30 CST"
exitCode: 3
---

## 已执行的命令与结果

```text
### AC1 迁移往返：删三列 + 存量提升为 chat 条目与绑定 + downgrade 可逆

```bash
migration_roundtrip
```

NOTICE:  database "ai_base_migration_check" does not exist, skipping
DROP DATABASE
CREATE DATABASE
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 20260719_0001, create users table
INFO  [alembic.runtime.migration] Running upgrade 20260719_0001 -> 20260720_0002, add user role foundation
INFO  [alembic.runtime.migration] Running upgrade 20260720_0002 -> 20260723_0003, create platforms and platform admins
INFO  [alembic.runtime.migration] Running upgrade 20260723_0003 -> 20260723_0004, create agents and immutable agent versions
INFO  [alembic.runtime.migration] Running upgrade 20260723_0004 -> 20260723_0005, create knowledge base, documents, chunks and ingestion tasks
INFO  [alembic.runtime.migration] Running upgrade 20260723_0005 -> 20260723_0006, create configurable skills and agent bindings
INFO  [alembic.runtime.migration] Running upgrade 20260723_0006 -> 20260725_0007, create remote MCP configuration, confirmations and audit logs
INFO  [alembic.runtime.migration] Running upgrade 20260725_0007 -> 20260725_0008, create agent knowledge bindings and conversations
INFO  [alembic.runtime.migration] Running upgrade 20260725_0008 -> 20260726_0009, add embed clients and platform end users
INFO  [alembic.runtime.migration] Running upgrade 20260726_0009 -> 20260728_0010, add host tool policies and call audits
INFO  [alembic.runtime.migration] Running upgrade 20260728_0010 -> 20260729_0011, add agent active state
INFO  [alembic.runtime.migration] Running upgrade 20260729_0011 -> 20260730_0012, add model usage detail records
INFO  [alembic.runtime.migration] Running upgrade 20260730_0012 -> 20260731_0013, add temporary tool capability to embed clients
INFO  [alembic.runtime.migration] Running upgrade 20260731_0013 -> 20260804_0014, add skill package storage metadata
INFO  [alembic.runtime.migration] Running upgrade 20260804_0014 -> 20260804_0015, add skill script execution audit
INFO  [alembic.runtime.migration] Running upgrade 20260804_0015 -> 20260804_0016, 修正既有技能包的存储定位键。
INFO  [alembic.runtime.migration] Running upgrade 20260804_0016 -> 20260805_0017, add agent loop observability and message content blocks
INFO  [alembic.runtime.migration] Running upgrade 20260805_0017 -> 20260806_0018, add knowledge retrieval threshold and top k
INFO  [alembic.runtime.migration] Running upgrade 20260806_0018 -> 20260807_0019, add builtin HTTP GET bindings and conversation assets
INFO  [alembic.runtime.migration] Running upgrade 20260807_0019 -> 20260807_0020, allow Embed principals in MCP audit and confirmation records
INFO  [alembic.runtime.migration] Running upgrade 20260807_0020 -> 20260813_0021, add thinking text to agent loop steps
INFO  [alembic.runtime.migration] Running upgrade 20260813_0021 -> 20260823_0022, create wechat bot bindings
INFO  [alembic.runtime.migration] Running upgrade 20260823_0022 -> 20260823_0023, add qr flow fields to wechat bot bindings
INFO  [alembic.runtime.migration] Running upgrade 20260823_0023 -> 20260823_0024, enable http_post for agents already using http_get
INFO  [alembic.runtime.migration] Running upgrade 20260823_0024 -> 20260825_0025, conversation_asset_processing 和 conversation_asset_chunks 表
INFO  [alembic.runtime.migration] Running upgrade 20260825_0025 -> 20260826_0026, conversation_asset_processing 增加 extracted_text 缓存列
INFO  [alembic.runtime.migration] Running upgrade 20260826_0026 -> 20260827_0027, conversation_asset_embeddings 表：附件切块会话级向量缓存
INFO  [alembic.runtime.migration] Running upgrade 20260827_0027 -> 20260827_0028, agent_versions 增加 capabilities 附件能力配置列
INFO  [alembic.runtime.migration] Running upgrade 20260827_0028 -> 20260827_0029, 平台模型注册表与 Agent 模型绑定
INFO  [alembic.runtime.migration] Running upgrade 20260827_0029 -> 20260828_0030, 为已有 Agent 启用 attachment_search 内置工具
INFO  [alembic.runtime.migration] Running upgrade 20260828_0030 -> 20260831_0031, 将 sys_users.password 列加宽到 160，以容纳 scrypt 密码哈希
INFO  [alembic.runtime.migration] Running upgrade 20260831_0031 -> 20260831_0032, 为已有 Agent 启用 knowledge_search 内置工具
INFO  [alembic.runtime.migration] Running upgrade 20260831_0032 -> 20260903_0033, agent_versions 新增 context_window_tokens 可空列
INFO  [alembic.runtime.migration] Running upgrade 20260903_0033 -> 20260919_0034, 新增任务定义与任务运行两张表
INFO  [alembic.runtime.migration] Running upgrade 20260919_0034 -> 20260919_0035, tasks 新增终端用户执行身份列
INFO  [alembic.runtime.migration] Running upgrade 20260919_0035 -> 20261013_0036, 新增工作流定义、工作流运行、步骤运行三张表，并给任务表加工作流外键
INFO  [alembic.runtime.migration] Running upgrade 20261013_0036 -> 20261014_0037, Agent 绑定编排工作流：新增绑定列，并把「同一工作流串行」的约束让开会话内触发
INFO  [alembic.runtime.migration] Running upgrade 20261014_0037 -> 20261015_0038, 运行期委派子 Agent：给运行记录加父运行列，让子运行可回溯到父运行
已升级到基线 20261015_0038
INSERT 0 1
INSERT 0 1
INSERT 0 1
基线库已插入 1 行带 model_name/model_base_url/api_key_encrypted 的 Agent 版本
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 20261015_0038 -> 20261016_0039, 对话主模型并入平台模型注册表
升级后 agent_versions 三列残留数：0（应为 0）
存量提升结果：chat|legacy-chat-model|true（应为 chat|legacy-chat-model|true）
存量绑定：migcheck-agent|chat|true（应为 migcheck-agent|chat|true）
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 20261016_0039 -> 20261015_0038, 对话主模型并入平台模型注册表
downgrade 回填：legacy-chat-model|http://legacy.local/v1|ciphertext|0|0（应为 legacy-chat-model|http://legacy.local/v1|ciphertext|0|0）
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 20261015_0038 -> 20261016_0039, 对话主模型并入平台模型注册表
再次 upgrade 后条目/绑定数：1|1（应为 1|1）
DROP DATABASE
临时库已删除
结果：通过

### AC2 agent 模块不再读写 api_key_encrypted / model_base_url / version.model_name

```bash
assert_no_model_credentials_in_agent_module
```

agent 模块内命中：
<无>
结果：通过

### AC2 AgentVersion 模型定义里已无 model_name 列

```bash
assert_model_name_column_dropped
```

agent/models.py 内 model_name 命中：
<无>
结果：通过

### AC6 后端回归 tests/model_registry tests/agent tests/conversation tests/gateway tests/tasks

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/model_registry tests/agent tests/conversation tests/gateway tests/tasks -q
```

........................................................................ [ 20%]
........................................................................ [ 41%]
........................................................................ [ 62%]
..........................................s............................. [ 83%]
........................................................                 [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
343 passed, 1 skipped, 1 warning in 14.16s
结果：通过

### AC7 前端构建与类型检查 pnpm --dir apps/front build

```bash
pnpm --dir apps/front build
```


> shadcn-admin@2.2.1 build /Users/lixingwen/xw/study/ai-base/apps/front
> tsc -b && vite build

08:30:14 [vite] warning: `esbuild` option was specified by "vite:react-swc" plugin. This option is deprecated, please use `oxc` instead.
vite v8.0.3 building client environment for production...
[2Ktransforming...✓ 4769 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                        4.29 kB │ gzip:   1.11 kB
dist/assets/dashboard-light-P68E3aSp.png             450.98 kB
dist/assets/dashboard-dark-XXx_X8s4.png              461.76 kB
dist/assets/_workflowId-DLioOiRN.css                  15.41 kB │ gzip:   2.56 kB
dist/assets/chats-CaOP_eO-.css                        27.42 kB │ gzip:   5.18 kB
dist/assets/authenticated-layout-CDYeKAlx.css         43.25 kB │ gzip:   7.79 kB
dist/assets/index-C7reYhsj.css                       119.22 kB │ gzip:  19.46 kB
dist/assets/dist-DInpRvmT.js                           0.06 kB │ gzip:   0.08 kB
dist/assets/404-C9pZu2RG.js                            0.07 kB │ gzip:   0.08 kB
dist/assets/500-DdbKDlAx.js                            0.07 kB │ gzip:   0.08 kB
dist/assets/403-BRqf98c3.js                            0.07 kB │ gzip:   0.08 kB
dist/assets/503-BopP2-6o.js                            0.08 kB │ gzip:   0.09 kB
dist/assets/401-B-39_H_3.js                            0.08 kB │ gzip:   0.09 kB
dist/assets/route-CHvy5rF9.js                          0.08 kB │ gzip:   0.09 kB
dist/assets/route-DUbS7aJJ.js                          0.08 kB │ gzip:   0.09 kB
dist/assets/check-B_unxq20.js                          0.12 kB │ gzip:   0.14 kB
dist/assets/chevron-down-Bc3q33zG.js                   0.12 kB │ gzip:   0.14 kB
dist/assets/matchContext-qVyDZbt3.js                   0.14 kB │ gzip:   0.12 kB
dist/assets/loader-circle-CMyn1grl.js                  0.14 kB │ gzip:   0.15 kB
dist/assets/plus-fTpbcDk4.js                           0.15 kB │ gzip:   0.15 kB
dist/assets/arrow-left-k8R5G8rH.js                     0.16 kB │ gzip:   0.16 kB
dist/assets/arrow-right-Ccm5WDmK.js                    0.16 kB │ gzip:   0.16 kB
dist/assets/search-DrCKhDEc.js                         0.17 kB │ gzip:   0.17 kB
dist/assets/auth-DkTnHMrE.js                           0.19 kB │ gzip:   0.14 kB
dist/assets/smartphone-CBjGnhcd.js                     0.19 kB │ gzip:   0.18 kB
dist/assets/rotate-cw--9XEly3e.js                      0.20 kB │ gzip:   0.18 kB
dist/assets/time-B4xQYaxw.js                           0.20 kB │ gzip:   0.16 kB
dist/assets/credit-card-C3h36KXr.js                    0.20 kB │ gzip:   0.18 kB
dist/assets/sign-up-DUYuxDKK.js                        0.22 kB │ gzip:   0.19 kB
dist/assets/git-branch-j3QCD4s-.js                     0.22 kB │ gzip:   0.19 kB
dist/assets/upload-B29dcOQU.js                         0.23 kB │ gzip:   0.19 kB
dist/assets/copy-BvKuWiOn.js                           0.23 kB │ gzip:   0.21 kB
dist/assets/link-2-DlfNa-v1.js                         0.24 kB │ gzip:   0.20 kB
dist/assets/skeleton-Bcb6XioF.js                       0.24 kB │ gzip:   0.20 kB
dist/assets/database-tPcUSlPG.js                       0.24 kB │ gzip:   0.20 kB
dist/assets/chart-column-DkD_NHo1.js                   0.25 kB │ gzip:   0.19 kB
dist/assets/external-link-DQuYHGle.js                  0.25 kB │ gzip:   0.20 kB
dist/assets/eye-Bm8LtpzF.js                            0.25 kB │ gzip:   0.20 kB
dist/assets/dist-BncS-ueq.js                           0.25 kB │ gzip:   0.18 kB
dist/assets/dist-56EZmKtB.js                           0.26 kB │ gzip:   0.21 kB
dist/assets/triangle-alert-Bn8dKm_c.js                 0.26 kB │ gzip:   0.21 kB
dist/assets/shield-CTdVjnzm.js                         0.27 kB │ gzip:   0.22 kB
dist/assets/send-osa1GHNn.js                           0.29 kB │ gzip:   0.23 kB
dist/assets/sign-in-Dyl2DA6V.js                        0.29 kB │ gzip:   0.24 kB
dist/assets/square-pen-CFDJHkrt.js                     0.32 kB │ gzip:   0.24 kB
dist/assets/refresh-cw-Clx8RcqG.js                     0.32 kB │ gzip:   0.22 kB
dist/assets/bot-oM3mG9yd.js                            0.32 kB │ gzip:   0.23 kB
dist/assets/trash-2-BWAOBt-T.js                        0.32 kB │ gzip:   0.21 kB
dist/assets/server-DffUI9RW.js                         0.33 kB │ gzip:   0.21 kB
dist/assets/platform-BhTDig3N.js                       0.34 kB │ gzip:   0.20 kB
dist/assets/main-C2Sxkjt2.js                           0.35 kB │ gzip:   0.26 kB
dist/assets/useNavigate-lmXrTWj5.js                    0.35 kB │ gzip:   0.25 kB
dist/assets/key-round-Bvqfhw5I.js                      0.35 kB │ gzip:   0.26 kB
dist/assets/file-code-corner-BY_BVQZE.js               0.36 kB │ gzip:   0.25 kB
dist/assets/show-submitted-data-ClfjgKfP.js            0.36 kB │ gzip:   0.27 kB
dist/assets/messages-square-BfvGWyL5.js                0.36 kB │ gzip:   0.25 kB
dist/assets/dist-B1m5gfE0.js                           0.37 kB │ gzip:   0.27 kB
dist/assets/dist-BEhS7_6s.js                           0.42 kB │ gzip:   0.32 kB
dist/assets/wrench-BtNizEuh.js                         0.48 kB │ gzip:   0.31 kB
dist/assets/cable-CQzS3SYI.js                          0.49 kB │ gzip:   0.27 kB
dist/assets/conversation-list-island-iVg-9LDd.js       0.51 kB │ gzip:   0.36 kB
dist/assets/dist-B0IovpU2.js                           0.53 kB │ gzip:   0.37 kB
dist/assets/logo-CGVUe-wf.js                           0.54 kB │ gzip:   0.36 kB
dist/assets/auth-layout-DXa3GdRw.js                    0.54 kB │ gzip:   0.31 kB
dist/assets/dist-DP4XSlwp.js                           0.55 kB │ gzip:   0.36 kB
dist/assets/redirect-l1N9PZdQ.js                       0.56 kB │ gzip:   0.33 kB
dist/assets/model-usage-D-9jP4iP.js                    0.56 kB │ gzip:   0.29 kB
dist/assets/content-section-oY_-uLY0.js                0.62 kB │ gzip:   0.32 kB
dist/assets/role-lLfrvehf.js                           0.63 kB │ gzip:   0.32 kB
dist/assets/user-Dg_nPzcA.js                           0.63 kB │ gzip:   0.32 kB
dist/assets/textarea-8WHxSkOJ.js                       0.67 kB │ gzip:   0.41 kB
dist/assets/useRouter-DHFlR_BM.js                      0.69 kB │ gzip:   0.39 kB
dist/assets/label-CXoMKpCv.js                          0.71 kB │ gzip:   0.45 kB
dist/assets/maintenance-error-HFHHUYxO.js              0.73 kB │ gzip:   0.41 kB
dist/assets/embed-clients-QDqtTqIV.js                  0.75 kB │ gzip:   0.27 kB
dist/assets/separator-C0o5egtw.js                      0.80 kB │ gzip:   0.44 kB
dist/assets/shim-cR3Cro0T.js                           0.82 kB │ gzip:   0.44 kB
dist/assets/model-registry-BwDg6xEQ.js                 0.84 kB │ gzip:   0.35 kB
dist/assets/useSearch-DoidwBfb.js                      0.84 kB │ gzip:   0.47 kB
dist/assets/input-CZPbkjGW.js                          0.86 kB │ gzip:   0.47 kB
dist/assets/lazyRouteComponent-QIzUmY2c.js             0.88 kB │ gzip:   0.52 kB
dist/assets/forbidden-DgrXM5BR.js                      0.90 kB │ gzip:   0.49 kB
dist/assets/learn-more--FVd8Ncf.js                     0.90 kB │ gzip:   0.53 kB
dist/assets/unauthorized-error-Cqfrdqc1.js             0.91 kB │ gzip:   0.50 kB
dist/assets/http-DT18C6X_.js                           0.95 kB │ gzip:   0.57 kB
dist/assets/_error-CZeRbzNk.js                         0.96 kB │ gzip:   0.50 kB
dist/assets/header-e-JjnRIG.js                         0.97 kB │ gzip:   0.58 kB
dist/assets/host-tools-C58GHyGs.js                     1.03 kB │ gzip:   0.30 kB
dist/assets/search-Dikurbld.js                         1.03 kB │ gzip:   0.61 kB
dist/assets/task-BF3VsRTj.js                           1.07 kB │ gzip:   0.39 kB
dist/assets/sign-in-Dmxmd910.js                        1.09 kB │ gzip:   0.54 kB
dist/assets/card-qIsdcATF.js                           1.10 kB │ gzip:   0.44 kB
dist/assets/alert-D9g1IYyX.js                          1.11 kB │ gzip:   0.55 kB
dist/assets/radio-group-BAtl8s-y.js                    1.11 kB │ gzip:   0.58 kB
dist/assets/agent-DuMgWCPC.js                          1.12 kB │ gzip:   0.37 kB
dist/assets/help-center-BZOCIudt.js                    1.12 kB │ gzip:   0.65 kB
dist/assets/preload-helper-C5gCWwwF.js                 1.19 kB │ gzip:   0.68 kB
dist/assets/agent-form-schema-DO6xyOKw.js              1.20 kB │ gzip:   0.69 kB
dist/assets/table-BQLO90Aw.js                          1.20 kB │ gzip:   0.48 kB
dist/assets/users-C8IyAhcb.js                          1.20 kB │ gzip:   0.59 kB
dist/assets/badge-OmG5jraG.js                          1.22 kB │ gzip:   0.59 kB
dist/assets/dist-D_83zX3a.js                           1.25 kB │ gzip:   0.63 kB
dist/assets/mcp-servers-DH2YLKm8.js                    1.30 kB │ gzip:   0.42 kB
dist/assets/theme-provider-D2sOwWPv.js                 1.37 kB │ gzip:   0.70 kB
dist/assets/createLucideIcon-DTF1kO5E.js               1.38 kB │ gzip:   0.77 kB
dist/assets/theme-switch-Bd4-qe1A.js                   1.40 kB │ gzip:   0.67 kB
dist/assets/password-input-BOTawp3e.js                 1.42 kB │ gzip:   0.77 kB
dist/assets/profile-dropdown-BoCoPZyi.js               1.46 kB │ gzip:   0.70 kB
dist/assets/form-D42SCiIp.js                           1.73 kB │ gzip:   0.76 kB
dist/assets/display-DBTbTdSt.js                        1.79 kB │ gzip:   0.86 kB
dist/assets/knowledge-DZm-_91z.js                      1.82 kB │ gzip:   0.61 kB
dist/assets/skills-B0nTnUG7.js                         1.89 kB │ gzip:   0.53 kB
dist/assets/sign-in-2-Bzh1lUxa.js                      2.08 kB │ gzip:   0.85 kB
dist/assets/dist-BXvp9l4E.js                           2.10 kB │ gzip:   0.93 kB
dist/assets/use-active-platform-Bcvt-Wba.js            2.15 kB │ gzip:   0.99 kB
dist/assets/forgot-password-DykYFXop.js                2.19 kB │ gzip:   1.08 kB
dist/assets/useMutation-C5SNe3p6.js                    2.29 kB │ gzip:   0.95 kB
dist/assets/workflow-DpHuW4iU.js                       2.31 kB │ gzip:   0.85 kB
dist/assets/dialog-ByDf2rLR.js                         2.37 kB │ gzip:   0.88 kB
dist/assets/collapsible-1KwHNzu7.js                    2.53 kB │ gzip:   1.05 kB
dist/assets/switch-DmJfu1hE.js                         2.79 kB │ gzip:   1.33 kB
dist/assets/route-tIqT48Uf.js                          3.21 kB │ gzip:   1.31 kB
dist/assets/user-auth-form-DFTvzwE6.js                 3.44 kB │ gzip:   1.50 kB
dist/assets/settings-dDLmB5xY.js                       3.45 kB │ gzip:   1.40 kB
dist/assets/react-dom-B0mxLzjk.js                      3.54 kB │ gzip:   1.34 kB
dist/assets/dist-BmBKpw8c.js                           3.56 kB │ gzip:   1.60 kB
dist/assets/dist-CQ70Vynn.js                           3.61 kB │ gzip:   1.59 kB
dist/assets/tabs--9NGdQAq.js                           3.68 kB │ gzip:   1.54 kB
dist/assets/route-7G2yuglR.js                          3.75 kB │ gzip:   1.80 kB
dist/assets/route-y4LkJ9aG.js                          3.93 kB │ gzip:   1.59 kB
dist/assets/route-DsRILG6Q.js                          4.18 kB │ gzip:   1.21 kB
dist/assets/button-DldY7v7e.js                         4.20 kB │ gzip:   1.81 kB
dist/assets/checkbox-CkenTkU3.js                       4.31 kB │ gzip:   1.83 kB
dist/assets/dist-C8je_4Yy.js                           4.46 kB │ gzip:   1.92 kB
dist/assets/sign-up-D2ZAnEFn.js                        4.47 kB │ gzip:   1.54 kB
dist/assets/appearance-Du7Mv-o4.js                     4.55 kB │ gzip:   1.36 kB
dist/assets/_principalType._principalId-BbURXGVK.js    4.68 kB │ gzip:   1.91 kB
dist/assets/notifications-kw8YWebZ.js                  4.83 kB │ gzip:   1.33 kB
dist/assets/user-management-ruYPBKi2.js                5.09 kB │ gzip:   2.05 kB
dist/assets/confirm-dialog-CrYzLFZv.js                 5.30 kB │ gzip:   1.92 kB
dist/assets/sign-out-dialog-IW0BVHpD.js                5.43 kB │ gzip:   2.39 kB
dist/assets/dist-DRN9m38s.js                           5.45 kB │ gzip:   2.11 kB
dist/assets/popover-DkSPeN_8.js                        5.58 kB │ gzip:   1.99 kB
dist/assets/_conversationId-DjhHULtW.js                5.91 kB │ gzip:   2.52 kB
dist/assets/apps-BjBEZDpG.js                           6.38 kB │ gzip:   2.28 kB
dist/assets/ai-html-pages-BHTcTmus.js                  6.88 kB │ gzip:   2.68 kB
dist/assets/platforms-Bay7AIvs.js                      6.93 kB │ gzip:   2.60 kB
dist/assets/bots-C76GZAyR.js                           7.80 kB │ gzip:   2.90 kB
dist/assets/jsx-runtime-Bg_NI1en.js                    8.52 kB │ gzip:   3.25 kB
dist/assets/useQuery-BZD8L8q4.js                       8.75 kB │ gzip:   3.20 kB
dist/assets/conversations-BhJfkJTI.js                  8.88 kB │ gzip:   2.90 kB
dist/assets/value-Dow4fuvN.js                          9.23 kB │ gzip:   3.96 kB
dist/assets/roles-CtJOHwN3.js                          9.25 kB │ gzip:   3.19 kB
dist/assets/wechat-bots-BV4tevgB.js                    9.90 kB │ gzip:   3.71 kB
dist/assets/_taskId-Bgae6K37.js                       10.40 kB │ gzip:   3.50 kB
dist/assets/users-Bbctb4Kx.js                         10.91 kB │ gzip:   3.66 kB
dist/assets/brand-icons-DGmgmC1s.js                   11.03 kB │ gzip:   2.11 kB
dist/assets/model-usage-DR9epTAt.js                   11.52 kB │ gzip:   3.56 kB
dist/assets/authenticated-layout-CDceXQpD.js          11.69 kB │ gzip:   4.24 kB
dist/assets/workflows-C4gvOHNO.js                     11.83 kB │ gzip:   4.09 kB
dist/assets/models-Qw8d_vcs.js                        12.43 kB │ gzip:   4.20 kB
dist/assets/tasks-BaHSrhZr.js                         12.70 kB │ gzip:   4.34 kB
dist/assets/react-icons.esm-qPRC21--.js               12.79 kB │ gzip:   3.46 kB
dist/assets/otp-CvjdC0mV.js                           12.89 kB │ gzip:   5.02 kB
dist/assets/QueryClientProvider-CRtxJhSP.js           13.79 kB │ gzip:   4.75 kB
dist/assets/embed-clients-DIlSh-1M.js                 14.07 kB │ gzip:   4.57 kB
dist/assets/host-tools-DeJNpa2r.js                    14.14 kB │ gzip:   4.35 kB
dist/assets/command-58vnU76i.js                       14.32 kB │ gzip:   5.36 kB
dist/assets/mcp-servers-Cr4IuIN3.js                   14.56 kB │ gzip:   4.36 kB
dist/assets/knowledge-bases-7pJ7ULXc.js               16.35 kB │ gzip:   5.16 kB
dist/assets/search-provider-KNPuRBLa.js               20.40 kB │ gzip:   7.01 kB
dist/assets/select-BqqqXuDN.js                        21.66 kB │ gzip:   7.37 kB
dist/assets/config-drawer-Ubv7EVlq.js                 22.36 kB │ gzip:   4.62 kB
dist/assets/link-BJ-XaPVI.js                          22.59 kB │ gzip:   8.41 kB
dist/assets/skills-CxJTUm3D.js                        25.44 kB │ gzip:   7.35 kB
dist/assets/utils-D09HVMnN.js                         26.86 kB │ gzip:   8.63 kB
dist/assets/dist-BWfAzbbh.js                          32.57 kB │ gzip:   9.13 kB
dist/assets/zod-DWZmEUKy.js                           34.70 kB │ gzip:  12.20 kB
dist/assets/axios-ClY8Pl96.js                         36.26 kB │ gzip:  14.39 kB
dist/assets/dropdown-menu-Bkn_G0CZ.js                 43.20 kB │ gzip:  11.85 kB
dist/assets/dist-BIRMShzw.js                          45.80 kB │ gzip:  16.71 kB
dist/assets/account-CvW0Edvo.js                       75.42 kB │ gzip:  22.45 kB
dist/assets/dist-Brmf1C2e.js                          89.55 kB │ gzip:  24.72 kB
dist/assets/_workflowId-CYPBuWO3.js                  217.23 kB │ gzip:  68.95 kB
dist/assets/zod-C2m4cF4N.js                          260.92 kB │ gzip:  59.69 kB
dist/assets/index-JllGoM-O.js                        284.75 kB │ gzip:  88.16 kB
dist/assets/xxai-agent.es-s5HOIfJZ.js                289.52 kB │ gzip: 106.84 kB
dist/assets/_agentId-BHut639F.js                     338.40 kB │ gzip:  97.89 kB
dist/assets/users-CCHFXgyD.js                        497.40 kB │ gzip: 176.56 kB
dist/assets/chats-CtpWaDYM.js                        860.30 kB │ gzip: 297.88 kB

✓ built in 843ms
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### AC7 前后端源码内无 gpt-4o-mini 字面量

```bash
bash -c ! grep -rn "gpt-4o-mini" apps/front/src apps/backend/app --include="*" --exclude-dir=__pycache__
```

结果：通过

### AC3/AC4 换绑后实际调用新模型（含 model_usage 快照），停用后返回 chat_model_unavailable

```bash
stub_probe
```

替身模型端口：65179
  新建嵌入客户端 client_sTOnlDMr046FFaz3WfVvmRK1
AC3：改绑后实际调用新模型，且用量快照记录新模型名
  通过：绑定替换接口返回 200 —— status=200
  通过：嵌入 token 签发成功 —— status=200
  WS 事件统计：{'session_ready': 1, 'message_started': 1, 'agent_loop_started': 1, 'agent_step_completed': 3, 'agent_step_started': 1, 'message_delta': 1, 'agent_loop_completed': 1, 'message_completed': 1}
  通过：WS 收到 message_completed —— {"session_ready": 1, "message_started": 1, "agent_loop_started": 1, "agent_step_completed": 3, "agent_step_started": 1, "message_delta": 1, "agent_loop_completed": 1, "message_completed": 1}
  通过：回复来自替身模型 —— {"id": "evt_10", "type": "message_completed", "protocolVersion": 1, "sequence": 10, "timestamp": "2026-10-17T00:30:17.896199+00:00", "payload": {"content": "STU
  通过：替身收到请求且模型名为 stub-model-x —— {"path": "/v1/chat/completions", "model": "stub-model-x"}
  通过：model_usage_records 快照记录了替身模型 —— 快照='stub-model-x|7|3'
AC4：停用绑定模型后返回稳定错误码，且不回落 .env 默认模型
  通过：SSE 返回 error 事件 —— error 事件数=1
  通过：错误码为 chat_model_unavailable —— event: error
  通过：未回落到 .env 默认模型 —— SSE 内无替身回复
  收尾：恢复 chat 绑定 deepseek/deepseek-v4.1-flash(id=1) status=200
  收尾：删除替身模型 id=2 status=200
  收尾：停用临时嵌入客户端 client_sTOnlDMr046FFaz3WfVvmRK1 status=200

替身收到的请求日志：
{"path": "/v1/chat/completions", "model": "stub-model-x"}
结果：通过

### AC5 一键重置后经 :8080 登录并完成一轮真实模型对话（success=true）

```bash
reset_and_chat
```


==> 清空数据库数据（保留 alembic_version，自增序号复位）
DO

==> 清空磁盘派生态 /Users/lixingwen/xw/study/ai-base/apps/backend/storage
/Users/lixingwen/xw/study/ai-base/apps/backend/storage/skill-packages

==> 清空 Redis DB 0（配额计数与事件回放流）
OK

==> 灌入开发环境种子
开发环境种子完成：
  · 平台：开发平台（id=1，code=dev-platform）
  · 管理员：admin / 见 SEED_ADMIN_PASSWORD 或开发默认密码
  · Agent：开发助手（id=1，slug=dev-assistant）
  · 对话模型：开发对话模型（deepseek/deepseek-v4.1-flash）（model_name=deepseek/deepseek-v4.1-flash，已绑定 role=chat）
  · 内置工具：ask_user, get_runtime_info, http_get
  · 技能包：dev-sample-skill（slug=dev-sample-skill，2 个文件）
    绑定技能：开发示例技能（slug=skill）
  · MCP 配置：开发样例 MCP（slug=dev-sample-mcp，未同步工具）
  · 工作流：开发助手单步流程（id=1，status=active）
  · Embed Client：client_3-obQ0Bnv4YxM5m3xu7RRaOS

==> 重置完成
登录 token 长度：119
{"success":true,"message":"ok","data":{"conversation_id":1,"message_id":2,"content":"我是「开发助手」，负责本仓库的本地开发与联调——可查运行时信息、读取公开网页、按需加载已绑定技能帮你解决问题。","citations":[],"knowledge_grounded":false,"pending_confirmation_id":null,"content_blocks":[{"id":"answer_markdown","type":"markdown","text":"我是「开发助手」，负责本仓库的本地开发与联调——可查运行时信息、读取公开网页、按需加载已绑定技能帮你解决问题。","status":"completed"}],"loop":{"id":"1","requestId":"conversation-1","status":"completed","summary":"已完成回答","steps":[{"id":"1","sequence":1,"stepType":"knowledge_retrieval","title":"检索知识库","status":"succeeded","outputSum
结果：通过

### python3 tools/harness/audit.py（排除「verify.md 尚未生成」的预期 ERROR）

```bash
audit_expect_known_errors
```


v2 requests: 12  存量跳过: 59  ERROR: 0  WARN: 0
结果：通过

## 未执行项与原因

- 浏览器人工点击：控制台「模型管理」页（apps/front/src/features/models）的解绑/换绑表单、
  「模型用量」页的展示与筛选，本脚本未在浏览器里点击；AC3/AC4 的接口行为由探针真进程覆盖。
- AI SDK 嵌入会话的浏览器验证：本脚本用 Python 直连 WebSocket（子协议 ai-agent.v1 + embed token）
  验证网关与用量落库，未在浏览器里跑 apps/ai-sdk 的浮窗。
- 全量后端测试轮（29 个目录）：本脚本按 spec 的 AC6 只跑 5 个受影响目录；
  完整一轮（每目录一次 pytest，避免跨目录重名模块 import mismatch）由人工执行。

## 验收结论

- AC1：临时库 ai_base_migration_check 上完成 0038 → head → 0038 → head 往返；升级后
  agent_versions 三列消失、存量行提升为 platform_models(model_type=chat) + chat 绑定，
  downgrade 回填原值并清空条目/绑定，再次 upgrade 重新提升。
- AC2：agent 模块内无 api_key_encrypted / model_base_url / version.model_name 命中；AgentVersion 定义无 model_name 列。
- AC3：换绑替身模型后，WS 回复 STUB-MODEL-REPLY、替身请求日志记录 stub-model-x，
  且 model_usage_records 新增行的 model_name 是 stub-model-x（不是 .env 默认模型）。
- AC4：停用被绑定的对话模型后，SSE error 事件的 code 为 chat_model_unavailable，未回落到 .env 默认模型。
- AC5：reset_dev_db.sh 之后 :8080 登录成功并完成一轮真实模型对话。
- AC6/AC7：5 个受影响测试目录全绿；前端 build 通过；前后端源码内无 gpt-4o-mini 字面量。
- 剩余风险：非流式 REST 通道的稳定错误码只体现在 HTTP 409 与 message 文案；
/Users/lixingwen/xw/study/ai-base/tools/harness/verify/2026-10-16-model-registry-unification.sh: line 258: error_code: command not found
   只在流式/事件通道以 payload.code 暴露（applications 依赖流式侧）。
- 是否可归档：达到验收标准；未执行项均为浏览器人工步骤与本 request 无关的既有问题。
```

## 未执行项与原因

- 脚本未声明未执行项。若确有无法在本机执行的项目，请在验证脚本中补上「## 未执行项与原因」章节。

## 验收结论

- 待人工补写：是否达到 spec.md 的验收标准；剩余风险；是否可归档。
- 脚本退出码：3
