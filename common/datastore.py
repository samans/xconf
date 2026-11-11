"""Shared datastore logic for the xconf multi-protocol lab.

All three servers (NETCONF, RESTCONF, CORECONF) model the same simple
YANG module `example`:

    list system {
        key "name";
        leaf name { type string; }
        leaf hostname { type string; default "default-host"; }
    }

The datastore is persisted to a small JSON file per server so that state
survives across requests within a running server process, and so that a
"reset" has observable, uniform semantics across protocols.

The canonical in-memory representation is a plain Python dict shaped like
the YANG data tree using module-qualified names, with the list rendered
as a JSON array (RFC 7951), i.e.:

    {"example:system": [
        {"name": "sys1", "hostname": "router-1"},
        {"name": "sys2", "hostname": "router-2"}
    ]}

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
LIST = "system"
KEY = "name"
LEAF = "hostname"

LIST_KEY = f"{MODULE_NAME}:{LIST}"


def default_config() -> dict:
    """Return a fresh canonical datastore.

    The list starts with a single seeded instance so the UI has something
    to show and GET/SET behave out of the box.
    """
    return {LIST_KEY: [{KEY: "default", LEAF: DEFAULT_HOSTNAME}]}


class InstanceNotFound(KeyError):
    """Raised when an operation references a non-existent instance key."""


class InstanceExists(KeyError):
    """Raised when adding an instance whose key already exists."""


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
                        # Migrate an older singleton-container file if present.
                        self._migrate()
                        return
                except (json.JSONDecodeError, OSError):
                    pass
            self._data = default_config()
            self._save()

    def _migrate(self) -> None:
        """Upgrade a legacy {'example:system': {...}} dict into a list."""
        node = self._data.get(LIST_KEY)
        if isinstance(node, dict):
            self._data[LIST_KEY] = [
                {KEY: "default", LEAF: node.get(LEAF, DEFAULT_HOSTNAME)}
            ]
            self._save()
        elif node is None:
            self._data = default_config()
            self._save()

    def _save(self) -> None:
        with self._lock:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)

    def _instances(self) -> list:
        return self._data.setdefault(LIST_KEY, [])

    def _find(self, name: str):
        for entry in self._instances():
            if entry.get(KEY) == name:
                return entry
        return None

    # -- public API ----------------------------------------------------

    def get(self) -> dict:
        """Return a deep copy of the full canonical datastore."""
        with self._lock:
            return json.loads(json.dumps(self._data))

    def list_names(self) -> list:
        """Return the list of instance keys in order."""
        with self._lock:
            return [entry.get(KEY) for entry in self._instances()]

    def get_instance(self, name: str) -> dict:
        with self._lock:
            entry = self._find(name)
            if entry is None:
                raise InstanceNotFound(name)
            return dict(entry)

    def add_instance(self, name: str, hostname: str | None = None) -> dict:
        """Create a new instance. Raises InstanceExists if the key is taken."""
        if not isinstance(name, str) or not name:
            raise ValueError("instance name must be a non-empty string")
        with self._lock:
            if self._find(name) is not None:
                raise InstanceExists(name)
            entry = {
                KEY: name,
                LEAF: hostname if isinstance(hostname, str) and hostname else DEFAULT_HOSTNAME,
            }
            self._instances().append(entry)
            self._save()
            return dict(entry)

    def remove_instance(self, name: str) -> None:
        with self._lock:
            instances = self._instances()
            for i, entry in enumerate(instances):
                if entry.get(KEY) == name:
                    del instances[i]
                    self._save()
                    return
            raise InstanceNotFound(name)

    def set_hostname(self, name: str, value: str) -> dict:
        """Set hostname on an existing instance `name`."""
        if not isinstance(value, str):
            raise ValueError("hostname must be a string")
        with self._lock:
            entry = self._find(name)
            if entry is None:
                raise InstanceNotFound(name)
            entry[LEAF] = value
            self._save()
            return dict(entry)

    def reset(self) -> dict:
        """Reset the datastore back to YANG defaults and return it."""
        with self._lock:
            self._data = default_config()
            self._save()
            return self.get()
