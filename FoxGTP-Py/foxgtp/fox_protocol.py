"""Wild Fox (野狐) AI protocol: packet build/parse.

Wire format (from 《野狐围棋AI接入协议》1.05 and FoxGTP.exe):

    $ABXXXX,ddd,...,ddd*hh<CR><LF>

* starts with ``$``, immediately followed by the command name (e.g. ``$FAMOVE``);
* items are separated by ``,``;
* ``*hh`` is the XOR of every byte between ``$`` and ``*`` (exclusive), two hex digits;
* terminated by CRLF.

This module is deliberately dependency-free so it can be unit-tested alone.
"""

from dataclasses import dataclass


class FoxProtocolError(ValueError):
    pass


def checksum(data: bytes) -> int:
    """XOR checksum over the bytes *after* the leading ``$``."""
    if data.startswith(b"$"):
        data = data[1:]
    value = 0
    for byte in data:
        value ^= byte
    return value & 0xFF


def build_packet(command: str, *items) -> bytes:
    """Build one packet, e.g. ``build_packet("AFPLAY", "B", "1^3^3^B")``."""
    if not command:
        raise FoxProtocolError("empty command")
    body = "$" + command
    for item in items:
        body += "," + str(item)
    raw = body.encode("utf-8")
    return raw + ("*%02X\r\n" % checksum(raw)).encode("ascii")


@dataclass
class FoxPacket:
    command: str
    items: list
    raw: str

    def __getitem__(self, index):
        return self.items[index]

    def __len__(self):
        return len(self.items)

    def __repr__(self):
        return "FoxPacket(%r, %r)" % (self.command, self.items)


def parse_packet(line: str, verify_checksum: bool = True) -> FoxPacket:
    """Parse one line into a :class:`FoxPacket`.

    Tolerances:
    * extra whitespace / missing ``$`` are accepted (some clients are sloppy);
    * a missing checksum is accepted but logged by the caller;
    * ``*`` inside the checksum area is handled by taking the *last* ``*``.
    """
    text = (line or "").strip()
    if not text:
        raise FoxProtocolError("empty packet")
    if not text.startswith("$"):
        text = "$" + text

    declared = None
    if "*" in text:
        head, _, tail = text.rpartition("*")
        tail = tail.strip()
        if tail:
            try:
                declared = int(tail[:2], 16)
            except ValueError:
                declared = -1
        text = head

    if verify_checksum and declared is not None:
        actual = checksum(text.encode("utf-8"))
        if declared >= 0 and declared != actual:
            raise FoxProtocolError(
                "checksum mismatch: declared %02X, actual %02X" % (declared, actual))

    parts = text[1:].split(",")
    command = parts[0].strip()
    if not command:
        raise FoxProtocolError("missing command name")
    items = [part.strip() for part in parts[1:]]
    return FoxPacket(command=command.upper(), items=items, raw=line.strip())


# --------------------------------------------------------------------------- moves
def parse_move(item: str):
    """Parse ``n^xx^yy^s`` into ``(move_no, x, y, color)``.

    Returns ``None`` for the "no move" placeholder ``0^0^0^N`` and for anything
    malformed, so callers can simply skip.
    """
    if not item:
        return None
    parts = item.split("^")
    if len(parts) != 4:
        return None
    try:
        move_no = int(parts[0])
        x = int(parts[1])
        y = int(parts[2])
    except ValueError:
        return None
    color = parts[3].strip().upper()[:1]
    if color not in ("B", "W"):
        return None
    if move_no == 0 and x == 0 and y == 0:
        return None
    return move_no, x, y, color


def format_move(move_no: int, x: int, y: int, color: str) -> str:
    return "%d^%d^%d^%s" % (int(move_no), int(x), int(y), str(color).upper()[:1])
