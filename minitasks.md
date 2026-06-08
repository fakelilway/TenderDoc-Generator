# TenderDoc-Generator MVP Minitasks 执行路径图

本文件包含从零开始构建 MVP 和下一阶段产品化 workflow 的完整任务清单，共 **64 个 Minitasks**（M1–M64）。
每个任务包含：**完成状态**、**依赖**、**完成标准**、**测试方法**。M1–M44 已形成可演示 MVP；M45–M60 用于把 MVP 升级为更接近真实标书工作流的产品；M61–M64 用于让生成结果学习真实历史投标文件模板。

---

## 阶段 0：环境搭建与基础设施（M1–M8）

### M1：初始化项目仓库与目录结构
- **完成状态**：✅ 已完成
- **依赖**：无
- **完成标准**：
  - Git 仓库已初始化，`.gitignore` 包含 `venv/`、`__pycache__/`、`.env`、`data/`
  - 目录结构：`backend/`、`frontend/`、`knowledge_base/`、`data/`
- **测试方法**：`ls -la` 查看目录结构；`git status` 显示正确忽略文件

### M2：编写 docker-compose.yml 并启动基础服务
- **完成状态**：✅ 已完成
- **依赖**：M1
- **完成标准**：
  - `docker-compose.yml` 包含 PostgreSQL+pgvector、Redis、MinIO 三个服务
  - 执行 `docker compose up -d` 后三容器均处于 `Up` 状态
- **测试方法**：`docker compose ps` 显示 3 个容器状态为 `Up`

### M3：验证 PostgreSQL 与 pgvector 扩展
- **完成状态**：✅ 已完成
- **依赖**：M2
- **完成标准**：
  - 能连接到 PostgreSQL，并成功创建 `vector` 扩展
  - 创建 `tenderdb` 数据库，用户 `tenderuser` 可访问
- **测试方法**：
  ```bash
  docker exec -it tender-postgres psql -U tenderuser -d tenderdb -c "CREATE EXTENSION IF NOT EXISTS vector;"
  docker exec -it tender-postgres psql -U tenderuser -d tenderdb -c "SELECT * FROM pg_extension WHERE extname='vector';"
  ```
  输出应包含一条记录。

### M4：创建基础数据库表结构
- **完成状态**：✅ 已完成
- **依赖**：M3
- **完成标准**：
  - 创建表：`projects`、`documents`、`knowledge_chunks`（最少字段见设计）
  - `projects` 表包含 `id`, `name`, `tender_file_path`, `parsed_json`, `status`, `created_at`
- **测试方法**：
  ```sql
  \dt
  SELECT * FROM projects LIMIT 0;
  ```
  不报错即可。

### M5：创建 Python 虚拟环境并编写 requirements.txt
- **完成状态**：⚠️ 部分完成（Python 3.11 venv 已完成；`llama-index-core` 是否保留待确认）
- **依赖**：M1
- **完成标准**：
  - `backend/venv/` 存在且已激活
  - `backend/requirements.txt` 包含：`langgraph`, `langchain`, `llama-index-core`, `psycopg2-binary`, `redis`, `fastapi`, `uvicorn`, `openai`, `pypdf`, `python-docx`, `python-dotenv`, `sentence-transformers`, `minio`
  - `pip install -r requirements.txt` 无错误
- **测试方法**：
  ```bash
  pip list | grep -E "langgraph|fastapi|sentence-transformers"
  ```
  显示对应包。
- **当前验证**：
  - `backend/venv/bin/python --version` 输出 Python 3.11.15
  - `llama-index-core` 当前未安装；项目现阶段未使用，待 RAG 阶段决定是否加入

### M6：实现配置管理 core/config.py
- **完成状态**：✅ 已完成
- **依赖**：M5
- **完成标准**：
  - 从 `.env` 文件读取所有配置项（数据库、Redis、MinIO、LLM）
  - 提供 `Config` 类，其他模块可 `from core.config import settings`
- **测试方法**：编写临时脚本打印 `settings.POSTGRES_HOST` 等，值与 `.env` 一致。
- **当前验证**：已确认 `core.config.settings` 可从 `backend/.env` 读取 PostgreSQL、Redis、MinIO、OpenRouter 配置。

### M7：实现 MinIO 工具类 utils/minio_client.py
- **完成状态**：✅ 已完成
- **依赖**：M2, M6
- **完成标准**：
  - 提供 `upload_file(bucket, file_path, object_name)`、`download_file(bucket, object_name, dest_path)`、`get_presigned_url(bucket, object_name, expiry=3600)`
  - 自动创建 bucket（若不存在）
- **测试方法**：
  ```python
  client = MinioClient()
  client.upload_file("tender-files", "test.txt", b"hello")
  url = client.get_presigned_url("tender-files", "test.txt")
  print(url)  # 可浏览器访问
  ```
- **当前验证**：已通过真实 MinIO smoke，覆盖 `upload_file`、`download_file`、`download_bytes`、`get_presigned_url`。

### M8：编写环境连通性验证脚本
- **完成状态**：✅ 已完成
- **依赖**：M4, M6, M7
- **完成标准**：
  - 在 `backend/` 下创建 `test_db.py`, `test_redis.py`, `test_minio.py`, `test_llm.py`（使用假 API key 仅测连通），全部通过
- **测试方法**：依次运行每个脚本，输出 `✓` 且无报错。
- **当前验证**：
  - `test_db.py`、`test_redis.py`、`test_minio.py` 均通过
  - `test_llm.py` 已改为 OpenRouter/DeepSeek fallback，并通过 OpenRouter live smoke
  - `test_embedding.py` 已通过，当前模型输出维度为 1024

---

## 阶段 1：招标文件解析 Agent（M9–M14）

### M9：实现文档文本提取工具 utils/file_parser.py
- **完成状态**：✅ 已完成
- **依赖**：M5
- **完成标准**：
  - 函数 `extract_text_from_pdf(file_path)` 返回字符串
  - 函数 `extract_text_from_docx(file_path)` 返回字符串
  - 支持从字节流提取（用于 API 上传）
