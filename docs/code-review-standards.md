# TenderDoc-Generator 代码审查标准

本文定义当前项目的审查规则。所有改动都以 V2 原格式复制链路为准。

## 必须重点审查的文件

- `backend/services/original_docx_format_service.py`
- `backend/services/generation_service.py`
- `backend/services/v2_generation_service.py`
- `backend/services/v2_audit_service.py`
- `backend/services/workflow_service.py`
- `backend/agents/parser_agent.py`
- `backend/agents/content_writer_agent.py`
- `backend/agents/reviewer_agent.py`
- `backend/prompts/generator_prompt.py`
- `backend/prompts/parser_prompt.py`
- `frontend/components/TenderWorkspace.tsx`
- `frontend/components/ParsedReviewPanel.tsx`

## 合并前检查

- 后端测试：`.venv/bin/python -m pytest backend/tests -q`
- 前端类型检查：`pnpm --dir frontend typecheck`
- 前端构建：`pnpm --dir frontend build`
- 空白检查：`git diff --check`
- 涉及 DOCX 导出时，至少打开一次导出文件，确认无空白页、错卷、裁切、表格拍扁和下划线丢失。

## 格式链路审查规则

1. 招标文件格式页必须由 `original_docx_format_service.py` 复制，不得由 Prompt 或 Markdown 表格重画商务/报价格式。
2. DOCX 输入必须保留 OOXML 结构，包括表格、边框、合并单元格、对齐、下划线和签章位。
3. PDF 输入必须按整页图像保真，导出拆卷必须按页块移动，不能把页面图片和文本层拆散。
4. `generation_service.py` 在原格式 DOCX 存在时只能做拆卷和技术正文追加，不能重新渲染商务/报价锁定区。
5. 技术卷追加内容必须来自技术 Markdown，不能把完整合并 Markdown 追加进技术卷。
6. `format_outline_tree` 可以辅助定位和标题收集，但不能替代原格式页。
7. `bid_format_requirements` 不得作为生成依据或前端确认关卡。

## 生成链路审查规则

1. `generate_v2_bid_package()` 是当前唯一生成入口。
2. Content Writer 只能写技术正文，不得输出商务/报价函件、表格或签章格式。
3. `BID_LLM_PROVIDER` 必须被 Parser 和 Content Writer 同时尊重。
4. 任何 LLM 调用失败都要抛出可读错误，不得静默吞掉。
5. 系统不得输出占位正文冒充成功结果。
6. 未知金额、证号、人员、日期等字段必须保留空白或进入人工确认。

## 审查链路审查规则

1. `v2_audit_service.py` 必须拦截表格拍扁、下划线丢失、签章位丢失、图片/图表要求未落实。
2. 内容审查必须拦截过短正文、AI 元话语、身份证号、报价金额等高风险内容。
3. 证据审查必须阻止填入值与公司档案不一致。
4. `reviewer_agent.py` 的规则审查不得被可选 LLM 审查覆盖。
5. `workflow_service.py` 必须保存失败原因，让前端实时状态能展示。

## 文档审查规则

1. README、minitasks、setup、TECH_STACK 和 `docs/*.md` 必须描述同一套当前架构。
2. 产品文档不保留已删除生成路线的操作说明。
3. 任何新增环境变量都要同时更新 `setup.md` 和 `TECH_STACK.md`。
4. 任何影响用户流程的前端变化都要更新 README 的用户使用过程。

## 端到端人工验收

每次改动格式或导出相关代码后，至少用一个真实招标文件跑：

1. 上传招标文件。
2. 确认解析结果和格式目录树。
3. 选择资料。
4. 生成。
5. 查看实时状态和审查报告。
6. 下载完整 DOCX 和三卷 DOCX。
7. 对照招标文件格式页检查：目录、投标函、授权委托书、投标保函、资格审查表、下划线、签章位、页块拆卷。
8. 用新点软件做一次导入测试时，记录格式损失项。
