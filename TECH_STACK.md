# TenderDoc-Generator 技术栈规划

> 最后更新：2026-05-29 | 状态：待确认

---

## 1. 前端

| 组件 | 选型 | 理由 |
|------|------|------|
| **框架** | React 18 + TypeScript | 生态成熟，组件库丰富，企业应用常用 |
| **状态管理** | TanStack Query v5 | 适合异步任务状态管理，与后端API配合无缝 |
| **UI 组件库** | Ant Design v5 | 完美支持中文企业应用，表单/表格/Modal丰富 |
| **富文本编辑** | React-Quill 或 Slate | 预览标书内容，支持导出 |
| **打包工具** | Vite | 开发速度快，配合 TypeScript 生产体验好 |
| **样式方案** | Tailwind CSS + CSS Modules | 实用优先，组件级样式隔离 |
| **HTTP 客户端** | Axios | 简洁，支持 interceptor 便于认证/错误处理 |
| **文件上传** | react-dropzone | 优雅的拖拽上传体验 |
| **表格** | TanStack Table v8 | 灵活高效，适合大数据量 |
| **路由** | React Router v6 | 标准路由管理 |
| **环境变量** | .env + Vite 内置 | Vite 原生支持 |

**部署**：Vercel / Netlify（快速）或 Nginx（自建）

---

## 2. 后端

| 组件 | 选型 | 理由 |
|------|------|------|
| **框架** | FastAPI | 异步高性能，自动 API 文档，易整合 AI 任务 |
| **Python 版本** | 3.11+ | 最新发布版本，性能优化 + 类型支持完善 |
| **异步运行时** | uvicorn | FastAPI 标准搭档 |
| **后台任务** | Celery + Redis Broker | 支持序列化状态检查点、重试机制 |
| **认证授权** | FastAPI-Security + JWT | 无状态认证，API 友好 |
| **ORM** | SQLAlchemy 2.0 | 支持 pgvector，async 原生支持 |
| **数据校验** | Pydantic v2 | FastAPI 官方，性能提升明显 |
| **日志** | structlog + Python logging | 结构化日志，便于监控 |
| **监控/追踪** | OpenTelemetry 基础集成 | 为后续扩展预留接口 |
| **配置管理** | pydantic-settings | 从 .env 读取，类型安全 |

**ASGI 服务器启动**：
```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```

---

## 3. AI / Agent 编排

| 组件 | 选型 | 理由 |
|------|------|------|
| **Agent 框架** | LangGraph | 支持状态图、循环、checkpointer；适合审查→修正闭环 |
| **LLM 集成** | LangChain | 统一接口调用多家大模型，减少 API 迁移成本 |
| **大模型 API** | DeepSeek（主）+ 通义千问 | 中文能力强，成本低；多源防止单点故障 |
| **向量模型** | BAAI/bge-large-zh-v1.5 | 中文语义理解最强，384 维度 |
| **文本分割** | langchain-text-splitters | 智能分块，支持自定义分隔符 |
| **验证** | Pydantic (schemas) | 结构化输出校验 |

**考虑的 Agent 模式**：
- **ReAct**：推理 + 行动，用于解析 Agent
- **工具调用**：生成、查询、修改操作集中管理
- **多轮對話**：审查修正的迭代

---

## 4. RAG 知识库 / 向量存储

| 组件 | 选型 | 理由 |
|------|------|------|
| **向量数据库** | PostgreSQL + pgvector | 单一数据库，减少运维复杂度；支持混合搜索（向量+关键词） |
| **向量维度** | 1024 | 使用 BGE-large 或相当模型 |
| **相似度指标** | COSINE 或 L2 | COSINE 更适合高维文本 |
| **索引方法** | IVFFlat (HNSW 可选) | IVFFlat 快，召回率 ≥95%；大规模用 HNSW |
| **检索策略** | BM25 + 向量混合 | 关键词精准 + 语义相似，互补 |
| **重排序** | Cross-Encoder | LocalAI 本地部署 或 调用 API（Cohere） |
| **文本处理** | LangChain TextSplitter | 支持滑动窗口分块 |
| **元数据存储** | JSONB (PostgreSQL) | 灵活扩展（文件名、页码、来源等） |

**RAG Pipeline**：
```
输入 query 
  → BM25 初排（快速召回）
  → 向量相似度检索（top-20）
  → Cross-Encoder 重排（top-5）
  → 返回上下文给 LLM
```

---

## 5. 文档处理 / 文本提取

| 组件 | 选型 | 理由 |
|------|------|------|
| **PDF 提取** | pypdf + pdfplumber | pypdf 快速；pdfplumber 提取表格/布局信息 |
| **Word 解析** | python-docx | 保留样式，支持编程修改 |
| **文本处理** | jieba (分词) + SnowNLP (情感) | 中文处理基础库 |
| **生成 Word** | python-docx | 一站式生成、格式控制 |
| **Word → PDF** | python-pptx/LibreOffice CLI | 可选（后续功能） |

---

## 6. 基础设施 / 数据持久化

| 组件 | 选型 | 理由 |
|------|------|------|
| **主数据库** | PostgreSQL 15+ | 成熟稳定，pgvector 扩展，JSONB 支持半结构化数据 |
| **缓存** | Redis 7.x | 会话、速率限制、Celery broker、实时通知 |
| **对象存储** | MinIO 或 S3 Compatible | 自建便宜，S3 兼容便于迁移；存原始文件、生成的 DOCX |
| **消息队列** | Redis（轻量）或 RabbitMQ（可选扩展） | MVP 阶段 Redis 足够 |
| **容器编排** | Docker Compose | 开发 ✓；生产考虑 K8s（后续） |
| **持久化卷** | Docker volumes | 数据库、MinIO 数据卷 |

