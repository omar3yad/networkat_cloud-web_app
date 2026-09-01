FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Create a non-root user that matches the host's devteam GID ───────────────
# APP_GID must match the GID of the 'devteam' group on the host
# (verify with: getent group devteam → devteam:x:1002:...)
# This ensures files written inside the container are owned by the same
# numeric GID that the host's devteam members use, so volume-mounted
# directories remain group-writable without manual chown on the host.
ARG APP_GID=1002
ARG APP_UID=1001

RUN groupadd -g ${APP_GID} devteam && \
    useradd -u ${APP_UID} -g devteam -m -s /bin/sh appuser

# ── Application setup ────────────────────────────────────────────────────────
WORKDIR /app

# Install Python dependencies first (leverages Docker layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Hand ownership of /app to appuser:devteam so the non-root process
# can write migrations, __pycache__, etc. without permission errors.
# g+rwX sets group read/write on files and execute only on directories.
RUN chown -R appuser:devteam /app && \
    chmod -R g+rwX /app

# ── Runtime config ───────────────────────────────────────────────────────────
COPY supervisord.conf /etc/supervisor/conf.d/web_app.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000 8097 8098

ENTRYPOINT ["/entrypoint.sh"]