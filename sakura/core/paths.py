"""运行目录与资源路径。"""

import os
import sys

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PACKAGE_DIR)


def app_dir():
    """配置/数据目录：打包后是 exe 所在目录，源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return PROJECT_DIR


def resource_dir():
    """只读资源目录：打包后在 _MEIPASS，源码运行时在 sakura/resources。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", app_dir())
    return os.path.join(PACKAGE_DIR, "resources")


def resource_path(name):
    return os.path.join(resource_dir(), name)
