#!/usr/bin/env bash
#
# Container entrypoint for the xconf lab.
#
# Starts the three protocol servers in the background, then runs the web
# client in the foreground so the container stays alive for as long as the
# control panel is serving. On SIGTERM/SIGINT (docker stop), the servers
# are shut down cleanly.
set -euo pipefail

cd /app

echo "[entrypoint] starting NETCONF, RESTCONF, CORECONF servers..."
python3 run.py start netconf
python3 run.py start restconf
python3 run.py start coreconf

# Expose the web UI outside the container.
export XCONF_WEB_HOST="${XCONF_WEB_HOST:-0.0.0.0}"

cleanup() {
  echo "[entrypoint] stopping servers..."
  python3 run.py stop netconf  || true
  python3 run.py stop restconf || true
  python3 run.py stop coreconf || true
}
trap cleanup EXIT INT TERM

echo "[entrypoint] starting web client in foreground (http://localhost:8080)"
# Run the web app in the foreground; this is the process that keeps the
# container running.
exec python3 client/web.py
