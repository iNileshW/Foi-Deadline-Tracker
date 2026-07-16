# Small, reproducible image for the FOI tracker.
# Runs under gunicorn — the Flask dev server is not production-safe.

FROM python:3.13-slim

# System packages: nothing beyond what python:slim provides. curl is
# only added for HEALTHCHECK; keep the image small otherwise.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. Fixed UID/GID so bind-mounted volumes behave
# predictably on the host.
RUN groupadd --gid 10001 foi \
    && useradd  --uid 10001 --gid foi --home /home/foi --create-home --shell /usr/sbin/nologin foi

WORKDIR /app

# Install deps first so the layer cache does its job.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. Copy explicitly rather than `COPY . .` so we do
# not accidentally ship .git, backups/, or the SQLite file.
COPY app.py auth.py audit.py backup.py restore.py create_user.py \
     deadlines.py seed.py users.py bank_holidays.json ./
COPY templates ./templates

# Data lives on a mounted volume. Own it so the non-root user can
# read and write.
RUN mkdir -p /data && chown -R foi:foi /data /app
ENV FOI_DB=/data/foi.db
ENV PORT=8080
EXPOSE 8080

USER foi

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# `--workers 2` is a starting point for six caseworkers; tune with
# the WEB_CONCURRENCY env var if traffic grows.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-2} --access-logfile - --error-logfile - app:app"]
