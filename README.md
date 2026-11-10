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

All three servers model the **same** YANG module (`yang/example.yang`):

```yang
container system {
  leaf hostname {
    type string;
    default "default-host";
  }
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
  state/                       # datastores, pid files, logs (created at run)
```

## Install

```bash
pip3 install -r requirements.txt
```

Dependencies: `flask`, `requests`, `cbor2`, `aiocoap`.

## Startup

Start everything (servers + client), or start a single component:

```bash
python3 run.py start all        # netconf, restconf, coreconf, client
python3 run.py start netconf    # just one component
python3 run.py start client
```

Each component runs in the background; its PID is recorded in
`state/pids/<name>.pid` and its output is appended to
`state/logs/<name>.log`.

Then open the control panel:

```
http://127.0.0.1:8080
```

Use the **hostname** field at the top, then click **GET / SET / RESET** on
any server card. SET writes the hostname field; RESET restores the YANG
default `default-host`.

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

There are **two** ways to reset, and both restore the YANG default
`hostname = "default-host"`:

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
# RESTCONF
curl http://127.0.0.1:8400/restconf/data/example:system
curl -X PUT http://127.0.0.1:8400/restconf/data/example:system/hostname \
     -H 'Content-Type: application/json' -d '{"example:hostname":"router-1"}'
curl -X POST http://127.0.0.1:8400/restconf/operations/example:reset-datastore

# NETCONF / CORECONF: drive through the client API on the panel backend
curl -X POST http://127.0.0.1:8080/api/command \
     -H 'Content-Type: application/json' \
     -d '{"protocol":"netconf","action":"set","hostname":"router-1"}'
```

The `/api/command` endpoint accepts `{"protocol": "...", "action":
"get|set|reset", "hostname": "..."}` and returns the native result.

## What each operation maps to

| UI action | NETCONF                         | RESTCONF                                   | CORECONF                         |
|-----------|---------------------------------|--------------------------------------------|----------------------------------|
| GET       | `<get-config><source><running/>`| `GET /restconf/data/example:system`        | `GET coap:/c` (CBOR by SID)      |
| SET       | `<edit-config>` running         | `PUT .../example:system/hostname`          | `PUT coap:/c/1701` (CBOR string) |
| RESET     | `<reset-datastore>` vendor RPC  | `POST .../operations/example:reset-datastore` | `POST coap:/c/reset`          |
