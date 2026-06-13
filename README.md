# TenderDoc-Generator

> 当前版本：V2 原文复制骨架 — 已接入API，5/5真实case验证通过
> 目标交付日期：2026-08-08

TenderDoc-Generator 是面向正奇建设投标场景的智能标书生成系统。

**第一性原理：招标文件第X章"投标文件格式"已经是一份完美格式的空白标书。**
系统只做三件事：复制原文结构 → 填入公司信息 → 写施工方案。

---

## V2 目标架构

```
招标文件 PDF/DOCX
  ↓
Layer 1: Parser — 格式提取（1次LLM）
  定位"第X章 投标/响应文件格式" → 格式树 + 13字段
  ↓
Layer 2: Skeleton Renderer — 零LLM ⭐
  复制格式页原文 → DOCX骨架（锁定区+可写区）
  ↓
Layer 3: 2 Agent 并行
  Agent A: Form Filler — 读知识库，填空锁定区（证号/法人/营业执照）
  Agent B: Content Writer — 写施工方案正文
  ↓
Layer 4: Audit
  格式比对原文(0LLM) + 内容审查(1LLM) + 证据审计(0LLM)
  ↓
Layer 5: Export → Word / PDF
```

**LLM 调用: 2-3次 | 生成: 20-30秒 | 结构错误: 0%**

## 当前能力

已完成并通过测试的主链路：

- 用户登录、注册、管理员注册码、普通用户权限控制。
- 项目创建、历史项目列表、项目属主鉴权、项目恢复和删除。
- 招标文件上传，支持 PDF/DOCX/TXT 解析。
- Parser Agent 抽取项目名称、核心字段、资质要求、评分项、废标项和投标文件格式要求等结构化 JSON。
- 人工确认解析结果、大纲和投标文件格式要求；格式要求为空时后端拒绝进入生成，避免套默认结构造成废标风险。
- 招标文件格式要求是卷册、表单、签字盖章、正副本、密封/电子标要求的最高权威；默认模板不再自动参与线上生成。
- 公司风格案例库保留历史投标 PDF 资产，生成案例画像，记录写作深度、表格/图片位、禁用语气等风格资产；只有用户主动选择时才作为参考。
- 生成前会构建 `EvidencePack`，把公司证件、人员证件、业绩、技术方案、报价附件、表格附件和图片证据分开。
- 生成前会从 `format_outline_tree` 构建商务/技术/报价三卷确定性骨架；缺少完整三卷格式树时直接失败，不再套默认模板。
- 骨架渲染会从招标文件“投标文件格式/投标文件组成”附近抽取函件、表格和清单说明原文，优先嵌入招标文件原文模板；抽不到才使用空白占位。
- 默认生成模式为 V2（`BID_GENERATION_MODE=v2`）：从招标文件格式页复制原文骨架，Form Filler 填表单空白，Content Writer 写施工方案正文，三层审计检查格式、内容和证据。解析/生成失败即失败，不自动降级生成可能废标的内容。
- 商务文件、技术文件、报价文件三卷生成与预览，完整标书作为按需合并稿。
- Markdown 预览、在线编辑、保存草稿、再次审查和终审确认。
- DOCX 导出，支持封面、目录域、页眉页脚、页码、标题/正文中文排版和基础表格。
- 知识库上传、列表、预览、删除、重命名、结构化 metadata 标签和 RBAC。
- 知识库资料批量整理脚本：扫描本地/NAS 目录，生成建议文件名、metadata 标签、CSV/JSON manifest、整理后副本，并可按 manifest 导入本地知识库。
- RAG 检索支持按项目类型、资料类别、册别、专业、地区、年份、证书类型、敏感级别、使用范围、核验状态、标签等过滤。
- 知识库图片资料可作为生成候选，生成内容可以在合适位置插入图片引用；图片是否可插入由 `image_insertable` 控制。
- Markdown 和 DOCX 导出支持基础表格，前端预览可渲染 Markdown 表格。
- 报价策略 Agent：只输出策略、风险和人工确认点，不自动编造清单价格。
- 评分预测 Agent：按评分项模拟分数、短板和不确定性说明，不替代人工判断。
- 审查响应矩阵：覆盖资质、废标项、评分项和商务人工字段。
- 公司风格案例库：管理员上传历史投标 PDF，解析为脱敏案例 JSON 和风格画像，按项目类型/专业/信封/地区/年份推荐，但不自动套用、不控制招标文件格式。
- 离线脚本：模板解析、格式分析、标书生成 demo、质量评估、AI 与真实投标文件差距评估。

