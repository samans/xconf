"""Shared datastore logic for the xconf multi-protocol lab.

All three servers (NETCONF, RESTCONF, CORECONF) model the same simple
YANG module `example`:

    container system {
        leaf hostname { type string; default "default-host"; }
    }

The datastore is persisted to a small JSON file per server so that state
survives across requests within a running server process, and so that a
"reset" has observable, uniform semantics across protocols.

The canonical in-memory representation is a plain Python dict shaped like
the YANG data tree using module-qualified names, i.e.:

    {"example:system": {"hostname": "<value>"}}

Each protocol server serializes this canonical form into its own wire
format (XML for NETCONF, JSON for RESTCONF, CBOR for CORECONF).
"""

from __future__ import annotations

import json
import os
import threading

# The YANG default for example:system/hostname.
DEFAULT_HOSTNAME = "default-host"

MODULE_NAME = "example"
CONTAINER = "system"
LEAF = "hostname"


def default_config() -> dict:
    """Return a fresh canonical datastore populated with YANG defaults."""
    return {f"{MODULE_NAME}:{CONTAINER}": {LEAF: DEFAULT_HOSTNAME}}


class Datastore:
    """A tiny, thread-safe, file-backed datastore for one server.

    Parameters
    ----------
    path:
        Path to the JSON file that persists this datastore.
    """

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.RLock()
        self._load()

    # -- persistence ---------------------------------------------------

    def _load(self) -> None:
        with self._lock:
            if os.path.exists(self._path):
                try:
                    with open(self._path, "r", encoding="utf-8") as fh:
                        self._data = json.load(fh)
                        return
                except (json.JSONDecodeError, OSError):
                    pass
            self._data = default_config()
            self._save()

    def _save(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)

    # -- public API ----------------------------------------------------

    def get(self) -> dict:
        """Return a deep copy of the full canonical datastore."""
        with self._lock:
            return json.loads(json.dumps(self._data))

    def get_hostname(self) -> str:
        with self._lock:
            return self._data[f"{MODULE_NAME}:{CONTAINER}"][LEAF]

    def set_hostname(self, value: str) -> None:
        """Set example:system/hostname to `value`."""
        if not isinstance(value, str):
            raise ValueError("hostname must be a string")
        with self._lock:
            self._data[f"{MODULE_NAME}:{CONTAINER}"][LEAF] = value
            self._save()

    def reset(self) -> dict:
        """Reset the datastore back to YANG defaults and return it."""
        with self._lock:
            self._data = default_config()
            self._save()
            return self.get()
