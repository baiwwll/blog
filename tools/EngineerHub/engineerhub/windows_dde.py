"""Unicode Windows document-open transport; no SolidWorks API or new instance."""
from __future__ import annotations

import ctypes as C
import threading
import time
from ctypes import wintypes as W
from pathlib import Path


def try_open_solidworks(target: Path) -> bool:
    # Keep DDE initialization separate from Tk's Windows message thread.
    result = []
    def execute():
        try:
            result.append(_open_on_thread(target))
        except Exception as error:
            result.append(error)
    worker = threading.Thread(target=execute, daemon=True, name="document-open-dde")
    worker.start()
    worker.join(12)
    if not result:
        raise OSError("Windows 文件打开命令仍在等待响应。请检查 SolidWorks 中的对话框。")
    if isinstance(result[0], Exception):
        raise result[0]
    return result[0]


def _open_on_thread(target: Path) -> bool:
    """False means no running DDE server. Rejected commands raise an error."""
    text = str(target)
    if any(character in text for character in ('"', '\r', '\n')):
        raise ValueError("文件路径包含无法用于 Windows 打开命令的字符。")
    user = C.WinDLL("user32", use_last_error=True)
    handle = C.c_void_p
    callback_type = C.WINFUNCTYPE(handle, W.UINT, W.UINT, handle, handle, handle,
                                 handle, C.c_size_t, C.c_size_t)
    callback = callback_type(lambda *_args: None)
    user.DdeInitializeW.argtypes = [C.POINTER(W.DWORD), callback_type, W.DWORD, W.DWORD]
    user.DdeInitializeW.restype = W.UINT
    user.DdeCreateStringHandleW.argtypes = [W.DWORD, W.LPCWSTR, C.c_int]
    user.DdeCreateStringHandleW.restype = handle
    user.DdeConnect.argtypes = [W.DWORD, handle, handle, handle]
    user.DdeConnect.restype = handle
    user.DdeClientTransaction.argtypes = [handle, W.DWORD, handle, handle, W.UINT,
                                         W.UINT, W.DWORD, C.POINTER(W.DWORD)]
    user.DdeClientTransaction.restype = handle
    user.DdeDisconnect.argtypes = [handle]
    user.DdeDisconnect.restype = W.BOOL
    user.DdeFreeStringHandle.argtypes = [W.DWORD, handle]
    user.DdeFreeStringHandle.restype = W.BOOL
    user.DdeUninitialize.argtypes = [W.DWORD]
    user.DdeUninitialize.restype = W.BOOL
    user.DdeGetLastError.argtypes = [W.DWORD]
    user.DdeGetLastError.restype = W.UINT
    instance = W.DWORD()
    service = topic = conversation = None
    if user.DdeInitializeW(C.byref(instance), callback, 0x10, 0):
        return False
    try:
        service = user.DdeCreateStringHandleW(instance.value, "SLDWORKS", 1200)
        topic = user.DdeCreateStringHandleW(instance.value, "System", 1200)
        if not service or not topic:
            return False
        conversation = user.DdeConnect(instance.value, service, topic, None)
        if not conversation:
            return False
        command = f'[open("{text}")]'.encode("utf-16-le") + b"\0\0"
        data = C.create_string_buffer(command)
        result = W.DWORD()
        accepted = user.DdeClientTransaction(C.cast(data, handle), len(data)-1,
                                            conversation, None, 0, 0x4050, 5000,
                                            C.byref(result))
        if not accepted:
            code = user.DdeGetLastError(instance.value)
            # Do not issue another open after an ambiguous timeout.
            raise OSError(f"SolidWorks 未确认打开命令（Windows DDE 错误 {code}）。请检查软件中是否有等待处理的对话框。")
        # SolidWorks acknowledges before dispatching the document-open event.
        # Keep the conversation alive briefly so termination cannot overtake it.
        time.sleep(0.25)
        return True
    finally:
        if conversation:
            user.DdeDisconnect(conversation)
        if topic:
            user.DdeFreeStringHandle(instance.value, topic)
        if service:
            user.DdeFreeStringHandle(instance.value, service)
        user.DdeUninitialize(instance.value)
