# syntax=docker/dockerfile:1
# fallcha-tools service. Build context is the tools/ directory:
#   docker build -t fallcha-tools tools/
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python -m venv "$VIRTUAL_ENV"

WORKDIR /src
COPY pyproject.toml ./
COPY fallcha_tools ./fallcha_tools
RUN --mount=type=cache,target=/root/.cache/uv uv pip install .

FROM python:3.13-slim

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin tools
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER tools
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "fallcha_tools.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
