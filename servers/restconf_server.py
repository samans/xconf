"""RESTCONF server (RFC 8040 style) implemented with Flask.

Exposes the `example` YANG module over HTTP/JSON:

  GET    /restconf/data/example:system
         -> {"example:system": {"hostname": "..."}}

  PUT    /restconf/data/example:system/hostname
         body: {"example:hostname": "new-name"}
         -> 204 No Content

  POST   /restconf/operations/example:reset-datastore
         -> {"example:output": {"status": "reset"}}  (vendor action)

  GET    /restconf/yang-library-version
         -> advertises the RESTCONF root (informational)

The JSON encoding follows RFC 7951 (module-qualified member names).
This is a simplified but wire-honest RESTCONF surface; see
FULL_IMPLEMENTATION.md for the gaps versus a compliant server.
"""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.datastore import Datastore  # noqa: E402

HOST = "127.0.0.1"
PORT = 8400
STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state",
    "restconf.json",
)

datastore = Datastore(STATE_FILE)
app = Flask(__name__)


@app.get("/restconf/yang-library-version")
def yang_library_version():
    return jsonify({"ietf-restconf:yang-library-version": "2019-01-04"})


@app.get("/restconf/data/example:system")
def get_system():
    return jsonify(datastore.get()), 200


@app.get("/restconf/data/example:system/hostname")
def get_hostname():
    return jsonify({"example:hostname": datastore.get_hostname()}), 200


@app.put("/restconf/data/example:system/hostname")
def put_hostname():
    payload = request.get_json(silent=True) or {}
    if "example:hostname" not in payload:
        return (
            jsonify(
                {
                    "ietf-restconf:errors": {
                        "error": [
                            {
                                "error-type": "application",
                                "error-tag": "missing-attribute",
                                "error-message": "expected member 'example:hostname'",
                            }
                        ]
                    }
                }
            ),
            400,
        )
    value = payload["example:hostname"]
    if not isinstance(value, str):
        return (
            jsonify(
                {
                    "ietf-restconf:errors": {
                        "error": [
                            {
                                "error-type": "application",
                                "error-tag": "invalid-value",
                                "error-message": "hostname must be a string",
                            }
                        ]
                    }
                }
            ),
            400,
        )
    datastore.set_hostname(value)
    return ("", 204)


@app.post("/restconf/operations/example:reset-datastore")
def reset_datastore():
    datastore.reset()
    return jsonify({"example:output": {"status": "reset"}}), 200


def main() -> None:
    print(f"[restconf] listening on http://{HOST}:{PORT}/restconf")
    print(f"[restconf] datastore: {STATE_FILE}")
    # threaded so a reset/get can overlap; debug off for clean lab output.
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
