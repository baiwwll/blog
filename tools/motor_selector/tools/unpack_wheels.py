# -*- coding: utf-8 -*-
r"""把事先下载好的 wheel 直接解包成"绿色 site-packages"，绕过 pip 安装。

某些受限环境下 pip 无法写入临时/系统目录，直接解包 zip 是最稳的办法。
解包目录通过 PYTHONPATH 提供给 PyInstaller。

用法： python tools/unpack_wheels.py
"""
from __future__ import annotations

import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WHEELS = os.path.join(HERE, "_wheels")
TARGET = os.path.join(HERE, "_pylibs")


def main() -> int:
    if not os.path.isdir(WHEELS):
        print("没有找到 wheel 目录：", WHEELS)
        return 1
    wheels = [f for f in os.listdir(WHEELS) if f.lower().endswith(".whl")]
    if not wheels:
        print("没有 wheel 文件")
        return 1
    os.makedirs(TARGET, exist_ok=True)
    for name in sorted(wheels):
        path = os.path.join(WHEELS, name)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(TARGET)
        print(f"已解包 {name}")
    sys.path.insert(0, TARGET)
    try:
        import PyInstaller                                     # noqa: F401
        print("\nPyInstaller 可用，版本：", end=" ")
        from PyInstaller import __version__
        print(__version__)
    except Exception as exc:                                    # noqa: BLE001
        print("\n导入 PyInstaller 失败：", exc)
        return 1
    print("解包目录：", TARGET)
    print("运行打包时请设置： set PYTHONPATH=" + TARGET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
