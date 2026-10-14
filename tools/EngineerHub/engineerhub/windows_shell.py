"""Open a folder through Explorer's native Shell API, avoiding file associations."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path


def open_directory(path: Path) -> None:
    ole = C.WinDLL('ole32')
    shell = C.WinDLL('shell32')
    ole.CoInitializeEx.argtypes = [C.c_void_p, W.DWORD]
    ole.CoInitializeEx.restype = W.LONG
    ole.CoUninitialize.argtypes = []
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    shell.SHParseDisplayName.argtypes = [W.LPCWSTR, C.c_void_p, C.POINTER(C.c_void_p),
                                       W.ULONG, C.POINTER(W.ULONG)]
    shell.SHParseDisplayName.restype = W.LONG
    shell.SHOpenFolderAndSelectItems.argtypes = [C.c_void_p, W.UINT,
                                                C.POINTER(C.c_void_p), W.DWORD]
    shell.SHOpenFolderAndSelectItems.restype = W.LONG
    apartment = ole.CoInitializeEx(None, 2)
    if apartment < 0 and apartment != -2147417850:
        raise OSError(f'Windows Shell 初始化失败：0x{apartment & 0xffffffff:08X}')
    pidl = C.c_void_p()
    try:
        result = shell.SHParseDisplayName(str(path.resolve()), None, C.byref(pidl), 0, None)
        if result < 0:
            raise OSError(f'无法解析文件夹：{path}\nWindows Shell：0x{result & 0xffffffff:08X}')
        # An empty relative ITEMIDLIST refers to the folder itself. Providing
        # one child opens this folder, rather than selecting it in its parent.
        empty_child = W.USHORT(0)
        children = (C.c_void_p * 1)(C.cast(C.byref(empty_child), C.c_void_p))
        result = shell.SHOpenFolderAndSelectItems(pidl, 1, children, 0)
        if result < 0:
            raise OSError(f'无法打开文件夹：{path}\nWindows Shell：0x{result & 0xffffffff:08X}')
    finally:
        if pidl:
            ole.CoTaskMemFree(pidl)
        if apartment >= 0:
            ole.CoUninitialize()
