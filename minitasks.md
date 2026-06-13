# TenderDoc-Generator 任务状态与路线图

本文件只记录当前状态和未完成任务。

**当前在跑版本：** V2 原文复制骨架（已接入 API，`BID_GENERATION_MODE=v2`）
**当前重点：** 内容质量优化（表格密度、施工方案篇幅、项目针对性、填空率）

---

## V2 迁移路线图（原文复制骨架）

> 第一性原理：招标文件第X章"投标文件格式"已经是一份完美格式的空白标书。系统只做三件事：复制原文结构 → 填入公司信息 → 写施工方案。

### V2-M1~M7：格式链路已完成

**目标：** 从招标文件 PDF/DOCX 定位“投标/响应文件格式”，复制原文骨架，填入公司信息，写施工方案正文，并进行三层审计。

- ✅ **全部完成** — V2-M1 到 V2-M7 已落地，V2 管线已接入 API
- ✅ **5/5 真实 case 验证通过** — 长丰/萧县/南陵/颍州/鸠江
- ✅ **API 模式：** `BID_GENERATION_MODE=v2` (.env)

---

## V2 已完成清单

| 阶段 | 状态 | 说明 |
|------|------|------|
| V2-M1 格式页提取器 | ✅ | `extract_format_pages()` — 支持三卷/双信封/磋商 |
| V2-M2 原文模板抽取 | ✅ | Codex 已完成 `extract_format_template_blocks()` |
| V2-M3 Form Filler | ✅ | `fill_page_template()` — 公司信息自动填空 |
| V2-M4 Content Writer | ✅ | `fill_technical_volume()` — 逐节点写施工方案 |
| V2-M5 三层审计 | ✅ | `full_audit()` — 格式/内容/证据 三层 |
| V2-M6 端到端管线 | ✅ | `generate_v2_bid_package()` — 已接入 API |
| V2-M7 真实样本验证 | ✅ | 5/5 case format 提取通过 |

## V2-M8 内容质量优化（当前）

| 任务 | 状态 | 验收 |
|------|------|------|
| V2-M8.1 表格密度提升 | 🔧 | 生成稿表格数量接近真实中标标书基线，不能只有 3 个左右的泛表 |
| V2-M8.2 施工方案扩写 | 🔧 | 技术卷篇幅从约 9K 字提升到可用于真实初稿的深度，章节不少于真实评分要求 |
| V2-M8.3 项目针对性增强 | 🔧 | 施工方案引用招标范围、工期、质量、安全、道路/养护/交安工程特点 |
| V2-M8.4 填空率降低 | 🔧 | 已知招标人、项目名、工期、质量、公司名等字段自动填入；未知字段保留下划线 |
| V2-M8.5 基线评估 | 🔧 | 每次生成后对比南陵县三里镇、萧县2025公路真实中标标书的表格密度/篇幅/填空率 |

## V2 代码位置

```
backend/services/v2_generation_service.py   — 端到端管线
backend/services/v2_audit_service.py        — 三层审计
backend/services/format_skeleton_service.py — 格式提取 (V2-M1)
backend/agents/form_filler_agent.py         — 表单填空
backend/agents/content_writer_agent.py      — 施工方案写手
backend/scripts/verify_v2.py               — 5-case 验证脚本
```



## 历史归档（V1 及之前）

旧 M1–M84 和 V1 M1-M10 是历史开发编号。自 2026-06-13 晚起，生成内核已切换为 V2 原文复制骨架。
### 新 M1/M2 已落地的代码点

- `backend/services/format_skeleton_service.py`
  - `render_all_volume_skeletons()` / `render_volume_skeleton()`：渲染三卷确定性骨架。
  - `extract_format_template_blocks()`：抽取格式章节里的函件、表格、清单说明原文块。
  - `expected_volume_titles()`：给确定性标题预审使用。
- `backend/agents/generator_agent.py`
  - 生成前检查三卷格式树完整性；不完整直接失败。
  - 初稿、修订、审计打回都传同一份 `volume_skeleton`。
  - LLM 结构审计前先跑确定性标题预审。
- `backend/prompts/generator_prompt.py`
  - Writer/Revision prompt 改为“在本卷确定性骨架内填内容”。
  - 若骨架内已有招标文件原文模板，优先保留原文模板，不改函件正文和表头。
- 测试：`236 passed, 2 skipped`，`pnpm --dir frontend typecheck` 通过。

### V1 新 M3 Mini Tasks（历史计划，已被 V2 路线替代）

- M3.1：定义 `SkeletonNode`/`FilledNode` 内部数据结构，不改变外部 `generate_bid_package(...)` 契约。
- M3.2：把骨架 Markdown 解析回节点树，保留节点标题、层级、原文模板和占位内容。
- M3.3：新增 node fill prompt：输入单节点模板 + 招标全文 + 证据包，输出该节点正文片段，不输出标题。
- M3.4：按卷串行或有限并发填节点，节点失败只重试该节点。
- M3.5：节点级拼回三卷 Markdown，确保标题/表头来自骨架，不来自 LLM。
- M3.6：审计失败时把问题定位到节点，而不是整卷重写。
- M3.7：用萧县/长丰县真实格式树做回归样例，验证投标函不重复、报价卷清单节点不丢。

