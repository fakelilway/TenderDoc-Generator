# TenderDoc-Generator

> 当前状态：本地 MVP 已跑通，已进入“正奇市政/公路专用化 + 知识库结构化 + 生产化准备”阶段
> 目标交付日期：2026-08-08

TenderDoc-Generator 是面向正奇建设投标场景的智能标书生成系统。第一版不做泛行业通用投标软件，而是优先服务市政工程、公路工程、交通安全设施养护、公路改建/扩建/维修养护等正奇高频业务。

系统从招标文件解析开始，结合真实投标文件模板、企业知识库、人工确认节点和审查 Agent，生成商务文件、技术文件、报价文件三卷草稿，并支持完整合并稿、DOCX 导出、废标风险审查、响应矩阵、评分预测和报价策略建议。

## 当前能力

已完成并通过测试的主链路：

- 用户登录、注册、管理员注册码、普通用户权限控制。
- 项目创建、历史项目列表、项目属主鉴权、项目恢复和删除。
- 招标文件上传，支持 PDF/DOCX/TXT 解析。
- Parser Agent 抽取项目名称、资质要求、评分项、废标项等结构化 JSON。
- 人工确认解析结果与大纲，生成前不再绕过人工确认。
- 真实投标模板 JSON 作为章节结构权威，Generator prompt 只负责角色、文风和真实性边界。
- 商务文件、技术文件、报价文件三卷生成与预览，完整标书作为按需合并稿。
- Markdown 预览、在线编辑、保存草稿、再次审查和终审确认。
- DOCX 导出，支持封面、目录域、页眉页脚、页码、标题/正文中文排版和基础表格。
- 知识库上传、列表、预览、删除、重命名、结构化 metadata 标签和 RBAC。
- RAG 检索支持按项目类型、资料类别、册别、专业、地区、年份、证书类型、敏感级别、使用范围、核验状态、标签等过滤。
- 知识库图片资料可作为生成候选，生成内容可以在合适位置插入图片引用；图片是否可插入由 `image_insertable` 控制。
- Markdown 和 DOCX 导出支持基础表格，前端预览可渲染 Markdown 表格。
- 报价策略 Agent：只输出策略、风险和人工确认点，不自动编造清单价格。
- 评分预测 Agent：按评分项模拟分数、短板和不确定性说明，不替代人工判断。
- 审查响应矩阵：覆盖资质、废标项、评分项和商务人工字段。
- 模板库：管理员上传历史投标 PDF，解析为脱敏模板 JSON，按项目类型/专业/信封/地区/年份推荐。
- 离线脚本：模板解析、格式分析、标书生成 demo、质量评估、AI 与真实投标文件差距评估。

最近一次完整验证：

- 后端全量测试：`182 passed, 2 skipped`
- 前端类型检查：通过
- 前端生产构建：通过

## 产品范围

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

- `TenderRequirements` 只回答“招标文件要求什么”。
- `BidTemplate JSON` 是唯一章节结构来源。
- RAG 只提供素材、证据、历史表达和图片候选，不改变结构。
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
- `/templates`：模板库管理，管理员可写，普通用户只读或按权限查看。
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
- `POST /api/templates`：上传历史投标 PDF 并解析为模板。
- `GET /api/templates/recommend`：按项目上下文推荐模板。

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

## 项目结构

```text
TenderDoc-Generator/
├── backend/
│   ├── agents/              # parser/generator/reviewer/pricing/scoring/response matrix
│   ├── api/                 # FastAPI 路由
│   ├── rag/                 # embedding、pgvector 检索和过滤
│   ├── schemas/             # Pydantic schema
│   ├── services/            # workflow、project、knowledge、template、quality eval
│   ├── templates/           # 内置投标模板 JSON
│   ├── utils/               # file parser、DOCX exporter、MinIO、template parser
│   └── tests/
├── frontend/
│   ├── app/                 # Next.js App Router 页面
│   ├── components/          # 工作台、知识库、模板库、预览和编辑组件
│   └── lib/                 # API client、类型、Markdown 解析
├── docs/
├── scripts/                 # 本地启动、离线生成、格式分析、模板索引
├── docker-compose.yml
├── setup.md
├── TECH_STACK.md
└── minitasks.md
```

## 下一步

短期下一步不是继续堆 Agent，而是把本地 MVP 推向公司可用：

1. 用少量真实脱敏资料填充知识库，验证资料预览、标签筛选、RAG 引用和图片插入效果。
2. 建立正奇真实模板库最小集合：市政、公路改扩建、交安养护各至少一类。
3. 用 3 个脱敏真实项目跑通端到端质量评估和 gap 评估。
4. 补生产化方案：部署、备份、权限、审计、对象存储加密、内网访问、NAS/资料库导入策略。
5. 明确和新点投标文件制作软件的边界：本系统生成 Word/Markdown 和资料包，新点负责最终电子投标文件制作、签章、加密和上传。
