# TenderDoc-Generator Tech Stack

## Frontend

- Next.js 14 App Router
- React 18
- TypeScript
- Tailwind CSS
- pnpm
- 原生 `fetch` 封装：`frontend/lib/api.ts`
- vitest 测试（已覆盖 `lib/api.ts`）

## Backend

- FastAPI
- Uvicorn
- Python 3.11
- Pydantic v2
- psycopg2 显式 SQL 和连接池
- JWT 登录态
- threading.Thread(daemon) 执行本地长生成任务
- ThreadPoolExecutor 有界并发：技术卷 25 节 LLM 由逐节串行改为有界并发生成（`BID_WRITER_CONCURRENCY` 默认 5），整卷约 25min→约 5-6min
- httpx：调用福昕国内云 PDF→可编辑 Word 转换 API
- `backend/core/llm_client.py`：统一 LLM 客户端（provider 解析 + has_real_key + chat_completion，对 LLM 调用做瞬态错误重试 + 指数退避，stdlib 实现）
- 标书质量自动按卷打分：`docx_health_check.py`（0-100 质量分）+ `delivery_quality.py`（出标自动按卷打分 → eval_results）
- GitHub Actions CI：后端 `pytest -m "not live_llm"` + 前端 typecheck/lint/test/build

## Storage

- PostgreSQL 15+
- pgvector
- Redis 7
- MinIO

## AI And Retrieval

- OpenAI SDK 兼容 DeepSeek/OpenRouter
- `BID_LLM_PROVIDER=deepseek|openrouter|auto`
- Parser Agent：结构化招标要求和格式目录树
- Content Writer：技术正文生成
- Reviewer Agent：废标风险审查
- BAAI/bge-large-zh-v1.5 embedding
- BAAI/bge-reranker-base rerank——**已接入生产检索**（`rag/retriever.rerank_results`：优先语义重排，模型不可用自动回退关键词重排，检索绝不因此报错）
- 已删除从未使用的 langchain 三包（langchain/langchain-community/langchain-openai，源码零引用）

## Document Processing

- **福昕国内云（httpx，无 SDK）**：PDF 招标 → 真·可编辑 Word（真段落/真表格），格式章复制的**唯一** PDF 路径
- python-docx：DOCX 读取、OOXML 复制、DOCX 导出
- PyMuPDF：PDF 文本提取、页面渲染（附表页定位、渲染验空白页）
- docxcompose：把福昕可编辑附表拼接到技术卷末尾（保留真表格/图片关系）
- openpyxl：读工程量清单 Excel（`.xlsx`/`.xlsm`）；`.xls` 走 LibreOffice
- ~~pdf2docx~~：**已移除**（原"福昕不可用的离线回退"整条删除，PDF 现只有一条路）
- pypdf/pdfplumber：辅助 PDF 文本解析
- `services/docx_format_doctor.py`：**格式医生**——healer 注册制的全文档格式体检，**只改格式、绝不改文字**。5 个注册表：福昕路填前 `_PREFILL_HEALERS`（孤字归位/浮框拆回正文流）、福昕路填后 `_HEALERS`（下划线断线/字距挤压/假两栏/幽灵图/劈句合并/落款栏位等 16+）、Word 路填前 `_NATIVE_PREFILL_HEALERS`（只含防叠印）、Word 路填后 `_NATIVE_DOCX_HEALERS`、成品级 `run_format_doctor_assembled`（核对表列宽/业绩图注绑定）
- `services/pagination_doctor.py`：排版医生，治"尾巴页"（一节溢出几行到下一页）
- `services/blank_page_doctor.py`：空白页硬闸（渲染逐页查→拆多余翻页→复查至零）
- `services/appendix_service.py`：技术卷附表逐张装配——公司定稿表原样拼（补"附表X"编号）→ 招标原表福昕转 → 占位页
- `services/commercial_fixed_fields.py`：公司名错别字纠正 + 商务固定字段一致性核对
- RapidOCR（rapidocr-onnxruntime）：证件扫描件 OCR；`services/id_card_ocr.py` 身份证正反面判定；`utils/image_orient.py` EXIF 摆正

## Current Generation Kernel

```mermaid
flowchart TD
    A["Tender PDF/DOCX/TXT"] --> B["Parser Agent"]
    B --> C["Confirmed Requirements"]
    C --> D["Original Format Copy"]
    D --> E["Form Field Replacement"]
    C --> F["Content Writer"]
    E --> G["V2 Audit"]
    F --> G
    G --> H["Reviewer Agent"]
    H --> I["DOCX / Markdown / Review Report"]
```

当前只有 V2 原格式复制生成内核（两卷交付：商务卷 + 技术卷；报价卷外部造价软件）：

- DOCX 招标文件：copy-then-prune 复制格式章（保留页眉脚/图片）。
- PDF 招标文件：**福昕国内云转可编辑 Word**（真段落/真表格，`CLOUD_PDF_CONVERT=foxit`）——**唯一路径，无降级**；开关非 foxit 或转换失败 = 硬报错，不出近似稿。纯文字版招标最佳，扫描版需先 OCR。
- 商务锁定格式：不由模型重画。
- 商务卷填值管线（唯一入口 `original_docx_format_service.fill_format_docx`，20+ 步、顺序固定）：剥卷首章标题 → 填前体检（福昕路全量 / Word 路仅防叠印）→ 剥红章 → 类似项目/公司组件 → 占位符（正文+浮框）→ 各类表格/内联空/授权书/日期/人员/业绩/简历/身份证 → 填后格式医生 → 清招标页码 → 缺字段告警 → 固定字段收尾。证件/业绩图锚点落位到对应表后，没命中退卷尾绝不丢图。
- 技术正文：按**人工确认目录**由 Content Writer 逐节生成（有界并发），独立成文；技术附表由 `appendix_service` 逐张装配（公司定稿表补"附表X"编号 / 招标原表福昕转 / 占位），docxcompose 拼到技术卷末。
- 出卷后收尾：加页码 → 排版医生（尾巴页）→ 成品级格式修复 → **空白页闸（最后）**。
- 审查：V2 格式/内容/证据审查 + 招标覆盖闸 + workflow 废标风险审查。

## Environment Variables

LLM：

```env
BID_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
PARSER_LLM_TIMEOUT_SECONDS=180
BID_LONG_CONTEXT_TIMEOUT_SECONDS=300
BID_LONG_CONTEXT_MAX_TOKENS=12000
```

云转换（福昕国内云 PDF→可编辑 Word，转的是公开招标格式章）：

```env
CLOUD_PDF_CONVERT=foxit          # PDF 招标唯一有效值；非 foxit 时上传 PDF 招标直接报错（无降级档）
FOXIT_CLOUD_CLIENT_ID=your-client-id
FOXIT_CLOUD_SECRET=your-secret   # 注意是 SECRET，不是 CLIENT_SECRET
```

Storage：

```env
DATABASE_URL=postgresql://tenderuser:tenderpwd@localhost:5432/tenderdb
REDIS_URL=redis://localhost:6379/0
MINIO_API_URL=http://localhost:9000
MINIO_CONSOLE_URL=http://localhost:9001
MINIO_BUCKET=tender-files
```

## Verification

```bash
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q -m "not live_llm"   # 基线 594 passed
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
git diff --check
```
