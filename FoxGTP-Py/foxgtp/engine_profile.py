"""Engine capability probing.

We never assume an engine supports an extension.  On attach we ask the engine
what it can do and store the answer here; the dialect layer then only emits
commands that are actually supported, which is what keeps odd engines alive.
"""

import os
import re

from . import gtp_protocol


def detect_family(text, hint=""):
    blob = ("%s %s" % (text or "", hint or "")).lower()
    if "katago" in blob or "kata-go" in blob:
        return "katago"
    if "leela" in blob or "leelaz" in blob or "lz" in blob.split():
        return "leela"
    if "gnu go" in blob or "gnugo" in blob:
        return "gnugo"
    if "fuego" in blob:
        return "fuego"
    if "pachi" in blob:
        return "pachi"
    if "sai" in blob.split():
        return "sai"
    return "unknown"


def _classify_echo(response):
    """Decide whether a response echoed the command id.

    Only unambiguous shapes are used: ``=3 text`` -> yes, ``= text`` -> no.
    Empty bodies (``=3``) are skipped because a numeric payload is possible.
    """
    if response is None:
        return None
    raw = (response.raw or "").lstrip()
    if not raw.startswith("="):
        return None
    rest = raw[1:].lstrip()
    if re.match(r"^\d+\s+\S", rest):
        return True
    if rest and not re.match(r"^\d+$", rest):
        return False
    return None


class EngineProfile:
    """What the attached engine can do."""

    def __init__(self):
        self.name = ""
        self.version = ""
        self.family = "unknown"
        self.commands = set()
        self.list_ok = False
        self.echoes_id = True
        self.probe_ok = False
        self.hint = ""

    # -- generic ---------------------------------------------------------
    def supports(self, command, default=True):
        if self.list_ok:
            return command in self.commands
        return default

    # -- shortcuts -------------------------------------------------------
    @property
    def kata(self):
        if self.family == "katago":
            return True
        if self.list_ok:
            return ("kata-genmove_analyze" in self.commands
                    or "kata-set-param" in self.commands)
        return False

    @property
    def kata_analyze(self):
        return self.supports("kata-genmove_analyze", self.family == "katago")

    @property
    def kata_analyze_only(self):
        return self.supports("kata-analyze", self.family == "katago")

    @property
    def lz_analyze(self):
        return self.supports("lz-genmove_analyze", False) or self.supports("lz-analyze", False)

    @property
    def undo(self):
        return self.supports("undo", self.family in ("katago", "leela", "gnugo"))

    @property
    def stop(self):
        return self.supports("stop", self.family in ("katago", "leela"))

    @property
    def final_score(self):
        return self.supports("final_score", True)

    @property
    def free_handicap(self):
        return self.supports("set_free_handicap", True)

    @property
    def fixed_handicap(self):
        return self.supports("fixed_handicap", self.family in ("gnugo", "fuego", "pachi"))

    @property
    def place_free_handicap(self):
        return self.supports("place_free_handicap", False)

    @property
    def time_settings(self):
        return self.supports("time_settings", True)

    @property
    def time_left(self):
        return self.supports("time_left", True)

    @property
    def kata_rules(self):
        return self.supports("kata-set-rules", self.family == "katago")

    @property
    def kata_params(self):
        return self.supports("kata-set-param", self.family == "katago")

    @property
    def display_name(self):
        bits = [b for b in (self.name, self.version) if b]
        return " ".join(bits) if bits else (self.family or "未知引擎")

    def summary(self):
        caps = []
        if self.kata:
            caps.append("kata")
        if self.kata_analyze:
            caps.append("kata-analyze")
        if self.lz_analyze:
            caps.append("lz-analyze")
        if self.undo:
            caps.append("undo")
        if self.final_score:
            caps.append("final_score")
        if self.free_handicap:
            caps.append("free-handicap")
        if self.time_settings:
            caps.append("time")
        if self.kata_rules:
            caps.append("rules")
        caps.append("id" if self.echoes_id else "no-id")
        return "%s [%s]" % (self.display_name, ",".join(caps))

    def as_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "family": self.family,
            "commands": sorted(self.commands),
            "list_ok": self.list_ok,
            "echoes_id": self.echoes_id,
            "kata": self.kata,
            "kata_analyze": self.kata_analyze,
            "lz_analyze": self.lz_analyze,
            "undo": self.undo,
            "stop": self.stop,
            "final_score": self.final_score,
            "free_handicap": self.free_handicap,
            "time_settings": self.time_settings,
            "kata_rules": self.kata_rules,
            "summary": self.summary(),
        }


# Commands worth asking about one by one when list_commands is unavailable.
_PROBE_COMMANDS = [
    "kata-genmove_analyze", "kata-analyze", "kata-set-param", "kata-set-rules",
    "kata-raw-nn", "lz-genmove_analyze", "lz-analyze", "undo", "stop",
    "ponderhit", "final_score", "set_free_handicap", "fixed_handicap",
    "place_free_handicap", "time_settings", "time_left", "boardsize", "komi",
    "genmove", "play", "clear_board", "protocol_version", "name", "version",
]


def probe(session, hint="", timeout=2.5, logger=None):
    """Ask the engine what it is.  Must be called while the queue is empty."""

    def log(message):
        if logger:
            logger(message)

    profile = EngineProfile()
    profile.hint = hint or ""

    version_resp = session.request("protocol_version", timeout=timeout,
                                   purpose="protocol_version")
    if version_resp is not None:
        profile.probe_ok = True
        profile.version = (version_resp.body or "").strip().split("\n")[0][:60]

    name_resp = session.request("name", timeout=timeout, purpose="name")
    if name_resp is not None and name_resp.ok:
        profile.name = (name_resp.body or "").strip().split("\n")[0][:80]

    if name_resp is not None and name_resp.ok:
        version_resp2 = session.request("version", timeout=timeout, purpose="version")
        if version_resp2 is not None and version_resp2.ok and version_resp2.body.strip():
            profile.version = version_resp2.body.strip().split("\n")[0][:60]

    list_resp = session.request("list_commands", timeout=max(timeout, 3.0),
                                purpose="list_commands", multiline=True)
    if list_resp is not None and list_resp.ok and list_resp.body.strip():
        commands = set()
        for token in re.split(r"[\s,]+", list_resp.body):
            token = token.strip()
            if token and re.match(r"^[A-Za-z][A-Za-z0-9_\-]*$", token):
                commands.add(token)
        if commands:
            profile.commands = commands
            profile.list_ok = True

    # Echo detection: `name` has a non-numeric body, so it is unambiguous.
    detected = _classify_echo(name_resp)
    if detected is None:
        detected = _classify_echo(list_resp)
    if detected is None and session.echoes_id and session.saw_id_token:
        detected = True
    if detected is not None:
        profile.echoes_id = detected

    profile.family = detect_family("%s %s" % (profile.name, profile.version), hint)

    if not profile.list_ok:
        found = set()
        for command in _PROBE_COMMANDS:
            resp = session.request("known_command %s" % command,
                                   timeout=min(timeout, 1.5),
                                   purpose="known_command")
            if resp is not None and resp.ok:
                if resp.body.strip().lower() in ("true", "1", "yes"):
                    found.add(command)
        if found:
            profile.commands = found
            # partial knowledge: keep defaults for core commands
            log("该引擎不支持 list_commands，已用 known_command 探测到 %d 条命令" % len(found))

    log("引擎能力: " + profile.summary())
    return profile


def engine_hint(path="", args=""):
    """Short hint string used for family detection (exe name + arguments)."""
    base = os.path.basename(path or "")
    return ("%s %s" % (base, args or "")).strip()