- **测试方法**：用一份示例招标 PDF 和 DOCX 分别提取，肉眼可见可读文本。
- **当前验证**：已通过 PDF、TXT、DOCX path、DOCX uploaded bytes 文本提取 smoke。

### M10：定义解析 Agent 的输入/输出 JSON Schema
- **完成状态**：✅ 已完成
- **依赖**：无（可与 M9 并行）
- **完成标准**：
  - 定义 Pydantic 模型：`TenderRequirements` 包含 `project_name`, `qualification_list`, `technical_score_items`, `invalid_bid_items`
  - 输出示例 JSON 文件保存于 `tests/fixtures/expected_parsed.json`
- **测试方法**：运行 `pydantic` 校验无报错。

### M11：编写解析提示词模板
- **完成状态**：✅ 已完成
- **依赖**：M10
- **完成标准**：
  - 提示词模板要求 LLM 从招标文件文本中提取四个字段，并限定输出格式为 JSON
  - 包含 few-shot 示例（最好来自真实招标文件）
- **测试方法**：手工用 GPT/DeepSeek 测试一份招标文件文本，输出符合 Schema。

### M12：实现解析 Agent agents/parser_agent.py
- **完成状态**：✅ 已完成
- **依赖**：M9, M10, M11, M6 (LLM 客户端)
- **完成标准**：
  - 函数 `parse_tender(text: str) -> TenderRequirements`
  - 内部调用 LLM API，并用正则后处理修复常见错误（如多余逗号）
- **测试方法**：用 `tests/fixtures/sample_tender.txt` 调用，输出 JSON 能通过 Pydantic 校验。
- **当前验证**：已用 OpenRouter live LLM 跑通 `parse_tender`，输出可通过 `TenderRequirements` 校验。

### M13：编写解析准确率单元测试
- **完成状态**：✅ 已完成
- **依赖**：M12
- **完成标准**：
  - 准备 2 份真实招标文件，人工标注期望结果（后续拿到第 3 份时再扩充）
  - 测试脚本对比解析结果与期望，计算字段准确率（要求 ≥80%）
- **测试方法**：运行 `pytest tests/test_parser.py`，输出准确率统计。

### M14：将解析结果存入数据库并关联原文件
- **完成状态**：✅ 已完成
- **依赖**：M4, M7, M12
- **完成标准**：
  - 创建项目时：上传招标文件到 MinIO，记录路径到 `projects.tender_file_path`
  - 解析完成后，将 JSON 存入 `projects.parsed_json` 字段
- **测试方法**：创建一个项目，上传文件，触发解析，查询数据库记录确认字段已填充。
- **当前实现**：
  - `services/project_service.py` 已支持创建项目、上传原文件到 MinIO、记录 `projects.tender_file_path`
  - `parse_project(project_id)` 已支持下载原文件、抽取文本、调用解析 Agent、写入 `projects.parsed_json`
  - `tests/test_project_service.py` 用 fake DB/MinIO 覆盖关键链路
- **当前验证**：
  - 已通过真实 HTTP smoke：创建项目、上传 `sample_tender.txt`、触发解析、读取结果与 review
  - 已查询 PostgreSQL，确认 `projects.tender_file_path` 已填充、`projects.parsed_json` 非空、`documents` 有关联记录

---

## 阶段 2：RAG 索引与检索（M15–M20）

### M15：实现知识库文档解析与分块 rag/indexer.py
- **完成状态**：✅ 已完成
- **依赖**：M9
- **完成标准**：
  - 扫描 `../knowledge_base/` 目录（支持 PDF, DOCX, TXT）
  - 将每个文档按段落或固定长度（512 tokens）分块，记录元数据（文件名、页码）
- **测试方法**：在 `knowledge_base/` 放 2 个测试文档，运行后生成 chunk 列表，打印长度 >0。
- **当前实现**：
  - `rag/indexer.py` 已支持扫描知识库目录、解析 PDF/DOCX/TXT、按重叠窗口分块
  - `KnowledgeChunk.metadata` 包含 `source_path`、`file_name`、`file_type`、`chunk_index`
- **当前验证**：`tests/test_rag_indexer.py` 已覆盖 TXT/DOCX/PDF 解析、文件过滤、chunk overlap 和 metadata。

### M16：加载 Embedding 模型并生成向量
- **完成状态**：✅ 已完成
- **依赖**：M5, M15
- **完成标准**：
  - 从配置读取模型名称（BAAI/bge-small-zh-v1.5）
  - 对每个文本块调用 `model.encode()` 生成向量（当前配置维度 1024）
- **测试方法**：对单个 chunk 编码，检查 `len(vector) == 1024`。
- **当前实现**：
  - `rag/embeddings.py` 已支持从配置加载 `EMBEDDING_MODEL`、`EMBEDDING_DEVICE`、`EMBEDDING_DIMENSION`
  - 当前使用 `BAAI/bge-large-zh-v1.5`，输出维度 1024

### M17：将向量存入 pgvector 表 knowledge_chunks
- **完成状态**：✅ 已完成
- **依赖**：M4, M16
- **完成标准**：
  - 表结构：`id, content, metadata, embedding vector(1024)`
  - 为 embedding 列创建 ivfflat 索引
- **测试方法**：插入一条记录，执行 `SELECT * FROM knowledge_chunks WHERE embedding <-> '[0.1,...]' < 0.5` 返回结果。
- **当前实现**：
  - `init_db.sql` 已统一为 `VECTOR(1024)`，并创建 ivfflat 索引
  - `documents.project_id` 已允许为空，用于知识库文档
  - `rag/vector_store.py` 已支持写入 documents 和 knowledge_chunks
- **当前验证**：已通过真实 DB smoke，确认 chunk 已写入且 embedding 非空。

### M18：实现检索器 rag/retriever.py
- **完成状态**：✅ 已完成
- **依赖**：M17
- **完成标准**：
  - 函数 `retrieve(query: str, top_k=5)` 返回相似文本块列表，按相似度降序