**docker-compose 容器**：
- PostgreSQL + pgvector
- Redis
- MinIO
- Milvus（可选，超大规模 RAG 时）

---

## 7. 开发工具 / 测试 / CI-CD

| 组件 | 选型 | 理由 |
|------|------|------|
| **单元测试** | pytest + pytest-asyncio | FastAPI 异步测试标准 |
| **集成测试** | pytest fixtures + TestClient | FastAPI 内置支持 |
| **Mock LLM** | unittest.mock 或 responses | 加速测试，减少 API 调用成本 |
| **代码质量** | black + flake8 + mypy | 代码格式、风格检查、静态类型 |
| **依赖管理** | pip + requirements.txt 或 Poetry | Poetry 更现代（可选） |
| **版本控制** | Git + GitHub/GitLab | 标准流程 |
| **CI/CD** | GitHub Actions 或 GitLab CI | 自动化测试 + 部署 |
| **API 文档** | FastAPI 自动生成 (Swagger/Redoc) | `/docs` 和 `/redoc` |
| **调试** | Python debugger + VS Code | 标准配置 |

---

## 8. 部署 / 运维

| 组件 | 选型 | 理由 |
|------|------|------|
| **开发环境** | Docker Compose 本地 | 完整堆栈一键启动 |
| **测试环境** | Docker + 云服务（阿里云/腾讯云） | 接近生产 |
| **生产环境（初期）** | Docker + Nginx（反向代理） + 单机 | 成本低 |
| **生产环境（扩展）** | K8s + Helm + 云服务 | 自动扩容、高可用 |
| **日志收集** | ELK Stack 或 Loki（可选） | 结构化日志聚合 |
| **监控告警** | Prometheus + Grafana（可选） | 性能指标可视化 |
| **SSL/TLS** | Let's Encrypt + Certbot | 免费自动化证书 |

---

## 9. 完整依赖清单（requirements.txt）

```
# FastAPI
fastapi==0.109.0
uvicorn[standard]==0.27.0
python-multipart==0.0.6

# 数据库与 ORM
sqlalchemy==2.0.25
psycopg2-binary==2.9.9
alembic==1.13.1

# AI / Agent
langgraph==0.0.30
langchain==0.1.10
langchain-community==0.0.20
langchain-openai==0.0.8

# LLM 调用
openai==1.3.9
requests==2.31.0

# 向量模型与检索
sentence-transformers==2.2.2
scikit-learn==1.3.2
numpy==1.24.3

# 文档处理
pypdf==4.0.1
pdfplumber==0.10.3
python-docx==0.8.11

# 异步与缓存
redis==5.0.1
celery==5.3.4

# 数据验证
pydantic==2.5.3
pydantic-settings==2.1.0

# 工具
python-dotenv==1.0.0
structlog==24.1.0
jieba==0.42.1

# MinIO
minio==7.2.0

# 测试
pytest==7.4.3
pytest-asyncio==0.23.1
httpx==0.25.2

# 开发
black==23.12.1
flake8==6.1.0
mypy==1.7.1
```

---

## 10. 技术栈决策矩阵

| 维度 | 关键因素 | 选型理由 |
|------|---------|---------|
| **开发速度** | 快速原型 | FastAPI + React 生态成熟，减少重复造轮子 |
| **中文支持** | NLP 能力 | BGE 向量模型 + jieba 分词，专为中文优化 |
| **成本控制** | 基础设施 | PostgreSQL + MinIO 自建，少花钱；API 调用按量计费 |
| **扩展性** | 多源 LLM | LangChain 统一接口，轻松切换 DeepSeek / 通义千问 |
| **可靠性** | 容错机制** | Redis checkpointer 保存 Agent 状态，支持恢复 |
| **维护成本** | 团队学习曲线 | Python + JavaScript 常见语言，文档完善 |

---

## 11. MVP 阶段（第 1–8 周）推荐配置

✅ **确定使用**：
- 后端：FastAPI + PostgreSQL + pgvector + Redis + MinIO
- Agent：LangGraph + DeepSeek API
- RAG：BGE-large-zh-v1.5 本地向量化
- 前端：React 18 + Ant Design（可选延后到第 8 周）
- 部署：Docker Compose 本地开发

⏸️ **暂不实现**（保留接口预留）：
- Kubernetes 编排
- 高级监控告警（Prometheus / ELK）
- 多区域部署

---

## 12. 后续扩展路线（V1.1+）

- [ ] **商务系统**：引入定价引擎、报价策略分析
- [ ] **模拟评分**：集成标会评标规则库
- [ ] **工作流审批**：多部门协作、任務追踪
- [ ] **数据分析**：标书对标、中标率趋势
- [ ] **移动端**：React Native 或 Flutter 应用
- [ ] **企业 SSO**：集成 LDAP / OAuth 2.0

---

## 13. 环境变量模板（.env）

```bash
# 数据库
DATABASE_URL=postgresql://tenderuser:tenderpwd@localhost:5432/tenderdb
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=tenderdb
POSTGRES_USER=tenderuser
POSTGRES_PASSWORD=tenderpwd

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_PASSWORD=

# MinIO
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_API_URL=http://localhost:9000
MINIO_CONSOLE_URL=http://localhost:9001

# LLM API
DEEPSEEK_API_KEY=sk_xxxx
QIANWEN_API_KEY=sk_xxxx
OPENAI_API_KEY=sk_xxxx (备用)

# Embedding 模型
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5

# 应用配置
DEBUG=true
LOG_LEVEL=INFO
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
```

---

