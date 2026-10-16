import sys
from PyQt5.QtWidgets import QApplication
from ui_main import SakuraGTPApp

__version__ = "1.2.1"


def main():
    app = QApplication(sys.argv)
    window = SakuraGTPApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()