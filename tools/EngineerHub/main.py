from __future__ import annotations

import argparse
import ctypes
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from engineerhub.app import App
from engineerhub.library import Library, load_library_path, save_library_path


def main():
    parser = argparse.ArgumentParser(description="EngineerHub 工程项目中心")
    parser.add_argument("--library", type=Path, help="使用指定工程库（不改变默认工程库设置）")
    args = parser.parse_args()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    root.withdraw()
    try:
        library = Library(args.library or load_library_path())
        if not args.library:
            save_library_path(library.root)
        App(root, library, persist_settings=not bool(args.library))
        root.deiconify()
        root.mainloop()
    except Exception as error:
        messagebox.showerror("EngineerHub 启动失败", f"{error}\n\n可通过 --library 指定可读写的工程库目录。", parent=root)
        root.destroy()


if __name__ == "__main__":
    main()
