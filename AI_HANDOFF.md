# AI Handoff

每次较大改动后更新本文件。另一个 AI 接手时先读这里，再读 README、minitasks 和 `docs/generation_contract.md`。

## 当前状态

日期：2026-07-02
当前生成内核：V2 原格式复制（两卷交付）
当前目标：等用户用清理好、命名规范的资料**重建知识库/公司档案**（现有本地库是临时测试数据，缺料不当缺口治），重建后陪跑整链验证；防废标"覆盖闸"P1（废标项分类后切回硬拦）；新点软件交付实测。近两周已落地"商务卷证据链（三大选派/证件业绩插图锚点落位/简历表台账填充）+ 格式医生（孤字归位/下划线断线）+ 技术卷附表逐张装配带附表X编号 + 拟分包去重 + RAG 语义重排接生产 + parser 评分项容错"。
⚠️ **未解决的已知病：福昕把投标函签名行/身份证明右列/授权委托书开头/日期槽转成浮动文本框**（python-docx 的 document.paragraphs 看不见 → 填不上）。曾修过一版（浮件删除/克隆），用户不认可已整体回退，工作保存在分支 `backup/textbox-fill-c9ee38c`；重做前先弄清用户看到的具体毛病，并守"诊断纪律"（真实文件+渲染亲眼看）。

## 当前架构铁律

1. **招标文件原格式页是最高权威。** 不重画商务格式，不输出近似稿。
2. **交付两卷：商务卷 + 技术卷。报价卷由外部造价软件单独做，本系统不产出、不拆分。**
3. **商务卷 = 照抄招标格式章 + 字段自动填 + 合规正文：**
   - PDF 招标：**优先福昕国内云转可编辑 Word**（真段落/真表格，开关 `CLOUD_PDF_CONVERT=foxit`）+ 自动填公司档案（投标人/地址/法代/资质等，复用 `_replace_known_fields`/`_fill_known_table_cells`）。云失败按阶梯下沉：pdf2docx 可编辑 → 整页截图+域（`_bake_fill_values_on_page`）→ 纯整页图 → 硬报错。`_audit_built_format_docx` 内容体检防空壳/丢页。
   - DOCX 招标：**copy-then-prune**（复制源文件后删格式章范围外元素），保留页眉页脚、图片、表格。格式章定位跳过 TOC、取最后一个非 TOC 标题。
4. **技术卷 = 严格按招标"投标文件格式"重建的目录 + LLM 写的施工组织设计正文 + 福昕可编辑附表**（`markdown_to_docx` 正奇排版 + 自动更新目录域；附表节经福昕转可编辑空表/或直接渲染成 Markdown 表格、`_append_docx`/docxcompose 拼到卷末另起页、数据格留空人工填），绝不追加到商务格式页上。
5. **技术卷目录"严格按招标投标文件格式重建"（本轮修根因 bug）**：招标没识别出技术标结构时，大纲原会退化成只剩"施工组织设计"一节占位 → 技术卷只一节(~7页)、占比详略与逐节知识库检索全失效。现 `workflow_service._expand_thin_outline`（检索前重建）：① `_extract_tender_format_structure` 抽招标"编制要点 + 附表清单"；② 有招标格式 → `_tender_format_outline` 照招标目录搭（编制要点成章、每张附表补成附表节）；③ 无 → `_boq_discipline_fallback`（按清单分部分项 + 标准章节）。施工方案按工程量清单分部分项 → 工序章节（`_discipline_sections`），章节标题带专业前缀让占比详略/知识库检索按专业落。人工确认的 `bid_outline_json` 仍优先；`construction_plan_outline.py` 25 节硬编码大纲已降为可选参考，**不再盲套**。技术卷编制不违反铁律 1（只管商务/报价格式）。
6. **占比拆工序 + 施工逻辑排序（占比只决定"写多少"、逻辑决定"先后"）**：占比越大的分部拆成越多道工序、每道工序单独成节（各一次 LLM 调用，突破单节 ~5000 字上限）——`_subsection_count`：≥40%→5 节 / ≥25%→4 / ≥15%→3 / ≥5%→2 / else 1。章节按施工逻辑排序（`_construction_rank`：路基→排水→路面→桥涵→交安→绿化），不按占比排。篇幅另由 `boq_service.adjust_min_chars` 按占比加厚/压缩（主导分部最高 2.2x、占比极小 0.7x；生成端有 ~1800 字硬底 `MIN_NODE_CONTENT_CHARS`，基准目标 `_CONFIRMED_OUTLINE_TARGET_CHARS=2200`）。
7. **防废标"招标覆盖闸"（交卷前最后一道，`v2_audit_service` 并入 `full_audit`）**：逐条核"评分项是否正面响应 / 废标项是否实质规避"。判定优先 LLM 评标视角语义判定（`prompts/coverage_audit_prompt`）；**废标项绝不靠关键词/bigram 放行**（废标条款原文常被抄进承诺表，关键词重合会把真违规误判成已覆盖）；LLM 不可用时 bigram 只兜底放宽评分项。废标漏=critical、评分漏=major。**当前为告警模式**：config `coverage_audit_block_invalid` 默认 False → 废标漏降为 major 不硬拦（因"初步评审不通过/报价超限价"等规则类废标项任何标书都不会专门写段响应，硬拦会对每份标误锁死）；待废标项按"实质响应类 vs 规则约束类"分类（P1）后设 True 切回硬拦。总开关 `enable_coverage_audit`。定向补写：某节未响应招标要求 → `content_writer.rewrite_node_for_compliance` 重写该节（best-effort）。
8. **失败语义**：格式复制失败、技术正文写作失败 = 硬错误，直接 `raise ValueError`，不回退不占位。审查发现严重问题（audit critical）则软阻断：不抛错，置 `audit_blocked=True` 并保留已生成内容供人工预览。
9. 知识库不控制格式结构，只提供事实证据与技术素材（**风格案例库已于 2026-07-03 整体删除**——从未接进写作提示词、大纲兜底被重建机制盖过）；**知识库"公司同类施工方案"当骨架打底**（沿用结构/工艺/深度，数据换本项目，严禁照搬旧项目数值/地名/项目名）。

