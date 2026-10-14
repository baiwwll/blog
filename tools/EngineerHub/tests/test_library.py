from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engineerhub.files import ScanResult, classify, contained_file, open_file, open_folder, scan_directory
from engineerhub.library import Library, load_library_path, save_library_path


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="engineerhub-test-")
        # Windows runners may expose the temp directory through an 8.3 alias.
        self.base = Path(self.temp.name).resolve()
        self.library = Library(self.base / "工程库")
        self.source = self.base / "升降平台"
        fixtures = {
            "总装.SLDASM": b"assembly fixture",
            "Parts/安装板.SLDPRT": b"part fixture",
            "Drawing/总装.SLDDRW": b"drawing fixture",
            "ANSYS/平台.wbpj": b"project fixture",
            "ANSYS/平台_files/dp0/support.bin": b"support fixture",
            "计算/载荷.xlsx": b"calculation fixture",
            "项目要求.pdf": b"document fixture",
            "其他/未知.custom": b"unknown fixture",
        }
        for relative, content in fixtures.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (self.source / "空文件夹").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_categories_and_compound_extensions(self):
        for name, expected in [("总装.SLDASM", "CAD"), ("板.SLDDRW", "Drawing"), ("flow.CAS.H5", "CAE"), ("载荷.XLSX", "Calculation"), ("说明.PDF", "Documents"), ("support.xyz", "Other"), ("bracket.prt.7", "CAD")]:
            with self.subTest(name=name):
                self.assertEqual(classify(name)[0], expected)

    def test_create_edit_remove_preserves_workspace_and_manifest(self):
        project = self.library.create('平台 "A" / 100kg', "machine", "双丝杆")
        workspace = self.library.workspace(project)
        self.assertTrue(workspace.is_dir())
        part = workspace / "板.sldprt"
        part.write_bytes(b"important")
        self.library.scan(project["id"])
        self.library.edit(project["id"], "升级平台", "component", "修改说明")
        updated = self.library.project(project["id"])
        self.assertEqual(self.library.workspace(updated), workspace)
        self.assertEqual(updated["type"], "component")
        manifest = json.loads((workspace.parent / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "升级平台")
        self.library.remove(project["id"])
        self.assertEqual(self.library.projects(), [])
        self.assertEqual(self.library.files(project["id"]), [])
        self.assertEqual(part.read_bytes(), b"important")
        self.assertTrue((workspace.parent / "project.json").exists())

    def test_copy_preserves_nested_files_empty_folders_and_originals(self):
        before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        project, result = self.library.import_project(self.source, "升降平台", "machine", "", True)
        workspace = self.library.workspace(project)
        after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue((workspace / "空文件夹").is_dir())
        self.assertEqual(len(result.files), 8)
        self.assertEqual(result.counts["Other"], 2)
        for path, content in before.items():
            self.assertEqual((self.source / path).read_bytes(), content)

    def test_linked_import_keeps_location_and_updates_original_index(self):
        project, _result = self.library.import_project(self.source, "原位置平台", "machine", "", False)
        self.assertEqual(self.library.workspace(project), self.source)
        self.assertEqual(list((self.library.root / "Projects").iterdir()), [])
        (self.source / "追加.txt").write_text("new", encoding="utf-8")
        self.library.scan(project["id"])
        self.assertEqual(len(self.library.files(project["id"])), 9)

    def test_rescan_upsert_modification_missing_and_reappearance(self):
        project, _result = self.library.import_project(self.source, "平台", "machine", "", False)
        project_id = project["id"]
        first = self.library.files(project_id)
        self.library.scan(project_id)
        self.assertEqual([row["id"] for row in first], [row["id"] for row in self.library.files(project_id)])
        path = self.source / "计算/载荷.xlsx"
        path.write_bytes(b"changed calculation bytes")
        self.library.scan(project_id)
        self.assertEqual(self.library.files(project_id, "Calculation")[0]["size"], path.stat().st_size)
        path.unlink()
        self.library.scan(project_id)
        self.assertEqual(self.library.files(project_id, "Calculation")[0]["missing"], 1)
        path.write_bytes(b"restored")
        self.library.scan(project_id)
        self.assertEqual(self.library.files(project_id, "Calculation")[0]["missing"], 0)

    def test_read_error_does_not_mark_inaccessible_files_missing(self):
        project, _result = self.library.import_project(self.source, "平台", "machine", "", False)
        incomplete = ScanResult(files=[], errors=["Permission denied: Parts"])
        with patch("engineerhub.library.scan_directory", return_value=incomplete):
            self.library.scan(project["id"])
        self.assertTrue(all(not row["missing"] for row in self.library.files(project["id"])))
        self.assertIn("读取失败", self.library.project(project["id"])["scan_note"])

    def test_missing_root_preserves_index(self):
        project, _result = self.library.import_project(self.source, "平台", "machine", "", False)
        moved = self.base / "临时改名"
        self.source.rename(moved)
        with self.assertRaises(FileNotFoundError):
            self.library.scan(project["id"])
        self.assertEqual(len(self.library.files(project["id"])), 8)
        self.assertTrue(all(not row["missing"] for row in self.library.files(project["id"])))

    def test_managed_library_can_be_relocated_as_a_whole(self):
        project, _result = self.library.import_project(self.source, "平台", "machine", "", True)
        relocated_root = self.base / "另一个磁盘位置"
        shutil.copytree(self.library.root, relocated_root)
        relocated = Library(relocated_root)
        row = relocated.project(project["id"])
        self.assertTrue(relocated.workspace(row).is_relative_to(relocated_root))
        self.assertTrue((relocated.workspace(row) / "总装.SLDASM").is_file())
        self.assertEqual(len(relocated.scan(project["id"]).files), 8)

    def test_root_and_ancestor_import_rejected(self):
        for path in (self.library.root, self.base):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.library.import_project(path, "递归工程", "machine", "", True)
        self.assertEqual(self.library.projects(), [])

    def test_path_traversal_and_missing_file_rejected(self):
        with self.assertRaises(ValueError):
            contained_file(self.source, "../工程库/engineerhub.db")
        with self.assertRaises(FileNotFoundError):
            contained_file(self.source, "missing.sldprt")

    @unittest.skipUnless(sys.platform == "win32", "Windows association")
    def test_open_delegates_exact_original_path_to_windows(self):
        with patch("engineerhub.files.try_open_solidworks", return_value=False), patch("engineerhub.files.os.startfile") as launch:
            result = open_file(self.source, "总装.SLDASM")
            launch.assert_called_once_with(str(self.source / "总装.SLDASM"))
            self.assertEqual(result, self.source / "总装.SLDASM")

    @unittest.skipUnless(sys.platform == "win32", "Windows Explorer")
    def test_folder_opens_when_shell_folder_association_is_denied(self):
        with patch("engineerhub.files.os.startfile", side_effect=PermissionError(5, "Access denied")) as shell, \
             patch("engineerhub.files.open_directory") as launch:
            open_folder(self.source)
            launch.assert_called_once_with(self.source)
            shell.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows document open")
    def test_solidworks_unicode_path_reuses_running_application(self):
        with patch("engineerhub.files.try_open_solidworks", return_value=True) as running, patch("engineerhub.files.os.startfile") as launch:
            result = open_file(self.source, "总装.SLDASM")
            running.assert_called_once_with(self.source / "总装.SLDASM")
            launch.assert_not_called()
            self.assertEqual(result, self.source / "总装.SLDASM")

    @unittest.skipUnless(sys.platform == "win32", "Windows document open")
    def test_unconfirmed_open_does_not_send_a_duplicate_command(self):
        with patch("engineerhub.files.try_open_solidworks", side_effect=OSError("DDE timeout")), patch("engineerhub.files.os.startfile") as launch:
            with self.assertRaises(OSError):
                open_file(self.source, "总装.SLDASM")
            launch.assert_not_called()

    def test_program_file_does_not_execute_from_document_entry(self):
        (self.source / "tool.exe").write_bytes(b"not an executable")
        with self.assertRaises(ValueError):
            open_file(self.source, "tool.exe")

    def test_import_failure_keeps_partial_copy_visible_and_source_intact(self):
        def interrupted_copy(source, target, **_kwargs):
            (Path(target) / "partial.txt").write_text("partial")
            raise OSError("disk full fixture")
        with patch("engineerhub.library.shutil.copytree", side_effect=interrupted_copy):
            with self.assertRaises(OSError):
                self.library.import_project(self.source, "平台", "machine", "", True)
        project = self.library.projects()[0]
        self.assertIn("导入未完成", project["description"])
        self.assertTrue((self.library.workspace(project) / "partial.txt").exists())
        self.assertTrue((self.source / "总装.SLDASM").exists())

    def test_unrecognized_files_and_lock_files(self):
        (self.source / "~$载荷.xlsx").write_bytes(b"lock")
        scan = scan_directory(self.source)
        self.assertEqual(len(scan.files), 8)
        self.assertIn("其他/未知.custom", {row["relative_path"] for row in scan.files})

    def test_project_type_and_unicode_search(self):
        self.library.create("升降平台", "machine", "丝杆驱动")
        part = self.library.create("安装板", "component", "铝合金")
        self.assertEqual(len(self.library.projects("machine")), 1)
        self.assertEqual(self.library.projects(query="铝合金")[0]["id"], part["id"])
        self.assertEqual(self.library.projects(query="P000002")[0]["id"], part["id"])

    def test_portable_settings_follow_application_folder(self):
        first = self.base / "portable-app"
        first.mkdir()
        with patch("engineerhub.library.application_directory", return_value=first):
            self.assertEqual(load_library_path(), first / "EngineerHubLibrary")
            save_library_path(first / "EngineerHubLibrary")
        moved = self.base / "moved-app"
        shutil.copytree(first, moved)
        with patch("engineerhub.library.application_directory", return_value=moved):
            self.assertEqual(load_library_path(), moved / "EngineerHubLibrary")


if __name__ == "__main__":
    unittest.main()
