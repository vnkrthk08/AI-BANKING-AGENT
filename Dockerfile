FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /app
RUN useradd --create-home --uid 10001 kural
COPY pyproject.toml ./
COPY app ./app
COPY kural ./kural
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir ".[postgres]"
USER kural
EXPOSE 8000
# Run `alembic upgrade head` as a release step before starting new API/worker containers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