## 当前关键文件

- `backend/services/cloud_pdf_convert.py`：福昕国内云 PDF→可编辑 Word。`convert_pdf_to_docx_via_foxit`（SN 签名 + `document/convert`→轮询 `task`→`download` 跟随302）、`convert_format_pages_via_cloud`（商务：切格式区→福昕→**填空与体检管线**：标签理顺/孤字归位→字段自动填→格式医生→清红章页码→固定字段收尾）、`convert_appendix_pages_via_cloud`（附表：切附表区→福昕，不填）。纯 httpx、无 SDK。
- `backend/services/docx_format_doctor.py`：**格式医生**（healer 注册制，铁律只改格式一字不改）。`run_format_doctor_prefill`（填前：孤字归位）+ `run_format_doctor(doc, profile)`（填后：下划线断线补齐，白名单+夹心兜底）。新格式病种往 `_HEALERS`/`_PREFILL_HEALERS` 加，别散落打补丁。
- `backend/services/appendix_service.py`：技术卷附表逐张装配（公司定稿表补"附表X"编号 / 招标原表福昕转 / 占位页；`match_company_appendix`/`_number_company_appendix`/`build_appendix_docx`）。
- `backend/services/asset_resolver.py` + `services/id_card_ocr.py`：按 owner_name/certificate_type 精确取证件图；身份证 OCR 判正反面（文件名分不出正反，必须 OCR）。
- `backend/rag/retriever.py`：`rerank_results` 生产重排（优先 bge-reranker 语义、失败回退关键词）。
- `backend/services/original_docx_format_service.py`：格式章复制与回退。`build_original_format_docx`（DOCX copy-then-prune）、`build_original_format_docx_from_pdf_editable`（pdf2docx 可编辑）、`build_original_format_docx_from_pdf_with_fields`（整页截图+值烧录）、`_find_format_page_range_in_pdf` / `_find_appendix_page_range_in_pdf`（商务/附表页区，跨引用"第X章"不误切 + 技术/报价卷边界识别）。
- `backend/services/generation_service.py`：两卷装配 `_assemble_two_volumes`（+ `appendix_format_path`）+ `_append_docx`（docxcompose 拼附表到技术卷末、先临时件校验再原子替换）+ 导出 `export_markdown_for_project`（拆卷前不剥 tdg:volume 标记）。
- `backend/services/v2_generation_service.py`：V2 编排 + Phase 0 格式复制阶梯（福昕→pdf2docx→图）+ `_audit_built_format_docx`（PDF 路径内容体检）+ `_sections_from_confirmed_outline`（读 `bid_outline_json` 驱动目录）+ `_collect_technical_sections`（旧回退：忠实跟招标，无则最小壳）+ `_distribute_requirement_items` + **附表渲染**（`_is_appendix_title`/`_appendix_markdown`：附表节不走 LLM 空写，渲染成 Markdown 表格——总体作业/进度计划表、劳动力计划表、临时占地计划表、外供电力需求计划表；施工总平面图为图占位）+ 覆盖闸触发定向补写 `rewrite_node_for_compliance`。技术卷各节 LLM 有界并发。
- `backend/services/workflow_service.py`：**技术卷大纲检索前重建**——`_expand_thin_outline`（招标格式退化时重建）、`_extract_tender_format_structure`（抽编制要点+附表）、`_tender_format_outline`（照招标目录搭）、`_boq_discipline_fallback`（按清单分部分项+标准章节）、`_discipline_sections`（清单分部分项→工序章节）、`_subsection_count`（占比→拆几节）、`_construction_rank`（施工逻辑排序）、`_DISCIPLINE_PROCESS`（各专业工序模板）。
- `backend/services/boq_service.py`：工程量清单解析 + `adjust_min_chars`（占比定详略，主导最高 2.2x / 极小 0.7x）+ `match_categories`/`_groups_of`。
- `backend/utils/file_parser.py`：`extract_text_from_xlsx`（openpyxl 读 .xlsx/.xlsm，行序列化"单元格|单元格"）+ .xls 走 LibreOffice；`SUPPORTED_EXTENSIONS` 含 .xlsx/.xlsm/.xls（工程量清单常为 Excel）。
- `backend/prompts/construction_plan_outline.py`：25 节标准施工组织设计深度大纲（已降为可选参考，不再盲套）。
- `backend/prompts/generator_prompt.py` / `backend/agents/content_writer_agent.py`：逐节写作（**最高准则置顶=招标要求：评分项逐条响应 ＞ BOQ 占比详略 ＞ 知识库骨架，冲突以招标为准**；评分/废标/必覆盖要点/字数预算注入 + 不达标重写 + `rewrite_node_for_compliance` 合规重写）。
- `backend/prompts/coverage_audit_prompt.py`：招标覆盖校验提示词（评标委员会视角逐条判"是否实质响应/规避"，废标项从严）。
- `backend/services/v2_audit_service.py`：格式、内容、证据审查 + **招标覆盖闸**（`evaluate_coverage`/`audit_coverage_layer`，废标漏 critical（受 `coverage_audit_block_invalid` 控制，当前降 major）、评分漏 major）。
- `backend/api/routers/project.py`：BOQ 上传接口 `POST /api/project/{id}/boq` 改为**只快速抽存清单全文即返回**，不再上传时同步算占比（原同步 ~30s LLM 把 DB 连接池抢空报 PoolError）；真实占比改到"开始生成"时算。
- `backend/agents/parser_agent.py`：解析 + `format_outline_tree`。
- `backend/core/llm_client.py`：统一 provider 解析（`resolve_llm_config`，`error_cls` 可注入）+ `has_real_key` + `chat_completion`（LLM 调用瞬态错误重试 + 指数退避，stdlib 实现）。parser/content_writer 复用，reviewer 保留自有策略。
- `backend/services/docx_health_check.py`：对落盘 `.docx` 做确定性体检，0-100 质量分（6 项加权：必填字段/表格填充/章节齐全/残留物/字体一致/篇幅响应）。`score_docx`（单卷）+ `score_delivery`（按卷拆分母：必填/表格量商务卷、章节/篇幅量技术卷、残留两卷取严、字体仅技术卷）。
- `backend/services/delivery_quality.py`：`score_delivery_files` / `score_project_delivery`；出标后挂非阻断钩子，自动按卷打分并落 `backend/eval_results/project_{id}.json`（已 gitignore），打分失败绝不影响出标。
- `backend/api/main.py`：已瘦身为 ~75 行装配层（app 构造 + lifespan + `/health` + `include_router`）；按域拆出 `backend/api/routers/{auth,admin,company,knowledge,project,performance_archive,cert_archive}.py`（各 APIRouter），共享依赖 `authorized_project`/`_raise_http_error` 在 `backend/api/deps.py`，main.py re-export 这些名字保向后兼容。
- `backend/services/project_service.py`：已瘦身为 ~122 行**门面**，真实逻辑拆进 `backend/services/project/` 子包（`errors/crud/parsing/outline/strategy/delivery/_helpers/_runtime` 共 8 模块），门面 re-export 全部公共名与异常类。
- `frontend/components/TenderWorkspace.tsx`：工作台主组件（三栏 Tab、**两卷下载、无报价**）。
- `backend/scripts/benchmark_vs_baseline.py` / `visual_regression.py`：质量/视觉度量。

