# Multi-stage build: React UI + Fastify TS API + Python eval_runner worker
FROM node:22-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM node:22-slim AS api-build
WORKDIR /app/api
COPY api/package.json api/package-lock.json* ./
RUN npm install
COPY api/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000 \
    HOST=0.0.0.0 \
    EVAL_ROOT_DIR=/app \
    EVAL_PYTHON_BIN=/usr/local/bin/python3

COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY eval_runner/ ./eval_runner/
RUN pip install --no-cache-dir .

COPY models.yaml ./
COPY configs/ ./configs/
COPY skills/ ./skills/
COPY tasks/ ./tasks/
COPY calibration/ ./calibration/

COPY --from=api-build /app/api/dist ./api/dist
COPY --from=api-build /app/api/node_modules ./api/node_modules
COPY --from=api-build /app/api/package.json ./api/package.json
COPY --from=web-build /app/web/dist ./web/dist

EXPOSE 3000
CMD ["node", "api/dist/server.js"]
