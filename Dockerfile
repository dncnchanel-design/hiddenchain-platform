FROM python:3.12-slim AS production-guard

WORKDIR /workspace
COPY backend/scripts/check_production.py backend/scripts/check_production.py
COPY Dockerfile Dockerfile
COPY backend/Dockerfile backend/Dockerfile
COPY backend/app backend/app
COPY frontend/src frontend/src
COPY frontend/.dockerignore frontend/.dockerignore
COPY docker-compose.production.yml docker-compose.production.yml
COPY .gitignore .gitignore
COPY .dockerignore .dockerignore
COPY render.yaml render.yaml
RUN python backend/scripts/check_production.py && touch /production-guard-passed

FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build:production

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /app
COPY --from=production-guard /production-guard-passed /tmp/production-guard-passed
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/scripts/provision_production_agents.py ./scripts/provision_production_agents.py
COPY policy ./policy
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist
RUN groupadd --system app \
    && useradd --system --gid app --no-create-home app \
    && mkdir -p /app/runtime /app/app/runtime/vault \
    && chown -R app:app /app/runtime /app/app/runtime

EXPOSE 8000
USER app
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
