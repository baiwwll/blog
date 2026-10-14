"""Start the packaged app, verify its own window/database, then close that window."""
from __future__ import annotations

import ctypes
import json
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing, contextmanager
from ctypes import wintypes
from pathlib import Path


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                ("exe", wintypes.WCHAR * 260)]


@contextmanager
def workspace_fixture(parent):
    # TemporaryDirectory uses a private ACL on Windows. The desktop execution
    # host launches packaged programs with a restricted token, so use inherited
    # workspace permissions for this external-process fixture instead.
    directory = parent / ("exe-fixture-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        if directory.resolve().is_relative_to(parent.resolve()) and directory.name.startswith("exe-fixture-"):
            shutil.rmtree(directory)


def process_family(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    rows = []
    entry = ProcessEntry()
    entry.size = ctypes.sizeof(entry)
    try:
        success = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while success:
            rows.append((entry.pid, entry.parent))
            success = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    family = {pid}
    for _ in range(5):
        family.update(child for child, parent in rows if parent in family)
    return family


def own_window(pids):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _data):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(hwnd, title, 512)
            if "EngineerHub" in title.value:
                windows.append((hwnd, title.value))
        return True
    user.EnumWindows(callback_type(callback), 0)
    return windows


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    project_root = Path(__file__).resolve().parents[1]
    executable = project_root / "dist" / "EngineerHub" / "EngineerHub.exe"
    artifacts = project_root / "artifacts" / "qa"
    artifacts.mkdir(parents=True, exist_ok=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError:
        pass
    with workspace_fixture(artifacts) as temporary:
        library = Path(temporary) / "工程库"
        process = subprocess.Popen([str(executable), "--library", str(library)], cwd=project_root)
        window = None
        deadline = time.monotonic() + 25
        try:
            while time.monotonic() < deadline:
                windows = own_window(process_family(process.pid))
                if windows:
                    window = windows[0]
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged app exited early: {process.returncode}")
                time.sleep(0.2)
            if not window:
                raise TimeoutError("Packaged app did not create a visible window")
            hwnd, title = window
            if "工程项目中心" not in title:
                from PIL import ImageGrab
                bounds = wintypes.RECT()
                user.GetWindowRect(hwnd, ctypes.byref(bounds))
                ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom)).save(artifacts / "startup-error.png")
                raise AssertionError(title)
            time.sleep(0.4)
            database = library / "engineerhub.db"
            assert database.exists()
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
                assert connection.execute("SELECT count(*) FROM projects").fetchone()[0] == 0
            from PIL import ImageGrab
            user.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            bounds = wintypes.RECT()
            user.GetWindowRect(hwnd, ctypes.byref(bounds))
            ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom)).save(artifacts / "packaged.png")
            user.PostMessageW(hwnd, 0x0010, 0, 0)
            process.wait(timeout=10)
            assert process.returncode == 0
            report = {"result": "PASS", "title": title, "exe_size_bytes": executable.stat().st_size,
                      "checks": ["standalone executable starts", "visible desktop window", "SQLite schema initialized", "clean close"],
                      "fixture": "temporary empty engineering library; no real projects imported"}
            (artifacts / "exe-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print("EXE PASS: standalone launch, visible window, SQLite schema, clean shutdown")
        finally:
            if process.poll() is None and window:
                user.PostMessageW(window[0], 0x0010, 0, 0)
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
