# -*- coding: utf-8 -*-
"""在 HTTPS 被拦截的环境下，用 HTTP 镜像把 PyInstaller 及其依赖抓到本地再离线安装。

用法： python tools\fetch_pyinstaller.py
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from typing import List, Tuple

MIRROR = "http://mirrors.aliyun.com/pypi/simple/"
PACKAGES = ["pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging",
            "pefile", "pywin32-ctypes", "setuptools"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_wheels")

TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"
SKIP_PLATFORM = ("macosx", "manylinux", "musllinux")


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pip/24.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _version_tuple(text: str) -> Tuple:
    parts = re.split(r"[._\-+]", text)
    out = []
    for p in parts:
        if p.isdigit():
            out.append((1, int(p)))
        elif p:
            out.append((0, p))
    return tuple(out)


def pick(urls: List[str]) -> List[str]:
    """挑选适用于当前解释器与平台的最新 wheel。

    注意：平台标签必须按结尾判断，否则包名里自带的 "win32"
    （如 pywin32-ctypes）会被误判成 32 位 Windows 轮子。
    """
    good: List[Tuple[Tuple, str]] = []
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        low = name.lower()
        if not low.endswith(".whl"):
            continue
        if any(bad in low for bad in SKIP_PLATFORM):
            continue
        parts = name[: -len(".whl")].split("-")
        version = parts[1] if len(parts) >= 3 else "0"
        py_tag = parts[2] if len(parts) >= 5 else ""
        abi_tag = parts[3] if len(parts) >= 5 else ""
        platform_tag = parts[-1].lower()
        is_win64 = platform_tag == "win_amd64"
        is_pure = platform_tag == "any" and py_tag.startswith(("py3", "py2"))
        if not (is_win64 or is_pure):
            continue
        if is_win64:
            if any(t.startswith("cp") and t != TAG for t in (py_tag, abi_tag)):
                continue
        good.append((_version_tuple(version), url))
    if not good:
        return []
    good.sort(key=lambda item: item[0], reverse=True)
    return [good[0][1]]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    got = []
    for pkg in PACKAGES:
        print(f"--- {pkg} ---")
        index_url = MIRROR + pkg + "/"
        try:
            page = fetch(index_url).decode("utf-8", "replace")
        except Exception as exc:                                # noqa: BLE001
            print(f"  索引获取失败：{exc}")
            continue
        hrefs = re.findall(r'href="([^"]+)"', page)
        urls = [urllib.parse.urljoin(index_url, html.unescape(h).split("#")[0])
                for h in hrefs]
        urls = [u for u in urls if u.lower().endswith(".whl")]
        if pkg == "setuptools":
            urls = [u for u in urls if "py3-none-any" in u]
        targets = pick(urls)
        if not targets:
            print(f"  没有找到合适的 wheel（共 {len(urls)} 个候选）")
            continue
        for url in targets:
            name = url.rsplit("/", 1)[-1]
            dest = os.path.join(OUT, name)
            if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
                print(f"  已存在 {name}")
                got.append(dest)
                continue
            try:
                data = fetch(url)
                with open(dest, "wb") as fh:
                    fh.write(data)
                print(f"  已下载 {name}  ({len(data)/1024:.0f} KB)")
                got.append(dest)
            except Exception as exc:                            # noqa: BLE001
                print(f"  下载失败 {name}：{exc}")

    if not got:
        print("没有下载到任何 wheel")
        return 1
    print(f"\n共 {len(got)} 个 wheel，开始离线安装 ...")
    rc = subprocess.call([sys.executable, "-m", "pip", "install", "--no-index",
                          "--find-links", OUT] + PACKAGES)
    print("pip 返回码:", rc)
    if rc == 0:
        subprocess.call([sys.executable, "-m", "PyInstaller", "--version"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
