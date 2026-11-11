# xconf — one client, three NETCONF-family servers

A small, runnable lab with **three network-management servers** speaking
three different YANG transport protocols, and a **single client** (with an
HTML control panel) that drives all three.

| Server    | Protocol | Transport        | Encoding | Port        |
|-----------|----------|------------------|----------|-------------|
| NETCONF   | RFC 6241 | plain TCP        | XML      | 8300 (TCP)  |
| RESTCONF  | RFC 8040 | HTTP             | JSON     | 8400 (TCP)  |
| CORECONF  | RFC 9254 | CoAP             | CBOR     | 5683 (UDP)  |
| Client UI | —        | HTTP (browser)   | HTML/JSON| 8080 (TCP)  |

All three servers model the **same** YANG module (`yang/example.yang`),
now a **keyed list** so you can create, select, modify, and remove
multiple instances:

```yang
list system {
  key "name";
  leaf name     { type string; }
  leaf hostname { type string; default "default-host"; }
}
```

> This is a **testing lab**, not production. The NETCONF server runs over
> plain TCP (not SSH), and CORECONF uses hand-assigned SIDs rather than a
> generated SID file. See `FULL_IMPLEMENTATION.md` for exactly what a
> standards-compliant deployment would require.

## Layout

```
xconf/
  yang/example.yang            # the shared YANG module
  common/datastore.py          # shared, file-backed, thread-safe datastore
  servers/netconf_server.py    # hand-rolled NETCONF over TCP
  servers/restconf_server.py   # Flask RESTCONF (HTTP/JSON)
  servers/coreconf_server.py   # aiocoap CORECONF (CBOR over CoAP)
  client/protocol_clients.py   # one client class per protocol
  client/web.py                # Flask app + /api/command
  client/templates/index.html  # the HTML control panel
  run.py                       # start / stop / status / reset launcher
  Dockerfile                   # single-container image of the whole lab
  docker-entrypoint.sh         # container startup (servers + web client)
  DOCKER.md                    # build / run / share the image
  state/                       # datastores, pid files, logs (created at run)
```

## Install

```bash
pip3 install -r requirements.txt
```

Dependencies: `flask`, `requests`, `cbor2`, `aiocoap`.

## Run with Docker (quickest)

The entire lab is also packaged as a single container image:

```bash
docker build -t xconf:latest .
docker run --rm -p 8080:8080 xconf:latest
# then open http://localhost:8080
```

See **`DOCKER.md`** for publishing the protocol ports, persisting state,
and sharing the image (tar file, Docker Hub, or ghcr.io).

## Run on native Windows 11 (no WSL2, no Docker)

The Python code is cross-platform, but the `run.py` launcher uses Unix
process-group calls. For native Windows there is an equivalent PowerShell
launcher, **`run.ps1`** (with a `run.cmd` wrapper for `cmd.exe`), that
mirrors the same verbs:

### Prerequisites

