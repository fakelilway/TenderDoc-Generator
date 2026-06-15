# TenderDoc-Generator 任务状态与路线图

本文只记录当前版本、当前路线和下一步任务。开发史请看 Git，不放在产品文档里。

**当前版本：** V2 原格式复制生成内核（两卷交付）
**当前重点：** 知识库真实资料入库、新点软件交付实测、公司内网落地
**硬边界：** 招标文件原格式页是最高权威；系统不输出近似重画格式稿。

## 当前主流程

```mermaid
flowchart LR
    A["上传招标文件"] --> B["Parser 提取要求+格式目录树"]
    B --> C["人工确认解析"]
    C --> D["选择知识库资料"]
    D --> E["复制招标格式章为商务卷"]
    E --> F["已知字段烧录进表单"]
    D --> G["写技术正文(标准施工组织设计大纲)"]
    F --> H["格式/内容/证据审查 + 废标风险审查"]
    G --> H
    H --> I["人工终审"]
    I --> J["下载 商务卷/技术卷 DOCX + 审查报告"]
```

## 交付与格式铁律（现状）

- **两卷交付：商务卷 + 技术卷。报价卷由外部造价软件单独做，本系统不产出。**
- **商务卷 = 照抄招标格式章 + 字段填空 + 合规正文**。
  - PDF 招标：每页**整页截图**（像素级保真），知识库已知值（投标人/地址/法定代表人/电话）在转图前**烧录进填空横线**；纯内联图，Pages/LibreOffice/Word 都能渲染；未知字段留空给新点/手填。
  - DOCX 招标：**copy-then-prune**（复制源文件、删格式章外元素），保留页眉页脚/图片/表格。
- **技术卷 = LLM 写的施工组织设计正文，独立成文**（正奇排版 + 自动更新目录），不与商务格式页混排。
- 失败语义：格式复制 / 技术正文写作失败 = 硬错误直接报错；审查发现严重问题 = 软阻断（`audit_blocked=True`，保留草稿供人工预览）。

## 已完成

