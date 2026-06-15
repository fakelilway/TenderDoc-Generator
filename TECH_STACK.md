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
- BAAI/bge-reranker-base rerank

## Document Processing

- PyMuPDF：PDF 文本提取、页面渲染、格式页整页截图 + 已知字段烧录
- python-docx：DOCX 读取、OOXML 复制、DOCX 导出
- pypdf/pdfplumber：辅助 PDF 文本解析

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
- PDF 招标文件：复制格式页整页图片，已知字段烧录进表单填空横线（不再叠 VML 文本层）。
- 商务锁定格式：不由模型重画。
- 技术正文：由 Content Writer 按标准施工组织设计深度大纲逐节生成，独立成文。
- 审查：V2 格式/内容/证据审查 + workflow 废标风险审查。

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
