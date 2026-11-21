"""Communication log: live view + optional file, with FoxGTP-style timestamps.

File layout mirrors FoxGTP (``logs/YYYYMMDD.log``) so old habits still work.
"""

import datetime
import os
import threading

IN, OUT, INFO, ERROR = "in", "out", "info", "error"

_ARROWS = {
    (IN, "fox"): "<----",
    (OUT, "fox"): "---->",
    (IN, "gtp"): "<----",
    (OUT, "gtp"): "---->",
}


class LogBook:
    def __init__(self, on_entry=None, max_entries=5000):
        self.on_entry = on_entry
        self.max_entries = max_entries
        self.entries = []                 # [(timestamp, channel, direction, text)]
        self._lock = threading.RLock()
        self._file = None
        self._file_date = None
        self._file_path = ""
        self.enabled = False
        self.timestamp = True
        self.log_dir = "logs"

    # ------------------------------------------------------------------ setup
    def configure(self, enabled, log_dir="logs", timestamp=True):
        with self._lock:
            self.enabled = bool(enabled)
            self.log_dir = log_dir or "logs"
            self.timestamp = bool(timestamp)
            self._close_file()

    def _open_file(self):
        today = datetime.date.today().strftime("%Y%m%d")
        if self._file is not None and self._file_date == today:
            return
        self._close_file()
        try:
            directory = self.log_dir
            if not os.path.isabs(directory):
                directory = os.path.join(os.getcwd(), directory)
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "%s.log" % today)
            self._file = open(path, "a", encoding="utf-8")
            self._file_date = today
            self._file_path = path
        except Exception:
            self._file = None

    def _close_file(self):
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
        self._file = None
        self._file_date = None

    def current_file(self):
        return self._file_path

    # ------------------------------------------------------------------ write
    def write(self, channel, direction, text, flush=True):
        """Append one communication line.

        ``channel`` is ``"fox"`` or ``"gtp"``; ``direction`` is IN/OUT/INFO/ERROR.
        """
        now = datetime.datetime.now()
        arrow = _ARROWS.get((direction, channel), "  " if direction == INFO else "-----")
        if direction in (INFO, ERROR):
            arrow = "*****" if direction == ERROR else "-----"
        line = "[%s] %s %s" % (now.strftime("%H:%M:%S.%f")[:-3], arrow, text)
        with self._lock:
            self.entries.append((now, channel, direction, text))
            if len(self.entries) > self.max_entries:
                del self.entries[: len(self.entries) - self.max_entries]
            if self.enabled:
                self._open_file()
                if self._file is not None:
                    try:
                        if self.timestamp:
                            self._file.write(line + "\n")
                        else:
                            self._file.write("%s %s\n" % (arrow, text))
                        if flush:
                            self._file.flush()
                    except Exception:
                        self._close_file()
        if self.on_entry:
            try:
                self.on_entry(channel, direction, line if self.timestamp else text)
            except Exception:
                pass
        return line

    def info(self, text):
        return self.write("gtp", INFO, text)

    def error(self, text):
        return self.write("gtp", ERROR, text)

    def clear(self):
        with self._lock:
            self.entries = []

    def dump(self):
        with self._lock:
            return list(self.entries)
