# syntax=docker/dockerfile:1

# xconf — one client, three NETCONF-family servers.
# A small, self-contained lab image: NETCONF (TCP), RESTCONF (HTTP),
# CORECONF (CoAP/UDP), and a web control panel, all in one container.

FROM python:3.12-slim

# Keep Python output unbuffered so logs stream, and don't write .pyc.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source. (.dockerignore keeps out state/ and
# __pycache__/ so the image stays clean.)
COPY . .

RUN chmod +x docker-entrypoint.sh

# Web UI binds to 0.0.0.0 inside the container so the mapped port works.
ENV XCONF_WEB_HOST=0.0.0.0

# Ports: 8080 web UI, 8300 NETCONF (TCP), 8400 RESTCONF (TCP),
# 5683 CORECONF (CoAP/UDP).
EXPOSE 8080/tcp 8300/tcp 8400/tcp 5683/udp

# Basic liveness check against the web UI.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/').read()" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