---

## 历史已完成阶段（旧 M1–M67、M75、M76）

| 阶段 | 任务 | 一句话结果 |
|------|------|-----------|
| 0. 环境与基础设施 | M1–M8 | Docker Compose（PostgreSQL+pgvector / Redis / MinIO）、表结构、FastAPI/Next.js 骨架 |
| 1. 解析链路 | M9–M14 | 招标文件上传、PDF/DOCX/TXT 抽取、Parser Agent 结构化 JSON、人工确认 |
| 2. RAG 知识库 | M15–M20 | bge-large-zh 向量化、pgvector 检索、知识库上传/索引/检索 API |
| 3. 生成与导出 | M21–M26 | Generator Agent、Markdown 生成、DOCX 导出、MinIO 产物管理 |
| 4. 审查与确认 | M27–M32 | Reviewer Agent（规则+LLM）、废标风险、人工终审、修正循环 |
| 5. 前端工作台 | M33–M40 | 登录/注册/RBAC、项目工作台、知识库/风格库/账号管理页面 |
| 6. MVP 收尾 | M41–M44 | 端到端演示、质量自查、文档 |
| 7. workflow 产品化 | M45–M52 | workflow state 持久化、大纲确认、资料选择、在线编辑、再审查 |
| 8. 策略 Agent | M53–M56 | 报价策略（只给策略不报价）、评分预测、响应矩阵 |
| 9. 项目管理与输出 | M57–M60 | 历史项目恢复、DOCX 升级（封面/目录域/页眉脚）、完成通知 |
| 10. 真实案例学习 | M61–M64 | 真实投标 PDF → 脱敏案例 JSON、风格库管理与推荐 |
| 11. 正奇专用化 | M65–M67 | 产品范围收敛、知识库结构化标签、公路案例样本 |
| 13. Multi-Agent 分卷生成 | M78–M84 | 格式骨架先行、商务/技术/报价分卷 Agent、分卷 Revision、总审打回循环，无生成 fallback |
| 架构收敛 | M75 | TemplateProfile + EvidencePack + BidPlan 三层职责边界 |
| 知识库批量入库 | M76 | manifest 扫描/审核/导入脚本，默认 dry-run |

### V1 架构调整归档（不在当前 V2 主线内）

- V1 生成内核曾切换为 **格式骨架 + Multi-Agent 分卷填充**（`BID_GENERATION_MODE=multi_agent`）：
  保持 `generate_bid_package(...)` 外部契约不变，内部先从 `format_outline_tree`
  渲染三卷确定性骨架，再从招标文件格式章节抽取函件/表格原文模板，随后由商务标 Agent、
  技术标 Agent、报价文件 Agent 在各自骨架内填内容。分卷 Revision Agent 结合招标全文纠错，
  总审 Agent 只输出 JSON 修改意见并按卷打回循环；三卷最终由代码确定性拼接，LLM 不再合稿。
  解析/生成失败即失败，不再自动 fallback。该路线已被 V2 原文复制骨架替代，保留作回溯参考。
- 招标全文持久化到 `projects.tender_text`；Parser 额外抽取招标人、地点、范围、工期、
  质量标准、安全目标、截止时间七个核心字段。
- 公司信息档案（`/company` 页 + `company_profile` 表）：企业工商/资质/账户/项目班子
  信息注入生成 prompt，填充投标人基本状况表等商务内容。
- DOCX 修复：目录域/总页数打开时自动更新、页码域规范 run 结构、整页图片不再溢出。
- 线上结构权威改为**招标文件格式树 + 招标文件原文模板 + 人工确认目录**：Parser 新增 `bid_format_requirements` 字段，
  从"投标文件的组成/格式/编制/密封"章节总结投标文件分卷、必交表单、份数、签字盖章、
  装订密封要求；`format_outline_tree` 提供三卷树形目录；`format_skeleton_service.py`
  负责将格式树和招标文件原文模板转为生成骨架。格式树不完整时后端拒绝生成；历史模板退为
  可选公司风格案例，不再默认控制结构。
- 大纲编辑支持手动插图位：按技术章节保存人工配图标题、插入位置和说明，生成稿保留
  `【人工插图】` 占位，后续可人工替换为施工图、现场图或流程图。

### Phase 13 Mini Tasks（M78–M84）✅ 已完成代码落地

- M78：固定生成契约。`generate_bid_package(...)` 仍是唯一外部入口，返回 `BidPackage` 三卷和合并稿。
- M79：新增 Agent Context Builder。生成链路接收人工确认 `document_outline`、BidPlan、企业档案、知识库文本/图片和招标全文。
- M80：新增分卷生成 Agent。商务/资格、技术/施工组织设计、报价/经济标分别独立生成。
- M81：新增分卷 Revision Agent。每卷拿本卷初稿、招标全文、格式要求和确认目录做纠错，不跨卷重写。
- M82：新增总审 Agent。总审只输出 JSON 审查结果和按卷打回指令；三卷 marker 由代码拼接，避免 LLM 合稿丢 marker。
- M83：合并导出兼容。继续使用 `combine_delivery_volumes`、`split_delivery_markdown`、`draft_volumes`、`draft_markdown`。
- M84：测试覆盖。新增 multi-agent prompt、分卷生成、分卷修订、总审打回循环、失败不 fallback 测试。

