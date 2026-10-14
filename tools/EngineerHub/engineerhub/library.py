from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .files import ScanResult, is_reparse, scan_directory


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:70] or "Project"


class Library:
    """Each operation owns a connection, so scans may run on a worker thread."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "Projects").mkdir(exist_ok=True)
        self.database = self.root / "engineerhub.db"
        with self.connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("此工程库来自更新版本，请使用新版 EngineerHub 打开。")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL CHECK(type IN ('machine','component')),
                    description TEXT NOT NULL DEFAULT '',
                    workspace TEXT NOT NULL,
                    storage_mode TEXT NOT NULL CHECK(storage_mode IN ('managed','linked')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    scanned_at TEXT,
                    scan_note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    category TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    missing INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(project_id, relative_path)
                );
                CREATE INDEX IF NOT EXISTS files_project_category ON files(project_id, category);
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def code(project_id: int) -> str:
        return f"P{project_id:06d}"

    def projects(self, project_type: str | None = None, query: str = "") -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("""
                SELECT p.*, COUNT(f.id) AS file_count,
                       COALESCE(SUM(f.missing), 0) AS missing_count
                FROM projects p LEFT JOIN files f ON f.project_id = p.id
                GROUP BY p.id ORDER BY p.updated_at DESC, p.id DESC
            """).fetchall()
        query = query.casefold().strip()
        return [dict(row) for row in rows if
                (not project_type or row["type"] == project_type) and
                (not query or query in (self.code(row["id"]) + " " + row["name"] + " " + row["description"]).casefold())]

    def project(self, project_id: int) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise ValueError("该项目已从工程库移除。")
        return dict(row)

    def create(self, name: str, project_type: str, description: str = "", linked: Path | None = None) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("请输入项目名称。")
        if project_type not in ("machine", "component"):
            raise ValueError("请选择整机或零部件。")
        if linked and (not linked.is_dir() or linked.resolve() == self.root or self.root.is_relative_to(linked.resolve())):
            raise ValueError("请选择有效的工程文件夹，不能选择工程库本身或包含工程库的上级目录。")
        created_folder = None
        try:
            with self.connection() as connection:
                timestamp = now()
                cursor = connection.execute("""
                    INSERT INTO projects(name, type, description, workspace, storage_mode, created_at, updated_at)
                    VALUES(?, ?, ?, '', ?, ?, ?)
                """, (name, project_type, description.strip(), "linked" if linked else "managed", timestamp, timestamp))
                project_id = cursor.lastrowid
                if linked:
                    workspace = linked.resolve()
                else:
                    # Never merge into a folder left behind after project removal.
                    folder = self.root / "Projects" / f"{self.code(project_id)}_{safe_name(name)}"
                    suffix = 2
                    while folder.exists():
                        folder = self.root / "Projects" / f"{self.code(project_id)}_{safe_name(name)}_{suffix}"
                        suffix += 1
                    folder.mkdir()
                    created_folder = folder
                    workspace = folder / "Workspace"
                    workspace.mkdir()
                stored = str(workspace) if linked else workspace.relative_to(self.root).as_posix()
                connection.execute("UPDATE projects SET workspace = ? WHERE id = ?", (stored, project_id))
                row = dict(connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())
                self._manifest(row)
            return row
        except BaseException:
            if created_folder:
                # Only clean the new, empty project created by this operation.
                if (created_folder / "project.json").exists():
                    (created_folder / "project.json").unlink()
                (created_folder / "Workspace").rmdir()
                created_folder.rmdir()
            raise

    def workspace(self, project: dict) -> Path:
        path = Path(project["workspace"])
        if project["storage_mode"] == "managed":
            path = (self.root / path).resolve()
            if not path.is_relative_to(self.root / "Projects"):
                raise ValueError("项目目录超出工程库。")
        return path

    def _manifest(self, project: dict) -> None:
        if project["storage_mode"] != "managed":
            return
        path = self.workspace(project).parent / "project.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({**project, "code": self.code(project["id"])}, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def edit(self, project_id: int, name: str, project_type: str, description: str) -> None:
        if not name.strip():
            raise ValueError("请输入项目名称。")
        with self.connection() as connection:
            cursor = connection.execute("UPDATE projects SET name=?, type=?, description=?, updated_at=? WHERE id=?", (name.strip(), project_type, description.strip(), now(), project_id))
            if not cursor.rowcount:
                raise ValueError("该项目已从工程库移除。")
            self._manifest(dict(connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()))

    def remove(self, project_id: int) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def import_project(self, source: Path, name: str, project_type: str, description: str,
                       copy: bool, progress: Callable[[int], None] | None = None) -> tuple[dict, ScanResult]:
        source = source.resolve()
        if not source.is_dir():
            raise ValueError("导入文件夹不存在。")
        if source == self.root or self.root.is_relative_to(source):
            raise ValueError("不能导入工程库本身或包含工程库的上级目录。")
        snapshot = scan_directory(source, progress)
        if copy and (snapshot.errors or snapshot.skipped):
            raise ValueError("源目录存在无法读取的文件或链接目录，无法保证完整复制。请查看预览提示，或选择保留原位置。")
        project = self.create(name, project_type, description, linked=None if copy else source)
        if copy:
            target = self.workspace(project)
            try:
                # copytree retains all ordinary files, including support files and
                # empty folders. No flattening or extension-based physical sorting.
                def reject_links(directory, names):
                    for item in names:
                        path = Path(directory) / item
                        if is_reparse(path):
                            raise ValueError(f"复制过程中发现链接，已中止：{path}")
                    return []
                shutil.copytree(source, target, dirs_exist_ok=True, ignore=reject_links)
            except BaseException:
                # Preserve any partial copy; never touch the source. Keep its project
                # registered so it is visible and the user can find it.
                self.edit(project["id"], project["name"], project_type, description + "\n导入未完成，请检查源文件后重新导入。")
                raise
        return project, self.scan(project["id"], progress)

    def scan(self, project_id: int, progress: Callable[[int], None] | None = None) -> ScanResult:
        project = self.project(project_id)
        result = scan_directory(self.workspace(project), progress)
        with self.connection() as connection:
            if not connection.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
                raise ValueError("扫描期间项目已被移除。")
            previous = {row["relative_path"]: tuple(row) for row in connection.execute(
                "SELECT relative_path, size, mtime_ns, missing FROM files WHERE project_id=?", (project_id,))}
            changed = False
            if not result.errors:
                connection.execute("UPDATE files SET missing=1 WHERE project_id=?", (project_id,))
            present = set()
            for item in result.files:
                relative = item["relative_path"]
                present.add(relative)
                old = previous.get(relative)
                changed = changed or old != (relative, item["size"], item["mtime_ns"], 0)
                connection.execute("""
                    INSERT INTO files(project_id, relative_path, name, extension, category, size, mtime_ns, missing)
                    VALUES(?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(project_id, relative_path) DO UPDATE SET
                        name=excluded.name, extension=excluded.extension, category=excluded.category,
                        size=excluded.size, mtime_ns=excluded.mtime_ns, missing=0
                """, (project_id, relative, item["name"], item["extension"], item["category"], item["size"], item["mtime_ns"]))
            if not result.errors:
                changed = changed or any(row[3] == 0 and path not in present for path, row in previous.items())
            notes = []
            if result.errors:
                notes.append(f"{len(result.errors)} 项读取失败；本次未标记丢失文件")
            if result.skipped:
                notes.append(f"{len(result.skipped)} 项链接已跳过")
            timestamp = now()
            connection.execute("UPDATE projects SET scanned_at=?, scan_note=?, updated_at=CASE WHEN ? THEN ? ELSE updated_at END WHERE id=?", (timestamp, "；".join(notes), changed, timestamp, project_id))
        return result

    def files(self, project_id: int, category: str | None = None, query: str = "") -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM files WHERE project_id=? ORDER BY missing, name COLLATE NOCASE, relative_path", (project_id,)).fetchall()
        query = query.casefold().strip()
        return [dict(row) for row in rows if (not category or row["category"] == category) and
                (not query or query in row["relative_path"].casefold())]


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def config_path() -> Path:
    return application_directory() / "EngineerHub.settings.json"


def load_library_path() -> Path:
    path = config_path()
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))["library"]
            if isinstance(value, str) and value:
                target = Path(value)
                return target if target.is_absolute() else application_directory() / target
        except (ValueError, KeyError, OSError):
            pass
    return application_directory() / "EngineerHubLibrary"


def save_library_path(path: Path) -> None:
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    resolved = path.resolve()
    base = application_directory()
    value = resolved.relative_to(base).as_posix() if resolved.is_relative_to(base) else str(resolved)
    temporary.write_text(json.dumps({"library": value}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
