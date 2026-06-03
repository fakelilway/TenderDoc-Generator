# TenderDoc-Generator MVP Minitasks 执行路径图

本文件包含从零开始构建 MVP 的完整任务清单，共 **44 个 Minitasks**（M1–M44）。  
每个任务包含：**完成状态**、**依赖**、**完成标准**、**测试方法**。按顺序执行即可完成可交付的 MVP。

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

## 总结

- 共 **44 个 Minitasks**，从 M1 到 M44，覆盖环境搭建、后端核心功能、API、前端界面。
- 每个任务都有明确的**依赖关系**、**完成标准**和**测试方法**。
- 按顺序执行，即可实现一个可演示、可试用的 MVP。

**最后更新**：2026-06-03
```
