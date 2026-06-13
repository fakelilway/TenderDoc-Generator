# TenderDoc-Generator 本地启动与验证指南

本文档说明如何在本地运行当前 MVP。当前版本仍是 localhost 开发部署，但已经包含完整后端、前端、数据库、对象存储、知识库、风格库和工作流。

## 1. 前置要求

| 组件 | 推荐版本 | 检查命令 |
|------|----------|----------|
| Docker Desktop / Docker Engine | 24+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python | 3.10+ | `python3 --version` |
| Node.js | 20+ | `node --version` |
| pnpm | 10.32.0 | `pnpm --version` |
| Git | 2.30+ | `git --version` |

如果没有 pnpm：

```bash
corepack enable
corepack prepare pnpm@10.32.0 --activate
```

## 2. 首次安装

在仓库根目录运行：

```bash
./scripts/setup_local.sh
```

脚本会做这些事：

- 如果 `backend/.env` 不存在，从 `backend/.env.example` 复制一份。
- 创建或复用根目录 `.venv`。
- 安装后端 Python 依赖。
- 安装前端 pnpm 依赖。
- 启动 PostgreSQL/Redis/MinIO。
- 应用 `backend/init_db.sql`。

如果遇到旧虚拟环境里 `pip` 损坏或缺失：

```bash
RESET_VENV=1 ./scripts/setup_venv.sh
```

然后再运行：

```bash
./scripts/setup_local.sh
```

## 3. 环境变量

真实 LLM 解析/生成需要编辑 `backend/.env`。本项目当前通过 OpenAI SDK 兼容 OpenRouter/DeepSeek：

```env
OPENROUTER_API_KEY=sk-or-v1-your-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=deepseek/deepseek-v4-pro
BID_LLM_PROVIDER=auto
BID_GENERATION_MODE=multi_agent
PARSER_LLM_TIMEOUT_SECONDS=180
# 生成跑在后台线程，multi_agent 会先确认框架，再分卷生成、分卷修订、总审打回；最终由代码拼接三卷，质量优先
BID_LONG_CONTEXT_TIMEOUT_SECONDS=300
BID_LONG_CONTEXT_MAX_TOKENS=12000
```

如需绕开 OpenRouter 直连 DeepSeek：

```env
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
BID_LLM_PROVIDER=deepseek
PARSER_LLM_TIMEOUT_SECONDS=180
```

基础服务默认值：

```env
DATABASE_URL=postgresql://tenderuser:tenderpwd@localhost:5432/tenderdb
REDIS_URL=redis://localhost:6379/0
MINIO_API_URL=http://localhost:9000
MINIO_CONSOLE_URL=http://localhost:9001
MINIO_BUCKET=tender-files
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIMENSION=1024
JWT_SECRET=change-me
```

如果首次运行 embedding 较慢，是在下载本地向量模型。国内网络可临时设置：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

## 4. 日常启动

```bash
./scripts/dev_local.sh
```

启动成功后访问：

- 前端工作台：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs
- 后端健康检查：http://localhost:8000/health
- MinIO Console：http://localhost:9001

MinIO 默认账号密码：

```text
minioadmin / minioadmin
```

默认管理员账号：

```text
admin / tenderdoc
```

`Ctrl+C` 会停止后端和前端开发服务，Docker 容器会继续在后台运行。

## 5. 拆分启动命令

```bash
# 启动 Docker 并应用数据库 schema
./scripts/init_db.sh

# 只启动后端
./scripts/start_backend.sh

# 只启动前端
./scripts/start_frontend.sh

# 只安装/更新后端虚拟环境
./scripts/setup_venv.sh

# 只安装前端依赖
./scripts/setup_frontend.sh
```

端口可临时覆盖：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=3010 ./scripts/dev_local.sh
```

## 6. 验证命令

后端全量测试：

```bash
.venv/bin/python -m pytest backend/tests -q
```

前端验证：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

不要把 `typecheck` 和 `build` 并行跑。Next.js build 会重建 `.next/types`，并行时 typecheck 可能读到临时缺失的类型文件。

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

健康检查：

```bash
curl -fsS http://localhost:8000/health
curl -fsSI http://localhost:3000
```

最近一次完整验证：

- `.venv/bin/python -m pytest backend/tests -q`：`232 passed, 2 skipped`（2026-06-12）
- `pnpm --dir frontend typecheck`：通过
- `pnpm --dir frontend build`：通过

## 7. 本地端到端流程

1. 运行 `./scripts/dev_local.sh`。
2. 打开 http://localhost:3000。
3. 使用 `admin / tenderdoc` 登录。
4. 可选进入风格库，上传脱敏历史投标 PDF 作为公司风格案例；新项目默认不套任何案例。
5. 进入知识库，上传少量测试资料并填写结构化标签。
6. 创建项目并上传招标文件 PDF/DOCX/TXT。
7. 查看并确认解析结果。
8. 生成并调整投标文件大纲。
9. 在资料选择面板筛选并勾选需要进入本次投标的企业资料。
10. 开始生成，后端会构建 `EvidencePack` 和 `BidPlan`，默认用长上下文模式一次性生成商务/技术/报价三卷；格式要求来自招标文件和人工确认目录，风格案例仅在主动选择时参考。
11. 查看审查报告、响应矩阵、评分预测和报价策略。
12. 在线编辑正文，保存后重新审查。
13. 终审确认后下载 DOCX、Markdown 或审查报告。

## 8. 知识库格式与预览

当前上传接口主要支持：

- 文本索引：PDF、DOCX、TXT。
- 图片资料：JPG、JPEG、PNG。
- 预览：文本资料显示提取文本，图片显示原图，PDF 提供预览类型，其他文件作为附件记录。

知识库不是单纯文件夹。上传时请尽量填写 metadata：

- 项目类型、资料类别、册别、专业、地区、年份。
- 人员/公司/项目归属和证书类型。
- 有效期、敏感级别、使用范围、核验状态。
- 图片是否允许插入标书。

这些字段会影响：

- 知识库页面筛选。
- 标书生成前的资料选择。
- RAG 检索过滤。
- 图片插入候选。
- `EvidencePack` 分类：公司证件、人员证件、业绩、技术方案、报价附件、表格附件和图片证据。
- `BidPlan` 分配：每个章节可用哪些知识片段、哪些图片候选、是否需要表格。
- 长上下文生成：已选资料、关键文本片段和可插入图片清单会进入同一个生成 prompt，减少分章节链路造成的上下文损失。
- 后续审计、过期提醒和资料治理。

批量整理和导入建议先走 manifest：

```bash
.venv/bin/python backend/scripts/prepare_knowledge_manifest.py \
  "/path/to/原始知识库资料" \
  --out "/path/to/knowledge_import_manifest.csv" \
  --json-out "/path/to/knowledge_import_manifest.json" \
  --copy-to "/path/to/04_知识库_整理后"
