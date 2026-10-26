# AI Handoff

每次较大改动后更新本文件。另一个 AI 接手时先读这里，再读 README、minitasks 和 `docs/generation_contract.md`。

## 当前状态

日期：**2026-10-27**｜代码基线：`main@7e32c8a`（GitHub `origin/main@ebb9298`，本地领先 1 个提交未推）
当前生成内核：V2 原格式复制（**两卷交付**）
测试基线：**594 passed / 2 deselected**（`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q -m "not live_llm"`，约 100 秒）

当前目标：① 用户用清理好、命名规范的资料重建知识库/公司档案后陪跑整链；② 防废标"覆盖闸"P1（废标项分类后切回硬拦）；③ 新点软件交付实测；④ 技术卷实质（缺施组文本）。

⚠️ **未解决的已知病：福昕把投标函签名行 / 身份证明右列 / 授权委托书开头 / 日期槽转成浮动文本框**（python-docx 的 `document.paragraphs` 看不见 → 填不上）。曾修过一版（浮件删除/克隆），用户不认可已整体回退，工作保存在分支 `backup/textbox-fill-c9ee38c`；重做前先弄清用户看到的具体毛病，并守"诊断纪律"（真实文件 + 渲染亲眼看）。

## 当前架构铁律

1. **招标文件原格式页是最高权威。** 不重画商务格式，不输出近似稿。
2. **交付两卷：商务卷 + 技术卷。报价卷由外部造价软件单独做，本系统不产出、不拆分。**
3. **商务卷 = 照抄招标格式章 + 字段自动填 + 合规正文。** 格式章获取按**字节头**分流，**两条路都没有降级**：
   - `tender_bytes[:2] == b"PK"`（Word 招标）→ `build_original_format_docx`：OOXML copy-then-prune，零转换损耗，保留页眉页脚/图片/表格。
   - `%PDF`（PDF 招标）→ `cloud_pdf_convert.convert_format_pages_via_cloud`（福昕国内云，`CLOUD_PDF_CONVERT=foxit`）转真段落/真表格。
   - **已删除的三档备胎：pdf2docx 可编辑 / 整页截图+域 / 纯整页图。** 开关非 foxit 或福昕失败 = `raise ValueError` 硬报错。`_audit_built_format_docx` 做内容体检防空壳/丢页。
   - 两条路拿到 docx 后走**同一个填值入口** `original_docx_format_service.fill_format_docx`（20+ 步），只有填前/填后 healer 分组不同（见铁律 10）。
