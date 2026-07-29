# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.title="crypto-bot" \
      org.opencontainers.image.description="Telegram-бот: SSH-ключи, хеши, X.509" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    HEALTHCHECK_FILE=/tmp/bot-healthy

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin botuser

COPY --chown=botuser:botuser app/ ./app/

USER botuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-m", "app.health"]

STOPSIGNAL SIGTERM

CMD ["python", "-m", "app"]
