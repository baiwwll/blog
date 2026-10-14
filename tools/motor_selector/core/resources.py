# -*- coding: utf-8 -*-
"""路径工具：兼容源码运行与 PyInstaller 单文件打包。"""
from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """程序所在目录（打包后为 exe 所在目录，源码运行为工程根目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_dir() -> str:
    """随程序打包的只读资源目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return base
    return app_dir()


def user_data_dir() -> str:
    """用户可写目录（导入的型号库、保存的方案、导出的报告）。"""
    candidate = os.path.join(app_dir(), "userdata")
    try:
        os.makedirs(candidate, exist_ok=True)
        probe = os.path.join(candidate, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return candidate
    except OSError:
        fallback = os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"), "MotorSelector"
        )
        os.makedirs(fallback, exist_ok=True)
        return fallback


def report_dir() -> str:
    path = os.path.join(user_data_dir(), "reports")
    os.makedirs(path, exist_ok=True)
    return path


def scheme_dir() -> str:
    path = os.path.join(user_data_dir(), "schemes")
    os.makedirs(path, exist_ok=True)
    return path