## 最近变更（2026-06-30 ~ 07-02 窗口，1f27072..8cdc2d7，已合 main）

围绕"商务卷证据链 + 格式体检 + 技术卷附表装配"：

- **技术卷附表逐张装配**（1f27072 + a873d27，`services/appendix_service.py`）：按招标附表清单逐张定来源——公司定稿表（`backend/assets/company_appendices/`）原样拼并自动补"**附表X**"编号（目录=Word TOC 域抓标题，一处修两处对）→ 招标原表福昕转 → 占位页。教训：`_number_company_appendix` 曾"定义了没接线"导致附表二~五没编号。
- **简历表按台账结构化信息填 + 总工对称 + 落位锚点补表头**（42a7ae4）：`build_pm_resume_fields(name, role)` 用台账（身份证号推年龄性别、builder_certs 取证号专业、职称），OCR 降为兜底；`_fill_resume_tables` 角色感知填项目经理+总工两张简历表；`_ANCHOR_SPECS` 三锚点（法定代表人身份证明/项目经理资历表/项目总工资历表）补表头关键词治"证件图掉卷尾"。
- **商务卷拟分包表去重**（959a279）：`_ORG_DOC_SOURCES` 移除拟分包注入——福昕格式章已带招标那张，再注入资料库 21×4 空表=重复变丑；只保留项目管理机构组织机构图注入。
- **切开标签理顺**（8ae120a，`_normalize_split_labels`）：福昕把"性 别""电 话"等两字标签塞了字间空格→填空认不出标签。只对"去空格后恰等于已知标签"的段去空格，填值前跑。
- **RAG 语义重排接生产**（d7a84f7）：`rag/retriever.rerank_results`——生产检索原走关键词数格子（垃圾目录片段排第1、漏"沥青混凝土≈路面"）；改为优先 bge-reranker、失败自动回退关键词。模型已缓存本机（首载下载 ~5min，后秒级）。
- **删 langchain 三包**（ab6eccf）：源码零引用，纯瘦身去攻击面。
- **格式医生**（71481f0 + 212652b，`services/docx_format_doctor.py`，healer 注册制）：用户定的新架构——不在转换环节散打补丁，转换+填空前后各加一道全文档体检；铁律只改格式一字不改。填后 `heal_underline_slots` 治"下划线画一半"（白名单=profile 我们填的值+夹心兜底，挡"年/月/日"误加线）；填前 `heal_orphan_split_labels` 孤字归位（"性…"+"别："拼回"性别："，孤字特征=前一个可见 run 是带线已填值，字符守恒）。均在用户真实文件上渲染前后对比验收过。
- **parser 评分项容错**（8cdc2d7）：LLM 漏 description 只给 title（项目176实测5项全漏）→ title/description 互相回填，不再炸整次解析。
- 回退记录：c9ee38c（浮动文本框填充）被用户要求整体回退，存 `backup/textbox-fill-c9ee38c`；根因诊断仍有效（见"当前状态"⚠️）。
- 测试基线：**431 passed / 2 skipped**（backend/venv 缺 openpyxl 时另有 3 个测试文件收集失败，属环境问题非代码）。

