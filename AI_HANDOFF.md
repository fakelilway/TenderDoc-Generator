# AI Handoff

每次较大改动后更新本文件。另一个 AI 接手时先读这里，再读 README、minitasks 和 `docs/generation_contract.md`。

## 当前状态

日期：2026-06-14
当前生成内核：V2 原格式复制
当前目标：让导出 DOCX 的商务/报价/格式表单尽量等同于招标文件原格式页，技术正文再单独提升质量。

## 当前架构铁律

1. 招标文件原格式页是最高权威。
2. DOCX 招标文件走 OOXML deepcopy。
3. PDF 招标文件走整页图片复制、可编辑文本层和隐藏页标记。
4. 拆卷必须按整页或 OOXML 块移动，不能把页图、文本层、表格或签章位拆散。
5. Content Writer 只写技术正文。
6. 失败就失败，不能输出占位正文或近似格式稿。
7. 公司风格案例和知识库不控制格式结构，只提供事实证据、技术素材和风格参考。

## 当前关键文件

- `backend/services/original_docx_format_service.py`：DOCX/PDF 原格式复制。
- `backend/services/generation_service.py`：导出、拆卷、技术正文追加。
- `backend/services/v2_generation_service.py`：V2 生成编排。
- `backend/services/v2_audit_service.py`：格式、内容、证据审查。
- `backend/agents/content_writer_agent.py`：技术正文写作和模型路由。
- `backend/agents/parser_agent.py`：结构化解析和格式目录树。
- `backend/agents/reviewer_agent.py`：废标风险审查。
- `frontend/components/ParsedReviewPanel.tsx`：解析确认和格式方式展示。

## 最近修复点

- Content Writer 尊重 `BID_LLM_PROVIDER`，显式选择 DeepSeek 或 OpenRouter。
- 原格式模式下技术正文写作失败会直接报错，不再生成占位句。
- PDF 原格式 DOCX 每页写入隐藏页标记，拆卷按页块移动。
- 原格式拆卷追加技术正文时，只追加技术卷 Markdown，不再追加完整合并稿。
- 文档已收敛到当前 V2 架构。

## 下个接手者优先看

1. 真实招标文件导出 DOCX 和原 PDF/DOCX 的格式差异。
2. 技术正文质量：篇幅、项目针对性、评分点响应。
3. 知识库真实资料：命名、标签、证据选择、图片插入。
4. 公司内网部署：任务队列、备份、审计、新点软件导入实测。
