# syntax=docker/dockerfile:1

# --- stage 1: build the React SPA ---
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- stage 2: python runtime serving API + built SPA ---
FROM python:3.11-slim
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir . && mkdir -p /data

COPY --from=frontend /fe/dist ./static

ENV TROVE_DB_PATH=/data/trove.db \
    TROVE_STATIC_DIR=/app/static \
    TROVE_ENRICH_MODEL=claude-haiku-4-5

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
