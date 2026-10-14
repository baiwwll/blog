"""Exercise real Tk widgets and background jobs using temporary project files."""
from __future__ import annotations

import argparse
import ctypes
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engineerhub.app import App, ImportDialog, ProjectDialog
from engineerhub.library import Library


def pump(root, condition=lambda: True, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        root.update()
        if condition():
            return
        if time.monotonic() > deadline:
            raise TimeoutError("GUI operation timed out")
        time.sleep(0.03)


def screenshot(root, path):
    from PIL import ImageGrab
    root.lift()
    root.focus_force()
    root.update()
    time.sleep(0.2)
    bounds = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
    ImageGrab.grab(bbox=bounds).save(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    with tempfile.TemporaryDirectory(prefix="engineerhub-gui-") as temporary:
        base = Path(temporary)
        library = Library(base / "library")
        source = base / "升降平台"
        source.mkdir()
        (source / "Parts").mkdir()
        for relative in ("总装.SLDASM", "Parts/安装板.SLDPRT", "总装.SLDDRW", "结构分析.wbpj", "载荷计算.xlsx", "设计说明.pdf", "支撑.custom"):
            (source / relative).write_bytes(b"test fixture only")
        project, _scan = library.import_project(source, "垂直升降平台（测试工程）", "machine", "100 kg · 双丝杆伺服驱动", True)
        library.create("导轨安装板（测试工程）", "component", "铝合金零件")
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        app = App(root, library, persist_settings=False)
        app.error = lambda error: errors.append(error)
        pump(root)
        assert len(app.project_tree.get_children()) == 2
        if args.screenshots:
            args.screenshots.mkdir(parents=True, exist_ok=True)
            screenshot(root, args.screenshots / "home.png")
        app.show_projects("component")
        pump(root)
        assert len(app.project_tree.get_children()) == 1
        app.project_query.set("不存在")
        pump(root, lambda: not app.project_tree.get_children())
        app.show_detail(project["id"])
        pump(root, lambda: not app.busy)
        assert len(app.file_tree.get_children()) == 7
        if args.screenshots:
            screenshot(root, args.screenshots / "project.png")
        app.set_category("CAD")
        assert len(app.file_tree.get_children()) == 2
        app.file_query.set("安装板")
        pump(root, lambda: len(app.file_tree.get_children()) == 1)
        app.file_tree.selection_set(app.file_tree.get_children()[0])
        with patch("engineerhub.files.try_open_solidworks", return_value=False), patch("engineerhub.files.os.startfile") as launch:
            app.open_selected_file()
            assert launch.call_args[0][0].endswith("安装板.SLDPRT")
        app.file_query.set("")
        app.set_category(None)
        # Exercise added / deleted detection through the actual UI worker queue.
        workspace = library.workspace(project)
        (workspace / "追加.txt").write_text("new")
        (workspace / "设计说明.pdf").unlink()
        app.scan_active()
        pump(root, lambda: not app.busy)
        assert len(app.file_tree.get_children()) == 8
        assert sum(row["missing"] for row in app.file_rows.values()) == 1
        dialog = ProjectDialog(app, project)
        pump(root)
        assert dialog.submit_button.winfo_ismapped()
        assert dialog.submit_button.winfo_rooty() + dialog.submit_button.winfo_height() < dialog.winfo_rooty() + dialog.winfo_height()
        if args.screenshots:
            screenshot(dialog, args.screenshots / "edit.png")
        dialog.name.set("平台已编辑")
        dialog.submit()
        assert dialog.result[0] == "平台已编辑"
        library.edit(project["id"], *dialog.result)
        dialog = ImportDialog(app)
        dialog.source.set(str(source))
        dialog.name.set("导入流程测试")
        dialog.preview()
        pump(root, lambda: not app.busy)
        assert dialog.previewed is not None
        assert dialog.confirm_button.winfo_ismapped()
        assert dialog.confirm_button.winfo_rooty() + dialog.confirm_button.winfo_height() < dialog.winfo_rooty() + dialog.winfo_height()
        if args.screenshots:
            screenshot(dialog, args.screenshots / "import.png")
        dialog.submit()
        pump(root, lambda: not app.busy)
        assert len(library.projects()) == 3
        assert app.view == "detail"
        assert len(app.file_tree.get_children()) == 7
        # Verify layout remains usable at the supported minimum window size.
        root.geometry("1040x700")
        pump(root)
        if args.screenshots:
            screenshot(root, args.screenshots / "minimum.png")
        assert app.category_buttons["Other"].winfo_x() + app.category_buttons["Other"].winfo_width() <= app.category_buttons["Other"].master.winfo_width()
        assert app.category_buttons["Other"].winfo_width() > 80
        assert app.open_file_button.winfo_ismapped()
        assert app.open_file_button.winfo_rooty() + app.open_file_button.winfo_height() <= root.winfo_rooty() + root.winfo_height() - 34
        assert not errors, errors
        root.destroy()
        print("GUI PASS: home, type filter, project search, detail, categories, file search, Windows open delegation, background scan, edit dialog, import preview/confirmation, minimum layout")


if __name__ == "__main__":
    main()
