"""Dialect layer: turn "what Wild Fox needs" into "what this engine understands".

The translation rules deliberately mirror FoxGTP 2.9 (it is the reference for
compatibility), with a few additions that do not hurt compatibility:

* optional ``kata-genmove_analyze`` for candidate moves (falls back to plain
  ``genmove`` automatically if the engine rejects it);
* optional ``kata-set-param`` for search limits (KataGo only);
* ``set_free_handicap`` -> ``fixed_handicap``/``place_free_handicap`` -> plain
  ``play`` fallback chain;
* ``kata-set-rules`` only when the engine advertises it.
"""

from dataclasses import dataclass, field
import math

from .gtp_protocol import format_komi

# Handicap points in GTP's canonical order, used to detect whether a Fox
# handicap set can be expressed with `fixed_handicap N`.
_STANDARD_HANDICAP = {
    2: ["D4", "Q16"],
    3: ["D4", "Q16", "D16"],
    4: ["D4", "Q16", "D16", "Q4"],
    5: ["D4", "Q16", "D16", "Q4", "K10"],
    6: ["D4", "Q16", "D16", "Q4", "D10", "Q10"],
    7: ["D4", "Q16", "D16", "Q4", "D10", "Q10", "K10"],
    8: ["D4", "Q16", "D16", "Q4", "D10", "Q10", "K10", "K4"],
    9: ["D4", "Q16", "D16", "Q4", "D10", "Q10", "K10", "K4", "K16"],
}


@dataclass
class DialectOptions:
    # 与 FoxGTP 注册表里的四个键一一对应
    use_go_byoyomi: bool = False          # UseGoByoYomi
    use_data_transfer_time: bool = False  # UseDataTransferTime
    data_transfer_time: int = 0           # DataTransferTime（秒）
    use_ai_cal_time: bool = False         # 指定 AI 读秒时间
    ai_cal_time: int = 5                  # AICalTime（秒）

    # 计算量（KataGo 专用；其他引擎用 ai_cal_time / data_transfer_time 控制）
    max_time: float = 0.0
    max_visits: int = 0
    max_playouts: int = 0

    # 是否用 analyze 类命令换取候选点/胜率；失败会自动退回 genmove
    use_analyze: bool = True
    analyze_interval_ms: int = 50
    analyze_max_moves: int = 12

    # 规则（仅当引擎支持 kata-set-rules）
    rule: str = ""

    # 让子：auto / free / fixed / play
    handicap_mode: str = "auto"


