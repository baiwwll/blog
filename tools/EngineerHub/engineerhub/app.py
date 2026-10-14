from __future__ import annotations

import gc
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .files import CATEGORIES, contained_file, open_file, open_folder, scan_directory
from .library import Library, save_library_path


BG = "#f4f6fa"
WHITE = "#ffffff"
INK = "#182438"
MUTED = "#68768a"
BLUE = "#2164da"
BORDER = "#e1e7ef"
TYPES = {"machine": "整机设计", "component": "零部件设计"}


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def local_date(value: str | None) -> str:
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M") if value else "尚未扫描"


def label(parent, text, size=10, color=INK, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                    font=("Microsoft YaHei UI", size, "bold" if bold else "normal"), **kwargs)


class ProjectDialog(tk.Toplevel):
    def __init__(self, app: "App", project: dict | None = None, project_type="machine"):
        super().__init__(app.root)
        self.app = app
        self.result = None
        self.project = project
        self.title("编辑项目" if project else "新建项目")
        self.configure(bg=WHITE)
        self.geometry("560x500")
        self.resizable(False, False)
        self.transient(app.root)
        body = tk.Frame(self, bg=WHITE, padx=28, pady=22)
        body.pack(fill="both", expand=True)
        label(body, "编辑项目信息" if project else "创建工程项目", 17, bold=True).pack(anchor="w", pady=(0, 18))
        label(body, "项目名称").pack(anchor="w")
        self.name = tk.StringVar(value=project["name"] if project else "")
        entry = ttk.Entry(body, textvariable=self.name)
        entry.pack(fill="x", pady=(6, 16))
        self.kind = tk.StringVar(value=project["type"] if project else project_type)
        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=(0, 16))
        for value, text in TYPES.items():
            ttk.Radiobutton(row, text=text, variable=self.kind, value=value).pack(side="left", padx=(0, 24))
        label(body, "项目说明（可选）").pack(anchor="w")
        self.description = tk.Text(body, height=4, font=("Microsoft YaHei UI", 10), relief="solid", bd=1, wrap="word")
        self.description.pack(fill="x", pady=(6, 12))
        if project:
            self.description.insert("1.0", project["description"])
        label(body, "文件目录保持原路径。" if project else "自动创建项目编号和 Workspace 工作目录。", color=MUTED).pack(anchor="w")
        buttons = tk.Frame(body, bg=WHITE)
        buttons.pack(fill="x", pady=(18, 0))
        self.submit_button = ttk.Button(buttons, text="保存" if project else "创建项目", style="Primary.TButton", command=self.submit)
        self.submit_button.pack(side="right")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right", padx=10)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        entry.focus_set()

    def submit(self):
        if not self.name.get().strip():
            messagebox.showinfo("项目名称", "请输入项目名称。", parent=self)
            return
        self.result = (self.name.get().strip(), self.kind.get(), self.description.get("1.0", "end").strip())
        self.destroy()


