"""GTP protocol helpers: line classification, coordinates, tolerant result parsing.

Everything here is pure and side-effect free; the session/controller layers use
these primitives.  The parsers are intentionally forgiving because real engines
disagree on formatting:

    =1 Q16          GTP with command id
    = Q16           GTP without id
    play Q16        bare line (KataGo's analyze commands)
    Leela: Q16      engines that prefix their output with their own name
    B+3.5 / W+R / 0 / Draw / White wins by 3.5    final_score variants
"""

import re

VERTEX_LETTERS = "ABCDEFGHJKLMNOPQRST"

# "=1 ..." / "?12 ..." / "= ..." / "?" / "="
_MARK_RE = re.compile(r"^\s*([=?])(.*)$", re.DOTALL)
_ID_RE = re.compile(r"^\s*(\d+)(?=$|\s)")

# "Leela: ", "GNU Go: ", "Pachi: " ...
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _.+\-]{0,23}:\s+")

_VERTEX_RE = re.compile(r"^([A-HJ-Ta-hj-t])(\d{1,2})$")


# --------------------------------------------------------------------------- lines
def parse_marker(line: str):
    """Return ``(ok, rest)`` if the line starts a GTP response, else ``None``.

    ``rest`` is everything after ``=``/``?`` with leading spaces removed.
    """
    match = _MARK_RE.match(line or "")
    if not match:
        return None
    return match.group(1) == "=", match.group(2).strip()


def split_id(body: str, known_ids=None):
    """Split a leading command id off a response body.

    ``known_ids`` (an iterable/container) makes this safe: the digits are only
    treated as an id when a command with that id is actually outstanding, which
    avoids eating numeric payloads such as ``protocol_version`` -> ``2``.
    """
    match = _ID_RE.match(body or "")
    if not match:
        return None, body or ""
    candidate = int(match.group(1))
    rest = body[match.end():]
    if known_ids is not None and candidate not in known_ids:
        return None, body or ""
    return candidate, rest.strip()


def strip_engine_prefix(text: str, max_layers: int = 2) -> str:
    """Drop ``Leela:`` / ``GNU Go:`` style prefixes (FoxGTP 2.1 does this too)."""
    text = (text or "").strip()
    for _ in range(max_layers):
        match = _PREFIX_RE.match(text)
        if not match:
            break
        rest = text[match.end():].strip()
        if not rest:
            break
        text = rest
    return text


def is_blank(line: str) -> bool:
    return not (line or "").strip()


# --------------------------------------------------------------------------- coordinates
def is_vertex(token: str) -> bool:
    return bool(_VERTEX_RE.match((token or "").strip()))


def xy_to_vertex(x: int, y: int, board_size: int = 19) -> str:
    """Fox coordinates (origin top-left) -> GTP vertex. Returns ``pass`` if out of board."""
    if 0 <= x < board_size and 0 <= y < board_size and x < len(VERTEX_LETTERS):
        return "%s%d" % (VERTEX_LETTERS[x], board_size - y)
    return "pass"


def vertex_to_xy(vertex: str, board_size: int = 19):
    """GTP vertex -> Fox coordinates, ``None`` for pass/resign/invalid."""
    if not vertex:
        return None
    text = vertex.strip().upper()
    if text in ("PASS", "RESIGN"):
        return None
    match = _VERTEX_RE.match(text)
    if not match:
        return None
    letter, number = match.group(1).upper(), int(match.group(2))
    if letter not in VERTEX_LETTERS:
        return None
    x = VERTEX_LETTERS.index(letter)
    y = board_size - number
    if not (0 <= x < board_size and 0 <= y < board_size):
        return None
    return x, y


# --------------------------------------------------------------------------- values
def format_komi(komi) -> str:
    """``6.5`` -> ``6.5``, ``7`` -> ``7``, ``6.75`` -> ``6.75`` (never lose precision)."""
    try:
        value = float(komi)
    except (TypeError, ValueError):
        return "6.5"
    if abs(value - round(value)) < 1e-9:
        return "%d" % int(round(value))
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return text or "0"


def parse_move_reply(body: str):
    """Interpret a genmove reply.

    Returns ``("move", "Q16")`` / ``("pass", None)`` / ``("resign", None)`` /
    ``(None, None)``.  Handles ``play Q16`` style replies and trailing lines.
    """
    text = strip_engine_prefix(body)
    if not text:
        return None, None
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n") if line.strip()]
    if not lines:
        return None, None
    # the last non-empty line carries the move in analyze output
    for line in reversed(lines):
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        lowered = [token.lower().strip(".") for token in tokens]
        if "resign" in lowered:
            return "resign", None
        if "pass" in lowered:
            return "pass", None
        for token in reversed(tokens):
            token = token.strip(".")
            if is_vertex(token):
                return "move", token.upper()
    return None, None


def parse_score_reply(body: str):
    """Interpret a ``final_score`` reply.

    Returns ``(winner, points, resign)`` where ``winner`` is ``"B"``/``"W"``/``"D"``
    or ``None`` when it cannot be understood, ``points`` is a float (None if the
    game ended by resignation) and ``resign`` a bool.
    """
    text = strip_engine_prefix(body)
    if not text:
        return None, None, False
    first = text.split("\n")[0].strip()
    low = first.lower()

    if low in ("0", "0.0", "draw", "jigo", "tie", "dame"):
        return "D", 0.0, False

    winner = None
    rest = ""

    match = re.match(r"^([BW])\s*([+\-])\s*(.+)$", first, re.IGNORECASE)
    if match:
        winner = match.group(1).upper()
        rest = match.group(3).strip()
    else:
        match = re.match(r"^(black|white|b|w)\b(.*)$", low)
        if match:
            word = match.group(1)
            winner = "B" if word in ("b", "black") else "W"
            rest = match.group(2).strip()
        else:
            match = re.search(r"\b(black|white)\b.*?([0-9]+(?:\.[0-9]+)?)", low)
            if match:
                winner = "B" if match.group(1) == "black" else "W"
                rest = match.group(2)

    if winner is None:
        return None, None, False

    if re.search(r"\bresign|\bres\b|投子|中盘", (rest + " " + low)):
        return winner, None, True

    number = re.search(r"[0-9]+(?:\.[0-9]+)?", rest or first)
    if not number:
        return winner, None, True
    try:
        return winner, float(number.group(0)), False
    except ValueError:
        return None, None, False


def fox_score_string(winner, points, resign=False) -> str:
    """Convert parsed score into the Fox ``$AFSCORE`` payload: ``B+350``/``W+R``/``0``."""
    if winner == "D":
        return "0"
    if winner not in ("B", "W"):
        return "error"
    if resign or points is None:
        return "%s+R" % winner
    return "%s+%d" % (winner, int(round(points * 100)))


def parse_fox_result(item: str):
    """Parse a Fox ``$FARESULT`` payload (``W+350``/``B+R``/``0``) for logging."""
    text = (item or "").strip()
    if not text or text == "0":
        return "和棋"
    match = re.match(r"^([BW])\+(R|\d+)$", text, re.IGNORECASE)
    if not match:
        return text
    color = "黑" if match.group(1).upper() == "B" else "白"
    tail = match.group(2).upper()
    if tail == "R":
        return "%s中盘胜" % color
    return "%s胜 %.2f 目" % (color, int(tail) / 100.0)
