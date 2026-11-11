# From lab to standards-compliant: NETCONF, RESTCONF, SID CORECONF

This document describes what the current lab **simplifies**, and what
would have to change to run **full, RFC-compliant** NETCONF, RESTCONF, and
CORECONF servers. It is organized per protocol, then cross-cutting
concerns (YANG tooling, datastore semantics, security).

The current lab deliberately trades compliance for zero-friction local
testing: no SSH, no TLS, no SID files, one leaf, in-memory/file datastore,
no validation. Each section below lists the gap and the realistic path to
close it.

---

## 0. The common foundation: real YANG + datastore tooling

Everything compliant starts here, because all three protocols are just
different transports over the **same YANG-modeled datastore**.

- **YANG parser / schema engine.** The lab hard-codes one leaf. A real
  server loads arbitrary YANG modules, validates them, and builds a schema
  tree. Use an engine instead of hand-written code:
  - **sysrepo** + **libyang** (C, the de-facto open-source datastore).
  - **pyangbind** / **libyang python bindings** for Python.
  - Vendor stacks: Cisco ConfD, YumaPro netconfd.
- **Datastore model (RFC 8342 / NMDA).** Implement the distinct datastores:
  `running`, `candidate`, `startup`, `intended`, `operational`, plus
  `<get-data>`/`<edit-data>`. The lab has a single flat JSON file with no
  candidate/commit model.
- **Validation.** Type checking, `must`/`when` constraints, `leafref`
  integrity, mandatory nodes, defaults handling (RFC 6243 `with-defaults`).
- **Transactions.** Atomic apply, rollback-on-error, and `confirmed-commit`
  with timeout/rollback. The lab applies writes immediately with no
  rollback.
- **Change notifications.** A subscription/notification bus
  (NETCONF notifications RFC 5277, YANG-Push RFC 8641) so clients can
  subscribe to datastore changes.

Recommended: **don't hand-roll this.** Put `sysrepo`+`libyang` underneath
and let `netopeer2` (NETCONF) and a RESTCONF front-end share that single
datastore, so all protocols stay consistent.

---

## 1. Full NETCONF (RFC 6241 / 6242 / 7950)

Current lab: plain TCP, `]]>]]>` framing, no SSH, no candidate datastore,
only `get`, `get-config`, `edit-config(running)`, `lock/unlock` as no-ops,
and a vendor reset RPC.

To be compliant:

- **SSH transport (RFC 6242).** NETCONF MUST run over SSH on port **830**
  using the `netconf` SSH subsystem (TLS per RFC 7589 is the alternative).
  Replace the raw `socketserver` with an SSH server that exposes the
  subsystem — e.g. `paramiko`/`asyncssh` in Python, or just use
  **netopeer2-server** which does this for you.
- **Chunked framing (RFC 6242 §4.2).** After negotiating `base:1.1` in the
  hello, messages use chunked framing (`\n#<len>\n...`), not `]]>]]>`.
  Support both and switch based on the negotiated capability.
- **Capabilities.** Advertise real capabilities and honor them:
  `:candidate`, `:confirmed-commit`, `:rollback-on-error`,
  `:validate`, `:startup`, `:writable-running`, `:xpath`,
  `:with-defaults`, and `:notification`.
- **Full RPC set.** `copy-config`, `delete-config`, `commit`,
  `discard-changes`, `validate`, `get-schema` (RFC 6022),
  `get-data`/`edit-data` (NMDA), plus `create-subscription`.
- **Real locking.** Per-datastore locks with session ownership, partial
  locks (RFC 5717), and `lock-denied` errors — not the no-op acknowledgements
  the lab returns.
- **`edit-config` semantics.** Honor the `operation` attribute
  (`merge`/`replace`/`create`/`delete`/`remove`), `default-operation`,
  `test-option`, and `error-option`, with correct `rpc-error` structures
  (error-type/tag/app-tag/path/info).
- **Standard error reporting.** Proper `<rpc-error>` taxonomy from RFC 6241
  Appendix A, with namespaces and `error-info`.

Fastest compliant path: run **netopeer2-server** on top of
**sysrepo/libyang** and load `example.yang`. Our hand-rolled server then
becomes a teaching reference, not the product.

---

## 2. Full RESTCONF (RFC 8040)

Current lab: Flask with a few fixed routes, JSON only, no TLS, no auth, no
`ETag`/`Last-Modified`, no query parameters, vendor reset action.

To be compliant:

- **Root discovery (RFC 8040 §3.1).** Implement
  `GET /.well-known/host-meta` returning the `restconf` root link, and the
  `{+restconf}/` resource with `data`, `operations`, `yang-library-version`,
  and `ietf-yang-library` modules-state.
- **Transport.** RESTCONF runs over **HTTPS/TLS**; serve behind a real WSGI
  server (gunicorn/uvicorn) + TLS, not Flask's dev server.
- **Full method set & resource model.**
  - `GET` with correct media types: `application/yang-data+json` **and**
    `application/yang-data+xml` (content negotiation).
  - `POST` to create resources (data resources and `operations`).
  - `PUT` (create/replace), `PATCH` (RFC 8072 YANG Patch and plain merge),
    `DELETE`.
  - Correct status codes (201 w/ `Location` on create, 204 on update,
    409 on conflict).
- **Query parameters (§4.8).** `content` (config/nonconfig/all), `depth`,
  `fields`, `with-defaults`, `filter`, `start-time`/`stop-time`,
  `insert`/`point` for ordered lists.