---

## 未完成任务

### M68：正奇真实样本验收集 ⚠️ 部分完成

- 已有：质量评估框架（`run_quality_eval.py`）、gap 评估（`run_bid_gap_eval.py`）、
  5 个脱敏评估样例和对应测试。
- 还缺：正奇真实脱敏样本本身（市政、公路改扩建、交安养护各 ≥1 个，含招标文件、
  人工中标投标文件、AI 输出、差距报告）。这是业务资料整理问题，不是代码问题。

### M69：公司内网部署方案 ⬜ 未开始

- 单机 Docker Compose 内网版优先；production `.env.example`、Nginx/HTTPS/域名、
  端口暴露策略；服务重启后数据和文件不丢。
- 验收：干净内网服务器按文档部署成功，登录/上传/生成/下载全通。

### M70：数据安全、备份与审计 ⬜ 未开始

- PostgreSQL 定时备份+恢复演练；MinIO 加密/版本保留；上传/下载/删除/生成/权限变更
  审计记录；敏感证件资料最小权限。
- 验收：删库后能从备份恢复；普通用户无法越权；审计日志可追踪关键操作。

### M71：长任务队列与稳定性 ⬜ 未开始

- 解析/embedding/生成/导出从 FastAPI BackgroundTasks 迁移到可重试队列
  （Celery/RQ/Arq），支持状态、失败原因、重试、取消、超时。
- 验收：并发提交多项目 API 仍可响应；LLM timeout / MinIO 故障可重试或明确报错。

### M72：真实知识库导入规则与批量入库 🟨 部分完成

- 已有：命名/标签/敏感级别规则落到 manifest；目录扫描生成 CSV/JSON manifest 和
  整理后副本；`--import-to-kb` 复用现有入库 service；默认 dry-run、跳过待复核。
  实测导入 9 条样本资料成功。
- 还缺：去重/更新策略、OCR 提取、`.doc` 转换策略、更大样本人工验收。

### M73：真实项目试运行与质量门槛 ⬜ 未开始

- ≥3 个脱敏真实项目（市政/公路改扩建/交安养护）端到端跑通；保留人工修改记录；
  建立验收门槛：章节完整率、废标检出率、人工修改量、格式问题数、生成耗时。

### M77：公司风格库与结构/风格解耦 ⬜ 未开始（设计已定向）

- **背景**：每个招标文件对投标文件结构/格式的要求都不同（已由 `bid_format_requirements`
  按项目提取）；跨项目真正可复用的公司资产是**风格**——施工组织设计的深度惯例、写作
  语气、表格习惯、DOCX 版式。当前风格散落四处：DOCX `zhengqi` profile 硬编码在
  `docx_exporter.py`、版式规格在 `docs/zhengqi_bid_docx_format_reference.md`、语气
  约束在 generator system prompt 和 `bid_tone_checker.py`、深度惯例跟着 TemplateProfile。
- **目标形态**：
  - 结构：每个项目从招标文件解析（`bid_format_requirements` 已实现第一步）。
  - 风格：公司风格库统一管理——DOCX 视觉 profile（从硬编码变为可配置）、写作风格
    画像（语气/深度/禁用语）、指向知识库历史中标标书的引用。一个公司预计 2–3 套
    风格（公路版/市政版），不需要复杂 CRUD。
  - 模板库降级并更名为风格案例库：只做技术标深度、表格、图片位和语气参考，不再是结构权威。
- **前置条件**：先跑 M73 真实项目试运行，拿到"当前风格输出差在哪"的质量反馈再动手，
  避免建错抽象。
- **验收**：同一招标文件 + 不同风格 profile 能产出版式/语气不同但结构都满足招标
  格式要求的标书；新增风格不需要改代码。

### M74：新点投标文件制作软件边界与交付包 ⬜ 未开始

- 本系统输出 Word/Markdown/审查报告/资料引用包；新点负责最终电子投标文件制作、
  CA 签章、加密、上传。不做绕过新点官方流程的事。
- 验收：用系统导出的 DOCX 在新点软件做一次人工导入测试，记录格式损失和手动处理项。

---

## 下一步优先级

1. V2-M8：提升内容质量，重点补表格密度、施工方案篇幅、项目针对性和填空率。
2. 建立真实中标标书质量基线：南陵县三里镇、萧县2025公路作为黄金标准，每次生成后对比。
3. 扩大知识库真实资料导入，补人员证件、公司证件、业绩、施工方案和图片证据。
4. V2-M9：真实项目试运行与质量门槛，至少 3 个脱敏项目端到端评测。
5. V2-M10：内网部署、备份审计、队列稳定性和新点软件交付边界实测。