## 上轮变更（2026-06-29，commit d404459，已合 main）

围绕"工程量清单(BOQ)驱动技术卷 + 严格按招标投标文件格式 + 防废标"：

- **工程量清单支持 Excel 上传**：`file_parser.extract_text_from_xlsx`（openpyxl 读 .xlsx/.xlsm，行序列化"单元格|单元格"）+ .xls 走 LibreOffice；`SUPPORTED_EXTENSIONS` 放开 .xlsx/.xlsm/.xls；前端 `ProjectBOQPanel` accept 放开。BOQ 上传接口改为**只快速抽存清单全文即返回**，不再上传时同步算占比（原同步 ~30s LLM 把 DB 连接池抢空报 PoolError）；真实占比改到"开始生成"时算。
- **技术卷大纲严格按招标"投标文件格式"重建（修根因 bug）**：招标没识别出技术标结构时大纲原退化成只剩"施工组织设计"一节占位 → 技术卷只一节(~7页)、占比详略与逐节检索全失效。现 `_expand_thin_outline`（检索前重建）：有招标格式 → `_tender_format_outline` 照招标目录搭（编制要点成章 + 每张附表补成附表节）；无 → `_boq_discipline_fallback`（清单分部分项 + 标准章节）。施工方案按清单分部分项 → 工序章节（`_discipline_sections`）。
- **占比拆工序 + 施工逻辑排序**：占比越大拆越多道工序（≥40%:5/≥25%:4/≥15%:3/≥5%:2/else 1），每道工序单独成节（各一次 LLM 调用，突破单节字数上限）；章节按施工逻辑排（`_construction_rank`：路基→排水→路面→桥涵→交安→绿化）。占比只决定"写多少"、逻辑决定"先后"。
- **附表渲染成真表格**（`v2_generation_service._is_appendix_title`/`_appendix_markdown`）：附表节不走 LLM 空写，渲染成 Markdown 表格（总体作业/进度计划表、劳动力计划表、临时占地计划表、外供电力需求计划表；施工总平面图为图占位），`markdown_to_docx` 转 docx 表格。
- **占比详略加强**（`boq_service.adjust_min_chars`）：占比大加厚小压缩，主导分部最高 2.2x、极小 0.7x；基准 `_CONFIRMED_OUTLINE_TARGET_CHARS` 1500→2200，最低 `MIN_NODE_CONTENT_CHARS` 1200→1800。
- **防废标"招标覆盖闸"**（`v2_audit_service` + `prompts/coverage_audit_prompt`）：交卷前逐条核"评分项是否正面响应/废标项是否实质规避"，并入 `full_audit`。废标漏=critical、评分漏=major；判定优先 LLM 评标视角语义判定，**废标项绝不靠关键词/bigram 放行**，LLM 不可用时 bigram 只兜底放宽评分项。**当前告警模式**：config `coverage_audit_block_invalid` 默认 False → 废标漏判 major 不硬拦（因"初步评审不通过/报价超限价"等规则类废标项任何标书都不会专门写段响应，硬拦会误锁死每份标）；待废标项按"实质响应类 vs 规则约束类"分类（P1）后设 True 切回硬拦。总开关 `enable_coverage_audit`。定向补写：某节未响应 → `rewrite_node_for_compliance` 重写该节（best-effort）。
- **生成提示词**（`generator_prompt.py`）：写作规则置顶"最高准则"=招标要求（评分项逐条响应/废标项一条不踩）＞ BOQ 占比详略 ＞ 知识库骨架，冲突以招标为准；知识库"公司同类施工方案"当骨架打底（沿用结构/工艺/深度，数据换本项目，严禁照搬旧项目数值/地名/项目名）。
- **DB 连接池**（`core/db.py`）：maxconn 10→20。
- ⚠️ 已知非代码项：**AI 账户余额（402 需充值）**——整链真单实测前必充；技术卷目录(TOC)是 Word 域，文件已设打开自动更新域，非 Word 预览软件需手动更新。
- 测试：后端 **~428 passed**（唯一失败 `test_assemble_two_volumes_commercial_copies_format_technical_is_prose` 是改前就存在的商务卷旧问题，与本轮无关）。

