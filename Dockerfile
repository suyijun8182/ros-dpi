# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端运行时 ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Asia/Shanghai
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt \
    # gosu 用于降权运行；Web 和 UDP 端口都大于 1024，非 root 也能监听
    && apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 1000 rosdpi
COPY backend/app ./app
COPY --from=frontend /fe/dist ./frontend_dist
RUN mkdir -p /app/data
VOLUME ["/app/data"]
# Web / IPFIX / TZSP-DNS
EXPOSE 8080/tcp 2055/udp 37008/udp
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"HTTP_PORT\",\"8080\")}/api/health',timeout=4)"
# 以 root 启动时先把数据目录交给 rosdpi 再降权运行；compose 里显式指定 user: 时按原方式运行
CMD ["sh", "-c", "if [ \"$(id -u)\" = 0 ]; then chown -R rosdpi:rosdpi /app/data && exec gosu rosdpi sh -c 'exec uvicorn app.main:app --host 0.0.0.0 --port ${HTTP_PORT:-8080} --no-access-log'; else exec uvicorn app.main:app --host 0.0.0.0 --port ${HTTP_PORT:-8080} --no-access-log; fi"]