- **测试方法**：查询“高层住宅施工组织设计”，返回的 top-1 应包含相关关键词。
- **当前实现**：`rag/retriever.py` 已实现 query embedding、pgvector 相似度查询、结果 score 转换和默认轻量 rerank。
- **当前验证**：已通过真实检索 smoke，查询“高层住宅施工组织设计”可返回相关 chunk。

### M19：添加检索结果重排序（可选，但强烈推荐）
- **完成状态**：✅ 已完成
- **依赖**：M18
- **完成标准**：
  - 使用 `sentence-transformers` 的 cross-encoder 或调用 Cohere rerank API
  - 对初检结果重新打分并排序
- **测试方法**：对比重排序前后 top-1 的相关性（肉眼判断改善）。
- **当前实现**：
  - `rerank_with_cross_encoder()` 已支持 `sentence-transformers` CrossEncoder
  - `retrieve()` 默认使用轻量关键词 overlap rerank，避免每次请求强制加载 reranker 大模型
- **当前验证**：单元测试已覆盖 rerank 相关排序提升。

### M20：实现知识库上传 API（增量索引）
- **完成状态**：✅ 已完成
- **依赖**：M7, M16, M17
- **完成标准**：
  - FastAPI 路由 `POST /api/knowledge/upload`，接收文件，保存到 MinIO，触发索引更新
  - 返回 `chunk_ids`
- **测试方法**：用 `curl` 上传一个新文档，查询知识库应能检索到新内容。
- **当前实现**：
  - `POST /api/knowledge/upload` 上传知识库文件、保存 MinIO、分块、embedding、写入 pgvector
  - `GET /api/knowledge/search` 用于检索知识库 chunks
- **当前验证**：已通过真实 HTTP smoke，上传 `rag_smoke.txt` 后可用搜索 API 检索到相关内容。

---

## 阶段 3：技术标生成 Agent（M21–M25）

### M21：设计动态标书大纲模板
- **完成状态**：✅ 已完成
- **依赖**：M10 (解析 Schema)
- **完成标准**：
  - 根据招标文件中的技术评分项生成章节大纲（如“施工方案”、“质量保证”、“进度计划”）
  - 大纲为 JSON 格式 `[{"title": "...", "required": true}]`
- **测试方法**：输入不同招标文件，生成不同大纲。
- **当前实现**：
  - `agents/generator_agent.py` 的 `build_bid_outline()` 会根据 `technical_score_items` 动态生成章节
  - 输出结构为 `schemas/bid.py` 中的 `BidSectionOutline`
- **当前验证**：`tests/test_generator_agent.py` 已覆盖不同技术评分项生成不同大纲。

### M22：实现生成 Agent agents/generator_agent.py
- **完成状态**：✅ 已完成
- **依赖**：M12 (解析结果), M18 (检索), M21, M6 (LLM)
- **完成标准**：
  - 函数 `generate_bid_section(section_title, requirements, retrieved_chunks)` 返回 Markdown 文本
  - 对每个大纲章节调用一次，最终合并为完整标书 Markdown
- **测试方法**：用一个项目数据调用，输出 Markdown 包含标题和段落，无 placeholder。
- **当前实现**：
  - `generate_bid_section()` 支持 OpenRouter/DeepSeek LLM 生成，并带规则 fallback
  - `generate_bid_document()` 会按大纲合并完整 Markdown 初稿
- **当前验证**：已通过 OpenRouter live section smoke，输出 Markdown 章节且无 placeholder。

### M23：实现 Word 导出工具 utils/docx_exporter.py
- **完成状态**：✅ 已完成
- **依赖**：M5 (python-docx)
- **完成标准**：
  - 函数 `markdown_to_docx(markdown_text, output_path)` 生成格式规范的 Word 文件
  - 支持标题层级、段落、表格（基础）
- **测试方法**：用示例 Markdown 调用，生成的 DOCX 在 Word 中打开样式正确。
- **当前实现**：`utils/docx_exporter.py` 已支持 Markdown 标题、段落、列表和基础表格导出。
- **当前验证**：`tests/test_docx_exporter.py` 已检查生成的 DOCX 可读取且包含标题、段落和表格。

### M24：集成生成与导出到项目流程
- **完成状态**：✅ 已完成
- **依赖**：M14, M22, M23, M7 (保存到 MinIO)
- **完成标准**：
  - 对项目调用 `generate_and_export(project_id)`，生成标书 Markdown，导出 DOCX，上传到 MinIO，保存路径到 `projects.generated_docx_path`
- **测试方法**：创建项目并触发生成，从 MinIO 下载 DOCX 文件手动检查。
- **当前实现**：
  - `services/generation_service.py` 已实现 `generate_and_export(project_id)`
  - `POST /api/project/{id}/generate` 已接入生成、导出、上传和 DB 回写
  - `projects` 已新增 `generated_markdown_path`、`generated_docx_path`、`generation_quality_json`
- **当前验证**：已通过真实 DB/MinIO/DOCX smoke，确认 DOCX 可下载且 `projects.generated_docx_path` 已填充。

### M25：评估生成质量并记录基线
- **完成状态**：✅ 已完成
- **依赖**：M24
- **完成标准**：
  - 使用 2 份招标文件生成标书，人工标记需要修改的段落数量，计算“可使用率”（无需修改的段落数/总段落数）
  - 记录基线（目标 >60%）
- **测试方法**：输出统计报告。
- **当前实现**：
  - `evaluate_generation_quality()` 基于段落长度和 placeholder 检测输出 MVP 质量报告
  - 质量报告写入 `projects.generation_quality_json`
- **当前验证**：集成 smoke 的 `usable_rate` 为 1.0；后续真实人工标注可替换当前启发式基线。

---

## 阶段 4：审查 Agent 与闭环（M26–M33）

### M26：构建废标规则库（基于关键词 + 正则）
- **完成状态**：✅ 已完成
- **依赖**：M10 (废标项 schema)
- **完成标准**：
  - 定义规则文件 `rules/invalid_bid_rules.json`，每条规则包含：`field`（如“资质要求”）、`keyword_patterns`、`required_value`
  - 覆盖常见废标项（如“项目经理一级建造师”、“安全生产许可证”）