- **Python 3.10 or newer** (3.11 / 3.12 recommended), 64-bit. Install from
  [python.org](https://www.python.org/downloads/windows/) or the Microsoft
  Store. During the python.org install, tick **"Add python.exe to PATH"**.
  Verify in a new PowerShell:

  ```powershell
  python --version        # or:  py -3 --version
  pip --version
  ```

- **pip** (bundled with the python.org installer).
- **PowerShell 5.1** (built into Windows 11) or PowerShell 7+. No other
  runtime is required — no WSL, no Docker, no C/C++ build tools (all four
  dependencies ship as pre-built Windows wheels).

Then install the Python dependencies once:

```powershell
pip install -r requirements.txt
```

### Start / stop / status / reset

```powershell
.\run.ps1 start all        # netconf, restconf, coreconf, client
.\run.ps1 start client     # just one component
.\run.ps1 status
.\run.ps1 stop all
.\run.ps1 reset all
```

Or from `cmd.exe` (or by double-clicking), which sidesteps the execution
policy:

```bat
run.cmd start all
run.cmd status
run.cmd stop all
```

If PowerShell blocks the script, allow it for the current shell only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Notes for Windows:

- Each component runs as a hidden background process; its PID is written
  to `state\pids\<name>.pid` and output to `state\logs\<name>.log` (plus
  `<name>.log.err` for stderr, since Windows keeps the two streams in
  separate files).
- `stop` uses `taskkill /PID <pid> /T /F`; `status` checks each PID with
  `Get-Process`.
- `reset` delegates to `python run.py reset`, whose datastore logic is
  pure, cross-platform Python.
- You can always skip the launcher and run the four components in four
  separate PowerShell windows:
  `python servers\netconf_server.py`, `...restconf_server.py`,
  `...coreconf_server.py`, `python client\web.py`.

See **`WINDOWS.md`** for the full native-Windows guide, including how to
package the project for someone who has no WSL and no Docker.

## Startup

Start everything (servers + client), or start a single component:

```bash
python3 run.py start all        # netconf, restconf, coreconf, client
python3 run.py start netconf    # just one component
python3 run.py start client
```

Each component runs in the background; its PID is recorded in
`state/pids/<name>.pid` and its output is appended to
`state/logs/<name>.log`. When the client starts, `run.py` prints the
web interface URL to stdout:

```
[client] started (pid 1572), log: state/logs/client.log
[client] web interface: http://127.0.0.1:8080
```

Then open that URL in a browser. Each server has its own card with a
small form:

- **instance dropdown** — select an existing instance; selecting one
  populates the name and hostname fields below from that instance.
  (Populated by GET ALL and auto-loaded on page load.)
- **instance name** — the list key. Used by ADD and SET.
- **hostname value** — used by ADD and SET.
- **GET ALL** — list every instance on that server.
- **ADD INSTANCE** — create a new instance (name + hostname). If the name
  already exists the UI blocks it immediately, and the server rejects it
  too. On success the form moves to the newly added instance.
- **REMOVE INSTANCE** — delete the selected instance.
- **SET HOSTNAME** — change the hostname of the named instance.
- **RESET** — restore the datastore to a single `default` instance.

### The result window

Every action renders four colour-coded, labelled blocks so you can tell
apart what you asked, what went on the wire, and what came back:

- **command** (blue) — the action, protocol, and arguments you issued.
- **sent** (amber) — the exact request sent to the server (NETCONF XML,
  RESTCONF method + URL + body, or CoAP method + path + CBOR).
- **received** (green, or red on failure) — the server's response: raw
  payload, status / response code, and any returned data.
- **wire statistics** (purple) — a table of the bytes exchanged for that
  operation, split into **payload** (the data: XML / JSON / CBOR body) and
  **headers** (framing / HTTP headers / CoAP header + options), for each
  direction plus totals. This makes the encoding trade-offs visible:
  - NETCONF carries a large XML payload with tiny framing (the `]]>]]>`
    delimiter).
  - RESTCONF has a small JSON payload but heavy HTTP text headers.
  - CORECONF is compact on both axes (binary CBOR payload, binary CoAP
    header + options).

  It also answers why a GET shows **0 payload sent**: a read request sends
  no data body, only headers/options naming what to fetch — so the payload
  column is 0 while the headers column is not.

  Measurement notes: NETCONF counts the full XML RPC plus framing;
  RESTCONF reconstructs the HTTP request/response line + header block and
  body; CORECONF measures the CBOR payload and the encoded CoAP header +
  URI-path options.

  See **`SIZE_ANALYSIS.md`** for a detailed comparison with measured
  numbers — why RESTCONF's headers dwarf NETCONF's, and when each
  protocol's total is larger.

## Shutdown

```bash
python3 run.py stop all         # stops client first, then the servers
python3 run.py stop coreconf    # stop just one
```

`stop` reads the PID files and sends `SIGTERM` to each process group.

## Status

```bash
python3 run.py status
```

```
component   state      pid
---------   --------   -----
netconf     running    1568
restconf    running    1569
coreconf    running    1570
client      running    1572
```

## Reset the datastores

There are **two** ways to reset, and both restore the datastore to a
single seeded instance `{name: "default", hostname: "default-host"}`:

1. **Over the wire** (server must be running) — from the HTML panel's
   RESET button, or directly:

   ```bash
   # NETCONF  : vendor RPC <reset-datastore xmlns="urn:example:xconf"/>
   # RESTCONF : POST /restconf/operations/example:reset-datastore
   # CORECONF : POST coap://127.0.0.1:5683/c/reset
   ```

2. **File-level** (works whether or not the server is running) — rewrites
   the datastore JSON file directly:

   ```bash
   python3 run.py reset all
   python3 run.py reset netconf
   ```

Datastores persist in `state/*.json` across restarts, so a server keeps
its last value until you reset it.

## Driving each server directly (without the UI)

```bash
# RESTCONF — list operations
curl http://127.0.0.1:8400/restconf/data/example:system                 # get all
curl -X POST http://127.0.0.1:8400/restconf/data/example:system \
     -H 'Content-Type: application/json' \
     -d '{"example:system":[{"name":"sys1","hostname":"router-1"}]}'     # add
curl -X PUT http://127.0.0.1:8400/restconf/data/example:system=sys1/hostname \
     -H 'Content-Type: application/json' -d '{"example:hostname":"router-9"}'  # set
curl -X DELETE http://127.0.0.1:8400/restconf/data/example:system=sys1   # remove
curl -X POST http://127.0.0.1:8400/restconf/operations/example:reset-datastore

# NETCONF / CORECONF: drive through the client API on the panel backend
curl -X POST http://127.0.0.1:8080/api/command \
     -H 'Content-Type: application/json' \
     -d '{"protocol":"netconf","action":"add","name":"sys1","hostname":"router-1"}'
```

The `/api/command` endpoint accepts
`{"protocol": "...", "action": "get_all|add|remove|set|reset",
"name": "...", "hostname": "..."}`. The response result includes a
`_request` field (the exact message sent on the wire — this is what the
panel's **sent** block shows), the native response (`_raw`, HTTP
`status` or CoAP `_code`), the wire-size statistics split into
`_sent_payload` / `_sent_headers` / `_recv_payload` / `_recv_headers`,
and a normalized `instances` list for reads.

## What each operation maps to

| UI action | NETCONF                                   | RESTCONF                                       | CORECONF                         |
|-----------|-------------------------------------------|------------------------------------------------|----------------------------------|
| GET ALL   | `<get-config>` running (all entries)      | `GET /restconf/data/example:system`            | `GET coap:/c/` (CBOR, all)       |
| ADD       | `<edit-config>` `operation="create"`      | `POST .../example:system`                      | `POST coap:/c/` (CBOR map)       |
| SET       | `<edit-config>` `operation="merge"`       | `PUT .../example:system=<name>/hostname`       | `PUT coap:/c/<name>` (CBOR str)  |
| REMOVE    | `<edit-config>` `operation="delete"`      | `DELETE .../example:system=<name>`             | `DELETE coap:/c/<name>`          |
| RESET     | `<reset-datastore>` vendor RPC            | `POST .../operations/example:reset-datastore`  | `POST coap:/c/reset`             |

> **Duplicate instances are rejected on ADD.** NETCONF uses
> `operation="create"`, which returns a `data-exists` error if the key is
> already present; RESTCONF returns `409`; CORECONF returns `4.00`. SET
> uses `operation="merge"` to update an existing instance's hostname. The
> HTML panel also blocks a duplicate ADD client-side before it is sent.
