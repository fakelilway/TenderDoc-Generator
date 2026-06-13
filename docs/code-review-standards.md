# TenderDoc-Generator 代码审查标准

> 本文档定义这个项目的审查规则。适用于所有 PR 和改动。

---

## 一、审查触发

以下情况必须审查，不得直接合并：

1. 修改 `workflow_service.py`、`v2_generation_service.py`、`generation_service.py` 任一文件
2. 新增或修改 `prompts/` 目录下的 prompt 文件
3. 修改 `schemas/` 影响数据库序列化
4. 新增 pip 依赖
5. 修改前端 `TenderWorkspace.tsx`

## 二、审查检查清单

### 🔴 P0 — 合并前必须通过

- [ ] **测试全绿**：`pytest tests/ -q` 256+ passed, 无 regression
- [ ] **虚拟环境一致**：新依赖同时加入 `backend/venv/` 和 `.venv/`（`scripts/dev_local.sh` 用 `.venv/`）
- [ ] **无静默异常吞没**：`try/except` 必须至少 `logger.error(..., exc_info=True)` 或显式抛出
- [ ] **导出路径双覆盖**：`export_markdown_for_project` 的两个调用点参数一致

### 🟡 P1 — 建议修

- [ ] **无重复导入**：同一模块不在三个不同函数里分别 `from X import Y`
- [ ] **输出文件可验证**：每次生成完立即用 `docx.Document()` 读回检查段落数/表格数
- [ ] **无死代码**：找不到调用者的函数直接删，不保留"可能以后用"
- [ ] **LLM 调用可追踪**：每次 LLM 调用打印节点标题和输出长度

### 💭 P2 — 可优化

- [ ] 函数不超过 40 行
- [ ] 条件分支不超过 3 层嵌套
- [ ] 无 `as _mc` / `as _sys` 等无意义别名

---

## 三、特定文件审查规则

### `workflow_service.py`

```
规则 1: 导出只在一个地方发生 → confirm_project
规则 2: 格式 DOCX 构建只在 generation 阶段 → generate_v2_bid_package
规则 3: 不得在 run_bid_workflow 里写 MinIO 操作
```

### `v2_generation_service.py`

```
规则 1: original_format_docx_available=True 时跳过文本管线
规则 2: format_docx_path 必须设到 V2BidPackage 并持久化到 state
规则 3: Content Writer 节点数 ≥ 7
```

### `generation_service.py`

```
规则 1: original_format_path 存在时直接 copy，不重画 Markdown
规则 2: 上传三卷 DOCX → commercial.docx / technical.docx / pricing.docx
```

### Prompt 文件 (`prompts/generator_prompt.py`)

```
规则 1: 每节 ≥ 8 段
规则 2: 必须包含具体工程参数、操作步骤、应急预案
规则 3: 禁止"根据实际情况""视情况而定"等模糊表述
```

---

## 四、审查流程

```
1. 作者自审（按检查清单跑一遍）
2. AI 审查（跑 tests + 读 diff + 输出检查报告）
3. 人工确认（看 AI 报告，逐条确认）
4. 合并 → 重启后端 → 端到端测试
```

## 五、端到端测试标准

每次修改后，用长丰县项目跑一次完整流程：

```
1. 上传 PDF → 解析 → 选资料 → 生成 → 审查 → 确认 → 下载
2. 下载的三个 DOCX 检查：
   - commercial.docx: 段落 > 100, 表格 > 10
   - technical.docx: 段落 > 150, 表格 > 10, 施工方案 > 1000 字
   - pricing.docx: 段落 > 50, 表格 > 5
3. 无页码乱入、无 AI 元文本、无空白占位符
```
