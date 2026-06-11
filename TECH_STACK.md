# TenderDoc-Generator 技术栈

> 最后更新：2026-06-11
> 状态：当前实现版，不是早期选型草案

## 1. 前端

| 组件 | 当前选型 | 说明 |
|------|----------|------|
| 框架 | Next.js 14.2.4 App Router | 页面位于 `frontend/app/` |
| UI 运行时 | React 18.3.1 + TypeScript 5.5 | 当前无 Ant Design |
| 样式 | Tailwind CSS 3.4 + 全局 CSS | 企业工作台风格，组件内 class 为主 |
| 图标 | lucide-react | 导航、按钮和状态图标 |
| 包管理 | pnpm 10.32.0 | `frontend/package.json` 声明 packageManager |
| API 调用 | 原生 `fetch` 封装 | `frontend/lib/api.ts` |
| Markdown 预览 | 自研轻量 parser | `frontend/lib/markdown.ts` 支持标题、段落、列表、表格 |
| 认证状态 | localStorage session | `frontend/lib/auth.ts` |

当前主要页面：

- `/login`
- `/projects`
- `/project/[projectId]`
- `/knowledge`
- `/templates`
- `/admin/users`

验证命令：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

## 2. 后端

| 组件 | 当前选型 | 说明 |
|------|----------|------|
| 框架 | FastAPI 0.109 | API 层在 `backend/api/main.py` |
| 运行 | uvicorn | 本地由 `scripts/start_backend.sh` 启动 |
| Python | 3.11+ | 根目录 `.venv` |
| 数据访问 | psycopg2 + SQL | 当前 service 层以显式 SQL 为主 |
| 数据校验 | Pydantic v2 | schema 位于 `backend/schemas/` |
| 认证 | JWT + bcrypt/passlib 风格 hash | 管理员、普通用户、知识库权限 |
| 后台任务 | FastAPI BackgroundTasks | 生成接口异步触发；Celery 依赖保留但尚未作为主队列 |
| 配置 | pydantic-settings + `.env` | `backend/core/config.py` |

主要 service：

- `project_service.py`：项目、下载、权限、最终版本。
- `workflow_service.py` / `workflow_graph.py`：解析、确认、检索、生成、审查、人工确认。
- `generation_service.py`：生成、导出、图片候选、分卷。
- `knowledge_service.py`：知识库上传、metadata、预览、图片引用。
- `template_service.py`：模板库 CRUD、推荐、项目绑定。
- `evidence_pack_service.py`：把知识库资料归类为证件、业绩、技术方案、报价附件、表格附件和图片证据。
- `bid_plan_service.py`：把模板画像、招标要求和证据包编排为生成计划。
- `quality_eval.py` / `bid_gap_eval.py`：质量评估和真实模板差距评估。

## 3. AI / Agent

| 模块 | 当前状态 | 说明 |
|------|----------|------|
| Parser Agent | 已实现 | 抽取招标要求 JSON |
| Template Profile Agent | 已实现 | 从 BidTemplate 生成分卷、章节、表格位、图片位和文风画像 |
| Generator Agent | 已实现 | 基于招标 JSON + BidPlan + RAG 生成分卷 Markdown |
| Reviewer Agent | 已实现 | 规则 + 可选 LLM 审查 |
| Pricing Agent | 已实现 | 只给策略，不自动报价 |
| Scoring Agent | 已实现 | 模拟评分与不确定性说明 |
| Response Matrix Agent | 已实现 | 招标要求到响应位置的矩阵 |
| Workflow 编排 | LangGraph + service 状态 | Redis/DB 持久化 workflow state |

LLM 当前通过 OpenAI SDK 兼容 OpenRouter/DeepSeek。Agent prompt 的长期约束是：必须明确角色、经验、任务边界和禁止编造事实；生成器不得在 prompt 中再写一套固定目录。

生成链路的结构权威顺序是：

1. `BidTemplate JSON`：来自真实模板或默认模板，决定基础章节结构。
2. `TemplateProfile`：把模板结构总结成章节、附表、图片位、表格位和禁用语气。
3. `EvidencePack`：把知识库资料分类，避免证件图片摘要混入技术正文。
4. `BidPlan`：把模板画像、招标要求和资料证据落到每个章节。
5. `Generator Agent`：只按计划写正文、表格和图片引用，不再自建目录体系。

## 4. RAG / 知识库

| 组件 | 当前选型 | 说明 |
|------|----------|------|
| 向量模型 | BAAI/bge-large-zh-v1.5 | 1024 维 |
| 向量库 | PostgreSQL + pgvector | `knowledge_chunks.embedding VECTOR(1024)` |
| 文档表 | `documents` | 原始文件 metadata 存 `metadata_json` |
| 分块表 | `knowledge_chunks` | chunk 内容、metadata、embedding |
| 检索 | pgvector 相似度 + 轻量 rerank | `backend/rag/retriever.py` |
| 过滤 | JSONB metadata filter | 支持项目类型、类别、册别、专业、地区、年份、证书、标签等 |

当前知识库 metadata 字段包括：

