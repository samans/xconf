"""CORECONF server (simplified) using CBOR over CoAP via aiocoap.

CORECONF (RFC 9254) manages YANG data over CoAP (RFC 7252) using CBOR
(RFC 8949), keying data items by YANG SIDs (RFC 9595) rather than names.
A full implementation needs a SID file assigning numeric identifiers to
every schema node. For this lab we assign SIDs by hand:

    SID 1700  ->  example:system        (container)
    SID 1701  ->  example:system/hostname (leaf)

The CORECONF datastore is exposed at the well-known CoAP resource `/c`
(the convention from the drafts). We implement:

  GET  /c            -> CBOR map {1700: {1701: "<hostname>"}}
  GET  /c/1701       -> CBOR "<hostname>"  (single leaf by SID)
  PUT  /c/1701       -> body CBOR string sets hostname, 2.04 Changed
  POST /c/reset      -> reset datastore to defaults, 2.04 Changed

This simplifies real CORECONF (which uses FETCH/iPATCH and CBOR
delta encodings) but is wire-honest CBOR-over-CoAP keyed by SID.
See FULL_IMPLEMENTATION.md for the full picture.
"""

from __future__ import annotations

import asyncio
import os
import sys

import cbor2
import aiocoap
import aiocoap.resource as resource
from aiocoap import Code, Message

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.datastore import Datastore  # noqa: E402

HOST = "127.0.0.1"
PORT = 5683  # default CoAP port
STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state",
    "coreconf.json",
)

# Hand-assigned SIDs for the example module.
SID_SYSTEM = 1700
SID_HOSTNAME = 1701

# CoAP content format numbers for CORECONF (application/yang-data+cbor;
# id=sid). 140 is the registered value used by the drafts.
CF_YANG_CBOR = 140

datastore = Datastore(STATE_FILE)


class DatastoreResource(resource.Resource):
    """Represents /c and /c/<sid>."""

    async def render_get(self, request: Message) -> Message:
        payload = cbor2.dumps({SID_SYSTEM: {SID_HOSTNAME: datastore.get_hostname()}})
        return Message(code=Code.CONTENT, payload=payload, content_format=CF_YANG_CBOR)


class LeafResource(resource.Resource):
    """Represents /c/1701 (the hostname leaf by SID)."""

    async def render_get(self, request: Message) -> Message:
        payload = cbor2.dumps(datastore.get_hostname())
        return Message(code=Code.CONTENT, payload=payload, content_format=CF_YANG_CBOR)

    async def render_put(self, request: Message) -> Message:
        try:
            value = cbor2.loads(request.payload)
        except Exception as exc:  # noqa: BLE001
            return Message(code=Code.BAD_REQUEST, payload=str(exc).encode())
        if not isinstance(value, str):
            return Message(code=Code.BAD_REQUEST, payload=b"hostname must be a CBOR text string")
        datastore.set_hostname(value)
        return Message(code=Code.CHANGED)


class ResetResource(resource.Resource):
    """Represents /c/reset (vendor reset action)."""

    async def render_post(self, request: Message) -> Message:
        datastore.reset()
        payload = cbor2.dumps({"status": "reset"})
        return Message(code=Code.CHANGED, payload=payload, content_format=CF_YANG_CBOR)


async def _serve() -> None:
    root = resource.Site()
    root.add_resource(["c"], DatastoreResource())
    root.add_resource(["c", str(SID_HOSTNAME)], LeafResource())
    root.add_resource(["c", "reset"], ResetResource())
    await aiocoap.Context.create_server_context(root, bind=(HOST, PORT))
    print(f"[coreconf] listening on coap://{HOST}:{PORT}/c (CBOR over CoAP, SID-keyed)")
    print(f"[coreconf] SIDs: system={SID_SYSTEM} hostname={SID_HOSTNAME}")
    print(f"[coreconf] datastore: {STATE_FILE}")
    await asyncio.get_running_loop().create_future()  # run forever


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        print("\n[coreconf] shutting down")


if __name__ == "__main__":
    main()