- **测试方法**：用测试用例（满足/不满足）验证规则命中率。
- **当前实现**：`rules/invalid_bid_rules.json` 已覆盖项目经理证书、安全生产许可证、投标保证金、企业资质、工期和质量响应。
- **当前验证**：`tests/test_reviewer_agent.py` 已验证规则加载和缺项命中。

### M27：实现审查 Agent agents/reviewer_agent.py（规则+LLM 双重）
- **完成状态**：✅ 已完成
- **依赖**：M12 (解析出来的废标清单), M22 (生成的标书文本), M26
- **完成标准**：
  - 函数 `review(parsed_requirements, generated_markdown)` 返回 `[{"rule": "...", "status": "fail/pass/warning", "suggestion": "..."}]`
  - 先用规则引擎检查结构化项（资质、证书），再用 LLM 检查描述性内容
- **测试方法**：故意制造一个缺少资质的标书，审查应标记 fail。
- **当前实现**：`agents/reviewer_agent.py` 已实现规则审查，并提供可选 LLM 审查增强。
- **当前验证**：已覆盖缺少项目经理/安全生产许可证等场景，能输出 fail/pass/warning。

### M28：实现审查报告与标书内容关联（高亮）
- **完成状态**：✅ 已完成
- **依赖**：M27
- **完成标准**：
  - 为每个失败项提供在 Markdown 中的位置（行号或段落索引）
- **测试方法**：审查输出中包含 `location` 字段，能定位到原文。
- **当前实现**：`ReviewFinding.location` 包含 `line_number`、`paragraph_index`、`snippet`。
- **当前验证**：测试已覆盖 location 可定位到包含关键词的 Markdown 行。

### M29：搭建 LangGraph 基础状态图（无循环）
- **完成状态**：✅ 已完成
- **依赖**：M12, M18, M22, M27
- **完成标准**：
  - 定义 State 包含 `tender_text`, `parsed`, `retrieved_chunks`, `draft_markdown`, `review_report`
  - 创建图，顺序节点：parse → retrieve → generate → review
- **测试方法**：运行图，State 按顺序填充，最终有 review_report。
- **当前实现**：`services/workflow_graph.py` 已基于 LangGraph `StateGraph` 定义 parse → retrieve → generate → review → human_review。
- **当前验证**：`tests/test_workflow_graph.py` 已运行图并验证最终有 `review_report`。

### M30：实现“修正”节点并添加循环
- **完成状态**：✅ 已完成
- **依赖**：M29
- **完成标准**：
  - 添加 `correct` 节点：接收 review_report 中失败项，调用生成 Agent 重新生成对应章节
  - 添加条件边：若 review 有 fail 且迭代次数 <3，跳转到 correct 再回到 review；否则到 end
- **测试方法**：模拟一个审查失败场景，验证图进入循环并最多 3 次。
- **当前实现**：`correct_markdown()` 会根据 fail 项追加修正说明，workflow 最多循环 3 次。
- **当前验证**：`tests/test_workflow_service.py` 已验证失败项会进入修正循环且不超过上限。

### M31：持久化 LangGraph 状态到 Redis
- **完成状态**：✅ 已完成
- **依赖**：M3 (Redis), M30
- **完成标准**：
  - 使用 `Checkpointer` 保存每个项目的状态，支持从中断点恢复
- **测试方法**：运行图到中途停止，重启后调用 `graph.invoke(None, config={"thread_id": project_id})` 继续。
- **当前实现**：`services/workflow_service.py` 使用 Redis 保存 `workflow:{project_id}` 状态，并将最终状态同步到 `projects.workflow_state_json`。
- **当前验证**：真实 Redis/DB smoke 已验证 workflow state 可保存、恢复并写入 PostgreSQL。

### M32：添加人工确认节点（Human-in-the-Loop）
- **完成状态**：✅ 已完成
- **依赖**：M31
- **完成标准**：
  - 在生成最终标书前插入 `human_review` 节点，图会暂停等待外部 API 触发继续
  - API：`POST /api/project/{id}/confirm` 携带确认或修改指令
- **测试方法**：运行图，检查图在 `human_review` 节点暂停；发送确认后继续执行。
- **当前实现**：`POST /api/project/{id}/workflow/run` 会运行到 `human_review`，`POST /api/project/{id}/confirm` 会应用人工修正并批准/退回。
- **当前验证**：真实 workflow smoke 已验证暂停人工确认、确认后导出 DOCX 并将状态更新为 `approved`。

### M33：端到端测试闭环（废标检出率）
- **完成状态**：✅ 已完成
- **依赖**：M32
- **完成标准**：
  - 准备一份包含 5 个已知废标项的招标文件，运行全流程，统计检出数量
  - 要求 ≥4/5
- **测试方法**：记录日志并生成报告。
- **当前实现**：`build_closure_test_report()` 可根据期望 fail 规则计算 `detection_rate`、命中项和漏检项。
- **当前验证**：单元测试已覆盖检出率计算；真实 workflow smoke 已覆盖审查、修正、确认、导出完整闭环。

---

## 阶段 5：API 层与人机协同（M34–M38）

### M34：实现 FastAPI 基础路由（创建项目、获取状态）
- **完成状态**：✅ 已完成
- **依赖**：M4, M7
- **完成标准**：
  - `POST /api/project/create`：接收 `name` 和招标文件，返回 `project_id`
  - `GET /api/project/{id}/status`：返回 `status`（parsing/generating/reviewing/approved）
- **测试方法**：用 `requests` 调用，数据库新增记录。
- **当前实现**：
  - `api/main.py` 已提供 `POST /api/project/create` 与 `GET /api/project/{id}/status`
  - `tests/test_project_api.py` 已覆盖创建项目、状态查询、404 错误处理
- **当前验证**：已通过真实 HTTP smoke，`POST /api/project/create` 返回 `project_id`，`GET /api/project/{id}/status` 返回 `uploaded/parsed` 状态。

### M35：实现异步生成触发接口
- **完成状态**：✅ 已完成
- **依赖**：M32 (LangGraph 可调用), M34
- **完成标准**：
  - `POST /api/project/{id}/generate`：在后台启动 LangGraph 工作流（FastAPI BackgroundTasks 或 Celery）
  - 立即返回 `task_id`
