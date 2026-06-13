# TenderDoc-Generator 本地启动与验证指南

本文说明如何在本地运行当前 MVP。当前版本仍是 localhost 开发部署，但已经包含前端、后端、数据库、对象存储、知识库、公司档案、生成工作流和 DOCX 导出。

## 1. 前置要求

| 组件 | 推荐版本 | 检查命令 |
|------|----------|----------|
| Docker Desktop / Docker Engine | 24+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python | 3.10+ | `python3 --version` |
| Node.js | 20+ | `node --version` |
| pnpm | 10.32.0 | `pnpm --version` |
| Git | 2.30+ | `git --version` |

如果没有 pnpm：

```bash
corepack enable
corepack prepare pnpm@10.32.0 --activate
```

## 2. 首次安装

```bash
./scripts/setup_local.sh
```

脚本会创建或复用根目录 `.venv`、安装后端依赖、安装前端依赖、启动 PostgreSQL/Redis/MinIO，并应用 `backend/init_db.sql`。

如果虚拟环境里的 `pip` 损坏或缺失：

```bash
RESET_VENV=1 ./scripts/setup_venv.sh
./scripts/setup_local.sh
```

## 3. 环境变量

编辑 `backend/.env`。推荐直连 DeepSeek 时：

```env
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
BID_LLM_PROVIDER=deepseek
PARSER_LLM_TIMEOUT_SECONDS=180
BID_LONG_CONTEXT_TIMEOUT_SECONDS=300
BID_LONG_CONTEXT_MAX_TOKENS=100000
```

使用 OpenRouter 时：

```env
OPENROUTER_API_KEY=sk-or-your-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=deepseek/deepseek-v4-pro
BID_LLM_PROVIDER=openrouter
PARSER_LLM_TIMEOUT_SECONDS=180
BID_LONG_CONTEXT_TIMEOUT_SECONDS=300
BID_LONG_CONTEXT_MAX_TOKENS=100000
```

`BID_LLM_PROVIDER=auto` 会优先使用 OpenRouter key，没有 OpenRouter key 时使用 DeepSeek key。为了避免看错计费后台，测试某个供应商时请显式设置 `deepseek` 或 `openrouter`。

基础服务默认值：

```env
DATABASE_URL=postgresql://tenderuser:tenderpwd@localhost:5432/tenderdb
REDIS_URL=redis://localhost:6379/0
MINIO_API_URL=http://localhost:9000
MINIO_CONSOLE_URL=http://localhost:9001
MINIO_BUCKET=tender-files
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DIMENSION=1024
JWT_SECRET=change-me
```

首次运行 embedding 如果下载慢，可临时设置：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

## 4. 日常启动

```bash
./scripts/dev_local.sh
```

启动成功后访问：

- 前端工作台：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs
- 后端健康检查：http://localhost:8000/health
- MinIO Console：http://localhost:9001

默认管理员账号：

```text
admin / tenderdoc
```

如果端口被占用：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=3010 ./scripts/dev_local.sh
```

## 5. 拆分启动命令

```bash
./scripts/init_db.sh
./scripts/start_backend.sh
./scripts/start_frontend.sh
./scripts/setup_venv.sh
./scripts/setup_frontend.sh
```

## 6. 验证命令

后端：

```bash
.venv/bin/python -m pytest backend/tests -q
```

前端：

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

不要并行跑 `typecheck` 和 `build`，Next.js build 会重建 `.next/types`。

基础服务：

```bash
.venv/bin/python backend/test_db.py
.venv/bin/python backend/test_redis.py
.venv/bin/python backend/test_minio.py
curl -fsS http://localhost:8000/health
curl -fsSI http://localhost:3000
```

LLM 和 embedding：

```bash
.venv/bin/python backend/test_llm.py
.venv/bin/python backend/test_embedding.py
```

## 7. 本地端到端流程

1. 运行 `./scripts/dev_local.sh`。
2. 打开 http://localhost:3000。
3. 用管理员账号登录。
4. 可选进入公司档案，补齐投标人名称、统一社会信用代码、资质、账户、项目班子等信息。
5. 进入知识库，上传少量公司证件、人员证件、业绩、技术方案和图片资料，并填写标签。
6. 创建项目并上传招标文件 PDF/DOCX/TXT。
7. 查看并确认解析结果，重点核对项目名、招标人、工期、质量、资质、评分项、废标项和格式目录树。
8. 调整技术大纲和资料选择。
9. 点击生成。后端会复制招标文件格式页，填已知字段，写技术正文并审查。
10. 查看实时状态和失败原因。失败时修正配置、资料或解析结果后重试。
11. 查看预览、审查报告、响应矩阵、评分预测和报价策略。
12. 在线编辑正文，保存后重新审查。
13. 终审确认后下载 DOCX、Markdown 或审查报告。

## 8. 知识库格式与预览

上传和预览支持：

- 文本索引：PDF、DOCX、TXT。
- 图片资料：JPG、JPEG、PNG。
- 预览：文本显示提取内容，图片显示原图，PDF 和其他文件作为附件查看。

上传时建议填写：

- `project_type`：市政工程、公路工程、交通安全设施养护等。
- `document_category`：人员证件、公司证件、业绩、施工方案、表格附件、图片资料。
- `volume`：商务文件、技术文件、报价文件、资格文件、完整投标文件。
- `specialty`：道路、排水、桥梁、交安、养护、管网等。
- `owner_type` / `owner_name`：公司、人员、项目、设备等归属。
- `certificate_type`：建造师证、身份证、毕业证、建安证、交安证、职称证书、社保、营业执照、资质证书、安全生产许可证、开户许可证。
- `valid_from` / `valid_to`：证件有效期。
- `sensitivity`：公开、内部、敏感、严格受限。
- `usage_scope`：可用于投标、仅参考、仅归档。
- `verified_status`：已核验、待核验、已过期、需更新。
- `image_insertable`：图片是否允许进入标书候选。

批量整理：

```bash
.venv/bin/python backend/scripts/prepare_knowledge_manifest.py \
  "/path/to/原始知识库资料" \
  --out "/path/to/knowledge_import_manifest.csv" \
  --json-out "/path/to/knowledge_import_manifest.json" \
  --copy-to "/path/to/04_知识库_整理后"