4. **技术卷 = 严格按招标"投标文件格式"重建的目录 + LLM 写的施工组织设计正文 + 福昕可编辑附表**（`markdown_to_docx` 正奇排版 + 自动更新目录域；附表 docxcompose 拼到卷末另起页、数据格留空人工填），绝不追加到商务格式页上。
5. **技术卷目录"严格按招标投标文件格式重建"**：招标没识别出技术标结构时，大纲会退化成只剩"施工组织设计"一节占位 → 技术卷只一节、占比详略与逐节检索全失效。`workflow_service._expand_thin_outline`（检索前重建）：① `_extract_tender_format_structure` 抽"编制要点 + 附表清单"；② 有招标格式 → `_tender_format_outline` 照招标目录搭；③ 无 → `_boq_discipline_fallback`。人工确认的 `bid_outline_json` 仍最优先；`prompts/construction_plan_outline.py` 的 25 节硬编码大纲已降为可选参考，**不再盲套**。
6. **占比拆工序 + 施工逻辑排序（占比只决定"写多少"、逻辑决定"先后"）**：`_subsection_count`（≥40%→5 节 / ≥25%→4 / ≥15%→3 / ≥5%→2 / else 1）；`_construction_rank`（路基→排水→路面→桥涵→交安→绿化）；`boq_service.adjust_min_chars`（主导最高 2.2x、极小 0.7x）；硬底 `MIN_NODE_CONTENT_CHARS=1800`，基准 `_CONFIRMED_OUTLINE_TARGET_CHARS=2200`。
7. **防废标"招标覆盖闸"**（`v2_audit_service` 并入 `full_audit`）：逐条核"评分项是否正面响应 / 废标项是否实质规避"。**废标项绝不靠关键词/bigram 放行**（废标条款原文常被抄进承诺表，关键词重合会把真违规误判成已覆盖）。LLM 不可用时 bigram 只兜底放宽评分项。废标漏 = critical、评分漏 = major。**当前告警模式**：`COVERAGE_AUDIT_BLOCK_INVALID` 默认 False → 废标漏降 major 不硬拦，待废标项分类（P1）后切回。定向补写 `rewrite_node_for_compliance`（best-effort）。
8. **失败语义**：格式复制失败、技术正文写作失败 = 硬错误 `raise ValueError`，不回退还占位。审查 critical = 软阻断（`audit_blocked=True`，不抛错，保留内容供人工预览）。
9. 知识库不控制格式结构，只提供事实证据与技术素材（风格案例库 2026-07-03 已整体删除）；**"公司同类施工方案"当骨架打底**（沿用结构/工艺/深度，数据换本项目，严禁照搬旧项目数值/地名/项目名）。
10. **格式医生分组（healer 注册制，铁律只改格式一字不改）**：
    - 福昕路：填前 `run_format_doctor_prefill`（孤字归位）+ 填后 `run_format_doctor`（下划线断线等全量）。
    - Word 路：填前 `run_format_doctor_prefill_native`（**只含防叠印 `defloat_long_textboxes`**）+ 填后 `run_format_doctor_native_docx`。
    - **为什么 Word 路也要防叠印**：用户上传的"Word 招标"多数其实是 PDF 转换件（每份上千字距伪影 run、几十个浮动文本框），叠印病同样发作。但福昕专属 healer（劈句合并/假两栏/幽灵图）在真原生 Word 上会误伤，故两路分组，不整体切通道。
11. **出卷后的收尾顺序（不得乱插）**：商务卷 → 加页码 → `pagination_doctor.heal_stub_pages`（尾巴页）→ `run_format_doctor_assembled`（核对表列宽 + 业绩图注绑定）→ **`blank_page_doctor.heal_blank_pages` 必须最后**（否则前面的步骤又会造出空白页）。全部 best-effort，失败只告警不阻断出标。

## 当前关键文件

