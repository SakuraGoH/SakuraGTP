import sys

from PyQt5.QtWidgets import QApplication

from ui_main import SakuraGTPApp

__version__ = "1.5.0"


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setOrganizationName("SakuraGTP")
    app.setApplicationName("SakuraGTP")
    app.setApplicationVersion(__version__)

    from splash import SakuraSplash
    splash = SakuraSplash()
    splash.show()
    app.processEvents()

    window = SakuraGTPApp()

    # 打包模式下关闭 PyInstaller 原生启动图（仅当构建时加了 --splash 才存在）
    if "_PYI_SPLASH_IPC" in os.environ:
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

    splash.finish()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
