# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci || npm install
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端运行时 ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Shanghai
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /fe/dist ./frontend_dist
RUN mkdir -p /app/data
VOLUME ["/app/data"]
# Web / IPFIX / TZSP-DNS
EXPOSE 8080/tcp 2055/udp 37008/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"HTTP_PORT\",\"8080\")}/api/health',timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${HTTP_PORT:-8080} --no-access-log"]
