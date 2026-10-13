FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# The PoC source is bind-mounted at runtime (see compose.yaml), so code changes need no rebuild.
WORKDIR /workspace/poc

CMD ["pytest"]