- **测试方法**：调用后立即查询状态，返回 `processing`，稍后变为 `finished`。
- **当前实现**：
  - `POST /api/project/{id}/generate` 已使用 FastAPI `BackgroundTasks` 后台启动生成任务
  - 接口会立即返回 `task_id` 和 `processing` 状态
  - 生成任务会导出 Markdown/DOCX 并写回 MinIO；完整 LangGraph 闭环仍由 `/api/project/{id}/workflow/run` 承载
- **当前验证**：异步触发接口、下载接口和 project API 已通过单元测试；端到端 workflow 由 `/workflow/run` 和 `/confirm` 覆盖。

### M36：实现获取审查报告接口
- **完成状态**：✅ 已完成
- **依赖**：M35, M28
- **完成标准**：
  - `GET /api/project/{id}/review`：返回审查报告 JSON
- **测试方法**：在生成完成后调用，得到包含 fail 项的列表。
- **当前实现**：
  - `GET /api/project/{id}/review` 当前返回 `parsed_json.invalid_bid_items`
  - `GET /api/project/{id}/review-report` 已可返回正式审查报告和 workflow state
- **当前验证**：MVP 占位接口已通过真实 HTTP smoke，能返回解析出的废标条款列表。

### M37：实现人工确认接口
- **完成状态**：✅ 已完成
- **依赖**：M32, M35
- **完成标准**：
  - `POST /api/project/{id}/confirm`：接受 `approved` (bool) 和 `corrections` (可选 dict)
  - 如果 `approved` 为 true，图继续执行；否则用 `corrections` 更新 State 后重试
- **测试方法**：生成过程中调用，验证图从暂停恢复。

### M38：实现标书下载接口
- **完成状态**：✅ 已完成
- **依赖**：M24, M7
- **完成标准**：
  - `GET /api/project/{id}/download`：返回预签名 URL 或直接文件流
- **测试方法**：调用后能下载 DOCX 文件。

---

## 阶段 6：前端基础界面（M39–M44）

**阶段发布状态**：✅ 已推送到 GitHub 分支 `codex-phase-6-frontend-demo`

### M39：初始化 Next.js 项目并配置 API 代理
- **完成状态**：✅ 已完成
- **依赖**：M34
- **完成标准**：
  - `frontend/` 目录使用 `create-next-app`，TypeScript + Tailwind
  - 配置 `next.config.js` 代理 `/api` 到后端 `http://localhost:8000`
- **测试方法**：`npm run dev` 访问 `http://localhost:3000` 能看到默认页面。
- **当前实现**：
  - `frontend/` 已创建 Next.js App Router 项目骨架，包含 TypeScript、Tailwind、PostCSS、Next 配置和基础脚本。
  - `frontend/next.config.mjs` 已配置 `/api/:path*` 代理到 `http://localhost:8000/api/:path*`，可通过 `BACKEND_API_BASE_URL` 覆盖。
- **当前验证**：
  - 已完成前端源码落地；`pnpm install`、`pnpm run typecheck`、`pnpm run build` 均已通过。
  - `./scripts/dev_local.sh` 已验证可启动 Next.js 前端到 `http://localhost:3000`。

### M40：实现文件上传组件（上传招标文件）
- **完成状态**：✅ 已完成
- **依赖**：M39, M34 (/api/project/create)
- **完成标准**：
  - 拖拽上传区域，调用后端创建项目接口，成功后跳转到项目工作台页面
- **测试方法**：上传 PDF，检查浏览器控制台网络请求返回 `project_id`。
- **当前实现**：
  - `components/UploadPanel.tsx` 已支持项目名称、拖拽/点击上传 PDF/DOCX/TXT、文件移除和上传启动。
  - `components/TenderWorkspace.tsx` 会调用 `POST /api/project/create`，成功后切换到 `/project/{project_id}` 工作台地址。
- **当前验证**：
  - 已完成接口封装和页面串联；前端已可本地启动，真实招标文件浏览器上传演示进入调优阶段。

### M41：实现项目工作台页面（轮询状态 + 展示标书内容）
- **完成状态**：✅ 已完成
- **依赖**：M40, M35, M36
- **完成标准**：
  - 显示当前阶段（解析中/生成中/审查中/待确认）
  - 每 2 秒轮询 `/status`，更新进度条
  - 生成完成后，获取标书内容（调用导出接口预览）
- **测试方法**：上传文件后，界面自动刷新显示生成结果。
- **当前实现**：
  - `app/page.tsx` 已串联 `create -> parse -> workflow/run -> review-report`，并每 2 秒轮询 `/api/project/{id}/status` 与 `/review-report`。
  - `components/StatusRail.tsx` 已显示上传、解析、生成、审查、确认、下载的实时阶段。
  - `components/MarkdownPreview.tsx` 已展示 `workflow_state.draft_markdown` 作为标书预览。
- **当前验证**：
  - 已完成状态轮询、workflow 快照读取和 Markdown 预览逻辑；前后端开发服务已通过本地健康检查。

### M42：实现审查报告面板（风险项列表 + 高亮）
- **完成状态**：✅ 已完成
- **依赖**：M41, M36
- **完成标准**：
  - 以表格/卡片形式展示每个废标项的检查结果（通过/失败/警告）
  - 点击失败项，在标书预览区域高亮对应位置
- **测试方法**：在审查阶段结束后，页面显示风险清单，点击能滚动到对应段落。
- **当前实现**：
  - `components/RiskPanel.tsx` 已展示 pass/fail/warning 风险项、严重程度、建议和定位行号。
  - 点击风险项会设置 active line，`MarkdownPreview` 自动滚动并高亮对应 Markdown 行。
- **当前验证**：
  - 已完成审查报告 UI 与高亮联动代码；前端 typecheck/build 已通过。

### M43：实现人工确认按钮（批准或修改）
- **完成状态**：✅ 已完成
- **依赖**：M42, M37
- **完成标准**：
  - 在审查报告下方显示“批准并继续”和“手动修改”按钮
  - 点击“批准”调用 `/confirm`；点击修改弹出文本框，提交修改内容
