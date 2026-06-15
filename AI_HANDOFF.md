# AI Handoff

每次较大改动后更新本文件。另一个 AI 接手时先读这里，再读 README、minitasks 和 `docs/generation_contract.md`。

## 当前状态

日期：2026-06-15
当前生成内核：V2 原格式复制（两卷交付）
当前目标：知识库真实资料入库、新点软件交付实测、公司内网落地。格式保真和技术正文深度大纲已落地。

## 当前架构铁律

1. **招标文件原格式页是最高权威。** 不重画商务格式，不输出近似稿。
2. **交付两卷：商务卷 + 技术卷。报价卷由外部造价软件单独做，本系统不产出、不拆分。**
3. **商务卷 = 照抄招标格式章 + 字段填空 + 合规正文：**
   - PDF 招标：每页**整页截图**（像素级保真）。已知字段在转图前用 CJK 字体**烧录进填空横线**（`_bake_fill_values_on_page`），纯内联图，Pages/LibreOffice/Word/新点都能渲染。未知字段留空给人工/新点。**不再用 VML 文本框叠层，也不用 pdf2docx**（多软件渲染会丢图/错位）。
   - DOCX 招标：**copy-then-prune**（复制源文件后删格式章范围外元素），保留页眉页脚、图片、表格等关联部件。格式章定位跳过目录(TOC)、取最后一个非 TOC 的格式章标题。
4. **技术卷 = LLM 写的施工组织设计正文，独立成文**（`markdown_to_docx` 正奇排版 + 自动更新目录域），绝不追加到商务格式页上。
5. **技术卷可自由组织深度结构**：招标技术大纲薄（<4 个具体子节）时扩展为 `construction_plan_outline.py` 的 25 节标准施工组织设计大纲，逐节生成。技术卷自由编制不违反铁律 1（铁律 1 只管商务/报价格式）。
6. **失败语义**：格式复制失败、技术正文写作失败 = 硬错误，直接 `raise ValueError`，不回退不占位。审查发现严重问题（audit critical）则软阻断：不抛错，置 `audit_blocked=True` 并保留已生成内容供人工预览。
7. 公司风格案例和知识库不控制格式结构，只提供事实证据、技术素材和风格参考。

## 当前关键文件

- `backend/services/original_docx_format_service.py`：格式章复制。`build_original_format_docx`（DOCX copy-then-prune）、`build_original_format_docx_from_pdf_with_fields`（PDF 整页截图+值烧录）、`_bake_fill_values_on_page` / `_find_cjk_font` / `_find_format_start`（跳 TOC 取末次）。
- `backend/services/generation_service.py`：两卷装配 `_assemble_two_volumes` + 导出 `export_markdown_for_project`（拆卷前不剥 tdg:volume 标记；`_append_prose_to_docx` 还原各节几何、图段落钉 SINGLE 行距）。
- `backend/services/v2_generation_service.py`：V2 编排 + `_collect_technical_sections`（薄大纲→标准大纲）+ `_distribute_requirement_items`（评分/废标按节分配）。
- `backend/prompts/construction_plan_outline.py`：25 节标准施工组织设计深度大纲。
- `backend/prompts/generator_prompt.py` / `backend/agents/content_writer_agent.py`：逐节写作（评分/废标/必覆盖要点/字数预算注入 + 不达标重写）。
- `backend/services/v2_audit_service.py`：格式、内容、证据审查。
- `backend/agents/parser_agent.py`：解析 + `format_outline_tree`。
- `frontend/components/TenderWorkspace.tsx`：工作台主组件（三栏 Tab、**两卷下载、无报价**）。
- `backend/scripts/benchmark_vs_baseline.py` / `visual_regression.py`：质量/视觉度量。

## 最近修复点（本轮）

- 交付从三卷重构为**两卷**（商务+技术，报价外部）；删除旧三卷拆分整链。
- PDF 商务格式：VML 文本层 → pdf2docx → 最终**整页截图 + 值烧录进图**（解决多软件渲染丢图/错位）。
- 修复三连"商务卷空白"bug：拆卷前误删卷标记（商务内容串进技术卷）→ deepcopy 丢图片关系 → `_configure_styles` 固定行距把整页图裁成空白。
- DOCX 格式定位误命中目录（招标#4）→ 跳 TOC 取末次匹配。
- DOCX 格式复制改 copy-then-prune，保留页眉页脚/图片。
- 技术正文：薄大纲扩展为 25 节标准施工组织设计深度大纲（多智能体设计+对抗式审查，对标 4 份真实中标标书）。
- 前端：去掉报价卷下载和报价策略面板。

## 下个接手者优先看

1. **M12 知识库真实资料入库**（公司证件/业绩/人员/方案/图片命名+标签）——技术正文有真料、商务字段填全的下一个瓶颈。
2. **M20 新点软件交付实测**——两卷（烧录图 DOCX + 技术正文）在新点能否导入/套打/出目录。
3. M16 知识库 OCR / `.doc` 兼容（M12 依赖）。
4. 公司内网部署：任务队列（生成现需 25 节 LLM 耗时长）、备份、审计。

## 验证命令

- 后端测试：`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q`
- 前端类型：`cd frontend && npx tsc --noEmit`
- 质量对标：`backend/scripts/benchmark_vs_baseline.py compare --generated <稿> --baseline <中标标书>`
- 视觉回归：`backend/scripts/visual_regression.py <导出DOCX>`
- 后端 `--reload` 热重载：纯 `.py` 改动不用重启；装新依赖或改 `.env` 才需重启。
