FROM python:3.12-slim AS production-guard

WORKDIR /workspace
COPY backend/scripts/check_production.py backend/scripts/check_production.py
COPY backend/Dockerfile backend/Dockerfile
COPY backend/app backend/app
COPY frontend/src frontend/src
COPY docker-compose.production.yml docker-compose.production.yml
RUN python backend/scripts/check_production.py && touch /production-guard-passed

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=production-guard /production-guard-passed /tmp/production-guard-passed
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY policy ./policy
RUN groupadd --system app \
    && useradd --system --gid app --no-create-home app \
    && mkdir -p /app/runtime/vault \
    && chown -R app:app /app/runtime /app/app/runtime

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS development
USER app

FROM runtime AS production
USER root
RUN rm -f /app/app/seed.py /app/app/test_schemas.py /app/app/routers/test_support.py
USER app
