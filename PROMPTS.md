# Project prompts

This file records the prompts that drove the construction of the xconf
lab, rewritten as concise, self-contained specifications. Each section is
a prompt you could issue (in order) to an AI coding agent to reproduce a
similar result. They are listed in the order the project was built, and
each builds on the state left by the previous one.

The project lives in the workspace root (`/home/samans/xconf`).

---

## 1. Scaffold three servers + one client

> Build a local, runnable lab in Python with three network-management
> servers — one **NETCONF**, one **RESTCONF**, one **CORECONF** — and a
> single client that drives all three. Provide a browser-based HTML
> control panel for the client. For initial testing use a trivial YANG
> module with one container holding one leaf. Support **startup**,
> **shutdown**, and **datastore reset** for each server.
>
> Pragmatic constraints for a dependency-light lab: hand-roll the NETCONF
> server over plain TCP (NETCONF 1.0 `]]>]]>` framing, no SSH); implement
> RESTCONF with Flask (HTTP/JSON, RFC 8040-style paths); implement
> CORECONF with aiocoap (CBOR over CoAP, hand-assigned SIDs). All three
> servers share the same YANG model and a common file-backed datastore so
> reset semantics are uniform. Per-server operations needed: get full
> config, set the leaf value, reset to default.
>
> Also write a `FULL_IMPLEMENTATION.md` describing what it would take to
> turn each of the three into a fully standards-compliant server
> (real NETCONF over SSH, compliant RESTCONF, SID-file-based CORECONF).

Deliverables: `yang/example.yang`, `common/datastore.py`, the three
servers under `servers/`, the client (`client/protocol_clients.py`,
`client/web.py`, `client/templates/index.html`), a `run.py` launcher
(start / stop / status / reset), `requirements.txt`, `README.md`, and
`FULL_IMPLEMENTATION.md`. Verify every protocol end to end before
finishing.

---

## 2. Persist the project in a knowledge base

> Index the whole project directory into a knowledge base so its contents
> persist across sessions and reboots and are searchable later.

---

## 3. Convert the model to a keyed list (multi-instance UI)

> Update the UI so the user can manage **multiple instances**. Since a
> YANG `container` is a singleton, convert the model from
> `container system { leaf hostname; }` to a **keyed list**
> `list system { key name; leaf name; leaf hostname; }`.
>
> Give each protocol card a small form: a **dropdown** to select an
> existing instance, a text box for a new leaf (hostname) value, an
> **Add instance** button, a **Remove instance** button, a **Set
> hostname** action, and a **Get all instances** button — all per
> protocol. Thread the list model through every layer (datastore, all
> three servers, all three protocol clients, the web API, and the HTML).

---

## 4. Populate fields on select; add by new name

> Two fixes:
> 1. When an instance is chosen in the dropdown, auto-populate the
>    instance-name and hostname fields from that instance.
> 2. If the user types a name that does not exist and presses **Add
>    instance**, create a new instance.

---

## 5. Reject duplicate adds

> When **Add instance** is pressed, verify the instance does not already
> exist before adding it. Enforce this both client-side (immediate
> feedback from the dropdown contents) and authoritatively on each server
> (NETCONF `operation="create"` → `data-exists`; RESTCONF `409`; CORECONF
> `4.00`). `Set hostname` should use merge/update semantics instead.

---

## 6. Move to new instance after add; show the request sent

> Two fixes:
> 1. After a successful **Add instance**, move the form (dropdown +
>    fields) to the newly created instance instead of staying on the
>    previous selection.
> 2. For **Set hostname** (and every operation), the result should show
>    the actual message sent on the wire, not just the server's reply.
>    Have each protocol client return the exact request it sent and
>    surface it in the UI.

---

## 7. Colour-code the result window

> Colour-code the result window so it is easy to tell apart **what was
> sent**, **what was received**, and **what the command was**. Render
> three labelled, colour-coded blocks per result (command / sent /
> received, with the received block turning red on failure) and add a
> colour legend.

---

## 8. Print the web URL on `start all`

> When `run.py start all` (or `start client`) runs, print the web
> interface URL to stdout so the user can click straight through.

---

## 9. Keep the README and knowledge base current

> Update `README.md` to reflect the current feature set (keyed list,
> per-instance form, duplicate rejection, select-populates-fields,
> colour-coded result window, URL printout), then refresh the project
> knowledge base.

(This "update README + refresh knowledge base" step was repeated after
later changes as well.)

---

## 10. Add wire-size statistics

> At the end of each result, add statistics about how much data is sent
> over the wire and how much is received. Measure the real application-
> layer bytes in each protocol client and show them in a dedicated,
> colour-coded stats block.

---

## 11. Split statistics into payload vs headers/options

> The "sent to wire" figure reads 0 for a GET (get-all) in RESTCONF and
> CORECONF because a read request carries no body. Add a **separate
> statistic for headers/options** alongside the payload bytes, so the
> stats block shows a payload / headers / total breakdown in each
> direction. This explains the 0-payload case (a GET sends only
> headers/options) and makes the per-protocol trade-offs visible
> (NETCONF: big payload, tiny framing; RESTCONF: small payload, heavy HTTP
> headers; CORECONF: compact on both axes).

---

## 12. Document the prompts

> Create a markdown file capturing all the prompts used to build this
> project, rewritten into concise descriptions that would yield a similar
> result. (This file.)

---

## 13. Package and share as a Docker image

> Package the whole lab (the three servers + the web client) as a single
> Docker image, and write a markdown guide for building, running, and
> sharing it. Make the web UI's bind host configurable via an environment
> variable so it stays loopback-only for bare-metal runs but binds
> `0.0.0.0` inside the container. Provide a container entrypoint that
> starts the three servers in the background and runs the web client in
> the foreground (stopping the servers cleanly on shutdown), a
> `.dockerignore`, port/EXPOSE declarations for all four services, and a
> health check. The sharing guide should cover a `docker save` tar file,
> Docker Hub, and ghcr.io. Then update the README and PROMPTS files.

Deliverables: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`,
`DOCKER.md`, an `XCONF_WEB_HOST` / `XCONF_WEB_PORT` env-var in
`client/web.py`, plus README/PROMPTS updates.

---

## 14. (repeat) Document the prompts

> After adding the Docker packaging, update this prompts file to include
> the new step.

## Notes for reproduction

- **Stack**: Python 3.12, `flask`, `requests`, `cbor2`, `aiocoap`.
- **Ports**: NETCONF TCP 8300, RESTCONF HTTP 8400, CORECONF CoAP/UDP 5683,
  client web UI 8080.
- **Working style that helped**: after every change, byte-compile the
  Python, start the stack with `run.py`, exercise each protocol through
  the client API (`POST /api/command`), confirm wire behaviour, then stop
  the stack and clean the `state/` directory. Watch for orphaned server
  processes holding ports between separate `start` invocations.
- **Scope discipline**: the lab deliberately trades standards compliance
  for a dependency-light, fully runnable local setup; the compliance gap
  is documented in `FULL_IMPLEMENTATION.md` rather than implemented.
- **Docker**: the whole lab also builds into one image (`docker build -t
  xconf . && docker run --rm -p 8080:8080 xconf`); see `DOCKER.md`. The
  web UI reads `XCONF_WEB_HOST` (default `127.0.0.1`, set to `0.0.0.0` in
  the image) so the published port is reachable from the host.
