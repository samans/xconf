"""Unified client for the three protocol servers.

The shared YANG model is now a keyed list:

    list system { key name; leaf name; leaf hostname; }

Each protocol client exposes the same operations so the web UI can treat
all three identically:

    get_all()                  -> {"instances": [{"name","hostname"}], ...}
    add(name, hostname)        -> add a new instance
    remove(name)               -> remove an instance by key
    set(name, hostname)        -> set hostname on an existing instance
    reset()                    -> restore datastore to defaults
"""

from __future__ import annotations

import asyncio
import json
import socket
import xml.etree.ElementTree as ET

import cbor2
import requests
from aiocoap import Context, Message, Code


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


def _xml_escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------
# NETCONF client (plain TCP, NETCONF 1.0 framing)
# --------------------------------------------------------------------------


class NetconfClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8300, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _session(self):
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._recv_message(sock)  # drain server hello
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

    def _rpc(self, inner: str) -> tuple:
        """Send one RPC, return (reply_text, sizes).

        `sizes` is a dict with payload and framing byte counts in each
        direction. For NETCONF there is no header/body split — the whole
        message is XML payload over TCP — so "headers" here means only the
        NETCONF 1.0 end-of-message framing delimiter (]]>]]>). The hello
        exchange and trailing close-session are session overhead, excluded.
        """
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
            sizes = {
                "_sent_payload": len(rpc.encode("utf-8")),
                "_sent_headers": len(DELIM),       # ]]>]]> framing
                "_recv_payload": len(reply.encode("utf-8")),
                "_recv_headers": len(DELIM),
            }
            return reply, sizes
        finally:
            sock.close()

    def get_all(self) -> dict:
        req = "<get-config><source><running/></source></get-config>"
        reply, sizes = self._rpc(req)
        return {"instances": self._extract_instances(reply), "_request": req,
                "_raw": reply, **sizes}

    def add(self, name: str, hostname: str) -> dict:
        # operation="create" fails (data-exists) if the instance is present.
        inner = (
            "<edit-config><target><running/></target>"
            '<config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
            f'<system xmlns="{NS_EXAMPLE}" nc:operation="create">'
            f"<name>{_xml_escape(name)}</name>"
            f"<hostname>{_xml_escape(hostname)}</hostname>"
            "</system></config></edit-config>"
        )
        reply, sizes = self._rpc(inner)
        return {"ok": "<ok/>" in reply, "_request": inner, "_raw": reply, **sizes}

    def remove(self, name: str) -> dict:
        inner = (
            '<edit-config><target><running/></target>'
            '<config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
            f'<system xmlns="{NS_EXAMPLE}" nc:operation="delete">'
            f"<name>{_xml_escape(name)}</name>"
            "</system></config></edit-config>"
        )
        reply, sizes = self._rpc(inner)
        return {"ok": "<ok/>" in reply, "_request": inner, "_raw": reply, **sizes}

    def set(self, name: str, hostname: str) -> dict:
        # operation="merge" updates an existing instance's hostname.
        inner = (
            "<edit-config><target><running/></target>"
            '<config xmlns:nc="urn:ietf:params:xml:ns:netconf:base:1.0">'
            f'<system xmlns="{NS_EXAMPLE}" nc:operation="merge">'
            f"<name>{_xml_escape(name)}</name>"
            f"<hostname>{_xml_escape(hostname)}</hostname>"
            "</system></config></edit-config>"
        )
        reply, sizes = self._rpc(inner)
        return {"ok": "<ok/>" in reply, "_request": inner, "_raw": reply, **sizes}

    def reset(self) -> dict:
        req = '<reset-datastore xmlns="urn:example:xconf"/>'
        reply, sizes = self._rpc(req)
        return {"ok": "<ok/>" in reply, "_request": req, "_raw": reply, **sizes}

    @staticmethod
    def _extract_instances(reply: str) -> list:
        try:
            root = ET.fromstring(reply)
        except ET.ParseError:
            return []
        instances = []
        for elem in root.iter():
            if elem.tag.split("}")[-1] == "system":
                name = hostname = ""
                for child in elem:
                    tag = child.tag.split("}")[-1]
                    if tag == "name":
                        name = child.text or ""
                    elif tag == "hostname":
                        hostname = child.text or ""
                instances.append({"name": name, "hostname": hostname})
        return instances


