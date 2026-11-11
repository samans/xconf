"""RESTCONF server (RFC 8040 style) implemented with Flask.

Exposes the `example` YANG module (a keyed list) over HTTP/JSON:

  GET    /restconf/data/example:system
         -> {"example:system": [{"name": "...", "hostname": "..."}, ...]}

  POST   /restconf/data/example:system
         body: {"example:system": [{"name": "sys1", "hostname": "h1"}]}
         -> 201 Created   (add instance)

  DELETE /restconf/data/example:system=<name>
         -> 204 No Content   (remove instance)

  PUT    /restconf/data/example:system=<name>/hostname
         body: {"example:hostname": "new-name"}
         -> 204 No Content   (set leaf on an instance)

  POST   /restconf/operations/example:reset-datastore
         -> {"example:output": {"status": "reset"}}  (vendor action)

List keys are encoded in the URI as `example:system=<key>` per RFC 8040
section 3.5.3. The JSON encoding follows RFC 7951 (module-qualified
member names, lists as arrays). See FULL_IMPLEMENTATION.md for gaps
versus a compliant server.
"""

from __future__ import annotations

import os
import sys

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.datastore import Datastore, InstanceExists, InstanceNotFound  # noqa: E402

HOST = "127.0.0.1"
PORT = 8400
STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state",
    "restconf.json",
)

datastore = Datastore(STATE_FILE)
app = Flask(__name__)


def _error(status, tag, message):
    return (
        jsonify(
            {
                "ietf-restconf:errors": {
                    "error": [
                        {
                            "error-type": "application",
                            "error-tag": tag,
                            "error-message": message,
                        }
                    ]
                }
            }
        ),
        status,
    )


@app.get("/restconf/yang-library-version")
def yang_library_version():
    return jsonify({"ietf-restconf:yang-library-version": "2019-01-04"})


@app.get("/restconf/data/example:system")
def get_system():
    """Retrieve all instances of the list."""
    return jsonify(datastore.get()), 200


@app.get("/restconf/data/example:system=<name>")
def get_instance(name):
    try:
        entry = datastore.get_instance(name)
    except InstanceNotFound:
        return _error(404, "invalid-value", f"instance '{name}' not found")
    return jsonify({"example:system": [entry]}), 200


@app.post("/restconf/data/example:system")
def add_instance():
    """Create a new list instance from a posted {'example:system': [ {...} ]}."""
    payload = request.get_json(silent=True) or {}
    entries = payload.get("example:system")
    if not isinstance(entries, list) or not entries:
        return _error(400, "missing-attribute", "expected member 'example:system' as a non-empty list")
    entry = entries[0]
    name = entry.get("name")
    hostname = entry.get("hostname")
    if not isinstance(name, str) or not name:
        return _error(400, "missing-attribute", "list entry requires a non-empty 'name' key")
    try:
        created = datastore.add_instance(name, hostname)
    except InstanceExists:
        return _error(409, "resource-denied", f"instance '{name}' already exists")
    except ValueError as exc:
        return _error(400, "invalid-value", str(exc))
    resp = jsonify({"example:system": [created]})
    resp.headers["Location"] = f"/restconf/data/example:system={name}"
    return resp, 201


@app.delete("/restconf/data/example:system=<name>")
def delete_instance(name):
    try:
        datastore.remove_instance(name)
    except InstanceNotFound:
        return _error(404, "invalid-value", f"instance '{name}' not found")
    return ("", 204)


@app.put("/restconf/data/example:system=<name>/hostname")
def put_hostname(name):
    payload = request.get_json(silent=True) or {}
    if "example:hostname" not in payload:
        return _error(400, "missing-attribute", "expected member 'example:hostname'")
    value = payload["example:hostname"]
    if not isinstance(value, str):
        return _error(400, "invalid-value", "hostname must be a string")
    try:
        datastore.set_hostname(name, value)
    except InstanceNotFound:
        return _error(404, "invalid-value", f"instance '{name}' not found")
    return ("", 204)


@app.post("/restconf/operations/example:reset-datastore")
def reset_datastore():
    datastore.reset()
    return jsonify({"example:output": {"status": "reset"}}), 200


def main() -> None:
    print(f"[restconf] listening on http://{HOST}:{PORT}/restconf")
    print(f"[restconf] datastore: {STATE_FILE}")
    app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