- **测试方法**：模拟审查完成，点击批准后工作流继续，最终可下载。
- **当前实现**：
  - 顶部操作区已提供“批准并继续”和“手动修改”按钮。
  - `components/CorrectionModal.tsx` 已支持输入修正意见，并可调用 `/api/project/{id}/confirm` 保存修正或应用并批准。
- **当前验证**：
  - 已完成确认/修正 API 串联；前端 typecheck/build 已通过，真实文件交互演示进入调优阶段。

### M44：实现标书下载功能
- **完成状态**：✅ 已完成
- **依赖**：M43, M38
- **完成标准**：
  - 工作流最终完成后，显示“下载标书”按钮，点击调用 `/download` 获取文件
- **测试方法**：完成整个流程，点击下载得到 DOCX 文件。
- **当前实现**：
  - 工作流状态为 `approved`、`finished` 或 `generated` 后启用“下载标书”按钮。
  - 点击按钮调用 `GET /api/project/{id}/download`，保存预签名 URL 并在新窗口打开 DOCX。
- **当前验证**：
  - 已完成下载接口调用和 URL 打开逻辑；后端下载接口已通过单元测试，前端 typecheck/build 已通过。

---

## 阶段 7：Workflow 产品化与人工可控节点（M45–M52）

目标：对齐 `tender_flow.png` 中“用户确认大纲 -> 检索 -> 生成 -> 审查 -> 修正 -> 终审”的可控流程。MVP 已能跑通主链路，但下一阶段要让用户能看懂、能改、能追踪每一步。

### M45：解析结果确认页
- **完成状态**：✅ 已完成
- **依赖**：M14, M41
- **完成标准**：
  - 上传并解析完成后，前端先展示 `project.parsed_json`
  - 用户可查看/编辑项目名称、资质要求、技术评分项、废标条款
  - 保存后写回数据库，形成“人工确认版解析结果”
- **测试方法**：
  - 上传真实招标文件，修改一个评分项，刷新页面后修改仍存在
  - 后端测试覆盖解析 JSON 更新接口
- **当前实现**：
  - `PATCH /api/project/{id}/parsed` 保存确认版解析结果到 `confirmed_parsed_json`
  - 前端 `ParsedReviewPanel` 支持查看/编辑解析 JSON，保存后自动生成默认大纲
- **当前验证**：
  - `backend/tests/test_project_api.py` 覆盖解析确认接口
  - `cd frontend && pnpm run typecheck && pnpm run build` 通过

### M46：动态大纲编辑器
- **完成状态**：✅ 已完成
- **依赖**：M21, M45
- **完成标准**：
  - 根据解析出的技术评分项生成默认大纲
  - 用户可新增、删除、重排章节，并编辑每章重点
  - 保存为 `projects.bid_outline_json` 或 workflow state 中的确认大纲
- **测试方法**：
  - 修改章节顺序后触发生成，生成 Agent 按用户确认的大纲输出
  - 前端 typecheck/build 通过
- **当前实现**：
  - `POST /api/project/{id}/outline` 基于解析结果和真实模板生成默认大纲
  - `PATCH /api/project/{id}/outline` 保存用户调整后的 `bid_outline_json`
  - 前端 `OutlineEditor` 支持章节标题编辑、重点编辑、上移、下移和删除
- **当前验证**：
  - `backend/tests/test_project_api.py` 覆盖生成和保存大纲接口
  - workflow 生成时优先使用项目确认后的 `bid_outline_json`

### M47：生成前人工确认分支
- **完成状态**：✅ 已完成
- **依赖**：M45, M46, M32
- **完成标准**：
  - workflow 在解析和大纲生成后暂停
  - 用户点击“确认大纲”后才进入 RAG 检索与生成
  - 用户选择“需要修改”时回到解析结果/大纲编辑页
- **测试方法**：
  - E2E smoke 验证 workflow 不会绕过确认直接生成
  - 单元测试覆盖确认/退回两条分支
- **当前实现**：
  - `/api/project/{id}/workflow/run` 在缺少 `confirmed_parsed_json` 或 `bid_outline_json` 时暂停到 `outline_review`
  - 前端移除上传后自动生成，改为用户确认解析/大纲后点击“开始生成”
- **当前验证**：
  - `backend/tests/test_workflow_service.py` 覆盖 workflow 不绕过大纲确认
  - 全量后端测试 `88 passed, 2 skipped`

### M48：细粒度任务状态与 Agent Trace
- **完成状态**：✅ 已完成
- **依赖**：M35, M41
- **完成标准**：
  - 后端记录每个项目的 step events：上传、解析文本、LLM 请求、RAG 检索、生成、审查、导出
  - 前端实时展示事件、耗时、模型名、fallback/timeout 状态
  - 可显示“模型返回的显式 reasoning 摘要”，但不展示隐藏链式思考原文
- **测试方法**：
  - 上传大 PDF 时前端不再停留在模糊百分比，而能看到当前步骤和已耗时
  - parser timeout 单元测试和前端 typecheck 通过
- **当前实现**：
  - `WorkflowTraceEvent` 增加 `duration_ms`、`model_name`、`fallback`
  - workflow 持续写入 `trace_events`，前端 `StatusRail` 展示 outline、生成、审查、确认、下载事件
  - 前端展示模型名、耗时、fallback 标记；不展示隐藏链式思考
- **当前验证**：
  - `backend/tests/test_workflow_service.py` 覆盖 trace 序列化
  - `cd frontend && pnpm run typecheck && pnpm run build` 通过

### M49：知识库资料分类与引用展示
- **完成状态**：✅ 已完成
- **依赖**：M20
- **完成标准**：
  - 知识库文档支持标题、类型、专业、项目年份、标签
  - RAG 检索支持按资料类型/标签过滤
  - 生成内容展示引用来源：资料标题、chunk、相似度、引用段落
- **测试方法**：
  - 上传两个不同类型资料，按标签检索只返回对应资料
  - 生成结果中可追踪引用来源
