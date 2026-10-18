# 阶段一：构建前端
# Vite 的 outDir 是 ../server/webroot，在 /web 里构建产物会落到 /server/webroot
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY web/ ./
RUN npm run build

# 阶段二：运行时
FROM python:3.13-slim
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    FTS_HOST=0.0.0.0 \
    FTS_PORT=8000 \
    FTS_CONFIG=/app/config.yaml
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ ./server/
# 应用配置必须存在于 FTS_CONFIG 指向的位置（数据目录由卷挂载，不放配置）
COPY server/config.yaml ./config.yaml
COPY --from=web /server/webroot/ ./server/webroot/

RUN mkdir -p /app/data && chown -R 1000:1000 /app
USER 1000

VOLUME ["/app/data"]
EXPOSE 8000

CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "4", \
     "-b", "0.0.0.0:8000", "--timeout", "120", "server.app:app"]
