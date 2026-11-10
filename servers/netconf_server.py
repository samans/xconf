"""Hand-rolled NETCONF server over plain TCP.

This is a deliberately minimal, dependency-free NETCONF server intended
for local testing. It implements enough of RFC 6241 to be driven by a
real client over the wire:

  * The <hello> capability exchange.
  * NETCONF 1.0 end-of-message framing (the ]]>]]> delimiter).
  * RPC operations: get, get-config, edit-config, lock, unlock,
    close-session, kill-session.
  * A vendor RPC `reset-datastore` (namespace urn:example:xconf) that
    restores the datastore to YANG defaults.

It does NOT use SSH (the standard transport). Transport is plain TCP so
the lab stays dependency-free. See FULL_IMPLEMENTATION.md for what a
standards-compliant deployment requires.

The datastore holds the `example` YANG module:
    <system xmlns="urn:example:simple"><hostname>...</hostname></system>
"""

from __future__ import annotations

import os
import socketserver
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.datastore import Datastore  # noqa: E402

HOST = "127.0.0.1"
PORT = 8300
STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state",
    "netconf.json",
)

NS_NETCONF = "urn:ietf:params:xml:ns:netconf:base:1.0"
NS_EXAMPLE = "urn:example:simple"
NS_XCONF = "urn:example:xconf"
DELIM = b"]]>]]>"

SERVER_HELLO = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">'
    "<capabilities>"
    "<capability>urn:ietf:params:netconf:base:1.0</capability>"
    "<capability>urn:example:simple</capability>"
    "</capabilities>"
    "<session-id>1</session-id>"
    "</hello>"
)

datastore = Datastore(STATE_FILE)


def _local(tag: str) -> str:
    """Strip the XML namespace from an ElementTree tag."""
    return tag.split("}")[-1] if "}" in tag else tag


def _config_xml() -> str:
    """Render the current datastore as NETCONF <data> XML."""
    hostname = datastore.get_hostname()
    return (
        f'<system xmlns="{NS_EXAMPLE}">'
        f"<hostname>{_escape(hostname)}</hostname>"
        f"</system>"
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _rpc_reply(message_id: str, inner: str) -> str:
    mid = f' message-id="{message_id}"' if message_id else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rpc-reply xmlns="{NS_NETCONF}"{mid}>'
        f"{inner}"
        "</rpc-reply>"
    )


def _rpc_error(message_id: str, message: str, tag: str = "operation-failed") -> str:
    inner = (
        "<rpc-error>"
        "<error-type>application</error-type>"
        f"<error-tag>{tag}</error-tag>"
        "<error-severity>error</error-severity>"
        f"<error-message>{_escape(message)}</error-message>"
        "</rpc-error>"
    )
    return _rpc_reply(message_id, inner)


def handle_rpc(rpc_xml: str) -> str:
    """Parse a single <rpc> element and produce an <rpc-reply>."""
    try:
        root = ET.fromstring(rpc_xml)
    except ET.ParseError as exc:
        return _rpc_error("", f"malformed XML: {exc}", "malformed-message")

    message_id = root.attrib.get("message-id", "")
    # The operation is the single child of <rpc>.
    op = None
    for child in root:
        op = child
        break
    if op is None:
        return _rpc_error(message_id, "empty rpc", "missing-element")

    name = _local(op.tag)

    if name in ("get", "get-config"):
        return _rpc_reply(message_id, f"<data>{_config_xml()}</data>")

    if name in ("lock", "unlock"):
        # No real multi-session locking in this lab; acknowledge.
        return _rpc_reply(message_id, "<ok/>")

    if name in ("close-session", "kill-session"):
        return _rpc_reply(message_id, "<ok/>")

    if name == "reset-datastore":
        datastore.reset()
        return _rpc_reply(message_id, "<ok/>")

    if name == "edit-config":
        return _handle_edit_config(message_id, op)

    return _rpc_error(message_id, f"unsupported operation: {name}", "operation-not-supported")


def _handle_edit_config(message_id: str, op: ET.Element) -> str:
    """Apply an edit-config whose <config> carries example:system/hostname."""
    # Find the hostname leaf anywhere under the operation.
    hostname = None
    for elem in op.iter():
        if _local(elem.tag) == "hostname":
            hostname = elem.text if elem.text is not None else ""
            break
    if hostname is None:
        return _rpc_error(
            message_id,
            "edit-config did not contain example:system/hostname",
            "missing-element",
        )
    datastore.set_hostname(hostname)
    return _rpc_reply(message_id, "<ok/>")


class NetconfHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        # 1. Send our hello immediately.
        self._send(SERVER_HELLO)
        buffer = b""
        hello_consumed = False
        while True:
            chunk = self.request.recv(4096)
            if not chunk:
                break
            buffer += chunk
            while DELIM in buffer:
                message, buffer = buffer.split(DELIM, 1)
                text = message.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                if not hello_consumed and "<hello" in text:
                    # Client hello; nothing to reply.
                    hello_consumed = True
                    continue
                reply = handle_rpc(text)
                self._send(reply)
                if "close-session" in text or "kill-session" in text:
                    return

    def _send(self, text: str) -> None:
        self.request.sendall(text.encode("utf-8") + DELIM)


class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    with ThreadedTCPServer((HOST, PORT), NetconfHandler) as server:
        print(f"[netconf] listening on {HOST}:{PORT} (plain TCP, NETCONF 1.0 framing)")
        print(f"[netconf] datastore: {STATE_FILE}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[netconf] shutting down")


if __name__ == "__main__":
    main()