## 历史变更（2026-06 早些轮次）

格式复制升级 + 技术卷目录人工确认 + 生成提速，均已合 main：

- **福昕云 PDF→可编辑 Word（核心）**：商务格式章 + 技术附表经福昕国内云转**真·可编辑 Word**（真段落/真表格）+ 自动填字段；Phase0 最上层（`CLOUD_PDF_CONVERT=foxit`）失败下沉 pdf2docx→图；附表 docxcompose 拼技术卷末；新依赖 `docxcompose==2.2.0`（不动钉死的 httpx0.25.2/numpy1.24.3）；凭证 `FOXIT_CLOUD_CLIENT_ID/SECRET` 在 `.env`。**解决"可编辑 vs 一模一样"取舍**——实测招标#122 商务 168 段 19 表 + 附表 6 可编辑表 + 字段已填。
- **技术卷目录人工确认**：放出大纲编辑器（「技术大纲」标签+「添加章节」）；parser 扫招标"编制要点+附表"逐条原样成 `technical_outline`；生成读人工确认的 `bid_outline_json` 驱动目录、无规定时最小中性壳（**不再盲套 25 节硬编码大纲**）；商务卷移出大纲环节。
- **技术卷生成并行化**：25 节 LLM 由串行改 `ThreadPoolExecutor` 有界并发（`BID_WRITER_CONCURRENCY` 默认 5），约 25min→5-6min。
- **P0-2**：PDF 原格式路径补 `_audit_built_format_docx` 内容体检，防空壳/丢页静默发布。
- 格式章页范围修复（跨引用"第X章"误切 + 技术/报价卷边界）；parser `max_tokens` 按输入动态算（修长招标 400）；前端加「新项目」按钮。后端测试 → **333 passed**（`-m "not live_llm"`）。
- ⚠️ 两个 best-effort 静默项，客户启用前真样张各验一次：**附表横表方向**（docxcompose 可能压成竖版）、**合并保真**（已加损坏校验→丢附表保纯技术卷兜底）。**项目经理行自动填故意不做**（实测会填错表/污染标书，人工填）。部署用仓库根 `/.venv`（已装 docxcompose），别用脏的 `backend/venv`。