- 公司信息档案：`/company` 页维护企业工商、资质、账户和拟派项目班子信息，生成时自动注入投标人基本状况表、投标函落款等商务内容。
- 招标全文持久化（`projects.tender_text`），Parser 额外抽取招标人、建设地点、招标范围、计划工期、质量标准、安全目标、投标截止时间七个核心字段。

最近一次架构验证（2026-06-13）：

- 后端完整回归：`236 passed, 2 skipped`
- 前端类型检查：通过

## 当前架构（V2 — 运行中）

```mermaid
flowchart TD
    U[上传招标文件 PDF/DOCX] --> P[Parser LLM<br/>全文一次提取 13 字段]
    P --> F[Format Page Extractor<br/>截取投标/响应文件格式页]
    F --> S[Skeleton Renderer<br/>复制原文格式骨架]
    S --> FF[Form Filler<br/>填招标人/项目名/工期/质量/公司字段]
    S --> CW[Content Writer<br/>写施工组织正文]
    FF --> A{Three-Layer Audit<br/>格式/内容/证据}
    CW --> A
    A -->|fail| R[定位问题并返修]
    R --> FF
    R --> CW
    A -->|pass| E[导出 Word/PDF/Markdown]
```

## V2 迁移路线（已接入 API，进入内容质量优化）

V1 证明了“结构交给代码”是对的。V2 进一步推到“结构交给原文”：不再用代码重画格式，而是直接从招标文件格式章节复制。当前 V2-M1~M7 已完成，短板转为表格密度、施工方案篇幅和项目针对性。

| 阶段 | 状态 | 目标 |
|------|------|------|
| V2-M1 格式页提取器 | ✅ | 逐页截取“第X章 投标/响应文件格式”原文 |
| V2-M2 原文骨架生成器 | ✅ | 锁定区（表单/表格/签章）+ 可写区（施工方案） |
| V2-M3 Form Filler Agent | ✅ | 读公司档案/知识库，填空锁定区空白字段 |
| V2-M4 Content Writer Agent | ✅ | 只写施工方案正文，不改任何结构 |
| V2-M5 三层审计 | ✅ | 格式比对原文（0LLM）+ 内容审查（1LLM）+ 证据审计（0LLM） |
| V2-M6 API/前端流程对接 | ✅ | `BID_GENERATION_MODE=v2` 已接入 workflow |
| V2-M7 真实样本验证 | ✅ | 5 个真实 case 格式提取通过 |
| V2-M8 内容质量优化 | 🔧 | 对齐南陵/萧县中标标书基线，提升表格数量、施工篇幅、项目针对性 |

详细 minitasks 见 [minitasks.md](minitasks.md)。

## 现有能力

第一版默认支持：

- 市政工程：道路、排水、管网、附属设施等。
- 公路工程：改建、扩建、维修、养护等。
- 交通安全设施：标志标线、护栏、防眩、隔离栅、交安设施养护等。
- 商务/技术/报价三卷独立生成与完整合并稿。

暂不作为第一版默认目标：

- 房建、园林、水利、机电、政府采购服务、货物采购等泛行业场景。
- 自动生成真实工程量清单报价、金额、费率或单价。
- 替代人工盖章、CA 签章、电子投标文件制作软件最终封装。

## 核心原则

系统当前最重要的边界在 [docs/generation_contract.md](docs/generation_contract.md)：

