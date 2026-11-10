"""Flask web app serving the HTML control panel for the unified client.

The browser POSTs {protocol, action, hostname} to /api/command; this
backend translates that into the appropriate NETCONF / RESTCONF /
CORECONF call and returns JSON that the page renders.
"""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, render_template, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client import protocol_clients  # noqa: E402

HOST = "127.0.0.1"
PORT = 8080

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/command")
def command():
    body = request.get_json(silent=True) or {}
    protocol = body.get("protocol")
    action = body.get("action")
    hostname = body.get("hostname")

    if protocol not in protocol_clients.CLIENTS:
        return jsonify({"ok": False, "error": f"unknown protocol {protocol!r}"}), 400
    if action not in ("get", "set", "reset"):
        return jsonify({"ok": False, "error": f"unknown action {action!r}"}), 400

    try:
        result = protocol_clients.do(protocol, action, hostname)
        return jsonify({"ok": True, "protocol": protocol, "action": action, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "protocol": protocol, "action": action, "error": str(exc)}), 502


def main() -> None:
    print(f"[client] control panel at http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
