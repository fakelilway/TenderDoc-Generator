# AI Handoff — WorkBuddy (DeepSeek V4-Pro) ↔ Codex (GPT-5.5)

> 不要在这里写代码或详细技术方案。只写"我做了什么、当前状态、下一步建议、需要对方确认的事"。
> 每次 push 后更新状态部分。另一个 AI 打开项目时先读这个文件。

---

## 当前状态 (2026-06-13 20:21)

**WorkBuddy 最后一次 push:** `9f0e906` — split writer/auditor prompts, unify issues field, fast-fail on empty revise

**测试:** 236 passed, 2 skipped

**Codex 最新进展:** M1 Skeleton Renderer + M2 原文模板抽取已本地落地，尚未 push。

**当前未提交改动:**
- `backend/services/format_skeleton_service.py`：新增确定性格式骨架层；M2 已接入招标文件格式章节原文抽取，能把函件/表格原文模板嵌入骨架。
- `backend/agents/generator_agent.py`：生成前强制要求三卷 `format_outline_tree` 完整；生成/修订/打回复用同一份骨架；LLM 结构审计前加确定性标题预审。
- `backend/prompts/generator_prompt.py`：writer/revision prompt 改为在“本卷确定性骨架”内填内容，标题、顺序、层级必须逐字保留；若骨架已有原文模板，必须优先保留原文模板。
- `backend/tests/test_format_skeleton_service.py`、`backend/tests/test_generator_agent.py`、`backend/tests/test_agent_persona_prompts.py`：覆盖骨架渲染、缺格式树硬失败、骨架传入生成/修订链路、重复投标函按卷抽取、目录行不抢模板、泛标题只做边界不抽模板。
- `backend/agents/parser_agent.py`：另有 9 行未提交改动，把 LLM 返回的字符串 `source` 归一化成 `{source_text, page_number}`；这不是 Skeleton 改动，但当前在工作区里。

---

## 今天做了什么

### WorkBuddy (我) 做的
- Parser: max_tokens→100K, format_outline_tree (第13字段), 全文传入LLM, 规则格式提取接入
- Generator: 全线prompt重写（去人格化、去重复、节点树前置、冲突裁决）
- 双段审计: Pass 1结构→Pass 2内容
- 死代码清理: 删 ~1300行 legacy (long_context/simple/section模式)
- Bug修复: _VOLUME_LABELS, 函数签名, 根容器误删, 空响应重试, structural_issues兼容
- 清洗了 ~1300行死代码
- 修复了多个prompt和数据流bug

### Codex 做的
- codex 审查指出的关键 Bug:
  1. 审计 prompt 自相矛盾 (System prompt 说"只输出 Markdown"，但审计要求 JSON) ✅ 已修
  2. structural_issues 被吃 (Prompt 输出 structural_issues，但解析器只读 issues) ✅ 已修
  3. 死代码残留 ✅ 已删
  4. 生成太裸 → 加了短人格 ✅
- codex 提出了完整的 Skeleton Renderer 方案 (代码铺骨架，LLM 填内容)
- codex 已落地 M1 Skeleton MVP:
  1. 从 `format_outline_tree` 渲染三卷 Markdown 骨架，跳过“投标文件（商务文件）”这类根容器，只保留真实表单/章节节点。
  2. Generator 在没有完整三卷格式树时直接失败，不再走默认模板或 fallback。
  3. 分卷初稿、修订、审计打回都传入同一份 `volume_skeleton`。
  4. 增加确定性标题预审：缺少招标文件格式树中的标题时先打回对应分卷，标题齐全后再进入 LLM 结构审计。
  5. 已验证 `232 passed, 2 skipped`，`pnpm --dir frontend typecheck` 通过，`git diff --check` 通过。
- codex 已落地 M2 原文模板抽取:
  1. `render_all_volume_skeletons(..., tender_text=...)` 会从“投标文件格式/投标文件组成”附近抽取每个叶子节点的原文块。
  2. 双信封重复标题按三卷顺序推进游标，商务投标函和报价投标函不会抽成同一个。
  3. 目录行过滤：如果命中的标题下一行还是编号标题，视为目录，不当正文模板。
  4. 泛标题（其他内容/其他材料/其他资料）只作为边界，不抽取模板，避免吸入 unrelated 内容。
  5. 真实 PDF smoke test：能跳过报价卷目录，抽到实际报价投标函和已标价工程量清单说明。
  6. 已验证 `236 passed, 2 skipped`，`pnpm --dir frontend typecheck` 通过，`git diff --check` 通过。

---

## 已对齐的原则

1. 不要 fallback——生成失败就报错，不造假
2. 格式是最高权威——招标文件格式章节 = 标书的框架
3. 不要为了过而过——查根因再改
4. 删代码前 grep 引用
5. LLM 不应该管结构——结构交给代码

---

## Codex 的下一步建议

### M1 Skeleton MVP — 已本地完成，待端到端验证

**目标:** 把 Generator 从"LLM 生成整卷(结构+内容)"改成"代码铺骨架 → LLM 只填槽位"

**已遵守的不改范围:**
- Parser / Knowledge Base / Workflow Service / Frontend / DOCX Export — 全不变
- `generate_bid_package()` 入口不变

**已加的:**
- `render_all_volume_skeletons()` / `render_volume_skeleton()` / `expected_volume_titles()`
- Content Fill Agent 的 prompt 从"按这些节点生成整卷"改成"在这个已有骨架的节点下填内容"

**期望效果:**
- LLM 不再自己决定标题结构；缺节点会被确定性预审打回。
- 结构审计仍保留 LLM Pass 1，用于层级、归属卷、多余节点等更复杂判断。

### M2 原文模板抽取 — 已本地完成，待端到端验证

**已加的:**
- `extract_format_template_blocks()`：按三卷格式树顺序，从 tender_text 的格式章节抽取叶子节点原文块。
- 骨架渲染优先嵌入招标文件原文模板；抽不到才使用通用空白占位。
- Prompt 明确要求优先保留骨架里的原文模板，不改函件正文和表头。

**注意:** M2 目前处理的是 Markdown 骨架里的原文模板，不是 DOCX 字体字号/页边距/表格线的最终版式复制。版式级复刻要放到后续 DOCX exporter/模板映射阶段做。

### 下一步建议 (M3)

- 用用户前端“重新生成”跑一个真实项目，重点看三件事：
  1. 商务/技术/报价目录是否严格来自招标文件格式树。
  2. 是否还会出现投标函重复、漏节点、报价卷层级错位。
  3. 函件和表格是否优先来自招标文件格式章节原文，而不是通用表格。
  4. 失败时实时状态是否能明确指出缺哪个分卷、哪个节点。
- 如果 M2 结构和原文模板稳定，再做 M3：节点级填槽，而不是让 LLM 输出整卷 Markdown；这样可以更彻底防止它改标题/改表头。

---

## 开发环境

```
后端: localhost:8001 (venv/ Python 3.11, uvicorn --reload)
前端: localhost:3000 (Next.js)
数据库: Docker (PostgreSQL + Redis + MinIO)
测试: ./venv/bin/python3 -m pytest tests/ -q
```

## 测试失败时的工作方式
用户会从前端点"重新生成"，失败后告诉你 `实时状态` 里显示的错误信息。然后我们分析根因，对比招标文件格式要求。

## 用户发现的真实 Case
- 长丰县罗塘乡: 商务文件10个表单、技术文件1个章节、报价文件2个表单
- 萧县2025公路: 双信封制 — 第一信封(商务+技术合并) + 第二信封(报价)。投标函在两个信封各出现一次（合法，不叫越卷重复）
