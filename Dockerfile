# syntax=docker/dockerfile:1

# ---------- 前端构建 ----------
FROM node:20-alpine AS web-builder
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm config set registry "$NPM_REGISTRY" \
    && (npm ci --no-audit --no-fund || npm install --no-audit --no-fund)
COPY frontend/ ./
RUN npm run build

# ---------- 后端运行 ----------
FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    STRMACTION_DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r /app/requirements.txt

COPY backend /app/backend
COPY --from=web-builder /web/dist /app/static
RUN mkdir -p /data/images

WORKDIR /app/backend
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
