#!/usr/bin/env python3
"""Unified launcher for the xconf multi-protocol lab.

Usage:
    python3 run.py start [netconf|restconf|coreconf|client|all]
    python3 run.py stop  [netconf|restconf|coreconf|client|all]
    python3 run.py status
    python3 run.py reset [netconf|restconf|coreconf|all]

`start` launches each component as a background process and records its
PID under state/pids/. `stop` reads those PID files and terminates the
processes. `reset` restores a server's datastore to YANG defaults
*without* going over the wire (it simply rewrites the datastore file),
so it works whether or not the server is running.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
PIDS = os.path.join(STATE, "pids")
LOGS = os.path.join(STATE, "logs")

COMPONENTS = {
    "netconf":  [sys.executable, os.path.join(ROOT, "servers", "netconf_server.py")],
    "restconf": [sys.executable, os.path.join(ROOT, "servers", "restconf_server.py")],
    "coreconf": [sys.executable, os.path.join(ROOT, "servers", "coreconf_server.py")],
    "client":   [sys.executable, os.path.join(ROOT, "client", "web.py")],
}

DATASTORES = {
    "netconf":  os.path.join(STATE, "netconf.json"),
    "restconf": os.path.join(STATE, "restconf.json"),
    "coreconf": os.path.join(STATE, "coreconf.json"),
}

ORDER = ["netconf", "restconf", "coreconf", "client"]

# Web control-panel URL (must match HOST/PORT in client/web.py).
CLIENT_URL = "http://127.0.0.1:8080"


def _pidfile(name: str) -> str:
    return os.path.join(PIDS, f"{name}.pid")


def _read_pid(name: str):
    path = _pidfile(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(name: str) -> None:
    os.makedirs(PIDS, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    existing = _read_pid(name)
    if existing and _is_running(existing):
        print(f"[{name}] already running (pid {existing})")
        if name == "client":
            print(f"[client] web interface: {CLIENT_URL}")
        return
    logf = open(os.path.join(LOGS, f"{name}.log"), "a")
    proc = subprocess.Popen(
        COMPONENTS[name],
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    with open(_pidfile(name), "w") as fh:
        fh.write(str(proc.pid))
    print(f"[{name}] started (pid {proc.pid}), log: state/logs/{name}.log")
    if name == "client":
        print(f"[client] web interface: {CLIENT_URL}")


def stop(name: str) -> None:
    pid = _read_pid(name)
    if not pid:
        print(f"[{name}] no pid file; not running")
        return
    if _is_running(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(0.3)
        print(f"[{name}] stopped (pid {pid})")
    else:
        print(f"[{name}] was not running (stale pid {pid})")
    try:
        os.remove(_pidfile(name))
    except OSError:
        pass


def status() -> None:
    print("component   state      pid")
    print("---------   --------   -----")
    for name in ORDER:
        pid = _read_pid(name)
        if pid and _is_running(pid):
            print(f"{name:<10}  running    {pid}")
        else:
            print(f"{name:<10}  stopped    -")


def reset(name: str) -> None:
    # Import here so `run.py` works even if deps for servers aren't loaded.
    sys.path.insert(0, ROOT)
    from common.datastore import Datastore  # noqa: WPS433

    path = DATASTORES[name]
    ds = Datastore(path)
    ds.reset()
    print(f"[{name}] datastore reset to YANG defaults ({path})")


def _resolve(target: str, universe):
    if target == "all":
        return list(universe)
    if target in universe:
        return [target]
    print(f"unknown target '{target}'. choices: {', '.join(universe)} | all")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else "all"

    if cmd == "start":
        for name in _resolve(target, ORDER):
            start(name)
            time.sleep(0.4)  # small stagger so servers bind before client
    elif cmd == "stop":
        for name in reversed(_resolve(target, ORDER)):
            stop(name)
    elif cmd == "status":
        status()
    elif cmd == "reset":
        for name in _resolve(target, list(DATASTORES)):
            reset(name)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