- `backend/services/v2_generation_service.py`（约 2300 行）：V2 编排。Phase 0 格式章获取（字节头分流 + 无降级）→ `_audit_built_format_docx` → 附表装配 → Phase 3 正文（BOQ 驱动 + 并发 LLM + 合规补写）→ Phase 4 装配 / 4b 商务补充 → Phase 5 `full_audit` → Phase 6 `combine_delivery_volumes`。
- `backend/services/original_docx_format_service.py`（约 2500 行）：格式章复制 + **`fill_format_docx` 商务卷唯一填值入口**（20+ 步，含 `_strip_leading_chapter_title` 剥卷首章标题、`_fill_textbox_placeholders` 浮动文本框占位符、`_fill_resume_tables`、`_attach_declared_id_scans`、`_strip_tender_page_numbers`、`_log_unfilled_fields`）。
- `backend/services/cloud_pdf_convert.py`：福昕国内云 PDF→可编辑 Word（SN 签名 + `document/convert`→轮询 `task`→`download` 跟随 302）。**只负责转换，不填值。** 纯 httpx、无 SDK。
- `backend/services/docx_format_doctor.py`（约 1700 行）：格式医生。4 个注册表：`_PREFILL_HEALERS` / `_HEALERS`（福昕路）、`_NATIVE_PREFILL_HEALERS` / `_NATIVE_DOCX_HEALERS`（Word 路）、`run_format_doctor_assembled`（成品级）。16+ healer。
- `backend/services/pagination_doctor.py` / `blank_page_doctor.py`：尾巴页 / 空白页硬闸。
- `backend/services/commercial_fixed_fields.py`：公司名错别字纠正（安徽正气→安徽正奇）+ 固定字段一致性核对。
- `backend/services/generation_service.py`：`export_markdown_for_project`（拆卷前**不剥** `tdg:volume` 标记）+ `_assemble_two_volumes` + `_append_docx`（docxcompose 拼附表、临时件校验后原子替换）+ `_place_anchored_images`（证据图锚点落位）。
- `backend/services/appendix_service.py`：附表逐张装配（公司定稿表补"附表X"编号 / 招标原表福昕转 / 占位页）。
- `backend/services/workflow_service.py`：`run_bid_workflow` / `confirm_project` + 大纲重建（`_expand_thin_outline` / `_tender_format_outline` / `_boq_discipline_fallback` / `_discipline_sections` / `_subsection_count` / `_construction_rank`）。
- `backend/services/boq_service.py`：`build_boq`（占比）+ `adjust_min_chars`（详略）。
- `backend/services/v2_audit_service.py`：格式/内容/证据 + 招标覆盖闸（`evaluate_coverage` / `audit_coverage_layer`）。
- `backend/services/conformance_service.py` + `tender_spec_service.py`：合规核对引擎（技术卷"招标核对表"来源）。
- 证据链：`asset_resolver.py`（按 owner_name/certificate_type 精确取证件图）、`id_card_ocr.py`（身份证 OCR 判正反面）、`similar_project_fill_service.py`（类似项目节克隆填充）、`company_component_service.py`（组织框图等成品组件照搬）、`cert_archive_service.py` / `performance_archive_service.py` / `personnel_roster_service.py`（证书/业绩/人员台账）。
- 质量：`docx_health_check.py`（单卷 0-100 分）、`delivery_quality.py`（出标后按卷打分，非阻断）、`backend/scripts/benchmark_vs_baseline.py` / `visual_regression.py`。
- `backend/core/config.py`：`CLOUD_PDF_CONVERT`（**唯一有效值 foxit**）、`FOXIT_CLOUD_CLIENT_ID` / `FOXIT_CLOUD_SECRET`（注意不是 `CLIENT_SECRET`）、`BID_WRITER_CONCURRENCY`（默认 5）、`ENABLE_COVERAGE_AUDIT` / `COVERAGE_AUDIT_BLOCK_INVALID`。
- `frontend/components/TenderWorkspace.tsx`：工作台主组件（三栏 Tab：解析确认 / 技术大纲 / 正文编辑 / 标书预览；**两卷下载、无报价**）。

## 最近变更（2026-08，`ebb9298..7e32c8a`）

- **防叠印接进 Word 通道（7e32c8a，本地未推）**：`defloat_long_textboxes` 挂进 `_NATIVE_PREFILL_HEALERS`（填前跑）、`filled_value_char_squeeze` 挂进 `_NATIVE_DOCX_HEALERS`（填后跑）。复盘 #217（8-17 修好、8-19 用户重生成仍满屏叠印）根因：**healer 只挂在福昕路，而生产里用户传的"招标文件"全是 PDF 转换出来的 Word，走的是 `build_original_format_docx` 通道，healer 一次都没执行过。** 守卫严（单一文本框 + ≥40 字纯文字 / 填值白名单 + |字距|≥20），真原生 Word 上无害空转。验证：拿 #217 真实招标走生产入口端到端，拆浮框 2 个、剥字距 1 处，产物 160 页全卷叠印扫描干净；新增 3 个接线回归测试（谁摘谁挂）+ 通道对照快照测试。教训：**验证必须走生产入口，直接调 healer 会绕过路由把假阳性当修好。**
- 前序（ebb9298 及之前）：马鞍山 #216 两层文字叠印三连修（浮框长条款拆回正文流 + 封面挤压字距剥除 + 出厂叠印自检）；卷首示范文本编者脚注剥净；章标题剥离认尾随脚注圈号；亲笔签字位守卫；外地格式四处适配；插图 DPI=0 除零修复；业绩视觉查重（dhash 双档）；资历表成品模版整表照搬；空白页闸时间预算 420s→1500s（88MB 全量附图卷）；商务卷卷首剥"第X章 投标文件格式"。

