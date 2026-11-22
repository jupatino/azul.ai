FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app \
    && chown -R app:app /app

USER app

EXPOSE 3000

CMD ["/app/.venv/bin/gunicorn", "--bind", "0.0.0.0:3000", "--workers", "1", "--threads", "8", "--access-logfile", "-", "azul_ai.channels.slack.app:flask_app"]
