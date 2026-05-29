# TenderDoc-Generator 环境搭建指南 (setup.md)

本文档用于帮助开发者在本地环境中快速搭建 TenderDoc-Generator 的完整开发环境。

---

## 目录

1. [前置要求](#前置要求)
2. [基础服务（Docker）](#基础服务docker)
3. [后端环境配置](#后端环境配置)
4. [环境变量配置](#环境变量配置)
5. [知识库准备](#知识库准备)
6. [环境验证](#环境验证)
7. [常见问题](#常见问题)

---

## 前置要求

在开始之前，请确保你的系统满足以下条件：

| 组件 | 最低要求 | 推荐配置 | 验证命令 |
|------|----------|----------|----------|
| 操作系统 | Windows 10 (WSL2) / macOS 11+ / Linux | Ubuntu 22.04 / macOS 13+ | - |
| CPU | 4 核 | 8 核 | - |
| 内存 | 8 GB | 16 GB | - |
| 磁盘 | 20 GB 可用空间 | 50 GB | - |
| Docker | 24.0+ | 最新稳定版 | `docker --version` |
| Docker Compose | 2.20+ | 2.20+ | `docker compose version` |
| Python | 3.11+ | 3.12 | `python3 --version` |
| Git | 2.30+ | 最新版 | `git --version` |

---

## 基础服务（Docker）

TenderDoc-Generator 依赖以下服务：
- **PostgreSQL + pgvector**：业务数据与向量存储
- **Redis**：缓存与 Agent 状态
- **MinIO**：对象存储（招标文件、生成文件）

### 步骤 1：克隆项目并进入目录

```bash
git clone <your-repo-url> TenderDoc-Generator
cd TenderDoc-Generator
```

### 步骤 2：编写 docker-compose.yml

在项目根目录创建 `docker-compose.yml`，内容如下：

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: tender-postgres
    environment:
      POSTGRES_DB: tenderdb
      POSTGRES_USER: tenderuser
      POSTGRES_PASSWORD: tenderpass
    ports:
      - "5432:5432"
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tenderuser -d tenderdb"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: tender-redis
    ports:
      - "6379:6379"
    volumes:
      - ./data/redis:/data
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    container_name: tender-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - ./data/minio:/data
    restart: unless-stopped
```

### 步骤 3：启动容器

```bash
# 启动所有服务（后台运行）
docker compose up -d

# 查看容器状态
docker compose ps

# 查看日志（如有异常）
docker compose logs -f
```

### 步骤 4：初始化 pgvector 扩展

PostgreSQL 容器启动后，需要手动创建 vector 扩展：

```bash
docker exec -it tender-postgres psql -U tenderuser -d tenderdb
```

在 psql 提示符下执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

验证扩展是否成功：

```bash
docker exec -it tender-postgres psql -U tenderuser -d tenderdb -c "SELECT * FROM pg_extension WHERE extname='vector';"
```

应该能看到一条记录。

---

## 后端环境配置

### 步骤 1：进入后端目录

```bash
cd backend
```

### 步骤 2：创建 Python 虚拟环境

```bash
# 使用 python3.11 或更高版本
python3 -m venv venv

# 激活虚拟环境
# Linux / macOS:
source venv/bin/activate
# Windows (cmd):
venv\Scripts\activate
# Windows (PowerShell):
venv\Scripts\Activate.ps1
```

激活后，命令行提示符会显示 `(venv)`。

### 步骤 3：安装 Python 依赖

创建 `requirements.txt`（如果尚未创建），内容如下（根据 TECH_STACK.md）：

```txt
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

执行安装：

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **注意**：
> - `sentence-transformers` 会自动安装 PyTorch CPU 版本。如果你的机器有 GPU，可以后续自行安装 CUDA 版本。
> - 国内用户如遇到镜像下载缓慢，可配置 pip 镜像源。

### 步骤 4：安装代码质量工具（可选但推荐）

为了保持代码质量，建议安装代码检查工具：

```bash
# 已在 requirements.txt 中，但也可单独安装
pip install black flake8 mypy

# 配置 black（代码格式化）
black --line-length=100 backend/

# 检查代码风格
flake8 backend/

# 类型检查
mypy backend/
```

---

## 环境变量配置

在 `backend/` 目录下创建 `.env` 文件，用于存储敏感配置和连接信息。

```bash
cp .env.example .env   # 如果存在模板，否则直接创建
```

编辑 `.env`，填入以下内容（请根据实际情况修改）。参考 TECH_STACK.md 第 13 部分：

```env
# ==================== 数据库 ====================
DATABASE_URL=postgresql://tenderuser:tenderpwd@localhost:5432/tenderdb
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=tenderdb
POSTGRES_USER=tenderuser
POSTGRES_PASSWORD=tenderpwd

# ==================== Redis ====================
REDIS_URL=redis://localhost:6379/0
REDIS_PASSWORD=

# ==================== MinIO ====================
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_API_URL=http://localhost:9000
MINIO_CONSOLE_URL=http://localhost:9001

# ==================== 大模型 API ====================
# 主选：DeepSeek (推荐，性价比高)
DEEPSEEK_API_KEY=sk_xxxx

# 备选：通义千问
QIANWEN_API_KEY=sk_xxxx

# 备选：OpenAI
OPENAI_API_KEY=sk_xxxx

# ==================== Embedding 模型 ====================
# 中文最强向量模型
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DEVICE=cpu   # 若 GPU 可用，改为 cuda

# ==================== 应用配置 ====================
DEBUG=true
LOG_LEVEL=INFO
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256

# 临时文件存储目录
TEMP_DIR=./temp
# 最大上传文件大小（MB）
MAX_FILE_SIZE=50
```

> **重要**：请将 `DEEPSEEK_API_KEY` 替换为你的真实密钥。若使用其他大模型，请相应调整。

---

## 知识库准备

在项目根目录的 `knowledge_base/` 文件夹中，放入企业相关的文档，用于 RAG 检索测试。

```bash
# 确保目录存在
mkdir -p ../knowledge_base
```

建议至少放入以下类型的文件：
- 公司资质证书扫描件（PDF）
- 过往中标技术标书（Word/PDF）
- 常用施工组织设计方案模板（Word）
- 公司业绩清单（Excel 或 Word）

**文件命名建议**：使用英文或拼音，避免特殊字符。

---

## 环境验证

我们提供一组简单的测试脚本，用于验证各组件是否正常工作。

在 `backend/` 目录下创建这些脚本并运行。

### 验证 1：PostgreSQL 连接

创建 `test_db.py`：

```python
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

try:
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )
    print("✓ PostgreSQL 连接成功")
    conn.close()
except Exception as e:
    print(f"✗ PostgreSQL 连接失败: {e}")
```

### 验证 2：Redis 连接

创建 `test_redis.py`：

```python
import redis
import os
from dotenv import load_dotenv

load_dotenv()

try:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT")),
        decode_responses=True
    )
    r.ping()
    print("✓ Redis 连接成功")
except Exception as e:
    print(f"✗ Redis 连接失败: {e}")
```

### 验证 3：MinIO 连接

创建 `test_minio.py`：

```python
from minio import Minio
import os
from dotenv import load_dotenv

load_dotenv()

try:
    client = Minio(
        os.getenv("MINIO_ENDPOINT"),
        access_key=os.getenv("MINIO_ACCESS_KEY"),
        secret_key=os.getenv("MINIO_SECRET_KEY"),
        secure=os.getenv("MINIO_SECURE", "False").lower() == "true"
    )
    bucket = os.getenv("MINIO_BUCKET")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        print(f"✓ 创建 bucket: {bucket}")
    print("✓ MinIO 连接成功")
except Exception as e:
    print(f"✗ MinIO 连接失败: {e}")
```

### 验证 4：大模型 API 调用

创建 `test_llm.py`（以 DeepSeek 为例）：

```python
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

try:
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL")
    )
    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL"),
        messages=[{"role": "user", "content": "请回复 OK"}],
        max_tokens=10
    )
    print("✓ 大模型 API 调用成功:", response.choices[0].message.content)
except Exception as e:
    print(f"✗ 大模型 API 调用失败: {e}")
```

### 验证 5：Embedding 模型加载

创建 `test_embedding.py`：

```python
from sentence_transformers import SentenceTransformer
import os
from dotenv import load_dotenv

load_dotenv()

try:
    model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
    device = os.getenv("EMBEDDING_DEVICE", "cpu")
    model = SentenceTransformer(model_name, device=device)
    emb = model.encode("测试文本")
    print(f"✓ Embedding 模型加载成功，输出维度: {len(emb)}")
except Exception as e:
    print(f"✗ Embedding 模型加载失败: {e}")
```

### 运行所有验证

确保虚拟环境已激活，然后逐个运行：

```bash
python test_db.py
python test_redis.py
python test_minio.py
python test_llm.py
python test_embedding.py
```

全部显示 `✓` 即为环境就绪。

---

## 前端环境配置（可选，MVP 第 8 周后）

待补充。参考 TECH_STACK.md 第 1 部分。

---

## 常见问题

### Q1: Docker 容器启动失败，端口被占用

**错误信息**：`port is already allocated`

**解决方法**：
- 修改 `docker-compose.yml` 中的宿主机端口，例如 `"5433:5432"`。
- 然后同步修改 `.env` 中的 `POSTGRES_PORT=5433`。

### Q2: pgvector 扩展安装失败

**现象**：执行 `CREATE EXTENSION vector` 时报错。

**解决方法**：
- 确认使用的镜像为 `pgvector/pgvector:pg16`，而非原版 PostgreSQL。
- 重启容器：`docker compose restart postgres` 后重试。

### Q3: sentence-transformers 下载模型很慢

**原因**：国内访问 HuggingFace 速度较慢。

**解决方法**：
- 设置镜像源（例如使用 hf-mirror.com）：
  ```bash
  export HF_ENDPOINT=https://hf-mirror.com
  ```
- 或者手动下载模型到本地缓存目录。

### Q4: 大模型 API 调用返回 401

**原因**：API Key 无效或未正确配置。

**解决方法**：
- 检查 `.env` 中的密钥是否正确（推荐先用 DEEPSEEK_API_KEY）。
- 确认账户余额充足。
- 验证网络能正常访问 API 域名。

### Q5: MinIO 创建 bucket 失败（权限问题）

**解决方法**：
- 检查 `.env` 中的 `MINIO_ROOT_USER` 和 `MINIO_ROOT_PASSWORD` 是否与 `docker-compose.yml` 中一致。
- 重启 MinIO 容器后重试。

### Q6: pip 依赖安装缓慢或失败

**原因**：网络问题或 PyPI 源不稳定。

**解决方法**：
- 配置清华大学 PyPI 镜像：
  ```bash
  pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
  ```
- 或者临时使用阿里镜像：
  ```bash
  pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
  ```

### Q7: SQLAlchemy / psycopg2 导入错误

**解决方法**：
- 确保 Python 3.11+ 且虚拟环境已激活。
- 重装 `psycopg2-binary`：
  ```bash
  pip install --force-reinstall psycopg2-binary==2.9.9
  ```

---

## 下一步

环境验证通过后，你可以开始开发第一个 Agent——**招标文件解析 Agent**。

开发指南请参考 `docs/agent_development.md`（待编写）。

---

**文档版本**：1.0  
**最后更新**：2026-05-29  
**维护者**：TenderDoc-Generator 团队