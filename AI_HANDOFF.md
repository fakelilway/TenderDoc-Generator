# AI Handoff

每次较大改动后更新本文件。另一个 AI 接手时先读这里，再读 README、minitasks 和 `docs/generation_contract.md`。

## 当前状态

日期：2026-06-17
当前生成内核：V2 原格式复制（两卷交付）
当前目标：福昕云格式链整链真实生成实测、新点软件交付实测、本项目专用技术材料库。格式保真（升级为「可编辑 Word」）和技术卷人工确认目录已落地。

## 当前架构铁律

1. **招标文件原格式页是最高权威。** 不重画商务格式，不输出近似稿。
2. **交付两卷：商务卷 + 技术卷。报价卷由外部造价软件单独做，本系统不产出、不拆分。**
3. **商务卷 = 照抄招标格式章 + 字段自动填 + 合规正文：**
   - PDF 招标：**优先福昕国内云转可编辑 Word**（真段落/真表格，开关 `CLOUD_PDF_CONVERT=foxit`）+ 自动填公司档案（投标人/地址/法代/资质等，复用 `_replace_known_fields`/`_fill_known_table_cells`）。云失败按阶梯下沉：pdf2docx 可编辑 → 整页截图+域（`_bake_fill_values_on_page`）→ 纯整页图 → 硬报错。`_audit_built_format_docx` 内容体检防空壳/丢页。
   - DOCX 招标：**copy-then-prune**（复制源文件后删格式章范围外元素），保留页眉页脚、图片、表格。格式章定位跳过 TOC、取最后一个非 TOC 标题。
4. **技术卷 = 人工确认目录 + LLM 写的施工组织设计正文 + 福昕可编辑附表**（`markdown_to_docx` 正奇排版 + 自动更新目录域；附表一~八经福昕转可编辑空表、`_append_docx`/docxcompose 拼到卷末另起页、数据格留空人工填），绝不追加到商务格式页上。
5. **技术卷目录由人工确认驱动**：parser 扫招标"编制要点+附表"逐条原样成 `technical_outline`；`_collect_technical_sections` 优先读人工确认的 `bid_outline_json`，招标没规定结构时给最小中性壳（**不再盲套** `construction_plan_outline.py` 的 25 节硬编码大纲——该常量降为可选参考）。技术卷编制不违反铁律 1（只管商务/报价格式）。
6. **失败语义**：格式复制失败、技术正文写作失败 = 硬错误，直接 `raise ValueError`，不回退不占位。审查发现严重问题（audit critical）则软阻断：不抛错，置 `audit_blocked=True` 并保留已生成内容供人工预览。
7. 公司风格案例和知识库不控制格式结构，只提供事实证据、技术素材和风格参考。

## 当前关键文件

- `backend/services/cloud_pdf_convert.py`：福昕国内云 PDF→可编辑 Word。`convert_pdf_to_docx_via_foxit`（SN 签名 + `document/convert`→轮询 `task`→`download` 跟随302）、`convert_format_pages_via_cloud`（商务：切格式区→福昕→复用四件套填字段）、`convert_appendix_pages_via_cloud`（附表：切附表区→福昕，不填）。纯 httpx、无 SDK。
- `backend/services/original_docx_format_service.py`：格式章复制与回退。`build_original_format_docx`（DOCX copy-then-prune）、`build_original_format_docx_from_pdf_editable`（pdf2docx 可编辑）、`build_original_format_docx_from_pdf_with_fields`（整页截图+值烧录）、`_find_format_page_range_in_pdf` / `_find_appendix_page_range_in_pdf`（商务/附表页区，跨引用"第X章"不误切 + 技术/报价卷边界识别）。
- `backend/services/generation_service.py`：两卷装配 `_assemble_two_volumes`（+ `appendix_format_path`）+ `_append_docx`（docxcompose 拼附表到技术卷末、先临时件校验再原子替换）+ 导出 `export_markdown_for_project`（拆卷前不剥 tdg:volume 标记）。
- `backend/services/v2_generation_service.py`：V2 编排 + Phase 0 格式复制阶梯（福昕→pdf2docx→图）+ `_audit_built_format_docx`（PDF 路径内容体检）+ `_sections_from_confirmed_outline`（读 `bid_outline_json` 驱动目录）+ `_collect_technical_sections`（旧回退：忠实跟招标，无则最小壳）+ `_distribute_requirement_items`。技术卷 25 节 LLM 有界并发。
- `backend/prompts/construction_plan_outline.py`：25 节标准施工组织设计深度大纲。
- `backend/prompts/generator_prompt.py` / `backend/agents/content_writer_agent.py`：逐节写作（评分/废标/必覆盖要点/字数预算注入 + 不达标重写）。
- `backend/services/v2_audit_service.py`：格式、内容、证据审查。
- `backend/agents/parser_agent.py`：解析 + `format_outline_tree`。
- `backend/core/llm_client.py`：统一 provider 解析（`resolve_llm_config`，`error_cls` 可注入）+ `has_real_key` + `chat_completion`（LLM 调用瞬态错误重试 + 指数退避，stdlib 实现）。parser/content_writer 复用，reviewer 保留自有策略。
- `backend/services/docx_health_check.py`：对落盘 `.docx` 做确定性体检，0-100 质量分（6 项加权：必填字段/表格填充/章节齐全/残留物/字体一致/篇幅响应）。`score_docx`（单卷）+ `score_delivery`（按卷拆分母：必填/表格量商务卷、章节/篇幅量技术卷、残留两卷取严、字体仅技术卷）。
- `backend/services/delivery_quality.py`：`score_delivery_files` / `score_project_delivery`；出标后挂非阻断钩子，自动按卷打分并落 `backend/eval_results/project_{id}.json`（已 gitignore），打分失败绝不影响出标。
- `backend/api/main.py`：已瘦身为 ~75 行装配层（app 构造 + lifespan + `/health` + `include_router`）；按域拆出 `backend/api/routers/{auth,admin,company,knowledge,project,templates}.py`（各 APIRouter），共享依赖 `authorized_project`/`_raise_http_error` 在 `backend/api/deps.py`，main.py re-export 这些名字保向后兼容。
- `backend/services/project_service.py`：已瘦身为 ~122 行**门面**，真实逻辑拆进 `backend/services/project/` 子包（`errors/crud/parsing/outline/strategy/delivery/_helpers/_runtime` 共 8 模块），门面 re-export 全部公共名与异常类。
- `frontend/components/TenderWorkspace.tsx`：工作台主组件（三栏 Tab、**两卷下载、无报价**）。
- `backend/scripts/benchmark_vs_baseline.py` / `visual_regression.py`：质量/视觉度量。