# --------------------------------------------------------------------------
# RESTCONF client (HTTP/JSON)
# --------------------------------------------------------------------------


class RestconfClient:
    def __init__(self, base: str = "http://127.0.0.1:8400", timeout: float = 5.0):
        self.base = base.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _sizes(r) -> dict:
        """Payload and header byte counts for a requests Response.

        Payload = HTTP message body. Headers = request line + request
        header block (sent) and status line + response header block
        (received), reconstructed to reflect what crosses the wire.
        """
        # --- sent ---
        body = r.request.body
        if body is None:
            sent_payload = 0
        elif isinstance(body, bytes):
            sent_payload = len(body)
        else:
            sent_payload = len(body.encode("utf-8"))
        method = r.request.method
        # Path + query portion of the URL for the request line.
        path = r.request.path_url
        request_line = f"{method} {path} HTTP/1.1\r\n"
        req_hdrs = "".join(f"{k}: {v}\r\n" for k, v in r.request.headers.items())
        sent_headers = len((request_line + req_hdrs + "\r\n").encode("utf-8"))

        # --- received ---
        recv_payload = len(r.content)
        status_line = f"HTTP/1.1 {r.status_code} {r.reason or ''}\r\n"
        resp_hdrs = "".join(f"{k}: {v}\r\n" for k, v in r.headers.items())
        recv_headers = len((status_line + resp_hdrs + "\r\n").encode("utf-8"))

        return {
            "_sent_payload": sent_payload,
            "_sent_headers": sent_headers,
            "_recv_payload": recv_payload,
            "_recv_headers": recv_headers,
        }

    def get_all(self) -> dict:
        url = f"{self.base}/restconf/data/example:system"
        r = requests.get(url, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return {"instances": data.get("example:system", []),
                "_request": f"GET {url}", "_raw": r.text, **self._sizes(r)}

    def add(self, name: str, hostname: str) -> dict:
        url = f"{self.base}/restconf/data/example:system"
        body = {"example:system": [{"name": name, "hostname": hostname}]}
        r = requests.post(url, json=body, timeout=self.timeout)
        return {"ok": r.status_code in (200, 201), "status": r.status_code,
                "_request": f"POST {url}\n{json.dumps(body)}", "_raw": r.text,
                **self._sizes(r)}

    def remove(self, name: str) -> dict:
        url = f"{self.base}/restconf/data/example:system={name}"
        r = requests.delete(url, timeout=self.timeout)
        return {"ok": r.status_code in (200, 204), "status": r.status_code,
                "_request": f"DELETE {url}", "_raw": r.text, **self._sizes(r)}

    def set(self, name: str, hostname: str) -> dict:
        url = f"{self.base}/restconf/data/example:system={name}/hostname"
        body = {"example:hostname": hostname}
        r = requests.put(url, json=body, timeout=self.timeout)
        return {"ok": r.status_code in (200, 204), "status": r.status_code,
                "_request": f"PUT {url}\n{json.dumps(body)}", "_raw": r.text,
                **self._sizes(r)}

    def reset(self) -> dict:
        url = f"{self.base}/restconf/operations/example:reset-datastore"
        r = requests.post(url, timeout=self.timeout)
        return {"ok": r.status_code == 200, "status": r.status_code,
                "_request": f"POST {url}", "_raw": r.text, **self._sizes(r)}


# --------------------------------------------------------------------------
# CORECONF client (CBOR over CoAP)
# --------------------------------------------------------------------------

SID_SYSTEM = 1700
SID_HOSTNAME = 1701
SID_NAME = 1702


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
            sizes = {
                "_sent_payload": len(payload),
                "_sent_headers": self._coap_overhead(code, path, payload),
                "_recv_payload": len(resp.payload or b""),
                "_recv_headers": self._coap_recv_overhead(resp),
            }
            return resp, sizes
        finally:
            await ctx.shutdown()

    @staticmethod
    def _coap_overhead(code, path, payload: bytes) -> int:
        """Header + options bytes of the request datagram (excl. payload).

        aiocoap assigns the message id / type / token at transmit time, so
        we reconstruct a representative CON message with a typical 1-byte
        token to measure the 4-byte CoAP header + token + encoded options
        (URI-path segments, and the payload marker when a body is present).
        """
        from aiocoap.numbers.types import Type
        probe = Message(code=code, uri=f"coap://127.0.0.1:5683{path}", payload=payload)
        probe.mid = 1
        probe.mtype = Type.CON
        probe.token = b"\x01"
        try:
            return len(probe.encode()) - len(payload)
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _coap_recv_overhead(resp) -> int:
        """Header + options bytes of the response datagram (excl. payload)."""
        try:
            return len(resp.encode()) - len(resp.payload or b"")
        except Exception:  # noqa: BLE001
            return 4  # minimum CoAP header

    def get_all(self) -> dict:
        resp, sizes = self._run(self._request(Code.GET, "/c/"))
        decoded = cbor2.loads(resp.payload) if resp.payload else {}
        instances = []
        if isinstance(decoded, dict):
            systems = decoded.get(SID_SYSTEM, {})
            if isinstance(systems, dict):
                for entry in systems.values():
                    if isinstance(entry, dict):
                        instances.append(
                            {
                                "name": entry.get(SID_NAME, ""),
                                "hostname": entry.get(SID_HOSTNAME, ""),
                            }
                        )
        return {"instances": instances, "_request": "GET coap:/c/",
                "_raw": repr(decoded), "_code": str(resp.code), **sizes}

    def add(self, name: str, hostname: str) -> dict:
        body = {"name": name, "hostname": hostname}
        resp, sizes = self._run(self._request(Code.POST, "/c/", cbor2.dumps(body)))
        return {"ok": resp.code.is_successful(), "_code": str(resp.code),
                "_request": f"POST coap:/c/  CBOR {body}",
                "_raw": resp.payload.decode("utf-8", "replace") if resp.payload else "",
                **sizes}

    def remove(self, name: str) -> dict:
        resp, sizes = self._run(self._request(Code.DELETE, f"/c/{name}"))
        return {"ok": resp.code.is_successful(), "_code": str(resp.code),
                "_request": f"DELETE coap:/c/{name}", **sizes}

    def set(self, name: str, hostname: str) -> dict:
        resp, sizes = self._run(self._request(Code.PUT, f"/c/{name}", cbor2.dumps(hostname)))
        return {"ok": resp.code.is_successful(), "_code": str(resp.code),
                "_request": f"PUT coap:/c/{name}  CBOR {hostname!r}", **sizes}

    def reset(self) -> dict:
        resp, sizes = self._run(self._request(Code.POST, "/c/reset"))
        decoded = cbor2.loads(resp.payload) if resp.payload else {}
        return {"ok": resp.code.is_successful(), "_code": str(resp.code),
                "_request": "POST coap:/c/reset", "_raw": repr(decoded), **sizes}


# --------------------------------------------------------------------------
# Registry + dispatcher used by the web UI
# --------------------------------------------------------------------------

CLIENTS = {
    "netconf": NetconfClient(),
    "restconf": RestconfClient(),
    "coreconf": CoreconfClient(),
}


def do(protocol: str, action: str, name: str | None = None, hostname: str | None = None) -> dict:
    client = CLIENTS[protocol]
    if action == "get_all":
        return client.get_all()
    if action == "add":
        return client.add(name or "", hostname or "")
    if action == "remove":
        return client.remove(name or "")
    if action == "set":
        return client.set(name or "", hostname or "")
    if action == "reset":
        return client.reset()
    raise ValueError(f"unknown action {action!r}")
