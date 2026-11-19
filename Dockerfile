# AI 自动交易系统（模拟）单服务镜像：前端构建产物由后端同进程托管。
# 用法示例（Render / Fly.io / 任意 VPS 均可）：
#   docker build -t ai-trading .
#   docker run -p 8000:8000 -v ai-trading-data:/data \
#     -e AUTH_PASSWORD_HASH=... -e SESSION_SECRET=... -e REQUIRE_AUTH=1 -e COOKIE_SECURE=1 \
#     ai-trading
# 环境变量清单见 docs/部署方案.md。数据文件在 /data/data.db（挂卷才不会丢）。

FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/data/data.db \
    FRONTEND_DIST=/app/frontend/dist
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
