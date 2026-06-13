# TenderDoc-Generator 任务状态与路线图

本文只记录当前版本、当前路线和下一步任务。开发史请看 Git，不放在产品文档里。

**当前版本：** V2 原格式复制生成内核
**当前重点：** 格式保真、技术正文质量、知识库真实资料、公司内网落地
**硬边界：** 招标文件原格式页是最高权威；系统不输出近似重画格式稿。

## 当前主流程

```mermaid
flowchart LR
    A["上传招标文件"] --> B["Parser 提取要求"]
    B --> C["人工确认解析和大纲"]
    C --> D["选择知识库资料"]
    D --> E["复制招标文件格式页"]
    E --> F["填写已知字段"]
    F --> G["写技术正文"]
    G --> H["格式/内容/证据审查"]
    H --> I["人工终审"]
    I --> J["下载 DOCX/Markdown/审查报告"]
```

## 已完成

| 编号 | 状态 | 内容 | 验收重点 |
|------|------|------|----------|
| M1 | ✅ | DOCX 招标文件格式页 OOXML 原样复制 | 表格、合并单元格、下划线、对齐、签章位保留 |
| M2 | ✅ | PDF 招标文件格式页整页复制 | 200 DPI 页面图像嵌入 DOCX，叠加可编辑文本层 |
| M3 | ✅ | PDF 页块拆卷 | 商务、技术、报价三卷按整页移动，避免页图和文字层拆散 |
| M4 | ✅ | V2 唯一生成入口 | 工作流只调用 `generate_v2_bid_package()` |
| M5 | ✅ | Content Writer 模型路由 | 尊重 `BID_LLM_PROVIDER=deepseek/openrouter/auto` |
| M6 | ✅ | 无占位正文输出 | 技术正文写作失败直接报错，不塞“待人工编写” |
| M7 | ✅ | 三层审查 | V2 格式/内容/证据审查 + workflow 废标风险审查 |
| M8 | ✅ | 前端格式说明收敛 | 不再展示误导性的格式总结文本框 |

## 当前进行中

| 编号 | 状态 | 内容 | 验收标准 |
|------|------|------|----------|
| M9 | 🔧 | 技术正文质量提升 | 施工组织设计有工程针对性、足够篇幅、响应评分项 |
| M10 | 🔧 | 真实中标标书基线 | 用真实中标标书对比页数、表格密度、章节深度、填空率 |
| M11 | 🔧 | 知识库真实资料入库 | 公司证件、人员证件、业绩、技术方案、图片资料完成命名和标签 |
| M12 | 🔧 | 样本项目端到端验收 | 至少 3 个脱敏真实项目跑通上传、生成、审查、下载 |

## 待做

| 编号 | 优先级 | 内容 | 说明 |
|------|--------|------|------|
| M13 | P0 | 真实格式回归集 | 收集多份招标文件及对应格式页，测试目录、函件、表格、签章位是否原样 |
| M14 | P0 | DOCX 视觉回归 | 导出后自动渲染关键页，对比是否出现裁切、重叠、空白页、错卷 |
| M15 | P0 | 知识库 OCR 和 `.doc` 兼容 | 支持公司资料里的扫描件、JPG/PNG、老 Word 文档入库 |
| M16 | P1 | 内网部署包 | Docker Compose 单机版、Nginx、HTTPS、环境变量模板 |
| M17 | P1 | 备份恢复和审计 | PostgreSQL/MinIO 备份、恢复演练、上传下载删除审计日志 |
| M18 | P1 | 长任务队列 | 解析、生成、导出从 BackgroundTasks 迁移到可重试队列 |
| M19 | P1 | 新点软件交付实测 | 用导出的 DOCX 在新点投标文件制作软件中导入并记录损失项 |
| M20 | P2 | 风格案例质量化 | 公司风格案例只影响技术正文深度和语气，不影响格式结构 |

## 格式相关代码责任

- `backend/services/original_docx_format_service.py`：格式页复制。DOCX 复制 OOXML，PDF 复制整页图像和文本层。
- `backend/services/generation_service.py`：导出和拆卷。原格式 DOCX 存在时按源格式拆出三卷，技术卷只追加技术正文。
- `backend/services/v2_generation_service.py`：生成编排。决定何时复制格式、何时调用 Content Writer、何时失败。
- `backend/services/format_skeleton_service.py`：文本格式页提取和页面分类，用于大纲、预览和普通文本路径。
- `backend/utils/docx_exporter.py`：普通 Markdown 到 DOCX 的排版，不负责重画招标锁定格式。
- `backend/agents/parser_agent.py`：提取 `format_outline_tree`，帮助定位目录和技术标题。
- `frontend/components/ParsedReviewPanel.tsx`：前端展示格式生成方式和人工确认信息。

## 审查相关代码责任

- `backend/services/v2_audit_service.py`：V2 内置格式、内容、证据审查。
- `backend/agents/reviewer_agent.py`：废标风险和响应性审查。
- `backend/services/workflow_service.py`：状态流转、失败原因、审查报告、人工确认。
- `backend/services/bid_tone_checker.py`：去除生成器语气和元话语。
- `backend/agents/response_matrix_agent.py`：资质、评分、废标项响应矩阵。
- `backend/agents/scoring_agent.py`：评分预测和短板提示。

## 用户使用过程

1. 启动本地服务，登录工作台。
2. 上传招标文件并等待解析。
3. 检查项目名称、招标人、工期、质量、资质要求、评分项、废标项和格式目录树。
4. 修正解析错误后确认。
5. 在知识库选择本项目要用的公司资料、人员资料、业绩、施工方案和图片证据。
6. 点击生成。
7. 查看实时状态：上传、解析、生成、审查、确认、下载。
8. 若失败，按失败原因修正配置、招标文件或资料后重新生成。
9. 若通过，查看预览和审查报告，在线编辑需要人工填的字段。
10. 终审确认后下载 DOCX/Markdown/审查报告，再进入新点软件做最终电子标处理。
