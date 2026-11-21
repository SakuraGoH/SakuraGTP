"""Game state: the two move sequences and the re-sync plan.

This is a faithful re-implementation of FoxGTP's core idea:

* the Wild Fox move list is the single source of truth;
* the engine keeps a second list of "moves I have already played";
* on every Fox notification we only append the difference, and when the two
  lists disagree we rebuild the whole position with ``clear_board`` + replay.

Because ``undo`` is never required, this works with *any* engine that can play
moves, which is the reason FoxGTP is compatible with so many of them.
"""

from dataclasses import dataclass, field

PASS = "pass"


@dataclass
class SyncPlan:
    kind: str                     # "none" | "append" | "rebuild"
    events: list = field(default_factory=list)
    reason: str = ""

    def __bool__(self):
        return self.kind != "none"


def plan_sync(engine_events, fox_events, dirty=False, reason=""):
    """Diff the engine list against the Fox list.

    * identical prefix and engine is shorter -> append the missing moves;
    * engine longer than Fox, or a mismatch, or ``dirty`` -> rebuild.
    """
    engine_events = list(engine_events or [])
    fox_events = list(fox_events or [])
    if dirty:
        return SyncPlan("rebuild", fox_events, reason or "引擎局面不可信")

    shared = 0
    while (shared < len(engine_events) and shared < len(fox_events)
           and engine_events[shared] == fox_events[shared]):
        shared += 1

    if shared < len(engine_events):
        return SyncPlan("rebuild", fox_events, "引擎与野狐棋谱不一致（第 %d 手）" % (shared + 1))
    if shared == len(fox_events):
        return SyncPlan("none", [], "")
    return SyncPlan("append", fox_events[shared:], "补 %d 手" % (len(fox_events) - shared))


class GameState:
    """Everything the controller knows about the current game."""

    def __init__(self):
        self.board_size = 19
        self.komi = 6.5
        self.main_time = 0
        self.byo_time = 0
        self.byo_count = 0
        self.rule = ""
        self.ai_color = "B"

        self.handicap = []            # GTP vertices placed by setup
        self.events = []              # [(color, vertex|PASS)] chronological
        self.engine_events = []       # what the engine has already played
        self.fox_moves = {}           # move number -> (color, vertex)
        self.last_move_no = 0
        self.remaining = (0, 0, 0)    # last $FATIMELEFT (main, byo, count)

        self.dirty = False            # engine position must be rebuilt
        self.needs_status = False     # a move number gap was seen

    # ------------------------------------------------------------------ reset
    def reset(self):
        self.events = []
        self.engine_events = []
        self.fox_moves = {}
        self.last_move_no = 0
        self.dirty = True
        self.needs_status = False

    # ------------------------------------------------------------------ Fox input
    def load_status(self, ai_color, moves, handicap=None):
        """Authoritative state from ``$FASTATUS``.

        ``moves`` is ``[(move_no, color, vertex)]`` as parsed by the controller.
        Handicap stones are removed from the front of the list because they were
        already placed by ``set_free_handicap``.
        """
        self.ai_color = ai_color or "B"
        if handicap is not None:
            self.handicap = list(handicap)
        usable = list(moves)
        if self.handicap:
            wanted = set(self.handicap)
            dropped = 0
            while usable and dropped < len(self.handicap):
                _no, color, vertex = usable[0]
                if color == "B" and vertex in wanted:
                    usable.pop(0)
                    dropped += 1
                else:
                    break
        self.events = [(color, vertex) for _no, color, vertex in usable]
        self.fox_moves = {}
        for index, vertex in enumerate(self.handicap):
            self.fox_moves[-index] = ("B", vertex)
        self.last_move_no = 0
        for no, color, vertex in usable:
            self.fox_moves[no] = (color, vertex)
            self.last_move_no = max(self.last_move_no, no)
        # engine_events 保留：由 plan_sync 决定「只补差异」还是「整盘重建」
        self.needs_status = False
        return len(usable)

    def ingest_move(self, move_no, color, vertex):
        """Add one Fox move. Returns ``new``/``echo``/``duplicate``/``gap``."""
        last = (self.events[-1] if self.events else None)
        if last == (color, vertex) and move_no <= self.last_move_no:
            self.fox_moves[move_no] = (color, vertex)
            return "echo"
        if move_no <= self.last_move_no and move_no in self.fox_moves:
            return "duplicate"

        gap = move_no - self.last_move_no
        self.events.append((color, vertex))
        self.fox_moves[move_no] = (color, vertex)
        self.last_move_no = max(self.last_move_no, move_no)
        if gap > 1:
            self.dirty = True
            self.needs_status = True
            return "gap"
        return "new"

    def ingest_pass(self, color, expect_duplicate=True):
        """Record a pass. Returns True when it was new."""
        if expect_duplicate and self.events:
            last_color, last_vertex = self.events[-1]
            if last_vertex == PASS and last_color == color:
                return False
        self.events.append((color, PASS))
        return True

    # ------------------------------------------------------------------ engine moves
    def accept_engine_move(self, color, vertex):
        """The engine has *already* played this move via genmove.

        We must remember it, otherwise the engine's own move would be played a
        second time when Wild Fox echoes it back.
        """
        no = self.last_move_no + 1
        self.last_move_no = no
        self.events.append((color, vertex))
        self.engine_events.append((color, vertex))
        if vertex != PASS:
            self.fox_moves[no] = (color, vertex)
        return no

    def engine_played(self, events):
        self.engine_events = list(events)

    # ------------------------------------------------------------------ sync
    def next_plan(self):
        return plan_sync(self.engine_events, self.events, self.dirty,
                         "标记为需要重建")

    def mark_synced(self):
        self.engine_events = list(self.events)
        self.dirty = False

    def mark_dirty(self):
        self.dirty = True

    # ------------------------------------------------------------------ helpers
    def turn_color(self):
        """Color that must play next, derived from the move list."""
        if not self.events:
            return "B" if not self.handicap else "W"
        last_color = self.events[-1][0]
        return "W" if last_color == "B" else "B"

    def is_ai_turn(self):
        return self.turn_color() == self.ai_color

    def ordered_moves(self):
        """``[(no, color, vertex)]`` sorted by move number, for board display."""
        return sorted((no, color, vertex) for no, (color, vertex) in self.fox_moves.items())

    def describe(self):
        return "棋盘%d 贴目%s AI执%s 手数%d 引擎同步%d" % (
            self.board_size, self.komi, self.ai_color,
            self.last_move_no, len(self.engine_events))