class ImportDialog(tk.Toplevel):
    def __init__(self, app: "App", project_type="machine"):
        super().__init__(app.root)
        self.app = app
        self.title("导入现有工程")
        self.configure(bg=WHITE)
        self.geometry("690x740")
        self.minsize(620, 610)
        self.transient(app.root)
        self.source = tk.StringVar()
        self.name = tk.StringVar()
        self.kind = tk.StringVar(value=project_type)
        self.copy = tk.BooleanVar(value=True)
        self.previewed = None
        body = tk.Frame(self, bg=WHITE, padx=28, pady=22)
        body.pack(fill="both", expand=True)
        label(body, "导入现有工程", 18, bold=True).pack(anchor="w")
        label(body, "保留完整目录结构，在界面中自动分类。", color=MUTED).pack(anchor="w", pady=(6, 20))
        label(body, "源工程文件夹").pack(anchor="w")
        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=(6, 12))
        ttk.Entry(row, textvariable=self.source).pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(row, text="选择…", command=self.browse)
        self.browse_button.pack(side="left", padx=(8, 0))
        label(body, "项目名称").pack(anchor="w")
        ttk.Entry(body, textvariable=self.name).pack(fill="x", pady=(6, 12))
        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=(0, 12))
        for value, text in TYPES.items():
            ttk.Radiobutton(row, text=text, variable=self.kind, value=value).pack(side="left", padx=(0, 24))
        ttk.Radiobutton(body, text="复制到工程库 · 保留源文件（推荐）", variable=self.copy, value=True).pack(anchor="w", pady=4)
        ttk.Radiobutton(body, text="保留原位置 · 只建立文件索引", variable=self.copy, value=False).pack(anchor="w", pady=4)
        label(body, "请选择包含装配零件、仿真配套目录的完整工程文件夹。", color=MUTED).pack(anchor="w", pady=(10, 8))
        self.preview_button = ttk.Button(body, text="扫描并预览分类", command=self.preview)
        self.preview_button.pack(anchor="w", pady=(0, 10))
        summary_frame = tk.Frame(body, bg=BG)
        self.summary = tk.Text(summary_frame, height=8, font=("Microsoft YaHei UI", 10), bg=BG, fg=INK, relief="flat", padx=12, pady=10, wrap="word")
        scrollbar = ttk.Scrollbar(summary_frame, orient="vertical", command=self.summary.yview)
        scrollbar.pack(side="right", fill="y")
        self.summary.configure(yscrollcommand=scrollbar.set)
        self.summary.pack(side="left", fill="both", expand=True)
        self.set_summary("尚未扫描。选择文件夹后，点击“扫描并预览分类”。")
        row = tk.Frame(body, bg=WHITE)
        row.pack(side="bottom", fill="x", pady=(18, 0))
        self.confirm_button = ttk.Button(row, text="确认导入", style="Primary.TButton", command=self.submit, state="disabled")
        self.confirm_button.pack(side="right")
        self.cancel_button = ttk.Button(row, text="取消", command=self.close)
        self.cancel_button.pack(side="right", padx=10)
        summary_frame.pack(fill="both", expand=True)
        self.source.trace_add("write", self.invalidate)
        self.scanning = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grab_set()

    def close(self):
        if self.scanning:
            self.app.status.set("正在扫描导入目录，请等待扫描结束。")
            return
        self.destroy()

    def invalidate(self, *_args):
        self.previewed = None
        self.confirm_button.configure(state="disabled")

    def browse(self):
        path = filedialog.askdirectory(title="选择完整工程文件夹", parent=self)
        if path:
            self.source.set(path)
            if not self.name.get():
                self.name.set(Path(path).name)

    def set_summary(self, text):
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", text)
        self.summary.configure(state="disabled")

    def preview(self):
        path = Path(self.source.get().strip()).expanduser().resolve()
        if not self.source.get().strip() or not path.is_dir():
            messagebox.showinfo("选择工程文件夹", "请选择有效的工程文件夹。", parent=self)
            return
        if path == self.app.library.root or self.app.library.root.is_relative_to(path):
            messagebox.showinfo("选择工程文件夹", "不能导入工程库或包含工程库的上级目录。", parent=self)
            return
        self.scanning = True
        self.preview_button.configure(state="disabled")
        self.browse_button.configure(state="disabled")
        self.confirm_button.configure(state="disabled")
        self.set_summary("正在扫描工程目录…")

        def finish(result):
            self.scanning = False
            self.preview_button.configure(state="normal")
            self.browse_button.configure(state="normal")
            lines = [f"共发现 {len(result.files):,} 个文件", ""]
            lines.extend(f"{text}    {result.counts[category]:,}" for category, text in CATEGORIES.items())
            if result.errors or result.skipped:
                lines.append(f"\n读取失败 {len(result.errors)} 项；跳过链接 {len(result.skipped)} 项。存在这些项时仅支持原位置索引。")
                lines.extend(result.errors[:3] + result.skipped[:3])
            self.set_summary("\n".join(lines))
            if Path(self.source.get()).resolve() == path:
                self.previewed = (path, result)
                self.confirm_button.configure(state="normal")

        def failed(error):
            self.scanning = False
            self.preview_button.configure(state="normal")
            self.browse_button.configure(state="normal")
            self.set_summary(str(error))

        self.app.run_job("正在预览工程文件", lambda: scan_directory(path, self.app.progress), finish, failed)

    def submit(self):
        if not self.previewed or not self.name.get().strip():
            messagebox.showinfo("导入工程", "请填写项目名称并完成扫描预览。", parent=self)
            return
        source, snapshot = self.previewed
        if self.copy.get() and (snapshot.errors or snapshot.skipped):
            messagebox.showinfo("无法完整复制", "源目录含无法读取的文件或链接，请修正后重新扫描，或选择“保留原位置”。", parent=self)
            return
        name, kind, copy = self.name.get().strip(), self.kind.get(), self.copy.get()
        self.destroy()
        self.app.run_job("正在导入工程，保留原目录结构", lambda: self.app.library.import_project(source, name, kind, "", copy, self.app.progress), self.app.import_finished)