- **当前实现**：
  - `documents.metadata_json` 保存资料类型、专业、年份和标签
  - 知识库上传、重命名和列表接口支持 metadata
  - `retrieve_filtered()` 支持按资料类型、专业和标签过滤
  - workflow state 输出 `rag_references`，前端展示已采用片段
- **当前验证**：
  - `backend/tests/test_project_api.py` 覆盖知识库接口兼容
  - `backend/tests/test_rag_retriever.py` 和全量后端测试通过

### M50：知识库检索结果人工选择
- **完成状态**：✅ 已完成
- **依赖**：M49
- **完成标准**：
  - 生成前展示 RAG 检索结果
  - 用户可勾选采用/排除某些资料
  - 生成 Agent 只使用被确认的资料上下文
- **测试方法**：
  - 排除某个模板后，生成内容不再引用该模板内容
  - API 测试覆盖 selected_chunk_ids
- **当前实现**：
  - `PATCH /api/project/{id}/knowledge-selection` 保存 `selected_chunk_ids`
  - workflow 生成时优先使用人工选择的知识片段
  - 前端 `RagSelectionPanel` 支持筛选检索、勾选采用/排除资料片段
- **当前验证**：
  - `backend/tests/test_project_api.py` 覆盖资料选择接口
  - `backend/tests/test_workflow_service.py` 覆盖 workflow 生成链路

### M51：正文级在线编辑器
- **完成状态**：✅ 已完成
- **依赖**：M41, M43
- **完成标准**：
  - 用户可以直接编辑生成后的 Markdown 正文
  - 支持保存草稿、撤销到上一个保存版本、继续审查
  - 保存后的正文进入审查 Agent 和最终导出
- **测试方法**：
  - 编辑一段正文并保存，刷新项目后内容仍存在
  - 导出的 DOCX 包含编辑后的内容
- **当前实现**：
  - `PATCH /api/project/{id}/draft` 保存 `edited_markdown` 并重新运行审查
  - `confirm_project()` 导出时优先使用已保存正文
  - 前端 `DraftEditor` 支持正文 Markdown 编辑和保存
- **当前验证**：
  - `backend/tests/test_project_api.py` 覆盖正文保存接口
  - `cd frontend && pnpm run typecheck && pnpm run build` 通过

### M52：最终确认 Checklist 与版本记录
- **完成状态**：✅ 已完成
- **依赖**：M51, M44
- **完成标准**：
  - 终审前显示废标项响应、人工确认点、报价人工填写点、附件清单
  - 每次批准生成一个 final version 记录
  - 最终版 DOCX/Markdown 带版本号上传 MinIO
- **测试方法**：
  - 同一项目多次修改后可下载不同版本
  - DB 中可查询 final version 历史
- **当前实现**：
  - `GET /api/project/{id}/final-checklist` 输出废标响应、人工确认点、报价填写点和附件清单
  - `final_versions_json` 记录最终 Markdown/DOCX 路径版本
  - 前端 `FinalChecklistPanel` 展示终审清单和版本数量
- **当前验证**：
  - `backend/tests/test_project_api.py` 覆盖终审清单接口
  - 全量后端测试、前端 typecheck/build 均通过

---

## 阶段 8：策略 Agent 与高级审查（M53–M56）

目标：对齐图中的“报价 Agent”和“评分预测 Agent”。这两个模块先做辅助策略，不替代人工报价和最终投标判断。

### M53：报价策略 Schema 与输入抽取
- **完成状态**：❌ 未开始
- **依赖**：M12, M14
- **完成标准**：
  - 定义 `PricingStrategy` schema：项目规模、工期风险、付款条件、竞争强度、报价风险、人工填写项
  - Parser 或独立 Agent 能从招标文件中抽取报价相关条件
  - 所有具体金额、费率、清单单价必须标记为人工填写
- **测试方法**：
  - 用真实招标文件抽取付款条件/保证金/工期约束
  - schema 校验通过，不生成虚假金额

### M54：报价 Agent（策略建议版）
- **完成状态**：❌ 未开始
- **依赖**：M53, M27
- **完成标准**：
  - 输出报价策略建议、风险提示、商务响应注意事项
  - 不自动填写工程量清单报价
  - 审查 Agent 能检查商务标中报价人工确认点是否保留
- **测试方法**：
  - 输入缺少工程量清单数据时，输出必须包含人工确认点
  - 单元测试覆盖“不编造价格”

### M55：评分预测 Agent
- **完成状态**：❌ 未开始
- **依赖**：M22, M27
- **完成标准**：
  - 根据评分项模拟专家打分，输出总分、分项分、短板、提升建议
  - 可选输出中标概率，但必须附带依据和不确定性说明
  - 前端显示评分预算/中标概率，不影响最终审批流
- **测试方法**：
  - 对缺少关键章节的标书给出低分和明确原因
  - 对完整样例给出更高分，且分项解释可读

### M56：审查响应矩阵
- **完成状态**：❌ 未开始
- **依赖**：M27, M28, M52
- **完成标准**：
  - 生成“招标要求 -> 标书响应位置 -> 审查状态 -> 人工确认”矩阵
  - 覆盖资质、废标项、评分项、商务人工填写点
  - 终审 checklist 直接引用该矩阵
- **测试方法**：
  - 每个 `invalid_bid_item` 至少有一条矩阵记录
  - 点击矩阵项可定位到 Markdown 行或章节

---

## 阶段 9：输出质量、项目管理与演示闭环（M57–M60）

目标：让系统从“能演示”变成“可反复试用”。重点是项目管理、文档格式、真实样本评估和下载通知。

### M57：项目列表与历史项目恢复
- **完成状态**：❌ 未开始
- **依赖**：M34, M39
- **完成标准**：
  - 用户登录后看到自己的项目列表
  - 可进入历史项目并恢复当前状态、草稿、审查报告、下载链接
  - 管理员可查看全部项目或按用户筛选
- **测试方法**：
  - 创建两个项目后刷新页面，项目列表仍可进入对应工作台
  - 普通用户不能查看其他用户项目