## 最近变更（本轮 2026-06）

格式复制升级 + 技术卷目录人工确认 + 生成提速，均已合 main：

- **福昕云 PDF→可编辑 Word（核心）**：商务格式章 + 技术附表经福昕国内云转**真·可编辑 Word**（真段落/真表格）+ 自动填字段；Phase0 最上层（`CLOUD_PDF_CONVERT=foxit`）失败下沉 pdf2docx→图；附表 docxcompose 拼技术卷末；新依赖 `docxcompose==2.2.0`（不动钉死的 httpx0.25.2/numpy1.24.3）；凭证 `FOXIT_CLOUD_CLIENT_ID/SECRET` 在 `.env`。**解决"可编辑 vs 一模一样"取舍**——实测招标#122 商务 168 段 19 表 + 附表 6 可编辑表 + 字段已填。
- **技术卷目录人工确认**：放出大纲编辑器（「技术大纲」标签+「添加章节」）；parser 扫招标"编制要点+附表"逐条原样成 `technical_outline`；生成读人工确认的 `bid_outline_json` 驱动目录、无规定时最小中性壳（**不再盲套 25 节硬编码大纲**）；商务卷移出大纲环节。
- **技术卷生成并行化**：25 节 LLM 由串行改 `ThreadPoolExecutor` 有界并发（`BID_WRITER_CONCURRENCY` 默认 5），约 25min→5-6min。
- **P0-2**：PDF 原格式路径补 `_audit_built_format_docx` 内容体检，防空壳/丢页静默发布。
- 格式章页范围修复（跨引用"第X章"误切 + 技术/报价卷边界）；parser `max_tokens` 按输入动态算（修长招标 400）；前端加「新项目」按钮。后端测试 → **333 passed**（`-m "not live_llm"`）。
- ⚠️ 两个 best-effort 静默项，客户启用前真样张各验一次：**附表横表方向**（docxcompose 可能压成竖版）、**合并保真**（已加损坏校验→丢附表保纯技术卷兜底）。**项目经理行自动填故意不做**（实测会填错表/污染标书，人工填）。部署用仓库根 `/.venv`（已装 docxcompose），别用脏的 `backend/venv`。

历史背景：更早几轮把交付从三卷重构为两卷、抽 `core/llm_client`、拆 `main.py`/`project_service`、加 CI+vitest、知识库证件/业绩入库（M12）+ OCR（M16）——均为现状基线，详见 Git。

## 下个接手者优先看

1. **整链真实生成实测（福昕开关已开）**：重启后端 → 真实生成一份 → 在 Pages/新点 验商务卷 + 附表可编辑且与招标一致；尤其 ⚠️ 附表横表方向、docxcompose 合并保真。
2. **M20 新点软件交付实测**——两卷（福昕可编辑 DOCX + 技术正文）在新点能否导入/套打/出目录。
3. **M23 本项目专用技术材料库**——技术卷实质的下一个瓶颈（全局库零技术方案文本），需用户提供真实施工组织设计文本、`project_id` 隔离喂 RAG。
4. 公司内网部署：任务队列（生成耗时长）、备份、审计。

## 验证命令

- 后端测试：`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q -m "not live_llm"`（基线 333 passed）
- 前端类型：`cd frontend && npx tsc --noEmit`
- 前端单测（vitest）：`pnpm --dir frontend test`
- 质量对标：`backend/scripts/benchmark_vs_baseline.py compare --generated <稿> --baseline <中标标书>`
- 视觉回归：`backend/scripts/visual_regression.py <导出DOCX>`
- CI（`.github/workflows/ci.yml`）会自动跑后端 pytest（`-m "not live_llm"`）+ 前端 typecheck/lint/test/build。
- 后端 `--reload` 热重载：纯 `.py` 改动不用重启；装新依赖或改 `.env` 才需重启。
