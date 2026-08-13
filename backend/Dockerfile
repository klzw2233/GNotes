# GNotes 后端：FastAPI + uvicorn
FROM python:3.12-slim

WORKDIR /app

# 系统依赖：sqlite3 便于运维查库；runuser 用于入口脚本降权
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /app/data \
    && useradd -r gnotes \
    && chown -R gnotes:gnotes /app

ENV PYTHONPATH=/app
EXPOSE 8000

# 以 root 进入，entrypoint 修正数据卷权限后降权到 gnotes
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
