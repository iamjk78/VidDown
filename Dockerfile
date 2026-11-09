FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIDDOWN_DATA=/data \
    VIDDOWN_DOWNLOAD_DIR=/downloads \
    VIDDOWN_HOST=0.0.0.0 \
    VIDDOWN_DOCKER=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Europe/Prague \
    PUID=1000 \
    PGID=1000

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tzdata ca-certificates util-linux passwd \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && python -m playwright install --with-deps chromium-headless-shell \
 && chmod -R a+rX /ms-playwright \
 && rm -rf /var/lib/apt/lists/* /root/.cache

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data", "/downloads"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/session', timeout=4)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