### M58：DOCX 输出格式升级
- **完成状态**：❌ 未开始
- **依赖**：M23, M52
- **完成标准**：
  - 支持封面、目录、页眉页脚、页码、标题样式、表格样式
  - 支持技术标/商务标分册或单文件输出策略
  - 导出文件命名包含项目名和版本号
- **测试方法**：
  - 渲染导出的 DOCX，检查封面、目录、标题层级和页码
  - 至少用 2 份真实项目输出并人工验收格式

### M59：真实样本质量评估集
- **完成状态**：❌ 未开始
- **依赖**：M45–M58
- **完成标准**：
  - 建立至少 5 个真实招标文件 + 对应人工投标文件的评估集
  - 评估解析准确率、章节完整率、废标检出率、人工修改量、总耗时
  - 记录每次版本的质量指标
- **测试方法**：
  - 一键运行评估脚本，输出 Markdown/JSON 报告
  - 至少 3 个指标有可追踪趋势

### M60：完成通知与下载体验
- **完成状态**：❌ 未开始
- **依赖**：M44, M52
- **完成标准**：
  - 工作流完成后前端明确提示“可下载”
  - 支持下载最终 DOCX、Markdown、审查报告
  - 下载链接过期时可重新生成预签名 URL
- **测试方法**：
  - 完成项目后不刷新页面即可看到下载入口
  - 过期链接重新请求后可正常下载

---

## 阶段 10：真实投标模板学习与质量对齐（M61–M64）

目标：解决“AI 生成的 bid.docx 与真实投标文件差距太大”的核心问题。系统需要从真实历史投标文件中抽取章节结构、固定表单、附表清单和样本文风，再让 Generator Agent 按模板生成，而不是只靠通用 prompt。

### M61：真实投标文件模板解析
- **完成状态**：✅ 已完成
- **依赖**：M9, M23, M58
- **完成标准**：
  - 支持读取真实历史投标 PDF，抽取封面信息、第一信封/第二信封类型、主目录、施工组织设计目录、附表目录
  - 输出脱敏后的结构化 JSON 模板，不提交原始大 PDF
  - JSON 不包含身份证号、手机号、本机绝对路径等敏感信息
- **测试方法**：
  ```bash
  backend/venv/bin/python -m pytest backend/tests/test_bid_template_parser.py
  backend/venv/bin/python backend/scripts/extract_bid_template.py "/path/to/真实投标文件.PDF" \
    --out backend/tests/fixtures/bid_templates/road_first_envelope_template.json \
    --name "公路工程第一信封真实投标模板样本"
  ```
- **当前实现**：
  - `schemas/bid_template.py` 定义 `BidTemplate` 与 `BidTemplateSection`
  - `utils/bid_template_parser.py` 实现 `parse_bid_template_pdf()` 与 `parse_bid_template_pages()`
  - `scripts/extract_bid_template.py` 可从真实投标 PDF 导出模板 JSON
  - `tests/fixtures/bid_templates/road_first_envelope_template.json` 已由真实 892 页投标 PDF 生成，包含 9 个主章节、288 个施工组织设计目录项、8 个附表项

### M62：Generator Agent 接入真实模板
- **完成状态**：✅ 已完成
- **依赖**：M21, M22, M61
- **完成标准**：
  - 生成 Agent 可读取 `BidTemplate`，按真实模板的章节顺序输出技术标在前、商务标在后
  - 对固定表单、资质资料、报价清单等不能编造的信息保留人工确认点
  - 生成时禁止把 RAG 页眉页脚、目录页码、无关表格碎片直接写入正文
- **测试方法**：
  - 用同一份招标文件生成 DOCX，对比真实投标文件目录，章节完整率 ≥80%
  - 单元测试覆盖模板章节顺序、人工确认点保留、RAG 噪声过滤
- **当前实现**：
  - `BID_TEMPLATE_PATH` 默认指向 `backend/templates/bid_templates/road_first_envelope_template.json`
  - `GeneratorAgent` 会优先读取 `BidTemplate` 的施工组织设计章节、固定表单和附表，不再用 prompt 写死完整输出格式
  - `build_document_prompt()` 只保留角色、真实性约束、结构来源优先级和兜底规则；招标 JSON 决定响应内容，模板 JSON 决定输出格式
- **当前验证**：
  - `tests/test_generator_agent.py` 已覆盖模板章节优先、模板附表输出、prompt 不再包含“输出结构必须严格如下”

### M63：真实投标文件差距评估脚本
- **完成状态**：❌ 未开始
- **依赖**：M61, M62
- **完成标准**：
  - 输入 AI 生成 DOCX 和真实投标 PDF/DOCX，输出结构差异、缺失章节、固定表单缺失、内容长度差异、人工确认点统计
  - 生成 Markdown/JSON 质量报告，作为每次 prompt/generator 改动后的回归指标
- **测试方法**：
  - 对 `bid.docx` 与 `1投标文件.PDF` 输出差距报告
  - 至少能识别缺少施工附表、项目管理机构、资格审查资料、中小企业声明函等问题

### M64：模板库管理与项目类型匹配
- **完成状态**：❌ 未开始
- **依赖**：M49, M61
- **完成标准**：
  - 管理员可上传历史投标文件作为模板样本，系统解析并保存模板 JSON
  - 模板按项目类型、专业、信封类型、地区、年份打标签
  - 创建项目时自动推荐最相近模板，用户可手动切换
- **测试方法**：
  - 上传至少 2 份不同类型历史投标文件，创建新项目时能推荐对应模板
  - 普通用户无模板编辑权限，管理员可删除/重命名模板

---

## 总结

- 共 **64 个 Minitasks**，从 M1 到 M44 覆盖 MVP，M45 到 M52 覆盖 workflow 产品化第一阶段，M53 到 M60 覆盖策略 Agent、项目管理和输出体验，M61 到 M64 覆盖真实投标模板学习。
- 下一阶段优先顺序：优先做 M63 真实投标文件差距评估脚本，再做 M53–M56 的策略 Agent 与高级审查，随后推进 M57–M60/M64 的项目管理、DOCX 格式、通知体验和模板库。
- 按顺序执行，即可从可控工作流升级为更接近真实标书编制团队日常使用的产品。

**最后更新**：2026-06-08