- `project_type`
- `document_type`
- `document_category`
- `volume`
- `specialty`
- `region`
- `project_year`
- `owner_type`
- `owner_name`
- `certificate_type`
- `valid_from`
- `valid_to`
- `sensitivity`
- `usage_scope`
- `verified_status`
- `image_insertable`
- `tags`

图片资料可以上传、预览、参与图片候选；过期或 `image_insertable=false` 的图片不会进入生成候选。

结构化证件和图片会进入 `EvidencePack`，主要用于资格章节和图片插入，不作为普通技术正文素材。历史施工方案、施工组织设计、技术措施类文本才进入技术正文 RAG。

## 5. 文档处理与 DOCX

| 能力 | 当前组件 | 说明 |
|------|----------|------|
| PDF 文本 | pypdf / pdfplumber / PyMuPDF | 文本提取、模板解析、格式分析 |
| Word 解析 | python-docx | DOCX 文本解析和测试生成 |
| TXT 解析 | 内置文本读取 | 招标文件和知识库基础格式 |
| 图片资料 | JPG/JPEG/PNG | 预览与标书图片引用候选 |
| DOCX 导出 | python-docx | `backend/utils/docx_exporter.py` |
| 表格 | Markdown 表格 -> 前端预览/DOCX 表格 | 基础表格已支持 |
| 模板解析 | 自研 parser | 从真实投标 PDF 抽取脱敏 BidTemplate JSON |

DOCX 当前排版能力：

- 封面。
- Word 目录域。
- 页眉、页脚、页码。
- 中文标题/正文样式。
- 列表和基础表格。
- 商务/技术/报价分卷与完整合并稿文件名策略。

## 6. 数据库与基础设施

| 组件 | 当前选型 | 说明 |
|------|----------|------|
| 主数据库 | PostgreSQL 15+ | JSONB + pgvector |
| 缓存/状态 | Redis 7 | workflow state、后续队列扩展 |
| 对象存储 | MinIO | 招标原文、知识库文件、生成产物 |
| 本地编排 | Docker Compose | PostgreSQL、Redis、MinIO |
| API 文档 | FastAPI Swagger | `/docs` |

核心表：

- `projects`
- `users`
- `registration_codes`
- `documents`
- `knowledge_chunks`
- `bid_templates`

`backend/init_db.sql` 采用 `CREATE TABLE IF NOT EXISTS` 和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，方便本地反复升级。

## 7. 测试与质量工具

| 类型 | 当前工具 | 说明 |
|------|----------|------|
| 后端测试 | pytest | `backend/tests/` |
| API 测试 | FastAPI TestClient/httpx | 覆盖项目、知识库、模板、认证等 |
| 前端类型 | TypeScript | `pnpm --dir frontend typecheck` |
| 前端构建 | Next build | `pnpm --dir frontend build` |
| 格式化 | black | 后端 Python |
| 标书质量评估 | `backend/scripts/run_quality_eval.py` | 解析准确率、章节完整率、废标检出率等 |
| Gap 评估 | `backend/scripts/run_bid_gap_eval.py` | AI 标书与真实模板差距 |

最近一次完整后端测试结果：

```text
182 passed, 2 skipped
```

## 8. 当前依赖事实

后端依赖以 `backend/requirements.txt` 为准，当前包含：

- FastAPI / uvicorn / python-multipart
- psycopg2-binary / SQLAlchemy / Alembic
- langgraph / langchain / langchain-openai
- openai / requests
- sentence-transformers / scikit-learn / numpy
- pypdf / pdfplumber / PyMuPDF / python-docx
- redis / celery
- pydantic / pydantic-settings
- python-dotenv / structlog / jieba
- minio
- pytest / pytest-asyncio / httpx
- black / flake8 / mypy

前端依赖以 `frontend/package.json` 为准，当前没有 Ant Design、Axios、TanStack Query、React Router 或 Vite。

## 9. 生产化建议栈

当前 repo 是 localhost MVP。要变成公司生产可用，建议演进为：

- 部署：Docker Compose 单机内网起步，成熟后再考虑 K8s。
- 入口：Nginx/Traefik 反向代理，HTTPS，内网域名。
- 后端：gunicorn + uvicorn worker，独立 worker 处理长任务。
- 队列：将长生成任务从 FastAPI BackgroundTasks 迁移到 Celery/RQ/Arq。
- 数据库：PostgreSQL 定时备份、WAL 归档、只读恢复演练。
- 对象存储：MinIO server-side encryption、bucket policy、版本保留、生命周期归档。
- 权限：细化项目级、知识库级、模板级 RBAC 和操作审计。
- 安全：JWT secret 管理、内网访问控制、上传文件大小和类型限制、敏感字段脱敏。
- 观测：结构化日志、任务耗时指标、错误告警、LLM 调用成本统计。
- 文档兼容：继续导出 Word/Markdown/资料包，新点投标文件制作软件负责最终电子投标文件封装、签章、加密和上传。

## 10. 暂不引入

为了保持 MVP 可控，当前不建议马上引入：

- 大型前端组件库重构。
- 多租户复杂组织架构。
- 自动报价引擎。
- 自动 CA 签章或绕过新点制作软件。
- 直接挂载公司 NAS 后无限制索引全部资料。
- 未经脱敏的真实投标文件提交到 Git。