- `TenderRequirements` 回答“招标文件要求什么”，其中 `bid_format_requirements` 是投标文件格式确认关卡。
- 招标文件格式要求和人工确认目录是线上生成的结构来源；默认模板不再作为结构权威。
- `TemplateProfile` 是公司风格案例画像，负责把历史投标文件总结为写作深度、表格习惯、图片位和禁用语气。
- `EvidencePack` 是知识库资料的分类层，证件/图片/表格/技术素材不能混作同一种 RAG 文本。
- `BidPlan` 是生成阶段计划层，负责把人工确认目录、招标要求、可选风格案例画像和证据包落到每个章节。
- RAG/知识库主要负责资料治理、资料选择、证据供给和图片候选；生成时已选资料会作为证据进入对应分卷/节点，不再把 RAG 碎片当成章节结构来源。
- Generator prompt 只约束角色、文风、真实性和禁止事项。
- DOCX 视觉排版统一由 `backend/utils/docx_exporter.py` 负责。
- 离线脚本只做分析、评估、初始化和调试，不替代线上 API/service 链路。

## 本地启动

首次安装：

```bash
./scripts/setup_local.sh
```

日常启动：

```bash
./scripts/dev_local.sh
```

默认入口：

- 前端工作台：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs
- MinIO Console：http://localhost:9001

更完整的本地安装、端口冲突、验证命令和常见问题见 [setup.md](setup.md)。

## 常用验证

