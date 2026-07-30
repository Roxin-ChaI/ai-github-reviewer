FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/

RUN python -m pip install --no-cache-dir .

USER 65532:65532

ENTRYPOINT ["ai-github-reviewer"]
