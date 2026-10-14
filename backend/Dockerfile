# Backend image. Build context: backend/ (see compose.yaml).
#   runtime : the API (pip install of the package, non-root user)
#   dev     : lint/type/test tools; the repository is mounted at /workspace by the backend-tools service
FROM python:3.12.15-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS runtime
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --no-create-home ei_ai
USER ei_ai
EXPOSE 8000
CMD ["uvicorn", "ei_ai.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS dev
WORKDIR /workspace/backend
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"