```bash
.venv/bin/python -m pytest backend/tests -q
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

注意：不要把 `pnpm --dir frontend typecheck` 和 `pnpm --dir frontend build` 并行执行。Next.js build 会重建 `.next/types`，并行时可能导致 typecheck 读到临时缺失文件。

## 主要页面

- `/login`：登录/注册。
- `/projects`：历史项目。
- `/project/{projectId}`：标书工作台。
- `/knowledge`：知识库资料管理。
- `/company`：公司信息档案，管理员可编辑，生成时自动填入商务内容。
- `/templates`：公司风格案例库管理，管理员可写，普通用户只读或按权限查看。
- `/admin/users`：管理员用户与权限管理。

## 主要 API

- `POST /api/project/create`：创建项目并上传招标文件。
- `PATCH /api/project/{id}/parsed`：保存人工确认版解析 JSON。
- `POST /api/project/{id}/outline`：生成默认大纲。
- `PATCH /api/project/{id}/outline`：保存人工调整后的大纲。
- `PATCH /api/project/{id}/knowledge-selection`：保存生成采用的知识片段。
- `POST /api/project/{id}/workflow/run`：运行工作流。
- `POST /api/project/{id}/confirm`：人工确认或提交修正意见。
- `PATCH /api/project/{id}/draft`：保存在线编辑正文。
- `GET /api/project/{id}/download?artifact=docx|markdown|review`：下载产物。
- `POST /api/knowledge/upload`：上传知识库资料并索引。
- `GET /api/knowledge/documents`：列出知识库资料。
- `GET /api/knowledge/documents/{id}/preview`：预览文本、图片、PDF 或文件。
- `PATCH /api/knowledge/documents/{id}`：编辑资料标题和 metadata。
- `GET /api/knowledge/search`：按语义和 metadata 检索知识库。
- `POST /api/templates`：上传历史投标 PDF 并解析为公司风格案例。
- `GET /api/templates/recommend`：按项目上下文推荐风格案例。
- `GET/PUT /api/company-profile`：读取/保存公司信息档案（PUT 需管理员）。

## 知识库资料标签

知识库资料已从“只有 tags 的素材库”升级为结构化资料库。建议上传时尽量填写：

- `project_type`：市政工程、公路工程、交通安全设施养护、公路改建/扩建/维修养护。
- `document_category`：人员证件、公司证件、业绩、施工方案、历史投标文件、表格附件、图片资料等。
- `volume`：商务文件、技术文件、报价文件、资格文件、完整投标文件。
- `specialty`：道路、排水、桥梁、交安、养护、管网等。
- `region` / `project_year`：地区和年份。
- `owner_type` / `owner_name`：公司、人员、项目、设备等归属。
- `certificate_type`：建造师证、身份证、毕业证、建安证、交安证、职称证书、社保、营业执照、资质证书、安全生产许可证、开户许可证等。
- `valid_from` / `valid_to`：证件有效期。
- `sensitivity`：公开、内部、敏感、严格受限。
- `usage_scope`：可用于投标、仅参考、仅归档等。
- `verified_status`：已核验、待核验、已过期、需更新。
- `image_insertable`：图片是否允许作为标书插图候选。

批量整理时优先使用 manifest 流程：

1. 扫描原始资料目录，只生成 `knowledge_import_manifest.csv` 和整理后副本，不改原文件。
2. 人工抽查或编辑 manifest 中的 `suggested_filename`、`certificate_type`、`valid_to`、`image_insertable`、`review_required`。
3. 确认后再加 `--import-to-kb` 导入本地知识库；默认会跳过 `review_required=true` 的资料，除非显式加 `--include-review-required`。

## 项目结构

```text
TenderDoc-Generator/
├── backend/
│   ├── agents/              # parser/generator/reviewer/pricing/scoring/response matrix
│   ├── api/                 # FastAPI 路由
│   ├── rag/                 # embedding、pgvector 检索和过滤
│   ├── scripts/             # 案例导入、质量评估、知识库 manifest/批量入库
│   ├── schemas/             # Pydantic schema
│   ├── services/            # workflow、project、knowledge、template、evidence pack、bid plan
│   ├── templates/           # 历史案例/离线评估 JSON
│   ├── utils/               # file parser、DOCX exporter、MinIO、template parser
│   └── tests/
├── frontend/
│   ├── app/                 # Next.js App Router 页面
│   ├── components/          # 工作台、知识库、风格库、预览和编辑组件
│   └── lib/                 # API client、类型、Markdown 解析
├── docs/
├── scripts/                 # 本地启动、离线生成、格式分析、模板索引
├── docker-compose.yml
├── setup.md                 # 本地安装、启动、排障
└── minitasks.md             # 任务状态与路线图
```

## 技术栈速览

- 前端：Next.js 14 App Router + React 18 + TypeScript + Tailwind，pnpm 管理，API 用原生 fetch 封装（`frontend/lib/api.ts`）。
- 后端：FastAPI + uvicorn，Python 3.11（根目录 `.venv`），psycopg2 显式 SQL + 连接池，Pydantic v2，JWT 认证，FastAPI BackgroundTasks 跑长任务。
- AI：OpenAI SDK 兼容 DeepSeek/OpenRouter（`BID_LLM_PROVIDER` 显式路由）；默认 `v2` 模式（原文复制骨架 + Form Filler + Content Writer + 三层审计），失败后无 fallback。
- RAG：BAAI/bge-large-zh-v1.5（1024 维）+ pgvector，JSONB metadata 过滤。
- 存储：PostgreSQL 15+（JSONB + pgvector）、Redis 7（workflow state）、MinIO（原文/资料/产物）。
- 文档处理：pypdf/pdfplumber/PyMuPDF 解析，python-docx 导出（`backend/utils/docx_exporter.py` 统一排版）。

依赖事实以 `backend/requirements.txt` 和 `frontend/package.json` 为准。

## 协作约定

- `main` 必须始终保持可用：提交前跑 `pytest backend/tests` 和 `pnpm --dir frontend typecheck`。
- 涉及数据库表结构、环境变量、docker 配置的改动，必须在提交说明里写明。
- 未经脱敏的真实投标文件、证件资料禁止提交到 Git。

## 生产化路线（尚未实施）

当前是 localhost MVP。推向公司内网可用需要（详见 [minitasks.md](minitasks.md) 新 M10 以及历史 M69–M74）：

- 部署：单机 Docker Compose 内网起步，Nginx/HTTPS 反向代理。
- 队列：长任务从 BackgroundTasks 迁移到 Celery/RQ 等可重试队列。
- 数据：PostgreSQL 定时备份与恢复演练，MinIO 加密与版本保留，操作审计。
- 边界：本系统输出 Word/Markdown/资料包；新点投标软件负责最终电子标书制作、签章、加密、上传。

暂不引入：大型前端组件库重构、多租户、自动报价引擎、自动 CA 签章、NAS 无限制全量索引。

## 下一步

短期：V2 格式链路已经跑通，下一步集中优化内容质量：补表格密度、扩写施工组织方案、增强项目针对性，并持续用南陵县三里镇和萧县2025公路真实中标标书作为质量基线。具体任务状态和优先级见 [minitasks.md](minitasks.md)。