## 上轮变更（2026-06-30 ~ 07-09）

- 技术卷附表逐张装配（`appendix_service`，公司定稿表自动补"附表X"编号）。
- 简历表按台账结构化填 + 总工对称 + 三角色证据锚点落位；身份证 OCR 分正反。
- 商务卷拟分包表去重；切开标签理顺；RAG 语义重排（bge-reranker）接生产；删 langchain 三包。
- **格式医生**（healer 注册制）+ 填前孤字归位 + 填后下划线断线。
- 福昕云 PDF→可编辑 Word 接进 Phase 0；技术卷目录人工确认（大纲编辑器）；技术卷 LLM 有界并发（25min→5-6min）；`_audit_built_format_docx` 内容体检。
- 局域网一键部署（`docker-compose.yml` 五件套 + `backend/Dockerfile` + `frontend/Dockerfile` + `MINIO_PUBLIC_URL` 解耦容器内连接与浏览器下载地址）。
- 回退记录：`c9ee38c`（浮动文本框填充）被用户要求整体回退，存 `backup/textbox-fill-c9ee38c`。

## 下个接手者优先看

0. **先读记忆再动手**：`~/.workbuddy/MEMORY.md` 与项目 `.workbuddy/memory/` 索引了历次拍板与坑（知识库命名规范、福昕表格保真结论"竖线台阶=招标原样别捋直"、诊断纪律"真实文件+渲染亲眼看"）。用户是不懂技术的业务方，说人话。
1. **知识库重建（等用户）**：现有本地库=临时测试数据，缺料（养护资质/社保图/交安B级标注）**不当缺口治**。
2. **真单实测**：真实招标 + 工程量清单跑通整链 → 验技术卷目录/附表编号、商务卷证件落位与简历表填充、格式医生效果、覆盖闸逐条核到评分/废标项。生成期间后端用 `BACKEND_NO_RELOAD=1 bash scripts/dev_local.sh`（`--reload` 会在改文件时杀掉生成线程）。
3. **覆盖闸 P1**：把废标项分成"实质响应类 vs 规则约束类"，只对前者切回 critical 硬拦，再设 `COVERAGE_AUDIT_BLOCK_INVALID=True`。
4. **整链格式实测**：Pages/新点 验商务卷 + 附表可编辑且与招标一致；尤其附表横表方向、docxcompose 合并保真。
5. **新点软件交付实测**：两卷（福昕可编辑 DOCX + 技术正文）能否导入/套打/出目录。
6. **技术卷实质**：全局库零技术方案文本，需用户提供真实施工组织设计文本、按 `project_id` 隔离喂 RAG。
7. 公司内网：任务队列（生成耗时长）、备份、审计。

## 验证命令

- 后端测试：`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q -m "not live_llm"`（基线 **594 passed / 2 deselected**，2026-10-27）。用仓库根 `.venv`；`backend/venv` 缺 openpyxl 会多 3 个收集失败（环境问题）。
- 前端类型：`cd frontend && npx tsc --noEmit`
- 前端单测：`pnpm --dir frontend test`
- 质量对标：`backend/scripts/benchmark_vs_baseline.py compare --generated <稿> --baseline <中标标书>`
- 视觉回归：`backend/scripts/visual_regression.py <导出DOCX>`（**只对技术卷可靠**；商务卷含浮动文本框时 soffice 渲染会膨胀，非 Word 真实缺陷）
- CI（`.github/workflows/ci.yml`）：后端 pytest（`-m "not live_llm"`）+ 前端 typecheck/lint/test/build。
