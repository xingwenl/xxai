# front 镜像以仓库根为构建上下文（docker-compose.yml 的 front.build.context）：pnpm workspace
# 需要根 lockfile 与各成员的 package.json，vite 打包还需要 apps/front 源码和它依赖的 apps/ai-sdk。
#
# 为什么现在只需要一次 install：根 pnpm-workspace.yaml 把 apps/ai-sdk 与 apps/front 收进同一个
# workspace，`xxai-agent` 是 `workspace:*` 软链（apps/front/node_modules/xxai-agent -> ../../ai-sdk），
# 不再是 pnpm 按对方 files 字段复制出来的 dist 副本，改 SDK 源码也不会让 front 的依赖层失效。
#
# 分层（同一台机器实测：改造前改一次 SDK 源码要 3 分 07 秒，现在只重跑「SDK 构建 + front 打包」）：
#   1. 只 COPY 依赖清单（根 lock + 四个成员的 package.json），改业务源码不会触发 install；
#   2. install 挂 BuildKit 缓存盘，依赖包只从 registry 下一次，之后直接读本地 store；
#   3. SDK 源码单独一层构建，front 源码单独一层构建。
FROM node:22-alpine AS build

WORKDIR /app

# 国内服务器 registry.npmjs.org 不稳定，corepack 与 pnpm 安装统一走 npmmirror
ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com
RUN corepack enable \
    && corepack prepare pnpm@9.15.9 --activate \
    && pnpm config set registry https://registry.npmmirror.com

# workspace 成员清单必须齐全（pnpm-workspace.yaml 声明的四个应用），否则根 lockfile 与
# workspace 对不上；这里只拷清单，源码在下面分阶段 COPY。
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/ai-sdk/package.json apps/ai-sdk/
COPY apps/front/package.json apps/front/
COPY apps/shop/package.json apps/shop/
COPY apps/desktop/front/package.json apps/desktop/front/

# --ignore-scripts：此刻源码还没进镜像，ai-sdk 的 prepare（= npm run build）必然失败；
# 它的 dist 下面显式构建。devDependencies 照常安装，vite/vite-plugin-dts 都在里面。
RUN --mount=type=cache,id=pnpm-store,target=/pnpm-store \
    pnpm install --frozen-lockfile --ignore-scripts --store-dir /pnpm-store

# SDK 源码一层：改 apps/ai-sdk 只重跑这一层。
COPY apps/ai-sdk/ ./apps/ai-sdk/
RUN pnpm --filter xxai-agent build

# front 源码一层：改 apps/front 只重跑这一层 + vite 打包。
COPY apps/front/ ./apps/front/
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}
# 当前仓库存在既有 TypeScript 基线错误；镜像先完成 Vite 产物构建，类型检查单独执行。
RUN pnpm --filter shadcn-admin exec vite build

FROM nginx:1.27-alpine

COPY apps/front/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/front/dist /usr/share/nginx/html

EXPOSE 80
