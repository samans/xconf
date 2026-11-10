"""Unified client for the three protocol servers.

Each protocol gets a client class exposing the same three operations:

    get()            -> dict  (full config, canonical form)
    set(hostname)    -> dict  (result/ack)
    reset()          -> dict  (ack)

This lets the web UI treat all three servers identically.
"""

from __future__ import annotations

import asyncio
import socket
import xml.etree.ElementTree as ET

import cbor2
import requests
from aiocoap import Context, Message, Code


# --------------------------------------------------------------------------
# NETCONF client (plain TCP, NETCONF 1.0 framing)
# --------------------------------------------------------------------------

NS_EXAMPLE = "urn:example:simple"
DELIM = b"]]>]]>"

CLIENT_HELLO = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">'
    "<capabilities>"
    "<capability>urn:ietf:params:netconf:base:1.0</capability>"
    "</capabilities>"
    "</hello>"
)


class NetconfClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8300, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _session(self):
        """Open a socket, exchange hellos, return a connected socket."""
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        # Read server hello (ignore content, just drain to delimiter).
        self._recv_message(sock)
        self._send(sock, CLIENT_HELLO)
        return sock

    def _send(self, sock, text: str) -> None:
        sock.sendall(text.encode("utf-8") + DELIM)

    def _recv_message(self, sock) -> str:
        buffer = b""
        while DELIM not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
        message, _, _ = buffer.partition(DELIM)
        return message.decode("utf-8", errors="replace")

    def _rpc(self, inner: str) -> str:
        sock = self._session()
        try:
            rpc = (
                '<rpc xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="1">'
                f"{inner}</rpc>"
            )
            self._send(sock, rpc)
            reply = self._recv_message(sock)
            self._send(
                sock,
                '<rpc xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="2">'
                "<close-session/></rpc>",
            )
            return reply
        finally:
            sock.close()

    def get(self) -> dict:
        reply = self._rpc("<get-config><source><running/></source></get-config>")
        hostname = self._extract_hostname(reply)
        return {"example:system": {"hostname": hostname}, "_raw": reply}

    def set(self, hostname: str) -> dict:
        inner = (
            "<edit-config><target><running/></target><config>"
            f'<system xmlns="{NS_EXAMPLE}"><hostname>{_xml_escape(hostname)}</hostname></system>'
            "</config></edit-config>"
        )
        reply = self._rpc(inner)
        return {"ok": "<ok/>" in reply, "_raw": reply}

    def reset(self) -> dict:
        reply = self._rpc('<reset-datastore xmlns="urn:example:xconf"/>')
        return {"ok": "<ok/>" in reply, "_raw": reply}

    @staticmethod
    def _extract_hostname(reply: str) -> str:
        try:
            root = ET.fromstring(reply)
        except ET.ParseError:
            return ""
        for elem in root.iter():
            if elem.tag.split("}")[-1] == "hostname":
                return elem.text or ""
        return ""


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# RESTCONF client (HTTP/JSON)
# --------------------------------------------------------------------------


class RestconfClient:
    def __init__(self, base: str = "http://127.0.0.1:8400", timeout: float = 5.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def get(self) -> dict:
        r = requests.get(f"{self.base}/restconf/data/example:system", timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return {**data, "_raw": r.text}

    def set(self, hostname: str) -> dict:
        r = requests.put(
            f"{self.base}/restconf/data/example:system/hostname",
            json={"example:hostname": hostname},
            timeout=self.timeout,
        )
        return {"ok": r.status_code in (200, 204), "status": r.status_code, "_raw": r.text}

    def reset(self) -> dict:
        r = requests.post(
            f"{self.base}/restconf/operations/example:reset-datastore",
            timeout=self.timeout,
        )
        return {"ok": r.status_code == 200, "status": r.status_code, "_raw": r.text}


# --------------------------------------------------------------------------
# CORECONF client (CBOR over CoAP)
# --------------------------------------------------------------------------

SID_SYSTEM = 1700
SID_HOSTNAME = 1701


class CoreconfClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5683):
        self.uri_base = f"coap://{host}:{port}"

    def _run(self, coro):
        return asyncio.run(coro)

    async def _request(self, code, path, payload=b""):
        ctx = await Context.create_client_context()
        try:
            msg = Message(code=code, uri=f"{self.uri_base}{path}", payload=payload)
            resp = await ctx.request(msg).response
            return resp
        finally:
            await ctx.shutdown()

    def get(self) -> dict:
        resp = self._run(self._request(Code.GET, "/c"))
        decoded = cbor2.loads(resp.payload) if resp.payload else {}
        hostname = ""
        if isinstance(decoded, dict):
            inner = decoded.get(SID_SYSTEM, {})
            if isinstance(inner, dict):
                hostname = inner.get(SID_HOSTNAME, "")
        return {
            "example:system": {"hostname": hostname},
            "_raw": repr(decoded),
            "_code": str(resp.code),
        }

    def set(self, hostname: str) -> dict:
        resp = self._run(
            self._request(Code.PUT, f"/c/{SID_HOSTNAME}", cbor2.dumps(hostname))
        )
        return {"ok": resp.code.is_successful(), "_code": str(resp.code)}

    def reset(self) -> dict:
        resp = self._run(self._request(Code.POST, "/c/reset"))
        decoded = cbor2.loads(resp.payload) if resp.payload else {}
        return {"ok": resp.code.is_successful(), "_code": str(resp.code), "_raw": repr(decoded)}


# --------------------------------------------------------------------------
# Registry used by the web UI
# --------------------------------------------------------------------------

CLIENTS = {
    "netconf": NetconfClient(),
    "restconf": RestconfClient(),
    "coreconf": CoreconfClient(),
}


def do(protocol: str, action: str, hostname: str | None = None) -> dict:
    client = CLIENTS[protocol]
    if action == "get":
        return client.get()
    if action == "set":
        return client.set(hostname or "")
    if action == "reset":
        return client.reset()
    raise ValueError(f"unknown action {action!r}")
