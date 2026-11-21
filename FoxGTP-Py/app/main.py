"""Application entry point."""

import os
import sys


def _bootstrap_path():
    if getattr(sys, "frozen", False):
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


_bootstrap_path()

from PyQt5.QtCore import Qt                                    # noqa: E402
from PyQt5.QtGui import QIcon                                  # noqa: E402
from PyQt5.QtWidgets import QApplication                       # noqa: E402

from app import theme                                          # noqa: E402
from app.ui_main import MainWindow                             # noqa: E402


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("FoxGTP-Py")
    app.setApplicationVersion("1.0.0")
    icon_path = resource_path("assets", "foxgtp.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    theme.apply_theme(app)
    window = MainWindow()
    window.show()

    if "--selftest" in sys.argv:
        # packaging smoke test: render the window, save a screenshot, exit
        from PyQt5.QtCore import QTimer

        def finish():
            try:
                target = os.path.join(os.getcwd(), "selftest.png")
                window.grab().save(target)
                print("selftest ok:", target)
            except Exception as exc:                 # pragma: no cover
                print("selftest failed:", exc)
            window.controller.shutdown()
            app.quit()

        QTimer.singleShot(1500, finish)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