历史背景：更早几轮把交付从三卷重构为两卷、抽 `core/llm_client`、拆 `main.py`/`project_service`、加 CI+vitest、知识库证件/业绩入库（M12）+ OCR（M16）——均为现状基线，详见 Git。

## 下个接手者优先看

0. **先读记忆再动手**：`~/.claude/.../memory/MEMORY.md` 索引了两周的拍板与坑（知识库命名规范、福昕表格保真结论"竖线台阶=招标原样别捋直"、诊断纪律"真实文件+渲染亲眼看"、用户协作硬约束）。用户是不懂技术的业务方，说人话。
1. **知识库重建（等用户）**：现有本地库=临时测试数据，缺料（养护资质/社保图/交安B级标注）**不当缺口治**；用户会用清理好、按规范命名的资料重跑导入脚本重建。命名规范见记忆 `kb-naming-and-resume-fill`。重建后陪跑整链，把"料齐了还填不上/插不上"的一次清干净。
2. **真单实测**：用一份真实招标 + 工程量清单跑通整链 → 验证技术卷目录/附表编号、商务卷证件落位与简历表填充、格式医生效果（下划线/孤字）、覆盖闸逐条核到评分/废标项。生成期间后端用 `BACKEND_NO_RELOAD=1 bash scripts/dev_local.sh` 起（--reload 会在改文件时杀掉生成线程）。
3. **覆盖闸 P1：废标项分类后切回硬拦**——当前 `coverage_audit_block_invalid=False`（告警模式）。需把废标项分成"实质响应类（如工期/质量/安全限值、要求的承诺资料）vs 规则约束类（初步评审不通过/报价超限价等任何标书都不会专门响应的）"，只对前者切回 critical 硬拦，再把开关设 True，做到"拦真该拦的、不误锁死每份标"。
4. **整链格式实测（福昕开关已开）**：在 Pages/新点 验商务卷 + 附表可编辑且与招标一致；尤其 ⚠️ 附表横表方向、docxcompose 合并保真。
5. **M20 新点软件交付实测**——两卷（福昕可编辑 DOCX + 技术正文）在新点能否导入/套打/出目录。
6. **M23 本项目专用技术材料库**——技术卷实质的下一个瓶颈（全局库零技术方案文本），需用户提供真实施工组织设计文本、`project_id` 隔离喂 RAG。
7. 公司内网部署：任务队列（生成耗时长）、备份、审计。

## 验证命令

- 后端测试：`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q -m "not live_llm"`（基线 **431 passed / 2 skipped**，2026-07-02；若用 backend/venv 会因缺 openpyxl 另有 3 个测试文件收集失败，属环境问题）
- 前端类型：`cd frontend && npx tsc --noEmit`
- 前端单测（vitest）：`pnpm --dir frontend test`
- 质量对标：`backend/scripts/benchmark_vs_baseline.py compare --generated <稿> --baseline <中标标书>`
- 视觉回归：`backend/scripts/visual_regression.py <导出DOCX>`
- CI（`.github/workflows/ci.yml`）会自动跑后端 pytest（`-m "not live_llm"`）+ 前端 typecheck/lint/test/build。
- 后端 `--reload` 热重载：纯 `.py` 改动不用重启；装新依赖或改 `.env` 才需重启。
