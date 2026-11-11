# Wire-size analysis: NETCONF vs RESTCONF vs CORECONF

The control panel reports, for every operation, how many bytes crossed the
wire — split into **payload** (the data: XML / JSON / CBOR body) and
**headers** (framing / HTTP headers / CoAP header + options), in each
direction. This document explains what those numbers mean and why they
differ so much between the three protocols.

All figures below are measured by the lab's own clients against the
running servers (see `client/protocol_clients.py`). They are
representative, not canonical — see [Caveats](#caveats).

---

## What counts as "headers" in each protocol

The three protocols frame messages in completely different ways, so the
"headers" bucket holds very different things:

| Protocol | Transport | "Headers" = …                                             |
|----------|-----------|-----------------------------------------------------------|
| NETCONF  | raw TCP   | just the 6-byte end-of-message delimiter `]]>]]>`         |
| RESTCONF | HTTP      | the full HTTP request/response line + text header block   |
| CORECONF | CoAP      | the 4-byte CoAP binary header + token + options (URI-path)|

NETCONF has **no header/body split at all**: the entire message is one XML
document sent over a TCP stream, terminated by `]]>]]>`. That delimiter is
the only framing there is, so everything else — `<rpc>`, `<edit-config>`,
namespaces, data — counts as payload.

RESTCONF rides on **HTTP**, which carries a verbose ASCII header block on
every request and every response, largely a fixed cost per message.

CORECONF uses **CoAP**, a binary protocol designed for constrained links,
so both its header and its payload (CBOR) are tiny.

---

## Measured example — SET hostname on one instance

Operation: set `example:system[name=sys1]/hostname` to `router-xyz`.

| Metric          | NETCONF | RESTCONF | CORECONF |
|-----------------|--------:|---------:|---------:|
| payload sent    |   309 B |     34 B |     11 B |
| headers sent    |     6 B |    217 B |     13 B |
| payload recv    |   129 B |      0 B |      0 B |
| headers recv    |     6 B |    161 B |      4 B |
| **total**       | **450 B** | **412 B** | **28 B** |

### Why RESTCONF headers (217 B sent) dwarf NETCONF headers (6 B)

The RESTCONF request headers for this SET are a full HTTP header block:

```
PUT /restconf/data/example:system=sys1/hostname HTTP/1.1
User-Agent: python-requests/2.34.2
Accept-Encoding: gzip, deflate
Accept: */*
Connection: keep-alive
Content-Length: 34
Content-Type: application/json
```

That request line plus the header lines is ~217 bytes and dwarfs the
34-byte JSON body. The response adds another ~161 bytes of headers
(`Server:`, `Date:`, `Content-Type:`, `Connection:`, …).

NETCONF, by contrast, sends only `]]>]]>` (6 bytes) as framing — so its
"headers" number is tiny. This is not RESTCONF being inefficient so much
as the two protocols putting their overhead in different places. The
comparison is not apples-to-apples: NETCONF's "headers" is a stream
delimiter, RESTCONF's "headers" is the entire HTTP protocol envelope.

### Where each protocol is "fat"

The two text protocols are bulky in opposite places:

- **NETCONF — fat payload, tiny framing.** Verbose XML with namespace
  declarations repeated inline (`<rpc xmlns="…">`,
  `<config xmlns:nc="…">`, `<system xmlns="urn:example:simple">`), and it
  echoes a full `<rpc-reply>` back. 309 B sent + 129 B received of payload.
- **RESTCONF — compact payload, fat headers.** 34-byte JSON body, but a
  large fixed HTTP header tax on both the request and the response.
- **CORECONF — tiny on both axes.** 11-byte CBOR body and a ~13-byte
  binary CoAP header + options. Purpose-built for constrained/IoT links.

---

## Is RESTCONF's larger total "normal"?

For a **small single operation like this SET, yes — and it's close.**
In the example above NETCONF's total (450 B) is actually slightly *larger*
than RESTCONF's (412 B), because NETCONF's XML verbosity roughly cancels
out RESTCONF's HTTP header tax.

Which of the two text protocols wins on total depends on the operation:

- **Tiny edits** (SET / ADD / REMOVE of one leaf): NETCONF and RESTCONF
  are in the same ballpark; they trade places. NETCONF's per-message XML
  bulk ≈ RESTCONF's per-message HTTP header block.
- **Large reads** (GET ALL over many instances): **RESTCONF pulls ahead.**
  The HTTP header block is a one-time fixed cost per request, while
  NETCONF's XML payload grows faster per instance — every element is
  re-tagged with angle brackets and namespaces.

**CORECONF wins on every axis, every time** — both its payload (CBOR) and
its framing (binary CoAP) are minimal. In the SET example it exchanged
28 B total versus 412–450 B for the text protocols, roughly a **15×**
reduction.

### Rule of thumb

```
payload size:   CORECONF (CBOR)  <<  RESTCONF (JSON)  <  NETCONF (XML)
header size:    NETCONF (6 B)    <   CORECONF (CoAP)  <<  RESTCONF (HTTP)
total (small):  CORECONF         <<  NETCONF ≈ RESTCONF
total (large):  CORECONF         <<  RESTCONF         <   NETCONF
```

---

## Caveats

These numbers are honest application-layer measurements, but a few things
shift the exact byte counts:

- **Client/server identity.** The RESTCONF header counts include headers
  injected by the Python `requests` client (`User-Agent:
  python-requests/…`, `Accept-Encoding: gzip, deflate`) and by the
  Werkzeug dev server (`Server: Werkzeug/…`, `Date:`). A different client
  or a production server would produce somewhat different header sizes.
  The structural conclusion (HTTP's header block is large and mostly
  fixed-cost vs NETCONF's 6-byte delimiter) holds regardless.
- **Transport layers below are not counted.** TCP/IP, TLS, DTLS, and UDP
  headers are excluded — these are application-layer payload + framing
  figures only. Real on-the-wire totals would add those.
- **NETCONF session overhead excluded.** The `<hello>` capability exchange
  and the trailing `<close-session>` are session setup/teardown, counted
  once per session rather than per operation, so they are excluded from
  these per-operation figures.
- **CoAP header is representative.** aiocoap assigns the message id / type
  / token at transmit time, so the sent CoAP overhead is measured from a
  reconstructed CON message with a typical 1-byte token.

---

## How to reproduce

Start the stack, then drive each protocol through the client API and read
the `_sent_payload` / `_sent_headers` / `_recv_payload` / `_recv_headers`
fields in the result:

```bash
python3 run.py start all

# Seed an instance, then SET and inspect the sizes:
curl -s -X POST localhost:8080/api/command \
  -H 'Content-Type: application/json' \
  -d '{"protocol":"restconf","action":"add","name":"sys1","hostname":"router-1"}'

curl -s -X POST localhost:8080/api/command \
  -H 'Content-Type: application/json' \
  -d '{"protocol":"restconf","action":"set","name":"sys1","hostname":"router-xyz"}' \
  | python3 -m json.tool
```

Or just use the web panel — every result ends with a **wire statistics**
block showing the payload / headers / total breakdown.
