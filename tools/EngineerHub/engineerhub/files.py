from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .windows_dde import try_open_solidworks
from .windows_shell import open_directory


CATEGORIES = {
    "CAD": "CAD 模型",
    "Drawing": "工程图",
    "CAE": "CAE 分析",
    "Calculation": "计算文件",
    "Documents": "项目资料",
    "Other": "其他文件",
}
EXTENSIONS = {
    "CAD": "sldasm sldprt step stp iges igs x_t x_b sat stl obj 3mf prt asm ipt iam catpart catproduct 3dxml f3d f3z jt par psm",
    "Drawing": "slddrw dwg dxf idw catdrawing dft",
    "CAE": "wbpj wbpz mechdb mechat mechdat agdb dsdb cas cas.h5 dat.h5 msh msh.h5 cdb rst rth db inp odb cae k key dyn d3plot op2 bdf fem sim scdoc scdocx pmdb",
    "Calculation": "xlsx xls xlsm xlsb csv ods mcd mcdx smath ipynb mat",
    "Documents": "pdf doc docx odt ppt pptx txt md rtf html htm png jpg jpeg bmp tif tiff svg webp",
}
EXTENSION_CATEGORY = {ext: category for category, extensions in EXTENSIONS.items() for ext in extensions.split()}
SKIP_DIRS = {".git", ".svn", "__pycache__", "$recycle.bin", "system volume information"}
EXECUTABLE_EXTENSIONS = {".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr", ".lnk", ".url"}


def classify(name: str) -> tuple[str, str]:
    lower = name.lower()
    for extension in ("cas.h5", "dat.h5", "msh.h5"):
        if lower.endswith("." + extension):
            return "CAE", extension
    extension = Path(lower).suffix.lstrip(".")
    # Creo versions append a number, e.g. bracket.prt.7.
    if extension.isdigit() and Path(Path(lower).stem).suffix in (".prt", ".asm"):
        extension = Path(Path(lower).stem).suffix.lstrip(".")
    return EXTENSION_CATEGORY.get(extension, "Other"), extension


def is_reparse(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


@dataclass
class ScanResult:
    files: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(CATEGORIES, 0)
        for item in self.files:
            counts[item["category"]] += 1
        return counts


def scan_directory(root: Path, progress: Callable[[int], None] | None = None) -> ScanResult:
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"工程目录不存在或无法访问：{root}")
    result = ScanResult()

    def onerror(error: OSError) -> None:
        result.errors.append(str(error))

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        parent = Path(directory)
        keep = []
        for name in dirs:
            path = parent / name
            try:
                if name.lower() in SKIP_DIRS:
                    continue
                if is_reparse(path):
                    result.skipped.append(str(path.relative_to(root)))
                    continue
                keep.append(name)
            except OSError as error:
                result.errors.append(str(error))
        dirs[:] = keep
        for name in names:
            path = parent / name
            try:
                if is_reparse(path):
                    result.skipped.append(str(path.relative_to(root)))
                    continue
                # Office / SolidWorks lock files are transient, not documents.
                if name.startswith(("~$", ".~lock.")):
                    continue
                stat = path.stat()
                category, extension = classify(name)
                result.files.append({
                    "relative_path": path.relative_to(root).as_posix(),
                    "name": name,
                    "extension": extension,
                    "category": category,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                })
                if progress and len(result.files) % 250 == 0:
                    progress(len(result.files))
            except OSError as error:
                result.errors.append(f"{path}: {error}")
    result.files.sort(key=lambda item: item["relative_path"].casefold())
    return result


def contained_file(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("文件路径超出项目工作目录，请重新扫描项目。")
    if not target.is_file():
        raise FileNotFoundError(f"文件已移动、删除或当前无法访问：\n{target}")
    return target


def open_file(root: Path, relative_path: str) -> Path:
    target = contained_file(root, relative_path)
    if target.suffix.lower() in EXECUTABLE_EXTENSIONS:
        raise ValueError("此入口用于打开工程文档。程序或脚本请在文件所在目录中自行运行。")
    try:
        if sys.platform == "win32":
            opened = target.suffix.lower() in {".sldprt", ".sldasm", ".slddrw"} and try_open_solidworks(target)
            if not opened:
                os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as error:
        raise OSError(f"无法调用本机程序打开文件。请检查是否安装对应软件，并在 Windows 中设置此类型的默认应用。\n\n{error}") from error
    return target


def open_folder(path: Path, select: bool = False) -> None:
    if not path.exists():
        raise FileNotFoundError(f"路径不存在：{path}")
    if sys.platform == "win32":
        folder = path.parent if select else path
        if not folder.is_dir():
            raise NotADirectoryError(f"路径不是文件夹：{folder}")
        open_directory(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path.parent if select else path)])
