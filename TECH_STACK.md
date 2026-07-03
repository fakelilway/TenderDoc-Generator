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

- PyMuPDF：PDF 文本提取、页面渲染、格式页整页截图 + 已知字段烧录
- python-docx：DOCX 读取、OOXML 复制、DOCX 导出
- docxcompose：把福昕可编辑附表拼接到技术卷末尾（保留真表格/图片关系）
- pdf2docx：PDF→可编辑 Word 的离线回退（福昕云不可用时）
- pypdf/pdfplumber：辅助 PDF 文本解析
- `services/docx_format_doctor.py`：**格式医生**——福昕转换+填空前后的全文档格式体检（healer 注册制）。填前：孤字归位（"性…"+"别："拼回"性别："，字符守恒）；填后：填空槽下划线断线补齐（白名单+夹心兜底）。铁律：只改格式、绝不改文字
- `services/appendix_service.py`：技术卷附表逐张装配——公司定稿表原样拼（补"附表X"编号）→ 招标原表福昕转 → 占位页
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
- PDF 招标文件：**优先福昕国内云转可编辑 Word**（真段落/真表格，开关 `CLOUD_PDF_CONVERT=foxit`）+ 自动填公司档案字段；失败下沉 pdf2docx → 整页截图+域 → 纯整页图 → 硬报错。纯文字版招标最佳，扫描版需先 OCR。
- 商务锁定格式：不由模型重画。
- 商务卷填空管线（`cloud_pdf_convert`，顺序固定）：福昕转换 → 标签理顺+孤字归位（填前体检）→ 按标签自动填（公司档案/选派人员台账/选中业绩；只填空格绝不覆盖已有内容）→ 格式医生（填后体检，治下划线断线）→ 清红章/招标页码 → 固定字段一致性收尾；证件/业绩图锚点落位到对应表后，没命中退卷尾绝不丢图。
- 技术正文：按**人工确认目录**由 Content Writer 逐节生成（有界并发），独立成文；技术附表由 `appendix_service` 逐张装配（公司定稿表补"附表X"编号 / 招标原表福昕转 / 占位），docxcompose 拼到技术卷末。
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
CLOUD_PDF_CONVERT=foxit          # off=用 pdf2docx/截图链;foxit=优先福昕云
FOXIT_CLOUD_CLIENT_ID=your-client-id
FOXIT_CLOUD_SECRET=your-secret
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
.venv/bin/python -m pytest backend/tests -q -m "not live_llm"
pnpm --dir frontend typecheck
pnpm --dir frontend test
pnpm --dir frontend build
git diff --check
```