class App:
    def __init__(self, root: tk.Tk, library: Library, persist_settings: bool = True):
        self.root = root
        self.library = library
        self.persist_settings = persist_settings
        self.busy = False
        self.events = queue.Queue()
        self.view = "home"
        self.project_type = None
        self.active_project = None
        self.category = None
        self.file_rows = {}
        self.status = tk.StringVar(value="就绪 · 文件保存在普通工程目录中")
        self.auto_scan = tk.BooleanVar(value=True)
        self.search_timer = None
        self.root.title(f"EngineerHub · 工程项目中心 v{__version__}")
        self.root.geometry("1250x820")
        self.root.minsize(1040, 700)
        self.root.configure(bg=BG)
        self.setup_styles()
        self.build_shell()
        self.show_home()
        self.root.after(100, self.poll)
        self.root.after(30000, self.periodic_scan)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def setup_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background=BG, foreground=INK)
        style.configure("TButton", padding=(12, 8), background=WHITE, bordercolor=BORDER, relief="flat")
        style.map("TButton", background=[("active", "#edf2fa"), ("disabled", BG)], foreground=[("disabled", "#9aa4b4")])
        style.configure("Primary.TButton", background=BLUE, foreground=WHITE, bordercolor=BLUE)
        style.map("Primary.TButton", background=[("active", "#1853bd"), ("disabled", "#9ab9ec")], foreground=[("disabled", WHITE)])
        style.configure("TEntry", padding=8, fieldbackground=WHITE, bordercolor=BORDER)
        style.configure("TRadiobutton", background=WHITE)
        style.configure("TCheckbutton", background=BG)
        style.configure("Treeview", background=WHITE, fieldbackground=WHITE, rowheight=38, borderwidth=0)
        style.configure("Treeview.Heading", background="#edf1f7", foreground=MUTED, padding=(10, 10), font=("Microsoft YaHei UI", 10))
        style.map("Treeview", background=[("selected", "#e8f0ff")], foreground=[("selected", "#174c9f")])

    def build_shell(self):
        header = tk.Frame(self.root, bg=WHITE, height=76)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        label(header, "EngineerHub", 22, bold=True).pack(side="left", padx=(28, 18))
        label(header, "工程项目中心", color=MUTED).pack(side="left")
        label(header, "LOCAL  /  V0.1", 9, color=MUTED).pack(side="right", padx=28)
        body = tk.Frame(self.root, bg=BG)
        body.grid(row=1, column=0, sticky="nsew")
        side = tk.Frame(body, bg=WHITE, width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        label(side, "工程库", 9, color=MUTED).pack(anchor="w", padx=24, pady=(28, 12))
        self.nav_buttons = {}
        for key, text, command in [
            ("home", "总览", self.show_home),
            ("machine", "整机设计", lambda: self.show_projects("machine")),
            ("component", "零部件设计", lambda: self.show_projects("component")),
            ("all", "全部项目", lambda: self.show_projects(None)),
        ]:
            button = tk.Button(side, text=text, anchor="w", relief="flat", bd=0, bg=WHITE, fg=INK,
                               activebackground="#e8f0ff", font=("Microsoft YaHei UI", 11), padx=24, pady=12, command=command, cursor="hand2")
            button.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = button
        bottom = tk.Frame(side, bg=WHITE)
        bottom.pack(side="bottom", fill="x", padx=22, pady=24)
        label(bottom, "当前工程库", 9, color=MUTED).pack(anchor="w")
        self.library_label = label(bottom, str(self.library.root), 9, color=MUTED, wraplength=176, justify="left")
        self.library_label.pack(anchor="w", pady=(6, 14))
        ttk.Button(bottom, text="选择工程库…", command=self.choose_library).pack(fill="x")
        self.content = tk.Frame(body, bg=BG, padx=28, pady=24)
        self.content.pack(side="left", fill="both", expand=True)
        footer = tk.Frame(self.root, bg=WHITE, height=34)
        footer.grid(row=2, column=0, sticky="ew")
        footer.pack_propagate(False)
        tk.Label(footer, textvariable=self.status, anchor="w", bg=WHITE, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=22, fill="x", expand=True)
        self.progress_bar = ttk.Progressbar(footer, mode="indeterminate", length=120)

    def ready(self):
        if self.busy:
            self.status.set("后台任务处理中，请稍候。")
            return False
        return True

    def clear(self, selected):
        if self.search_timer:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        for widget in self.content.winfo_children():
            widget.destroy()
        for key, button in self.nav_buttons.items():
            button.configure(bg="#e8f0ff" if key == selected else WHITE, fg=BLUE if key == selected else INK)

    def heading(self, title, subtitle):
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(0, 20))
        left = tk.Frame(row, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        label(left, title, 22, bold=True).pack(anchor="w")
        label(left, subtitle, 10, color=MUTED).pack(anchor="w", pady=(6, 0))
        return row

    def show_home(self):
        if not self.ready():
            return
        self.view, self.active_project, self.project_type = "home", None, None
        self.clear("home")
        self.heading("让工程文件，回到项目里", "从整机或零部件出发，集中查看模型、仿真、计算与资料。")
        projects = self.library.projects()
        cards = tk.Frame(self.content, bg=BG)
        cards.pack(fill="x", pady=(2, 22))
        for kind, title, description in [
            ("machine", "整机设计", "管理设备总装、工程图与整机分析"),
            ("component", "零部件设计", "管理零件、组件与独立设计任务"),
        ]:
            card = tk.Frame(cards, bg=WHITE, highlightbackground=BORDER, highlightthickness=1, padx=24, pady=20)
            card.pack(side="left", fill="both", expand=True, padx=(0, 12) if kind == "machine" else (0, 0))
            count = sum(project["type"] == kind for project in projects)
            label(card, title, 17, bold=True).pack(anchor="w")
            label(card, description, color=MUTED).pack(anchor="w", pady=(8, 18))
            row = tk.Frame(card, bg=WHITE)
            row.pack(fill="x")
            label(row, f"{count} 个项目", 12, color=BLUE, bold=True).pack(side="left")
            ttk.Button(row, text="进入 →", command=lambda value=kind: self.show_projects(value)).pack(side="right")
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(0, 14))
        label(row, "最近项目", 14, bold=True).pack(side="left")
        ttk.Button(row, text="导入现有工程", command=self.import_dialog).pack(side="right")
        ttk.Button(row, text="＋ 新建项目", style="Primary.TButton", command=self.new_project).pack(side="right", padx=10)
        self.project_tree = self.make_project_tree()
        self.fill_projects(projects[:8])
        if not projects:
            label(self.content, "工程库还没有项目。新建一个工程，或导入已有文件夹开始使用。", color=MUTED).pack(anchor="w", pady=(14, 0))

    def make_project_tree(self):
        frame = tk.Frame(self.content, bg=WHITE)
        frame.pack(fill="both", expand=True)
        columns = ("code", "name", "type", "files", "updated", "mode")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=6)
        specs = [("code", "编号", 100), ("name", "项目名称", 250), ("type", "类型", 100), ("files", "文件", 65), ("updated", "最近修改", 145), ("mode", "存储方式", 110)]
        for key, text, width in specs:
            tree.heading(key, text=text, anchor="w")
            tree.column(key, width=width, minwidth=50, stretch=key == "name", anchor="w")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.bind("<Double-1>", lambda _event: self.open_selected_project())
        tree.bind("<Return>", lambda _event: self.open_selected_project())
        return tree

    def fill_projects(self, projects):
        self.project_tree.delete(*self.project_tree.get_children())
        for project in projects:
            self.project_tree.insert("", "end", iid=str(project["id"]), values=(
                self.library.code(project["id"]), project["name"], TYPES[project["type"]],
                str(project["file_count"]) + (f" / 丢失 {project['missing_count']}" if project["missing_count"] else ""),
                local_date(project["updated_at"]), "工程库" if project["storage_mode"] == "managed" else "原位置索引"))

    def show_projects(self, kind):
        if not self.ready():
            return
        self.view, self.active_project, self.project_type = "projects", None, kind
        self.clear(kind or "all")
        row = self.heading(TYPES.get(kind, "全部项目"), "双击项目进入工程文件中心 · 按最近修改时间排序")
        ttk.Button(row, text="＋ 新建项目", style="Primary.TButton", command=self.new_project).pack(side="right")
        toolbar = tk.Frame(self.content, bg=BG)
        toolbar.pack(fill="x", pady=(0, 14))
        self.project_query = tk.StringVar()
        search = ttk.Entry(toolbar, textvariable=self.project_query, width=28)
        search.pack(side="left")
        label(toolbar, "搜索名称、编号或说明", 9, color=MUTED).pack(side="left", padx=10)
        self.project_query.trace_add("write", lambda *_args: self.debounce(self.refresh_projects))
        ttk.Button(toolbar, text="导入工程", command=self.import_dialog).pack(side="right")
        ttk.Button(toolbar, text="移除登记", command=self.remove_project).pack(side="right", padx=6)
        ttk.Button(toolbar, text="编辑", command=self.edit_project).pack(side="right")
        ttk.Button(self.content, text="进入选中项目 →", command=self.open_selected_project).pack(side="bottom", anchor="e", pady=(14, 0))
        self.project_tree = self.make_project_tree()
        self.refresh_projects()

    def debounce(self, callback):
        if self.search_timer:
            self.root.after_cancel(self.search_timer)
        def execute():
            self.search_timer = None
            callback()
        self.search_timer = self.root.after(180, execute)

    def refresh_projects(self):
        self.fill_projects(self.library.projects(self.project_type, self.project_query.get()))

    def selected_project(self):
        if self.view == "detail":
            return self.active_project
        selected = self.project_tree.selection()
        if not selected:
            messagebox.showinfo("选择项目", "请先选择一个项目。", parent=self.root)
            return None
        return int(selected[0])

    def open_selected_project(self):
        if self.ready():
            project_id = self.selected_project()
            if project_id:
                self.show_detail(project_id)

    def new_project(self):
        if not self.ready():
            return
        dialog = ProjectDialog(self, project_type=self.project_type or "machine")
        self.root.wait_window(dialog)
        if dialog.result:
            try:
                project = self.library.create(*dialog.result)
                self.status.set(f"已创建 {self.library.code(project['id'])} · {project['name']}")
                self.show_detail(project["id"])
            except Exception as error:
                self.error(error)

    def edit_project(self):
        if not self.ready():
            return
        project_id = self.selected_project()
        if not project_id:
            return
        dialog = ProjectDialog(self, self.library.project(project_id))
        self.root.wait_window(dialog)
        if dialog.result:
            try:
                self.library.edit(project_id, *dialog.result)
                self.show_detail(project_id, scan=False) if self.view == "detail" else self.refresh_projects()
                self.status.set("项目信息已保存。")
            except Exception as error:
                self.error(error)

    def remove_project(self):
        if not self.ready():
            return
        project_id = self.selected_project()
        if not project_id:
            return
        project = self.library.project(project_id)
        if messagebox.askyesno("移除项目登记", f"从工程库移除“{project['name']}”？\n\n仅移除项目和文件索引，所有工程文件保留在原目录。\n\n{self.library.workspace(project)}", parent=self.root):
            try:
                self.library.remove(project_id)
                self.show_projects(project["type"])
                self.status.set("项目登记已移除，工程文件已保留。")
            except Exception as error:
                self.error(error)

    def import_dialog(self):
        if self.ready():
            ImportDialog(self, self.project_type or "machine")

    def import_finished(self, result):
        project, scan = result
        self.show_detail(project["id"], scan=False)
        self.status.set(f"导入完成 · {len(scan.files):,} 个文件" + (" · 部分目录读取异常，见扫描提示" if scan.errors else ""))

    def show_detail(self, project_id, scan=True):
        if not self.ready():
            return
        project = self.library.project(project_id)
        self.view, self.active_project, self.project_type = "detail", project_id, project["type"]
        self.category = None
        self.clear(project["type"])
        row = self.heading(project["name"], f"{self.library.code(project_id)}  /  {TYPES[project['type']]}  /  {'工程库文件' if project['storage_mode'] == 'managed' else '原位置索引'}")
        ttk.Button(row, text="编辑项目", command=self.edit_project).pack(side="right")
        if project["description"]:
            label(self.content, project["description"], color=MUTED, wraplength=820, justify="left").pack(anchor="w", pady=(0, 12))
        path = str(self.library.workspace(project))
        path_row = tk.Frame(self.content, bg=BG)
        path_row.pack(fill="x", pady=(0, 14))
        path_entry = ttk.Entry(path_row)
        path_entry.insert(0, path)
        path_entry.configure(state="readonly")
        path_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(path_row, text="打开项目目录", command=self.open_workspace).pack(side="right", padx=(10, 0))
        categories = tk.Frame(self.content, bg=BG)
        categories.pack(fill="x", pady=(0, 16))
        self.category_buttons = {}
        for index, (category, text) in enumerate([(None, "全部")] + list(CATEGORIES.items())):
            button = ttk.Button(categories, text=text, command=lambda value=category: self.set_category(value))
            button.grid(row=0, column=index, sticky="ew", padx=(0, 5))
            categories.columnconfigure(index, weight=1, uniform="categories")
            self.category_buttons[category] = button
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=(0, 12))
        self.file_query = tk.StringVar()
        ttk.Entry(row, textvariable=self.file_query, width=26).pack(side="left")
        label(row, "搜索文件名或相对路径", 9, color=MUTED).pack(side="left", padx=10)
        self.file_query.trace_add("write", lambda *_args: self.debounce(self.refresh_files))
        ttk.Button(row, text="立即扫描", command=self.scan_active).pack(side="right")
        ttk.Checkbutton(row, text="自动刷新", variable=self.auto_scan).pack(side="right", padx=12)
        frame = tk.Frame(self.content, bg=WHITE)
        columns = ("name", "category", "type", "size", "modified", "path", "state")
        self.file_tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=6)
        specs = [("name", "文件名称", 225), ("category", "分类", 100), ("type", "类型", 85), ("size", "大小", 80), ("modified", "修改时间", 140), ("path", "相对路径", 260), ("state", "状态", 65)]
        for key, text, width in specs:
            self.file_tree.heading(key, text=text, anchor="w", command=lambda value=key: self.sort_files(value))
            self.file_tree.column(key, width=width, minwidth=50, stretch=key in ("name", "path"))
        self.file_tree.tag_configure("missing", foreground="#ad5353")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.file_tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.file_tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.file_tree.bind("<Double-1>", lambda _event: self.open_selected_file())
        self.file_tree.bind("<Return>", lambda _event: self.open_selected_file())
        row = tk.Frame(self.content, bg=BG)
        row.pack(side="bottom", fill="x", pady=(14, 0))
        self.scan_text = label(row, "", 9, color=MUTED)
        self.scan_text.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="定位文件", command=self.locate_file).pack(side="right")
        self.open_file_button = ttk.Button(row, text="打开选中文件", style="Primary.TButton", command=self.open_selected_file)
        self.open_file_button.pack(side="right", padx=10)
        frame.pack(fill="both", expand=True)
        self.refresh_files()
        if scan:
            self.scan_active()

    def set_category(self, category):
        self.category = category
        self.refresh_files()

    def refresh_files(self):
        if self.view != "detail":
            return
        all_files = self.library.files(self.active_project)
        counts = {category: sum(item["category"] == category and not item["missing"] for item in all_files) for category in CATEGORIES}
        for category, button in self.category_buttons.items():
            count = counts[category] if category else sum(counts.values())
            button.configure(text=f"{CATEGORIES.get(category, '全部')}  {count}", style="Primary.TButton" if self.category == category else "TButton")
        selection = self.file_tree.selection()
        self.file_tree.delete(*self.file_tree.get_children())
        self.file_rows = {}
        for item in self.library.files(self.active_project, self.category, self.file_query.get()):
            iid = str(item["id"])
            self.file_rows[iid] = item
            self.file_tree.insert("", "end", iid=iid, values=(
                item["name"], CATEGORIES[item["category"]], item["extension"].upper() or "—", human_size(item["size"]),
                datetime.fromtimestamp(item["mtime_ns"] / 1e9).strftime("%Y-%m-%d %H:%M"), item["relative_path"], "丢失" if item["missing"] else "可用"), tags=("missing",) if item["missing"] else ())
        if selection and selection[0] in self.file_rows:
            self.file_tree.selection_set(selection[0])
        project = self.library.project(self.active_project)
        missing = sum(item["missing"] for item in all_files)
        text = f"索引 {len(all_files):,} 项 · 丢失 {missing} 项 · 扫描 {local_date(project['scanned_at'])}"
        if project["scan_note"]:
            text = project["scan_note"]
        self.scan_text.configure(text=text)

    def sort_files(self, key):
        reverse = getattr(self, "sort_state", (None, False)) == (key, False)
        self.sort_state = (key, reverse)
        mapping = {"type": "extension", "modified": "mtime_ns", "path": "relative_path", "state": "missing"}
        field = mapping.get(key, key)
        rows = sorted(self.file_rows, key=lambda iid: self.file_rows[iid][field].casefold() if isinstance(self.file_rows[iid][field], str) else self.file_rows[iid][field], reverse=reverse)
        for position, iid in enumerate(rows):
            self.file_tree.move(iid, "", position)

    def selected_file(self):
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showinfo("选择文件", "请先选择一个工程文件。", parent=self.root)
            return None
        return self.file_rows[selected[0]]

    def open_selected_file(self):
        item = self.selected_file()
        if item:
            try:
                path = open_file(self.library.workspace(self.library.project(self.active_project)), item["relative_path"])
                self.status.set(f"已发送本机文件打开命令：{path.name}")
            except Exception as error:
                self.error(error)

    def locate_file(self):
        item = self.selected_file()
        if item:
            try:
                path = contained_file(self.library.workspace(self.library.project(self.active_project)), item["relative_path"])
                open_folder(path.parent)
                self.status.set(f"已打开文件所在文件夹：{path.parent}")
            except Exception as error:
                self.error(error)

    def open_workspace(self):
        try:
            open_folder(self.library.workspace(self.library.project(self.active_project)))
        except Exception as error:
            self.error(error)

    def scan_active(self, silent=False):
        if self.busy or self.view != "detail":
            return
        project_id = self.active_project
        def finished(result):
            if self.active_project == project_id:
                self.refresh_files()
            self.status.set(f"扫描完成 · {len(result.files):,} 个文件" + (f" · {len(result.errors)} 项读取失败" if result.errors else ""))
        def failed(error):
            self.status.set(f"扫描失败 · {error}")
            if not silent:
                self.error(error)
        self.run_job("正在扫描工程目录", lambda: self.library.scan(project_id, self.progress), finished, failed)

    def periodic_scan(self):
        if self.auto_scan.get() and self.view == "detail" and not self.busy and not self.root.grab_current():
            self.scan_active(silent=True)
        self.root.after(30000, self.periodic_scan)

    def progress(self, count):
        self.events.put(("progress", count))

    def run_job(self, text, work, success, failure=None):
        if self.busy:
            return
        self.busy = True
        # Tk objects must be finalized on the GUI thread. A scanner allocating
        # many dictionaries can otherwise trigger cyclic GC of old dialog widgets.
        gc.collect()
        self.gc_was_enabled = gc.isenabled()
        gc.disable()
        self.status.set(text)
        self.progress_bar.pack(side="right", padx=16)
        self.progress_bar.start(12)
        def worker():
            try:
                result = work()
                self.events.put(("success", success, result))
            except Exception as error:
                self.events.put(("failure", failure or self.error, error))
        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    self.status.set(f"正在读取工程目录 · 已识别 {event[1]:,} 个文件")
                else:
                    self.worker_thread.join()
                    if self.gc_was_enabled:
                        gc.enable()
                    gc.collect()
                    self.busy = False
                    self.progress_bar.stop()
                    self.progress_bar.pack_forget()
                    try:
                        event[1](event[2])
                    except Exception as error:
                        self.error(error)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def choose_library(self):
        if not self.ready():
            return
        path = filedialog.askdirectory(title="选择或创建 EngineerHub 工程库", initialdir=self.library.root, parent=self.root)
        if path:
            try:
                library = Library(Path(path))
                if self.persist_settings:
                    save_library_path(library.root)
                self.library = library
                self.library_label.configure(text=str(library.root))
                self.show_home()
                self.status.set("已切换工程库。")
            except Exception as error:
                self.error(error)

    def error(self, error):
        self.status.set(str(error).splitlines()[0])
        messagebox.showerror("EngineerHub", str(error), parent=self.root)

    def close(self):
        if self.busy:
            self.status.set("后台任务处理中，请等待完成后关闭程序。")
            return
        self.root.destroy()
