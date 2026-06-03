# TenderDoc-Generator 本地启动指南

本文档说明如何在本地直接启动 TenderDoc-Generator MVP。当前推荐使用仓库内脚本完成环境安装、数据库初始化、后端启动和前端启动。

---

## 1. 前置要求

| 组件 | 推荐版本 | 检查命令 |
|------|----------|----------|
| Docker Desktop / Docker Engine | 24+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python | 3.11+ | `python3.11 --version` |
| Node.js | 20+ | `node --version` |
| pnpm | 10+ | `pnpm --version` |
| Git | 2.30+ | `git --version` |

如果没有 pnpm，可以先安装：

```bash
corepack enable
corepack prepare pnpm@10.32.0 --activate
```

---

## 2. 首次安装

在仓库根目录运行：

```bash
./scripts/setup_local.sh
```

这个脚本会执行：

- 如果 `backend/.env` 不存在，从 `backend/.env.example` 复制一份
- 创建或复用根目录 `.venv`
- 安装后端依赖
- 安装前端依赖
- 启动 Docker 服务
- 应用 `backend/init_db.sql`

真实 LLM 解析/生成流程需要编辑 `backend/.env`，至少配置：

```env
OPENROUTER_API_KEY=sk-or-v1-your-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=deepseek/deepseek-chat
```

基础服务默认配置：

```env
DATABASE_URL=postgresql://tenderuser:tenderpwd@localhost:5432/tenderdb
REDIS_URL=redis://localhost:6379/0
MINIO_API_URL=http://localhost:9000
MINIO_CONSOLE_URL=http://localhost:9001
MINIO_BUCKET=tender-files
```

---

## 3. 日常启动

日常开发只需要：

```bash
./scripts/dev_local.sh
```

启动成功后访问：

- 前端工作台：`http://localhost:3000`
- 后端 API 文档：`http://localhost:8000/docs`
- 后端健康检查：`http://localhost:8000/health`
- MinIO Console：`http://localhost:9001`

MinIO 默认账号密码：

```text
minioadmin / minioadmin
```

按 `Ctrl+C` 会停止后端和前端开发服务；Docker 容器会继续在后台运行。

---

## 4. 拆分启动命令

如果需要单独排查某一层，可以使用下面的脚本。

初始化基础服务和数据库：

```bash
./scripts/init_db.sh
```

只启动后端：

```bash
./scripts/start_backend.sh
```

只启动前端：

```bash
./scripts/start_frontend.sh
```

只安装前端依赖：

```bash
./scripts/setup_frontend.sh
```

只安装后端虚拟环境：

```bash
./scripts/setup_venv.sh
```

强制重建 `.venv`：

```bash
RESET_VENV=1 ./scripts/setup_venv.sh
```

---

## 5. 验证命令

后端单元测试：

```bash
.venv/bin/python -m pytest backend/tests -q
```

基础服务 smoke：

```bash
.venv/bin/python backend/test_db.py
.venv/bin/python backend/test_redis.py
.venv/bin/python backend/test_minio.py
```

LLM 和 embedding smoke：

```bash
.venv/bin/python backend/test_llm.py
.venv/bin/python backend/test_embedding.py
```

前端类型检查和生产构建：

```bash
cd frontend
pnpm run typecheck
pnpm run build
```

健康检查：

```bash
curl -fsS http://localhost:8000/health
curl -fsSI http://localhost:3000
```

当前已验证结果：

- `./scripts/init_db.sh` 通过
- `.venv/bin/python -m pytest backend/tests -q` 通过：49 passed, 2 skipped
- `pnpm run typecheck` 通过
- `pnpm run build` 通过
- `./scripts/dev_local.sh` 可启动前端和后端

---

## 6. 本地 Demo 流程

1. 运行 `./scripts/dev_local.sh`
2. 打开 `http://localhost:3000`
3. 上传真实招标文件（PDF/DOCX/TXT）
4. 等待系统创建项目、解析、生成、审查
5. 在页面查看 Markdown 初稿和审查风险项
6. 点击“批准并继续”或“手动修改”
7. 点击“下载标书”获取 DOCX

企业历史标书、资质文件、施工方案模板等知识库文件可以放入 `knowledge_base/`，也可以通过 `POST /api/knowledge/upload` 上传索引。

---

## 7. 常见问题

### Q1: 端口被占用

默认端口：

- PostgreSQL：5432
- Redis：6379
- MinIO：9000 / 9001
- Backend：8000
- Frontend：3000

如果前后端端口冲突，可以临时指定：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=3010 ./scripts/dev_local.sh
```

Docker 服务端口冲突需要修改 `docker-compose.yml`，并同步修改 `backend/.env`。

### Q2: `python3.11 not found`

macOS 推荐：

```bash
brew install python@3.11
```

确认：

```bash
python3.11 --version
```

### Q3: 前端依赖安装慢

脚本默认使用 `https://registry.npmmirror.com`。如果想换回官方源：

```bash
NPM_REGISTRY=https://registry.npmjs.org ./scripts/setup_frontend.sh
```

### Q4: embedding 第一次很慢

首次运行会下载 `BAAI/bge-large-zh-v1.5`，文件较大。国内网络可以设置 HuggingFace 镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

### Q5: LLM 返回 401

检查 `backend/.env`：

- `OPENROUTER_API_KEY` 是否正确
- OpenRouter 账户是否有额度
- `OPENROUTER_MODEL` 是否可用

### Q6: MinIO 下载链接打不开

确认容器运行：

```bash
docker compose ps
```

确认 bucket 配置一致：

```env
MINIO_API_URL=http://localhost:9000
MINIO_BUCKET=tender-files
```

### Q7: 想重置本地数据

这会删除本地 Docker volume 数据：

```bash
docker compose down -v
./scripts/init_db.sh
```

---

## 8. 脚本清单

| 脚本 | 用途 |
|------|------|
| `scripts/setup_local.sh` | 首次完整安装 |
| `scripts/dev_local.sh` | 日常一键启动前后端 |
| `scripts/init_db.sh` | 启动 Docker 并应用 DB schema |
| `scripts/setup_venv.sh` | 创建/更新 Python `.venv` |
| `scripts/setup_frontend.sh` | 安装前端依赖 |
| `scripts/start_backend.sh` | 只启动 FastAPI |
| `scripts/start_frontend.sh` | 只启动 Next.js |

---

**文档版本**：2.0  
**最后更新**：2026-06-03  
**维护者**：TenderDoc-Generator 团队