```

确认 manifest 后再导入本地知识库：

```bash
.venv/bin/python backend/scripts/prepare_knowledge_manifest.py \
  --manifest "/path/to/knowledge_import_manifest.csv" \
  --out "/path/to/knowledge_import_manifest.csv" \
  --import-to-kb \
  --import-report "/path/to/knowledge_import_report.csv"
```

默认会跳过 `review_required=true` 的资料；样本试导或已人工确认时才加 `--include-review-required`。脚本不会改动原始资料目录，`--copy-to` 只生成整理后的副本。

## 9. 风格案例与离线脚本

导入历史案例样本到风格库：

```bash
.venv/bin/python backend/scripts/seed_default_template.py
```

从真实历史投标 PDF 抽取脱敏案例 JSON：

```bash
.venv/bin/python backend/scripts/extract_bid_template.py "/path/to/投标文件.pdf" \
  --out backend/templates/bid_templates/my_template.json \
  --name "某类项目风格案例"
```

分析真实 PDF 格式特征：

```bash
.venv/bin/python scripts/analyze_pdf_format.py /path/to/投标文件.pdf \
  --out-json data/pdf_format_analysis.json
```

离线生成 demo：

```bash
.venv/bin/python scripts/generate_bid.py --demo --output-dir data/output/demo
```

质量评估：

```bash
.venv/bin/python backend/scripts/run_quality_eval.py
```

AI 标书与真实模板差距评估：

```bash
.venv/bin/python backend/scripts/run_bid_gap_eval.py \
  --ai /path/to/generated.docx \
  --reference backend/templates/bid_templates/road_first_envelope_template.json
```

## 10. 常见问题

### 端口被占用

默认端口：

- PostgreSQL：5432
- Redis：6379
- MinIO：9000 / 9001
- Backend：8000
- Frontend：3000

临时换端口：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=3010 ./scripts/dev_local.sh
```

Docker 服务端口冲突需要修改 `docker-compose.yml`，并同步修改 `backend/.env`。

### LLM 返回 401

检查：

- `OPENROUTER_API_KEY` 是否正确。
- OpenRouter 账户是否有额度。
- `OPENROUTER_MODEL` 是否可用。
- `BID_GENERATION_MODE` 是否为 `multi_agent` 或 `long_context`；如需回滚可临时改为 `long_context`。
- 公司网络是否拦截外部 API。

### MinIO 下载链接打不开

检查容器状态：

```bash
docker compose ps
```

检查配置：

```env
MINIO_API_URL=http://localhost:9000
MINIO_BUCKET=tender-files
```

### 想重置本地数据

这会删除本地数据库和对象存储 volume：

```bash
docker compose down -v
./scripts/init_db.sh
```

### Git 提示 gc.log / loose objects

这通常是本地 Git 仓库维护警告，不影响运行、测试或 push。不要在不了解影响时随手删历史或 reset；需要清理时单独处理。

## 11. 脚本清单

| 脚本 | 用途 |
|------|------|
| `scripts/setup_local.sh` | 首次完整安装 |
| `scripts/dev_local.sh` | 日常一键启动前后端 |
| `scripts/init_db.sh` | 启动 Docker 并应用 DB schema |
| `scripts/setup_venv.sh` | 创建/更新 Python `.venv` |
| `scripts/setup_frontend.sh` | 安装前端依赖 |
| `scripts/start_backend.sh` | 只启动 FastAPI |
| `scripts/start_frontend.sh` | 只启动 Next.js |
| `scripts/generate_bid.py` | 离线生成脱敏标书 demo |
| `scripts/analyze_pdf_format.py` | 分析真实 PDF 格式特征 |
| `scripts/index_bid_templates.sh` | 将模板资料索引到本地知识库 |
| `backend/scripts/seed_default_template.py` | 导入历史案例样本到风格库 |
| `backend/scripts/extract_bid_template.py` | 从历史投标 PDF 抽取案例 JSON |
| `backend/scripts/prepare_knowledge_manifest.py` | 批量生成知识库命名/标签 manifest，并可导入本地知识库 |
| `backend/scripts/run_quality_eval.py` | 运行质量评估集 |
| `backend/scripts/run_bid_gap_eval.py` | 评估 AI 标书与真实模板差距 |

---

**文档版本**：3.0
**最后更新**：2026-06-11
**维护者**：TenderDoc-Generator 团队
