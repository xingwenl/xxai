# `apps/front` 以 `file:../ai-sdk` 依赖仓库内的 AI SDK（见 package.json），因此构建上下文是
# 仓库根（docker-compose.yml 的 front.build.context），需要同时拿到 apps/front 与 apps/ai-sdk。
# pnpm 对 `file:` 依赖是复制而非软链，且不会执行对方的 `prepare` 钩子，所以必须先把 SDK 的
# dist 构建出来，否则 front 安装时会在 `/ai-sdk` 上直接 ENOENT 失败。
FROM node:22-alpine AS sdk

WORKDIR /ai-sdk

# 国内服务器 registry.npmjs.org 不稳定，corepack 与 pnpm 安装统一走 npmmirror
ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com
RUN corepack enable \
    && corepack prepare pnpm@10.12.1 --activate \
    && pnpm config set registry https://registry.npmmirror.com

COPY apps/ai-sdk/ ./
RUN pnpm install --frozen-lockfile \
    && pnpm run build

FROM node:22-alpine AS build

WORKDIR /app

ENV COREPACK_NPM_REGISTRY=https://registry.npmmirror.com
RUN corepack enable \
    && corepack prepare pnpm@10.12.1 --activate \
    && pnpm config set registry https://registry.npmmirror.com

COPY apps/front/package.json apps/front/pnpm-lock.yaml ./
# `file:../ai-sdk` 相对 /app 解析到 /ai-sdk，与上一阶段的工作目录保持一致
COPY --from=sdk /ai-sdk /ai-sdk
RUN pnpm install --frozen-lockfile

COPY apps/front/ .
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}
# 当前仓库存在既有 TypeScript 基线错误；容器镜像先完成 Vite 产物构建，类型检查单独执行。
RUN pnpm exec vite build

FROM nginx:1.27-alpine

COPY apps/front/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
