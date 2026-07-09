# TenderDoc 前端镜像(Next.js)。多阶段构建:先编译,再只保留运行所需的最小产物。
# --- 构建阶段 ---
FROM node:20-slim AS builder

# 国内构建更稳:npm/pnpm 走淘宝镜像;用官方源构建加 --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com
ENV npm_config_registry=${NPM_REGISTRY}

WORKDIR /app

# 用与仓库一致的 pnpm 版本(package.json 的 packageManager 字段)
RUN corepack enable

# 先装依赖(利用层缓存)
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 再拷源码并编译(产出 .next/standalone 精简服务)
COPY . .
RUN pnpm build

# --- 运行阶段 ---
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production

# 只拷贝 standalone 运行所需产物
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
# standalone 产物入口是 server.js;绑 0.0.0.0 让局域网其他电脑能访问
ENV HOSTNAME=0.0.0.0 PORT=3000
CMD ["node", "server.js"]
