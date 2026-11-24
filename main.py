"""SakuraGTP 入口：兼容 `python main.py` 与 PyInstaller 打包。"""

from sakura.app import main

if __name__ == "__main__":
    main()
