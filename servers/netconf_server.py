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

The datastore holds the `example` YANG module, a keyed list:
    <system xmlns="urn:example:simple">
      <name>sys1</name><hostname>router-1</hostname>
    </system>
    <system xmlns="urn:example:simple">
      <name>sys2</name><hostname>router-2</hostname>
    </system>

edit-config conventions used by this lab:
  * A <system> whose <name> carries operation="delete" (or "remove")
    removes that instance.
  * Any other <system> creates the instance if missing, or updates its
    <hostname> if it already exists (merge semantics).
"""

from __future__ import annotations

import os
import socketserver
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.datastore import Datastore, InstanceExists, InstanceNotFound  # noqa: E402

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
    """Render the current datastore as NETCONF <data> XML (all instances)."""
    data = datastore.get()
    parts = []
    for entry in data.get("example:system", []):
        parts.append(
            f'<system xmlns="{NS_EXAMPLE}">'
            f"<name>{_escape(entry.get('name', ''))}</name>"
            f"<hostname>{_escape(entry.get('hostname', ''))}</hostname>"
            f"</system>"
        )
    return "".join(parts)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
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
        return _rpc_reply(message_id, "<ok/>")

    if name in ("close-session", "kill-session"):
        return _rpc_reply(message_id, "<ok/>")

    if name == "reset-datastore":
        datastore.reset()
        return _rpc_reply(message_id, "<ok/>")

    if name == "edit-config":
        return _handle_edit_config(message_id, op)

    return _rpc_error(message_id, f"unsupported operation: {name}", "operation-not-supported")


def _elem_text(parent: ET.Element, child_local: str):
    for elem in parent:
        if _local(elem.tag) == child_local:
            return elem
    return None


def _handle_edit_config(message_id: str, op: ET.Element) -> str:
    """Apply an edit-config carrying one or more <system> list entries.

    The per-entry NETCONF 'operation' attribute (on the <system> element or
    its <name> child) selects the semantics, per RFC 6241 section 7.2:

      * create  -> the instance MUST NOT already exist (else data-exists).
      * merge   -> create if absent, otherwise update the hostname (default
                   when no operation attribute is present).
      * replace -> same as merge for this single-leaf model.
      * delete  -> the instance MUST exist (else data-missing).
      * remove  -> delete if present; no error if absent.
    """
    systems = [elem for elem in op.iter() if _local(elem.tag) == "system"]
    if not systems:
        return _rpc_error(
            message_id,
            "edit-config did not contain any example:system entry",
            "missing-element",
        )

    for system in systems:
        name_elem = _elem_text(system, "name")
        host_elem = _elem_text(system, "hostname")
        if name_elem is None or not (name_elem.text or "").strip():
            return _rpc_error(message_id, "system entry missing key 'name'", "missing-element")
        key = name_elem.text.strip()
        hostname = (
            host_elem.text if host_elem is not None and host_elem.text is not None else None
        )

        op_attr = (_operation_attr(system) or _operation_attr(name_elem) or "merge")

        if op_attr in ("delete", "remove"):
            try:
                datastore.remove_instance(key)
            except InstanceNotFound:
                if op_attr == "delete":
                    return _rpc_error(
                        message_id, f"instance '{key}' does not exist", "data-missing"
                    )
            continue

        if op_attr == "create":
            try:
                datastore.add_instance(key, hostname)
            except InstanceExists:
                return _rpc_error(
                    message_id,
                    f"instance '{key}' already exists",
                    "data-exists",
                )
            continue

        # merge / replace: create if absent, update hostname if present.
        try:
            datastore.add_instance(key, hostname)
        except InstanceExists:
            if hostname is not None:
                datastore.set_hostname(key, hostname)

    return _rpc_reply(message_id, "<ok/>")


def _operation_attr(elem: ET.Element):
    """Return the NETCONF 'operation' attribute value, namespace-agnostic."""
    for attr, value in elem.attrib.items():
        if _local(attr) == "operation":
            return value
    return None


class NetconfHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
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