- **Concurrency.** `ETag` + `If-Match` / `Last-Modified` +
  `If-Unmodified-Since` on data resources.
- **Errors.** `ietf-restconf:errors` structure with proper
  `error-type`/`error-tag` and HTTP status mapping (the lab already
  returns this shape for a couple of cases; it needs to be universal).
- **Notifications.** `GET` on the event-stream resource using Server-Sent
  Events, driven by the same notification bus as NETCONF.
- **Identifier encoding.** Correct RFC 8040 §3.5.3 list-key encoding in
  URIs (`list=key1,key2`) and module-qualified first nodes.

Fastest compliant path: generate the data layer from YANG via
**libyang** and mount a RESTCONF front-end (e.g. the one bundled with
sysrepo, or **jetconf**) over the shared datastore.

---

## 3. Full CORECONF with SID files (RFC 9254 + RFC 9595)

Current lab: aiocoap server, hand-assigned SIDs (1700/1701/1702), the
`system` node is now a keyed **list** encoded as a CBOR map keyed by the
instance name (`{1700: {"<name>": {1702: name, 1701: hostname}}}`) with
GET/POST on `/c/`, GET/PUT/DELETE on `/c/<name>`, POST on `/c/reset`. No
FETCH/iPATCH, no proper CBOR list encoding, no `.well-known/core`, no
DTLS/OSCORE.

To be compliant:

- **SID file generation (RFC 9595).** SIDs MUST come from a registered
  **SID file** that allocates a mega-range to the module and assigns a
  stable SID to every schema node, identity, and feature. Generate it with
  a tool, e.g. `pyang --sid-file` / the IETF `sid` tooling, and ship the
  `.sid` JSON alongside the module. No more hand-picked integers.
  - SIDs in payloads are typically **delta-encoded** relative to the parent
    (RFC 9254 §3.2) — the lab uses absolute SIDs.
- **Proper YANG list encoding (RFC 9254).** A keyed list is encoded as a
  **CBOR array of maps**, each map carrying the key leaf(s) and other
  nodes by (delta) SID — not the name-keyed CBOR map shortcut this lab
  uses. List instances are addressed by their key values per the CoMI
  rules, not by a bare name path segment.
- **CBOR encoding rules (RFC 9254).** Full type mapping: deltas for keys,
  correct encoding of `identityref` (as SIDs), `instance-identifier`,
  `bits`, `decimal64`, `union`, `anydata`; and the
  `application/yang-data+cbor` content formats with `id=sid` vs `id=name`.
- **CoAP methods & resources (RFC 9254 §4).**
  - `FETCH` on the datastore resource with a CBOR list of SIDs to retrieve
    a subset (this is the core read primitive — the lab only does GET of
    the whole tree / one leaf).
  - `iPATCH` (RFC 8132) with a CBOR patch document for partial edits,
    instead of per-leaf PUT.
  - Correct response codes and the datastore resource discovery.
- **Resource discovery (RFC 6690).** Serve `/.well-known/core` advertising
  the CORECONF datastore resource(s) with the right resource types (`rt`).
- **Block-wise transfer (RFC 7959).** Large datastores exceed a single
  datagram; implement Block1/Block2.
- **Security.** CoAP MUST be protected: **DTLS** (RFC 6347) or
  **OSCORE** (RFC 8613). The lab is plaintext UDP.
- **Observe (RFC 7641).** For notifications/telemetry, support CoAP Observe
  on datastore resources, tied to the notification bus.

Fastest compliant path: use a real CORECONF/CoMI stack (e.g. tooling built
on `aiocoap` + a generated SID file + `libyang` for the schema), keeping
the single shared datastore underneath.

---

## 4. Cross-cutting: security, identity, operations

- **AAA.** NETCONF/RESTCONF use `ietf-netconf-acm` (NACM, RFC 8341) for
  per-user/group path authorization; add authentication (SSH keys,
  HTTP auth / client certs, DTLS PSK or raw public keys for CoAP).
- **TLS/DTLS everywhere.** Real certs, cipher policy, and for CoAP either
  DTLS or OSCORE.
- **One datastore, three faces.** The biggest architectural change: today
  each server owns a separate JSON file, so the three protocols can diverge.
  A compliant deployment points all three front-ends at **one** datastore
  (sysrepo) so a NETCONF `edit-config`, a RESTCONF `PUT`, and a CORECONF
  `iPATCH` all mutate the same state and raise consistent notifications.
- **Operational vs config state (NMDA).** Separate applied/operational data
  from intended config; expose `operational` datastore reads.
- **Scale & robustness.** Streaming/pagination for large trees, back-pressure,
  and production servers (gunicorn/uvicorn for RESTCONF, netopeer2 for
  NETCONF) instead of dev servers.

---

## 5. Suggested migration order

1. Replace the hand-rolled datastore with **libyang + sysrepo**; load
   `example.yang`. All three servers now share real schema + datastore.
2. Swap the NETCONF server for **netopeer2** over SSH:830.
3. Put a compliant **RESTCONF** front-end (HTTPS) over the same datastore.
4. Generate a **SID file** for `example.yang` and move the CORECONF server
   to FETCH/iPATCH + DTLS/OSCORE using those SIDs.
5. Add **NACM**, notifications (NETCONF/RESTCONF SSE/CoAP Observe), and
   NMDA operational state.
6. Grow the YANG model beyond one leaf; the rest of the stack already
   generalizes because it is schema-driven.
