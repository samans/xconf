"""CORECONF server (simplified) using CBOR over CoAP via aiocoap.

CORECONF (RFC 9254) manages YANG data over CoAP (RFC 7252) using CBOR
(RFC 8949), keying data items by YANG SIDs (RFC 9595) rather than names.
A full implementation needs a SID file assigning numeric identifiers to
every schema node. For this lab we assign SIDs by hand:

    SID 1700  ->  example:system           (list)
    SID 1701  ->  example:system/hostname  (leaf)
    SID 1702  ->  example:system/name       (key leaf)

The `system` node is now a keyed YANG list. Real CORECONF encodes a list
as a CBOR array of maps with delta-encoded SID keys. For clarity in this
lab we encode it as a CBOR map keyed by the instance name:

    {1700: {"<name>": {1702: "<name>", 1701: "<hostname>"}}}

The CORECONF datastore is exposed at the well-known CoAP resource `/c`:

  GET    /c            -> whole datastore (all instances)
  POST   /c            -> body CBOR {"name": n, "hostname": h}  add instance
  GET    /c/<name>     -> CBOR {1702: name, 1701: hostname}     one instance
  PUT    /c/<name>     -> body CBOR text string sets hostname
  DELETE /c/<name>     -> remove instance
  POST   /c/reset      -> reset datastore to defaults

See FULL_IMPLEMENTATION.md for the full CORECONF list/FETCH/iPATCH story.
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

from common.datastore import Datastore, InstanceExists, InstanceNotFound  # noqa: E402

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
SID_NAME = 1702

# CoAP content format for CORECONF (application/yang-data+cbor; id=sid).
CF_YANG_CBOR = 140

datastore = Datastore(STATE_FILE)


def _encode_all() -> bytes:
    data = datastore.get()
    instances = {}
    for entry in data.get("example:system", []):
        instances[entry.get("name", "")] = {
            SID_NAME: entry.get("name", ""),
            SID_HOSTNAME: entry.get("hostname", ""),
        }
    return cbor2.dumps({SID_SYSTEM: instances})


class CoreconfSite(resource.Resource, resource.PathCapable):
    """A single PathCapable resource mounted at /c.

    It parses the remaining uri_path itself so that /c, /c/reset, and
    /c/<any-instance-name> are all handled dynamically — aiocoap's Site
    otherwise only matches fixed resource tuples.

      path ()          -> datastore collection (GET all, POST add)
      path ("reset",)  -> reset action (POST)
      path ("<name>",) -> one list instance (GET / PUT / DELETE)
    """

    async def render(self, request: Message) -> Message:
        path = request.opt.uri_path

        if path in ((), ("",)):
            return await self._collection(request)

        if path == ("reset",):
            return await self._reset(request)

        if len(path) == 1:
            return await self._instance(request, path[0])

        return Message(code=Code.NOT_FOUND)

    # -- /c ------------------------------------------------------------

    async def _collection(self, request: Message) -> Message:
        if request.code == Code.GET:
            return Message(code=Code.CONTENT, payload=_encode_all(), content_format=CF_YANG_CBOR)
        if request.code == Code.POST:
            try:
                body = cbor2.loads(request.payload) if request.payload else {}
            except Exception as exc:  # noqa: BLE001
                return Message(code=Code.BAD_REQUEST, payload=str(exc).encode())
            if not isinstance(body, dict) or not body.get("name"):
                return Message(code=Code.BAD_REQUEST, payload=b"expected CBOR map with 'name'")
            try:
                datastore.add_instance(body["name"], body.get("hostname"))
            except InstanceExists:
                return Message(code=Code.BAD_REQUEST, payload=b"instance already exists")
            except ValueError as exc:
                return Message(code=Code.BAD_REQUEST, payload=str(exc).encode())
            return Message(code=Code.CREATED)
        return Message(code=Code.METHOD_NOT_ALLOWED)

    # -- /c/reset ------------------------------------------------------

    async def _reset(self, request: Message) -> Message:
        if request.code != Code.POST:
            return Message(code=Code.METHOD_NOT_ALLOWED)
        datastore.reset()
        return Message(code=Code.CHANGED, payload=cbor2.dumps({"status": "reset"}), content_format=CF_YANG_CBOR)

    # -- /c/<name> -----------------------------------------------------

    async def _instance(self, request: Message, name: str) -> Message:
        if request.code == Code.GET:
            try:
                entry = datastore.get_instance(name)
            except InstanceNotFound:
                return Message(code=Code.NOT_FOUND)
            payload = cbor2.dumps({SID_NAME: entry["name"], SID_HOSTNAME: entry["hostname"]})
            return Message(code=Code.CONTENT, payload=payload, content_format=CF_YANG_CBOR)
        if request.code == Code.PUT:
            try:
                value = cbor2.loads(request.payload)
            except Exception as exc:  # noqa: BLE001
                return Message(code=Code.BAD_REQUEST, payload=str(exc).encode())
            if not isinstance(value, str):
                return Message(code=Code.BAD_REQUEST, payload=b"hostname must be a CBOR text string")
            try:
                datastore.set_hostname(name, value)
            except InstanceNotFound:
                return Message(code=Code.NOT_FOUND)
            return Message(code=Code.CHANGED)
        if request.code == Code.DELETE:
            try:
                datastore.remove_instance(name)
            except InstanceNotFound:
                return Message(code=Code.NOT_FOUND)
            return Message(code=Code.DELETED)
        return Message(code=Code.METHOD_NOT_ALLOWED)


async def _serve() -> None:
    root = resource.Site()
    root.add_resource(["c"], CoreconfSite())
    await aiocoap.Context.create_server_context(root, bind=(HOST, PORT))
    print(f"[coreconf] listening on coap://{HOST}:{PORT}/c (CBOR over CoAP, SID-keyed)")
    print(f"[coreconf] SIDs: system={SID_SYSTEM} name={SID_NAME} hostname={SID_HOSTNAME}")
    print(f"[coreconf] datastore: {STATE_FILE}")
    await asyncio.get_running_loop().create_future()  # run forever


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        print("\n[coreconf] shutting down")


if __name__ == "__main__":
    main()
