# NAMOA runtime image.
#
# The image contains only the application package, runtime configuration,
# Python dependencies, FFmpeg, and the process supervisor. Development
# material such as .ai/, docs/, scripts/, tests/, data/, logs/, and .git/
# is excluded by .dockerignore.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CONFIG_HOME=/config \
    NAMOA_PREVIEW_DIR=/data/previews

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates \
      tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config

RUN groupadd --gid 1000 namoa \
 && useradd --uid 1000 --gid 1000 --create-home \
      --shell /usr/sbin/nologin namoa \
 && mkdir -p /data /config /app/logs \
 && chown -R namoa:namoa /app /data /config

USER namoa

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/', timeout=3)"

STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python3", "-m", "app.main", "serve", "0.0.0.0", "8080", "--db", "/data/media.db"]