class Dialect:
    def __init__(self, profile, options=None):
        self.profile = profile
        self.options = options or DialectOptions()
        self.board_size = 19
        self.main_time = 0
        self.byo_time = 0
        self.byo_count = 0

    # ------------------------------------------------------------------ 时间
    def byoyomi(self, main_time=None, byo_time=None, byo_count=None):
        """Return ``(main, byo, stones)`` in the engine's dialect.

        Fox sends "N seconds x M periods" (Go convention).  GTP's ``s`` argument
        is *stones per byo-yomi period* (Canadian byo-yomi), unless the engine
        is known to understand the Go convention.  FoxGTP exposes exactly this
        switch; when the switch is off we send 1 stone per period, which every
        engine understands.
        """
        main = self.main_time if main_time is None else main_time
        byo = self.byo_time if byo_time is None else byo_time
        count = self.byo_count if byo_count is None else byo_count
        main = max(0, int(main or 0))
        byo = max(0, int(byo or 0))
        count = max(1, int(count or 1))

        opts = self.options
        if opts.use_ai_cal_time and opts.ai_cal_time > 0:
            byo = int(opts.ai_cal_time)
        elif opts.use_data_transfer_time:
            byo = max(1, byo - max(0, int(opts.data_transfer_time)))

        # 非 KataGo 引擎没有 maxTime 参数：用读秒时间给它封顶，避免算满整个读秒
        if not self.profile.kata and opts.max_time and opts.max_time > 0:
            byo = max(1, min(byo, int(math.ceil(opts.max_time))))

        stones = count if opts.use_go_byoyomi else 1
        return main, byo, stones

    def time_settings_commands(self):
        if not self.profile.time_settings:
            return []
        main, byo, stones = self.byoyomi()
        return ["time_settings %d %d %d" % (main, byo, stones)]

    def time_left_commands(self, color):
        if not self.profile.time_left:
            return []
        main, byo, _stones = self.byoyomi()
        return ["time_left %s %d %d" % (color.upper(), main, byo)]

    # ------------------------------------------------------------------ 规则
    def rules_command(self):
        rule = (self.options.rule or "").strip().lower()
        if not rule or not self.profile.kata_rules:
            return ""
        mapping = {
            "chinese": "chinese", "japanese": "japanese", "korean": "korean",
            "tromp-taylor": "tromp-taylor", "aga": "aga",
            "nz": "new-zealand", "new-zealand": "new-zealand",
        }
        return "kata-set-rules %s" % mapping.get(rule, rule)

    # ------------------------------------------------------------------ 让子
    def handicap_commands(self, vertices):
        verts = [v for v in (vertices or []) if v and v.upper() != "PASS"]
        if not verts:
            return []
        mode = (self.options.handicap_mode or "auto").lower()

        if mode in ("auto", "free") and self.profile.free_handicap:
            return ["set_free_handicap " + " ".join(verts)]

        count = len(verts)
        standard = _STANDARD_HANDICAP.get(count)
        is_standard = standard is not None and set(standard) == {v.upper() for v in verts}
        if mode in ("auto", "fixed") and is_standard:
            if self.profile.fixed_handicap:
                return ["fixed_handicap %d" % count]
            if self.profile.place_free_handicap:
                return ["place_free_handicap %d" % count]

        # 最保守：逐子摆放（任何引擎都支持）
        return ["play B %s" % vertex for vertex in verts]

    # ------------------------------------------------------------------ 开局
    def setup_commands(self, board_size, komi, handicap_vertices, main_time,
                       byo_time, byo_count):
        self.board_size = int(board_size or 19)
        self.main_time = main_time
        self.byo_time = byo_time
        self.byo_count = byo_count

        commands = ["clear_board", "boardsize %d" % self.board_size,
                    "komi %s" % format_komi(komi)]
        rule_cmd = self.rules_command()
        if rule_cmd:
            commands.append(rule_cmd)
        commands.extend(self.time_settings_commands())
        commands.extend(self.handicap_commands(handicap_vertices))
        return commands

    # ------------------------------------------------------------------ 行棋
    def play_command(self, color, vertex):
        color = color.upper()
        if vertex in (None, "", "pass", "PASS"):
            return "play %s pass" % color
        return "play %s %s" % (color, vertex)

    def genmove_command(self, color, want_analysis=True):
        """Return ``(command, mode)`` with mode in ``plain``/``kata-analyze``/``lz-analyze``."""
        color = color.upper()
        opts = self.options
        if want_analysis and opts.use_analyze and self.profile.kata_analyze:
            interval = max(10, int(opts.analyze_interval_ms))
            maxmoves = max(1, int(opts.analyze_max_moves))
            return ("kata-genmove_analyze %s interval %d maxmoves %d"
                    % (color, interval, maxmoves), "kata-analyze")
        return "genmove %s" % color, "plain"

    def param_commands(self):
        opts = self.options
        commands = []
        if not self.profile.kata_params:
            return commands
        if opts.max_time and opts.max_time > 0:
            commands.append("kata-set-param maxTime %.2f" % float(opts.max_time))
        if opts.max_visits and opts.max_visits > 0:
            commands.append("kata-set-param maxVisits %d" % int(opts.max_visits))
        if opts.max_playouts and opts.max_playouts > 0:
            commands.append("kata-set-param maxPlayouts %d" % int(opts.max_playouts))
        return commands

    def final_score_command(self):
        if not self.profile.final_score:
            return None
        return "final_score"

    def stop_command(self):
        return "stop" if self.profile.stop else None

    def undo_command(self):
        return "undo" if self.profile.undo else None