| 编号 | 状态 | 内容 | 验收重点 |
|------|------|------|----------|
| M1 | ✅ | DOCX 招标格式章 copy-then-prune 复制 | 表格/合并单元格/下划线/签章位/**页眉页脚/图片**保留 |
| M2 | ✅ | PDF 招标格式整页截图 + 值烧录进图 | 像素级保真、全软件可渲染、知识库字段已填、未知留空 |
| M4 | ✅ | V2 唯一生成入口 | 工作流只调用 `generate_v2_bid_package()` |
| M5 | ✅ | Content Writer 模型路由 | 尊重 `BID_LLM_PROVIDER=deepseek/openrouter/auto` |
| M6 | ✅ | 无占位正文输出 | 技术正文写作失败直接报错 |
| M7 | ✅ | 三层审查 | V2 格式/内容/证据审查 + reviewer 废标风险审查 |
| M9 | ✅ | 前端 UX | 移除大纲编辑、Tab 化中心列、渐进展示、**两卷下载（去报价）** |
| M10 | ✅ | 技术正文深度大纲 | 招标技术大纲薄时扩展为 25 节标准施工组织设计大纲（对标真实中标标书设计+对抗式审查），逐节注入评分项/废标项/必覆盖要点/字数预算+不达标重写 |
| M11 | ✅ | 真实中标标书基线 | `benchmark_vs_baseline.py` + `docs/quality_scorecard.md`，4 份脱敏中标标书 + 4 份招标文件 |
| M15 | ✅ | 视觉回归 | `backend/scripts/visual_regression.py`（soffice 渲染断言）+ `docs/visual_review_checklist.md` |
| - | ✅ | 两卷重构 | 删除旧三卷拆分整链；`_assemble_two_volumes` 为唯一原格式导出路径 |

## 当前进行中

| 编号 | 状态 | 内容 | 验收标准 |
|------|------|------|----------|
| M13 | 🔧 | 样本项目端到端验收 | 招标#1–#4 格式跑通（#4 DOCX 定位 bug 已修）；技术正文 E2E 篇幅对标待最终确认 |

## 下一步该做什么（按优先级）

**最高优先（决定能不能真正中标 / 真正能用）：**

| 编号 | 优先级 | 内容 | 为什么是下一步 |
|------|--------|------|----------------|
| **M12** | **P0** | **知识库真实资料入库** | 现在技术正文是"无知识库/结构有了但缺真实工程数据"的状态，商务填空也只填了基础字段。把公司证件/业绩/人员证件/施工方案/图片**命名+打标签**入库后，技术正文才有真料、篇幅和针对性才真正到位，商务字段才填得全。**这是篇幅/质量提升的下一个真正瓶颈。** |
| **M20** | **P0** | **新点软件交付实测** | 用导出的**商务卷（烧录图 DOCX）+ 技术卷**在新点投标文件制作软件里导入，记录损失项（图能否进、字段能否套打、目录是否正常）。验证整条链路在真实投标工具里可用。 |
| M16 | P0 | 知识库 OCR 和 `.doc` 兼容 | 公司证件多为扫描件/JPG/老 Word，M12 入库依赖它 |

**其后（生产化/打磨）：**

| 编号 | 优先级 | 内容 | 说明 |
|------|--------|------|------|
| M14 | P1 | 真实格式回归集 | 把 4 份招标文件的格式生成接入自动回归（现为手测） |
| M17 | P1 | 内网部署包 | Docker Compose 单机版、Nginx、HTTPS、环境变量模板 |
| M18 | P1 | 备份恢复和审计 | PostgreSQL/MinIO 备份、恢复演练、上传下载删除审计日志 |
| M19 | P1 | 长任务队列 | 解析/生成/导出从 BackgroundTasks 迁移到可重试队列（生成现需 25 节 LLM、耗时长） |
| - | P2 | benchmark 按卷拆分响应率 | 技术评分项 vs 技术正文、商务/报价废标 vs 商务卷+reviewer，分母分开 |
| - | P2 | PDF 健壮性 | 页旋转检测、超大/超小页缩放、密集表格文本 |
| M21 | P2 | 风格案例质量化 | 公司风格案例只影响技术正文深度和语气，不影响格式结构 |

## 格式相关代码责任

- `backend/services/original_docx_format_service.py`：格式章复制。DOCX 走 copy-then-prune；PDF 走整页截图 + `_bake_fill_values_on_page` 把已知值烧进填空横线（弃用 VML 文本层/pdf2docx）。
- `backend/services/generation_service.py`：两卷装配 `_assemble_two_volumes`（商务=copy2 格式章+合规正文，技术=独立生成正文）和导出。
- `backend/services/v2_generation_service.py`：生成编排 + `_collect_technical_sections`（薄大纲扩展为标准施工组织设计大纲）。
- `backend/prompts/construction_plan_outline.py`：25 节标准施工组织设计深度大纲常量（对标真实中标标书）。
- `backend/prompts/generator_prompt.py`：逐节写作 prompt（评分项/废标项/必覆盖要点/字数预算注入）。
- `backend/agents/content_writer_agent.py`：技术正文逐节生成、不达标重写、模型路由。
- `backend/agents/parser_agent.py`：提取 `format_outline_tree` 和招标要求。
- `backend/utils/docx_exporter.py`：Markdown→DOCX 排版（技术卷），含自动更新目录域。

## 审查相关代码责任

- `backend/services/v2_audit_service.py`：V2 内置格式、内容、证据审查。
- `backend/agents/reviewer_agent.py`：废标风险和响应性审查。
- `backend/services/workflow_service.py`：状态流转、失败原因、审查报告、人工确认、导出调用。
- `backend/agents/scoring_agent.py` / `response_matrix_agent.py`：评分预测、响应矩阵。

## 质量度量工具

- `backend/scripts/benchmark_vs_baseline.py`：页数/字数/表格/章节/填空率/评分点响应率，对标真实中标标书。
- `backend/scripts/visual_regression.py`：soffice 渲染断言（页数/连续空白页/关键 token）。
- `docs/quality_scorecard.md`：满意阈值定义。
- `docs/visual_review_checklist.md`：人工终审目视清单。

## 用户使用过程

1. 启动本地服务，登录工作台。
2. 上传招标文件（PDF/DOCX/TXT）并等待解析。
3. 检查项目名称、招标人、工期、质量、资质、评分项、废标项和格式目录树，修正后确认。
4. 在知识库选择本项目要用的公司资料、人员资料、业绩、施工方案和图片证据。
5. 点击生成（系统复制商务格式章+烧录字段、写技术正文、三层审查）。
6. 查看实时状态；失败按原因修正后重试。
7. 通过后看预览和审查报告，在线编辑人工填字段。
8. 终审确认后下载**商务卷 + 技术卷 DOCX + 审查报告**（用 Word/Pages/新点打开）。
9. **报价卷用造价软件单独做好**，与上面两卷一起进新点软件做最终电子标。
