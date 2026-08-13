# GNotes 后端：FastAPI + uvicorn
FROM python:3.12-slim

WORKDIR /app

# 系统依赖（sqlite3 仅用于运维查库，非运行必需，但便于调试）
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pytest.ini ./pytest.ini
COPY tests ./tests

# 数据目录（SQLite 文件由卷挂载到此）
RUN mkdir -p /app/data

# 非 root 用户运行
RUN useradd -r gnotes && chown -R gnotes:gnotes /app
USER gnotes

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
