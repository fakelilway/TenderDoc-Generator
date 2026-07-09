# TenderDoc 后端镜像（FastAPI + AI 生成 + OCR + 向量检索）
# 基础镜像固定 Python 3.11，与 .python-version(3.11.15) 一致。
FROM python:3.11-slim

# 国内构建更稳:pip 默认走清华镜像;需要用官方源时构建加 --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 系统库:
#   libgl1 / libglib2.0-0  -> rapidocr(opencv) 运行所需
#   libgomp1               -> onnxruntime 运行所需
#   curl                   -> 容器健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖(利用镜像层缓存:代码改动不必重装依赖)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 再拷后端代码
COPY . /app

# 生成过程的临时文件目录(挂载卷持久化,见 docker-compose)
RUN mkdir -p /app/temp
ENV TEMP_DIR=/app/temp

EXPOSE 8000

# 生产模式:不加 --reload(生成跑在后台线程,热重载会杀掉在跑的生成)
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
