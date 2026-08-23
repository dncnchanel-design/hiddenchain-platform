FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8100

WORKDIR /app
COPY connector/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY connector/app ./app
RUN groupadd --system connector \
    && useradd --system --gid connector --no-create-home connector \
    && mkdir -p /app/runtime \
    && chown -R connector:connector /app/runtime

USER connector
EXPOSE 8100
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8100}"]