```

确认 manifest 后导入：

```bash
.venv/bin/python backend/scripts/prepare_knowledge_manifest.py \
  --manifest "/path/to/knowledge_import_manifest.csv" \
  --out "/path/to/knowledge_import_manifest.csv" \
  --import-to-kb \
  --import-report "/path/to/knowledge_import_report.csv"
```

脚本不会改动原始资料目录，`--copy-to` 只生成整理后的副本。

## 9. 风格案例与评估脚本

导入公司风格案例样本：

```bash
.venv/bin/python backend/scripts/seed_default_template.py
```

从真实投标 PDF 抽取脱敏案例 JSON：

```bash
.venv/bin/python backend/scripts/extract_bid_template.py "/path/to/投标文件.pdf" \
  --out backend/templates/bid_templates/my_template.json \
  --name "某类项目风格案例"
```

分析真实 PDF 格式特征：

```bash
.venv/bin/python scripts/analyze_pdf_format.py /path/to/投标文件.pdf \
  --out-json data/pdf_format_analysis.json
```

质量评估：

```bash
.venv/bin/python backend/scripts/run_quality_eval.py
.venv/bin/python backend/scripts/run_bid_gap_eval.py \
  --ai /path/to/generated.docx \
  --reference backend/templates/bid_templates/road_first_envelope_template.json
```

## 10. 常见问题

### 后端或前端端口被占用

```bash
lsof -i :8000
lsof -i :3000
BACKEND_PORT=8010 FRONTEND_PORT=3010 ./scripts/dev_local.sh
```

### LLM 没有计费记录

检查：

- `BID_LLM_PROVIDER` 是否指向你想看的供应商。
- `DEEPSEEK_API_KEY` 或 `OPENROUTER_API_KEY` 是否设置在 `backend/.env`。
- 后端是否重启并读取了新的 `.env`。
- 生成失败是否发生在调用 LLM 之前，例如格式章节未定位、文件解析失败、审查拦截。

### 生成失败但进度条还在动

以实时状态里的最新失败原因为准。后端后台任务和前端轮询可能有几秒延迟，刷新后会以数据库保存状态为准。

### MinIO 下载链接打不开

```bash
docker compose ps
```

确认：

```env
MINIO_API_URL=http://localhost:9000
MINIO_BUCKET=tender-files
```

### 重置本地数据

这会删除本地数据库和对象存储 volume：

```bash
docker compose down -v
./scripts/init_db.sh
```

## 11. 脚本清单

| 脚本 | 用途 |
|------|------|
| `scripts/setup_local.sh` | 首次完整安装 |
| `scripts/dev_local.sh` | 日常一键启动前后端 |
| `scripts/init_db.sh` | 启动 Docker 并应用 DB schema |
| `scripts/setup_venv.sh` | 创建/更新 Python `.venv` |
| `scripts/setup_frontend.sh` | 安装前端依赖 |
| `scripts/start_backend.sh` | 只启动 FastAPI |
| `scripts/start_frontend.sh` | 只启动 Next.js |
| `scripts/analyze_pdf_format.py` | 分析真实 PDF 格式特征 |
| `scripts/index_bid_templates.sh` | 将风格案例资料索引到本地知识库 |
| `backend/scripts/seed_default_template.py` | 导入公司风格案例样本 |
| `backend/scripts/extract_bid_template.py` | 从真实投标 PDF 抽取案例 JSON |
| `backend/scripts/prepare_knowledge_manifest.py` | 批量生成知识库命名/标签 manifest，并可导入本地知识库 |
| `backend/scripts/run_quality_eval.py` | 运行质量评估集 |
| `backend/scripts/run_bid_gap_eval.py` | 评估生成稿与真实样本差距 |

**最后更新：** 2026-06-14
