# -*- coding: utf-8 -*-
"""电机选型程序 —— 图形界面入口。

运行：python main.py
打包：见 build_exe.ps1（生成单个 exe）
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import (                                    # noqa: E402
    GEARBOX_COLUMNS, MOTOR_COLUMNS, all_gearboxes, all_motors,
    clear_user_motors, export_gearbox_template, export_motor_template,
    import_user_gearboxes, import_user_motors,
    save_gearboxes_csv, save_motors_csv,
)
from core.entities import (                                   # noqa: E402
    CASES, EFFICIENCY_HINT, INERTIA_SHAPES, MOTOR_KINDS, TRANSMISSIONS,
    VOLTAGES, CheckItem, Evaluation, LoadCase, Motor, Requirement,
    _fmt, fmt_input,
)
from core.mechanics import compute, inertia_of_shape, load_inertia  # noqa: E402
from core.report import build_html, write_evals_csv, write_html     # noqa: E402
from core.resources import report_dir, scheme_dir, user_data_dir    # noqa: E402
from core.selector import auto_select, check_manual, summarize      # noqa: E402

APP_TITLE = "电机选型计算程序 v1.0"
FONT = ("Microsoft YaHei UI", 10)
FONT_SM = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 15, "bold")


def enable_dpi_awareness() -> None:
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:                                          # noqa: BLE001
        pass


# ==========================================================================
# 参数表单定义
# ==========================================================================
LINEAR_ONLY = lambda lc: lc.is_linear                              # noqa: E731
ROTARY_ONLY = lambda lc: lc.is_rotary                              # noqa: E731
ALWAYS = lambda lc: True                                           # noqa: E731


def _case_in(*names: str) -> Callable[[LoadCase], bool]:
    return lambda lc: lc.case in names


def _trans_in(*names: str) -> Callable[[LoadCase], bool]:
    return lambda lc: lc.transmission in names


def _eq(key: str, value: str) -> Callable[[LoadCase], bool]:
    return lambda lc: getattr(lc, key) == value


# (key, 标签, 单位, 类型, 选项, 提示, 显示条件, 分组)
FIELDS: List[Tuple] = [
    # ---------------- 工况与负载 ----------------
    ("case", "工况类型", "", "choice", CASES, "决定受力模型：水平/垂直/倾斜/输送/旋转/卷绕", ALWAYS, "① 工况与负载"),
    ("mass", "负载质量", "kg", "float", None, "运动部件的总质量（工件+夹具+滑台）", LINEAR_ONLY, "① 工况与负载"),
    ("belt_mass", "皮带/承载件质量", "kg", "float", None, "输送机的皮带、链板、托辊折算质量", _eq("case", "conveyor"), "① 工况与负载"),
    ("counterweight", "配重质量", "kg", "float", None, "垂直/倾斜工况的平衡配重（0=无配重）",
     _case_in("vertical_lift", "incline", "conveyor"), "① 工况与负载"),
    ("mu", "摩擦系数 μ", "-", "float", None, "直线导轨 0.003~0.01；滑块/滚轮 0.02~0.05；滑动导轨 0.1~0.2",
     LINEAR_ONLY, "① 工况与负载"),
    ("incline_deg", "倾斜角", "°", "float", None, "水平=0，垂直=90", _case_in("incline", "conveyor"), "① 工况与负载"),
    ("ext_force", "恒定外部阻力", "N", "float", None, "切削力、弹簧力、刮擦阻力等（与运动方向相反为正）", LINEAR_ONLY, "① 工况与负载"),
    ("friction_torque", "轴承摩擦转矩", "N·m", "float", None, "旋转工况的轴承/密封阻力矩", ROTARY_ONLY, "① 工况与负载"),
    ("ext_torque", "外部阻力矩", "N·m", "float", None, "与转向相反的外部力矩（切削、刮擦等）", ROTARY_ONLY, "① 工况与负载"),
    ("unbalanced_torque", "不平衡重力矩", "N·m", "float", None, "偏心负载产生的最大重力矩", ROTARY_ONLY, "① 工况与负载"),

    # ---------------- 运动与时间 ----------------
    ("speed", "运动 / 线速度", "m/s", "float", None, "直线工况的目标速度；卷绕时为线速度",
     lambda lc: lc.is_linear or lc.case == "winding", "② 运动与时间"),
    ("load_rpm", "负载转速", "rpm", "float", None, "旋转工况负载侧的目标转速", ROTARY_ONLY, "② 运动与时间"),
    ("accel_time", "加速时间", "s", "float", None, "从 0 到目标速度的时间，决定加速度与加速转矩", ALWAYS, "② 运动与时间"),
    ("decel_time", "减速时间", "s", "float", None, "减速段用于计算回馈能量与 RMS 转矩", ALWAYS, "② 运动与时间"),
    ("const_time", "匀速运行时间", "s", "float", None, "单周期里匀速段的时间", ALWAYS, "② 运动与时间"),
    ("dwell_time", "停留时间", "s", "float", None, "单周期里停止的时间，影响占空比与发热校核", ALWAYS, "② 运动与时间"),
    ("stroke", "行程", "m", "float", None, "校验加减速距离是否放得下", LINEAR_ONLY, "② 运动与时间"),
    ("positioning_mm", "定位精度要求", "mm", "float", None, "用于校核步距角 / 编码器分辨率 / 减速机背隙", ALWAYS, "② 运动与时间"),
    ("starts_per_hour", "每小时启停次数", "次/h", "float", None, "0 = 按上面的时间参数自动推算", ALWAYS, "② 运动与时间"),

    # ---------------- 传动与效率 ----------------
    ("transmission", "传动形式", "", "choice", TRANSMISSIONS, "决定力→转矩的换算方式", ALWAYS, "③ 传动与效率"),
    ("ratio", "减速比 i", "-", "float", None, "i = 电机转速 / 负载转速；不加减速机填 1", ALWAYS, "③ 传动与效率"),
    ("efficiency", "传动效率 η", "-", "float", None, "只填传动机构效率（减速机效率按型号自动叠加）", ALWAYS, "③ 传动与效率"),
    ("pulley_dia", "带轮/齿轮节圆直径", "m", "float", None, "填了就用 π·D 作为每转移动量；0 = 用下面的每转移动量",
     _trans_in("belt", "chain", "rack", "drum"), "③ 传动与效率"),
    ("per_rev_travel", "每转移动量 L", "m/rev", "float", None, "负载轴转一圈，负载移动多少米", _trans_in("belt", "chain", "rack", "drum"), "③ 传动与效率"),
    ("screw_lead", "丝杆导程 P", "m", "float", None, "丝杆转一圈前进的距离", _trans_in("screw_ball", "screw_trap"), "③ 传动与效率"),
    ("screw_dia", "丝杆公称直径", "m", "float", None, "用于估算丝杆自身惯量", _trans_in("screw_ball", "screw_trap"), "③ 传动与效率"),
    ("screw_len", "丝杆长度", "m", "float", None, "用于估算丝杆惯量与长径比", _trans_in("screw_ball", "screw_trap"), "③ 传动与效率"),
    ("screw_efficiency", "丝杆效率", "-", "float", None, "滚珠 0.85~0.95；梯形 0.30~0.50", _trans_in("screw_ball", "screw_trap"), "③ 传动与效率"),
    ("trans_inertia", "传动件惯量(负载侧)", "kg·m²", "float", None, "带轮/齿轮/丝杆自身惯量；丝杆留 0 会自动估算", ALWAYS, "③ 传动与效率"),
    ("coupling_inertia", "联轴器惯量(电机侧)", "kg·m²", "float", None, "联轴器、制动器、编码器的惯量", ALWAYS, "③ 传动与效率"),

    # ---------------- 旋转负载惯量 ----------------
    ("inertia_mode", "负载惯量来源", "", "choice", INERTIA_SHAPES, "可按形状算，也可直接填实测值", ROTARY_ONLY, "④ 旋转负载惯量"),
    ("load_inertia", "负载惯量", "kg·m²", "float", None, "负载（含工装）绕回转轴的总惯量", lambda lc: lc.is_rotary and lc.inertia_mode == "manual", "④ 旋转负载惯量"),
    ("in_mass", "惯量计算·质量", "kg", "float", None, "用于按形状计算惯量", lambda lc: lc.is_rotary and lc.inertia_mode != "manual", "④ 旋转负载惯量"),
    ("in_r2", "外半径 r₂ / r", "m", "float", None, "实心圆柱/圆环/球的外半径", lambda lc: lc.is_rotary and lc.inertia_mode in ("solid_cylinder", "ring", "sphere"), "④ 旋转负载惯量"),
    ("in_r1", "内半径 r₁", "m", "float", None, "仅圆环用", lambda lc: lc.is_rotary and lc.inertia_mode == "ring", "④ 旋转负载惯量"),
    ("in_a", "边长 a", "m", "float", None, "长方体用", lambda lc: lc.is_rotary and lc.inertia_mode == "box", "④ 旋转负载惯量"),
    ("in_b", "边长 b", "m", "float", None, "长方体用", lambda lc: lc.is_rotary and lc.inertia_mode == "box", "④ 旋转负载惯量"),
    ("in_l", "长度 l", "m", "float", None, "细长杆用（绕端部）", lambda lc: lc.is_rotary and lc.inertia_mode == "rod_end", "④ 旋转负载惯量"),

    # ---------------- 卷绕参数 ----------------
    ("drum_dia0", "最小卷径 D0", "m", "float", None, "芯轴（空卷）直径，决定最高转速", _eq("case", "winding"), "⑤ 卷绕参数"),
    ("drum_dia1", "最大卷径 D1", "m", "float", None, "满卷直径，决定最大转矩", _eq("case", "winding"), "⑤ 卷绕参数"),
    ("tension", "张力", "N", "float", None, "收放卷的材料张力", _eq("case", "winding"), "⑤ 卷绕参数"),
    ("drum_mass", "卷筒质量", "kg", "float", None, "用于估算卷筒惯量", _eq("case", "winding"), "⑤ 卷绕参数"),
    ("drum_inertia", "卷筒惯量", "kg·m²", "float", None, "留 0 则按实心圆柱自动估算", _eq("case", "winding"), "⑤ 卷绕参数"),

    # ---------------- 选型要求 ----------------
    ("motor_kind_pref", "电机类型要求", "", "choice", [("任意", "任意")] + [(k, k) for k in MOTOR_KINDS],
     "限定只在某类电机里选", ALWAYS, "⑥ 选型要求"),
    ("allow_gearbox", "允许加装减速机", "", "bool", None, "勾选后会自动搜索合适减速比", ALWAYS, "⑥ 选型要求"),
    ("sf_torque", "转矩安全系数", "-", "float", None, "需求转矩×该系数 后再与电机能力比较（建议 1.3~2.0）", ALWAYS, "⑥ 选型要求"),
    ("sf_power", "功率安全系数", "-", "float", None, "功率校核用的安全系数（建议 1.1~1.5）", ALWAYS, "⑥ 选型要求"),
    ("max_inertia_ratio", "惯量比上限", "-", "float", None, "0 = 按电机类型默认（伺服10 / 步进5 / 异步100）", ALWAYS, "⑥ 选型要求"),
    ("voltage", "供电条件", "", "choice", [(v, v) for v in VOLTAGES], "按电压筛选型号库", ALWAYS, "⑥ 选型要求"),
    ("max_motor_power", "最大电机功率", "W", "float", None, "0 = 不限；用于限制机座号/成本", ALWAYS, "⑥ 选型要求"),
]

MANUAL_FIELDS = [
    ("manual_kind", "电机类型", "", "choice", [(k, k) for k in MOTOR_KINDS]),
    ("manual_power", "额定功率", "W", "float", None),
    ("manual_rpm", "额定转速", "rpm", "float", None),
    ("manual_max_rpm", "最高转速", "rpm", "float", None),
    ("manual_torque", "额定转矩", "N·m", "float", None),
    ("manual_peak_torque", "峰值/最大转矩", "N·m", "float", None),
    ("manual_inertia", "转子惯量", "kg·m²", "float", None),
]


# ==========================================================================
# 可滚动容器
# ==========================================================================
class ScrollFrame(ttk.Frame):
    """带垂直滚动条的容器，内容放在 self.body。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _on_body(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_wheel(self, event) -> None:
        """只有当鼠标指针确实落在本滚动区域内时才滚动。"""
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
            while widget is not None:
                if widget is self:
                    self.canvas.yview_scroll(int(-event.delta / 120), "units")
                    return
                widget = getattr(widget, "master", None)
        except Exception:                                      # noqa: BLE001
            pass


# ==========================================================================
# 参数表单
# ==========================================================================
class ParamForm:
    """按 FIELDS 定义自动生成输入控件，并按工况动态显示。"""

    VISIBILITY_KEYS = {"case", "transmission", "inertia_mode"}

    def __init__(self, parent: tk.Widget, lc: LoadCase, on_change: Callable[[], None]):
        self.lc = lc
        self.on_change = on_change
        self.vars: Dict[str, tk.Variable] = {}
        self.entries: Dict[str, tk.Widget] = {}
        self.choice_maps: Dict[str, Dict[str, str]] = {}
        self.items: List[Dict] = []
        self.groups: Dict[str, ttk.LabelFrame] = {}
        self.groups_order: List[str] = []

        outer = ScrollFrame(parent)
        outer.pack(fill="both", expand=True)
        holder = outer.body

        for spec in FIELDS:
            key, label, unit, kind, choices, tip, show, group = spec
            if group not in self.groups:
                frame = ttk.LabelFrame(holder, text=" " + group + " ", padding=(8, 4, 8, 6))
                frame.pack(fill="x", padx=6, pady=(6, 0))
                self.groups[group] = frame
                self.groups_order.append(group)
            frame = self.groups[group]
            var, widget = self._make_widget(frame, key, kind, choices)
            self.vars[key] = var
            self.entries[key] = widget
            self.items.append({"key": key, "label": label, "unit": unit, "tip": tip,
                               "show": show, "group": group, "kind": kind, "widget": widget,
                               "lbl": None, "unit_lbl": None, "visible": True})
        self.relayout()

    # ------------------------------------------------------------------
    def _make_widget(self, parent, key, kind, choices):
        if kind == "bool":
            var = tk.BooleanVar(value=bool(getattr(self.lc, key)))
            widget = ttk.Checkbutton(parent, variable=var, text="允许加装减速机",
                                     command=lambda k=key: self._changed(k))
        elif kind == "choice":
            self.choice_maps[key] = {lab: val for val, lab in choices}
            labels = [c[1] for c in choices]
            cur = getattr(self.lc, key)
            text = self.choice_maps[key].get(cur, labels[0] if labels else "")
            var = tk.StringVar(value=text)
            widget = ttk.Combobox(parent, textvariable=var, values=labels,
                                  state="readonly", width=26, font=FONT_SM)
            widget.bind("<<ComboboxSelected>>", lambda _e, k=key: self._changed(k))
        else:
            var = tk.StringVar(value=fmt_input(getattr(self.lc, key)))
            widget = ttk.Entry(parent, textvariable=var, width=14, font=FONT_SM)
            var.trace_add("write", lambda *_a, k=key: self._changed(k))
        return var, widget

    def _changed(self, key: str = "") -> None:
        if key in self.VISIBILITY_KEYS:
            self.relayout()
        self.on_change()

    # ------------------------------------------------------------------
    def relayout(self) -> None:
        """按当前工况重新排布（隐藏不适用的参数）。"""
        lc = self.sync_to_case(apply=False)
        rows: Dict[str, int] = {}
        for item in self.items:
            try:
                visible = bool(item["show"](lc))
            except Exception:                                  # noqa: BLE001
                visible = True
            item["visible"] = visible
            for key in ("lbl", "unit_lbl", "widget"):
                widget = item.get(key)
                if widget is not None:
                    widget.grid_remove()
            if not visible:
                continue
            group = item["group"]
            r = rows.get(group, 0)
            rows[group] = r + 1
            frame = self.groups[group]
            if item.get("lbl") is None:
                item["lbl"] = ttk.Label(frame, text=item["label"], font=FONT_SM, width=20,
                                        anchor="e")
            if item.get("unit_lbl") is None:
                item["unit_lbl"] = ttk.Label(frame, text=item["unit"] or "", font=FONT_SM,
                                             foreground="#555", width=9, anchor="w")
            item["lbl"].grid(row=r, column=0, sticky="e", padx=(0, 6), pady=1)
            item["widget"].grid(row=r, column=1, sticky="w", pady=1)
            item["unit_lbl"].grid(row=r, column=2, sticky="w", pady=1)

    # ------------------------------------------------------------------
    def sync_to_case(self, apply: bool = True) -> LoadCase:
        """控件 -> LoadCase。apply=False 时只构造副本用于判断可见性。"""
        lc = self.lc if apply else LoadCase.from_dict(self.lc.to_dict())
        for item in self.items:
            key, kind = item["key"], item["kind"]
            var = self.vars[key]
            if kind == "bool":
                value: object = bool(var.get())
            elif kind == "choice":
                value = self.choice_maps.get(key, {}).get(var.get(), var.get())
            else:
                value = _parse_number(var.get())
            setattr(lc, key, value)
        return lc

    def load_case(self, lc: LoadCase) -> None:
        self.lc = lc
        for item in self.items:
            key, kind = item["key"], item["kind"]
            value = getattr(lc, key)
            if kind == "bool":
                self.vars[key].set(bool(value))
            elif kind == "choice":
                text = self.choice_maps.get(key, {}).get(value)
                if text is None:
                    text = str(value)
                self.vars[key].set(text)
            else:
                self.vars[key].set(fmt_input(value))
        self.relayout()


def _parse_number(text: str, default: float = 0.0) -> float:
    """把输入框文本解析成数字。

    兼容用户手打的千分位逗号（"1,450" 与 "1,234,567"），
    但不会把 "0,5" 这种小数点误当千分位。
    """
    text = (text or "").strip().replace("，", ",").replace(" ", "")
    if not text:
        return default
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    try:
        return float(text)
    except ValueError:
        return default


# ==========================================================================
# 主窗口
# ==========================================================================
class MotorSelectorApp(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x860")
        self.minsize(1180, 720)
        self._configure_style()

        self.lc = LoadCase()
        self.req: Optional[Requirement] = None
        self.evaluations: List[Evaluation] = []
        self.manual_ev: Optional[Evaluation] = None
        self._recalc_job: Optional[str] = None

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self.after(120, self.recalculate)

    # ------------------------------------------------------------------
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure(".", font=FONT)
        style.configure("TButton", font=FONT, padding=(9, 4))
        style.configure("Accent.TButton", font=FONT_BOLD, padding=(11, 5))
        style.configure("TLabelframe.Label", font=FONT_BOLD, foreground="#1e3a8a")
        style.configure("Treeview", font=FONT_SM, rowheight=23)
        style.configure("Treeview.Heading", font=FONT_SM)
        style.configure("TNotebook.Tab", font=FONT, padding=(14, 6))

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(10, 8, 10, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="方案名称：", font=FONT).pack(side="left")
        self.var_name = tk.StringVar(value=self.lc.name)
        ent = ttk.Entry(bar, textvariable=self.var_name, width=16, font=FONT_SM)
        ent.pack(side="left", padx=(0, 14))
        ent.bind("<KeyRelease>", lambda _e: setattr(self.lc, "name", self.var_name.get()))

        ttk.Button(bar, text="计算需求", style="Accent.TButton",
                   command=self.recalculate).pack(side="left", padx=3)
        ttk.Button(bar, text="自动选型", style="Accent.TButton",
                   command=self.run_selection).pack(side="left", padx=3)
        ttk.Button(bar, text="导出计算书(HTML)",
                   command=self.export_report).pack(side="left", padx=3)
        ttk.Button(bar, text="导出选型清单(CSV)",
                   command=self.export_csv).pack(side="left", padx=3)
        ttk.Button(bar, text="保存方案", command=self.save_scheme).pack(side="left", padx=3)
        ttk.Button(bar, text="打开方案", command=self.open_scheme).pack(side="left", padx=3)
        ttk.Button(bar, text="惯量计算器",
                   command=self.open_inertia_tool).pack(side="left", padx=3)
        ttk.Button(bar, text="型号库", command=self.open_library).pack(side="left", padx=3)
        ttk.Button(bar, text="恢复默认", command=self.reset_case).pack(side="left", padx=3)

    # ------------------------------------------------------------------
    def _build_body(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=2)
        self.form = ParamForm(left, self.lc, self.schedule_recalc)

        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        self._build_tab_result()
        self._build_tab_checks()
        self._build_tab_selection()
        self._build_tab_manual()
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    # ---------------- 结果页 ----------------
    def _make_tree(self, parent, columns, widths, height=18, anchors=None):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        for idx, col in enumerate(columns):
            tree.heading(col, text=col)
            tree.column(col, width=widths[idx],
                        anchor=(anchors[idx] if anchors else "w"), stretch=True)
        vs = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        tree.tag_configure("ok", foreground="#14532d")
        tree.tag_configure("bad", foreground="#991b1b")
        tree.tag_configure("warn", foreground="#92400e")
        tree.tag_configure("group", background="#eef2ff", font=FONT_BOLD)
        tree.tag_configure("even", background="#fafafa")
        return tree

    def _build_tab_result(self) -> None:
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="计算结果")
        self.lbl_summary = ttk.Label(tab, text="", font=FONT_BOLD, foreground="#1e3a8a")
        self.lbl_summary.pack(anchor="w", pady=(0, 4))
        self.tree_result = self._make_tree(
            tab, ("项目", "数值", "公式 / 说明"), (230, 150, 620),
            anchors=("w", "e", "w"))

    def _build_tab_checks(self) -> None:
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="校核明细")
        self.lbl_check_head = ttk.Label(tab, text="", font=FONT_BOLD, foreground="#1e3a8a")
        self.lbl_check_head.pack(anchor="w", pady=(0, 4))
        self.tree_checks = self._make_tree(
            tab, ("校核项", "需求值", "电机能力", "余量", "结论", "说明"),
            (150, 110, 120, 62, 60, 460), anchors=("w", "e", "e", "e", "center", "w"))
        warn_box = ttk.LabelFrame(tab, text=" 工程提示 ", padding=6)
        warn_box.pack(fill="both", expand=False, pady=(6, 0))
        self.txt_warn = tk.Text(warn_box, height=6, wrap="word", font=FONT_SM,
                                relief="flat", background="#fffdf5")
        self.txt_warn.pack(fill="both", expand=True)
        self.txt_warn.configure(state="disabled")

    def _build_tab_selection(self) -> None:
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="选型推荐")
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, 4))
        self.lbl_sel = ttk.Label(top, text="点击「自动选型」在型号库中筛选", font=FONT_BOLD,
                                 foreground="#1e3a8a")
        self.lbl_sel.pack(side="left")
        ttk.Button(top, text="查看选中方案校核明细",
                   command=self.show_selected_detail).pack(side="right", padx=3)
        self.tree_sel = self._make_tree(
            tab, ("排名", "类型", "电机 + 减速机", "减速比", "转速rpm", "峰值转矩N·m",
                  "有效转矩N·m", "需求功率W", "惯量比", "匹配度", "结论"),
            (48, 80, 250, 62, 82, 92, 92, 88, 66, 62, 250),
            anchors=("center", "w", "w", "e", "e", "e", "e", "e", "e", "e", "w"))
        self.tree_sel.bind("<Double-1>", lambda _e: self.show_selected_detail())

    def _build_tab_manual(self) -> None:
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="手填电机校核")
        box = ttk.LabelFrame(tab, text=" 手头上一台电机的参数（用于复核，等价于原来的 Excel 用法） ",
                             padding=8)
        box.pack(fill="x")
        self.manual_vars: Dict[str, tk.Variable] = {}
        for idx, (key, label, unit, kind, choices) in enumerate(MANUAL_FIELDS):
            r, c = divmod(idx, 2)
            ttk.Label(box, text=label, font=FONT_SM, width=15, anchor="e").grid(
                row=r, column=c * 3, sticky="e", padx=(4, 4), pady=3)
            if kind == "choice":
                var: tk.Variable = tk.StringVar(value=getattr(self.lc, key))
                w = ttk.Combobox(box, textvariable=var, state="readonly", width=16,
                                 values=[c2[1] for c2 in choices])
            else:
                var = tk.StringVar(value=fmt_input(getattr(self.lc, key)))
                w = ttk.Entry(box, textvariable=var, width=18, font=FONT_SM)
            self.manual_vars[key] = var
            w.grid(row=r, column=c * 3 + 1, sticky="w", pady=3)
            ttk.Label(box, text=unit, font=FONT_SM, foreground="#555", width=8).grid(
                row=r, column=c * 3 + 2, sticky="w", padx=(3, 14))
        btn = ttk.Frame(tab)
        btn.pack(fill="x", pady=6)
        ttk.Button(btn, text="用这台电机做校核", style="Accent.TButton",
                   command=self.run_manual_check).pack(side="left")
        ttk.Button(btn, text="把选型第 1 名填入此处",
                   command=self.fill_manual_from_top).pack(side="left", padx=8)
        self.lbl_manual = ttk.Label(btn, text="", font=FONT_BOLD)
        self.lbl_manual.pack(side="left", padx=12)
        self.tree_manual = self._make_tree(
            tab, ("校核项", "需求值", "电机能力", "余量", "结论", "说明"),
            (150, 110, 120, 62, 60, 460), anchors=("w", "e", "e", "e", "center", "w"))

    # ------------------------------------------------------------------
    def _build_statusbar(self) -> None:
        self.var_status = tk.StringVar(value="就绪")
        bar = ttk.Frame(self, padding=(10, 2))
        bar.pack(fill="x", side="bottom")
        ttk.Separator(self, orient="horizontal").pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.var_status, font=FONT_SM,
                  foreground="#444").pack(side="left")
        ttk.Label(bar, text="数据目录：" + user_data_dir(), font=FONT_SM,
                  foreground="#888").pack(side="right")

    # ==================================================================
    # 计算流程
    # ==================================================================
    def schedule_recalc(self) -> None:
        if self._recalc_job:
            try:
                self.after_cancel(self._recalc_job)
            except Exception:                                  # noqa: BLE001
                pass
        self._recalc_job = self.after(280, self.recalculate)

    def _collect(self) -> bool:
        try:
            lc = self.form.sync_to_case()
        except Exception as exc:                               # noqa: BLE001
            messagebox.showerror("参数读取失败", str(exc))
            return False
        lc.name = self.var_name.get().strip() or "方案1"
        self.lc = lc
        self.form.lc = lc
        return True

    def recalculate(self) -> None:
        self._recalc_job = None
        if not self._collect():
            return
        self.req = compute(self.lc)
        self._fill_result()
        self._fill_manual_env()
        # 自动选型较重（约 0.1~0.5 s），仅在推荐页可见时自动刷新
        if not self.req.ok:
            self.lbl_sel.configure(text="输入有误，请先修正左侧参数")
        elif self.nb.index(self.nb.select()) == 2:
            self.run_selection(silent=True)
        else:
            self.lbl_sel.configure(text="参数已更新，点击「自动选型」或切到本页刷新")

    def run_selection(self, silent: bool = False) -> None:
        if not self._collect():
            return
        self.req = compute(self.lc)
        if not self.req.ok:
            self.lbl_sel.configure(text="输入有误，请先修正左侧参数")
            if not silent:
                messagebox.showwarning("无法选型", "请先修正输入参数：\n" + "\n".join(self.req.errors))
            return
        self.tree_sel.delete(*self.tree_sel.get_children())
        self.update_idletasks()
        try:
            evals = auto_select(self.lc, self.req, all_motors(), all_gearboxes(), top_n=60)
        except Exception as exc:                               # noqa: BLE001
            messagebox.showerror("选型失败", f"{type(exc).__name__}: {exc}")
            return
        self.evaluations = evals
        for idx, ev in enumerate(evals, start=1):
            tag = "ok" if ev.feasible else "bad"
            if not ev.feasible:
                tag = "bad"
            elif ev.score < 70:
                tag = "warn"
            self.tree_sel.insert("", "end", iid=str(idx), tags=(tag,), values=(
                idx, ev.motor.kind, ev.train_label, _fmt(ev.ratio), _fmt(ev.n_motor),
                _fmt(ev.T_peak), _fmt(ev.T_rms), _fmt(ev.P_req), _fmt(ev.inertia_ratio),
                _fmt(ev.score), summarize(ev)))
        if evals:
            best = evals[0]
            self.lbl_sel.configure(
                text=f"共 {len(evals)} 个可行方案 ｜ 首选：{best.motor.kind} {best.train_label}"
                     f"　匹配度 {best.score}　（双击行看校核明细）")
        else:
            self.lbl_sel.configure(text="没有满足全部校核项的方案：可放宽安全系数、允许加减速机或更换电机类型")
        self.var_status.set(f"选型完成：{len(evals)} 个可行方案")

    def run_manual_check(self) -> None:
        if not self._collect():
            return
        for key, var in self.manual_vars.items():
            value = var.get()
            ref = getattr(self.lc, key)
            if isinstance(ref, float):
                setattr(self.lc, key, _parse_number(str(value)))
            else:
                setattr(self.lc, key, value)
        self.req = compute(self.lc)
        if not self.req.ok:
            messagebox.showwarning("输入有误", "\n".join(self.req.errors))
            return
        ev = check_manual(self.lc, self.req)
        self.manual_ev = ev
        self._fill_checks(self.tree_manual, ev.checks)
        ok = ev.feasible
        self.lbl_manual.configure(
            text=("校核通过 ✔" if ok else "校核不通过 ✘：" + "、".join(ev.failed_names)),
            foreground="#15803d" if ok else "#b91c1c")
        self._fill_warnings(ev.warnings + [f"匹配度评分：{ev.score}"])
        self.var_status.set("手填电机校核 " + ("通过" if ok else "不通过"))

    def fill_manual_from_top(self) -> None:
        if not self.evaluations:
            messagebox.showinfo("提示", "请先执行「自动选型」")
            return
        ev = self.evaluations[0]
        m = ev.motor
        values = {
            "manual_kind": m.kind, "manual_power": m.rated_power, "manual_rpm": m.rated_rpm,
            "manual_max_rpm": m.max_rpm, "manual_torque": m.rated_torque,
            "manual_peak_torque": m.torque_at(ev.n_motor) if m.kind != "直线电机" else m.peak_force,
            "manual_inertia": m.inertia,
        }
        for key, value in values.items():
            var = self.manual_vars.get(key)
            if var is None:
                continue
            var.set(value if isinstance(value, str) else fmt_input(value))
        self.var_status.set(f"已填入：{m.model}（减速比 i={_fmt(ev.ratio)}）")

    # ==================================================================
    # 结果渲染
    # ==================================================================
    def _fill_result(self) -> None:
        req = self.req
        self.tree_result.delete(*self.tree_result.get_children())
        if req is None:
            return
        if not req.ok:
            self.lbl_summary.configure(text="✘ 输入有误，无法计算", foreground="#b91c1c")
            for err in req.errors:
                self.tree_result.insert("", "end", tags=("bad",), values=("错误", "", err))
            self._fill_warnings([])
            return
        self.lbl_summary.configure(
            text=f"需求汇总：转速 {_fmt(req.n_motor)} rpm ｜ 峰值转矩 {_fmt(req.T_peak_motor)} N·m ｜ "
                 f"有效转矩 {_fmt(req.T_rms_motor())} N·m ｜ 折算惯量 {_fmt(req.J_reflected)} kg·m² ｜ "
                 f"建议功率 {_fmt(req.P_req)} W",
            foreground="#1e3a8a")
        self.tree_result.insert("", "end", tags=("group",), values=("— 输入要点 —", "", ""))
        lc = self.lc
        rows = [
            ("工况", lc.case_label, "受力模型"),
            ("传动方式", lc.transmission_label + f"，效率 η={_fmt(lc.efficiency)}", ""),
            ("每转移动量 L", f"{_fmt(req.travel_per_rev)} m", "负载轴每转的直线位移"),
            ("负载转速 / 电机转速", f"{_fmt(req.n_load)} / {_fmt(req.n_motor)} rpm",
             f"减速比 i={_fmt(req.ratio)}"),
            ("负载惯量(含传动件)", f"{_fmt(load_inertia(lc) if lc.is_rotary else req.J_load_side)} kg·m²", ""),
            ("折算到电机轴惯量", f"{_fmt(req.J_reflected)} kg·m²", "J/i²"),
            ("需求峰值转矩", f"{_fmt(req.T_peak_motor)} N·m", "稳态 + 加速（未含电机转子惯量）"),
            ("需求有效(RMS)转矩", f"{_fmt(req.T_rms_motor())} N·m", "按四段工时加权"),
            ("占空比", f"{_fmt(req.duty)} %", f"每小时启停 {_fmt(req.starts_per_hour)} 次"),
            ("峰值功率 / 建议功率", f"{_fmt(req.P_peak)} / {_fmt(req.P_req)} W",
             f"功率安全系数 {_fmt(lc.sf_power)}"),
        ]
        for name, value, formula in rows:
            self.tree_result.insert("", "end", values=(name, value, formula))
        self.tree_result.insert("", "end", tags=("group",), values=("— 详细计算过程 —", "", ""))
        for idx, (name, value, formula) in enumerate(req.steps):
            self.tree_result.insert("", "end", tags=(("even",) if idx % 2 else ()),
                                    values=(name, value, formula))
        self._fill_warnings(req.warnings)

    def _fill_warnings(self, warnings: Sequence[str]) -> None:
        self.txt_warn.configure(state="normal")
        self.txt_warn.delete("1.0", "end")
        if warnings:
            for w in warnings:
                self.txt_warn.insert("end", "· " + str(w) + "\n")
        else:
            self.txt_warn.insert("end", "（无提示）\n")
        self.txt_warn.configure(state="disabled")

    def _fill_checks(self, tree: ttk.Treeview, checks: Sequence[CheckItem]) -> None:
        tree.delete(*tree.get_children())
        for idx, c in enumerate(checks):
            if not c.mandatory:
                tag = "warn"
            else:
                tag = "ok" if c.ok else "bad"
            margin = "-" if c.required <= 0 else f"{c.margin:.2f}×"
            tree.insert("", "end", tags=(tag,), values=(
                c.name, c.text_required, c.text_capacity, margin, c.text_result, c.note))
        if not checks:
            tree.insert("", "end", values=("（无校核项）", "", "", "", "", ""))

    def _fill_manual_env(self) -> None:
        """需求变化时刷新校核页的标题。"""
        if self.req is None or not self.req.ok:
            self.lbl_check_head.configure(text="等待有效输入")
            return
        self.lbl_check_head.configure(
            text=f"需求：{_fmt(self.req.n_motor)} rpm / 峰值 {_fmt(self.req.T_peak_motor)} N·m "
                 f"/ 有效 {_fmt(self.req.T_rms_motor())} N·m　—　"
                 "下面的「手填电机校核」页可用手头电机参数复核")

    def _on_tab_changed(self, _event=None) -> None:
        if self.nb.index(self.nb.select()) == 2 and not self.evaluations:
            self.run_selection(silent=True)

    # ==================================================================
    def show_selected_detail(self) -> None:
        sel = self.tree_sel.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表里选一行")
            return
        idx = int(sel[0]) - 1
        if not (0 <= idx < len(self.evaluations)):
            return
        ev = self.evaluations[idx]
        self.nb.select(1)
        self.lbl_check_head.configure(
            text=f"{ev.motor.kind} {ev.train_label}　减速比 i={_fmt(ev.ratio)}　"
                 f"匹配度 {ev.score}　结论：{summarize(ev)}")
        self._fill_checks(self.tree_checks, ev.checks)
        self.lbl_summary.configure(
            text=f"当前查看方案：{ev.motor.kind} {ev.train_label}　"
                 f"需求转速 {_fmt(ev.n_motor)} rpm ｜ 峰值 {_fmt(ev.T_peak)} N·m ｜ "
                 f"有效 {_fmt(ev.T_rms)} N·m ｜ 惯量比 {_fmt(ev.inertia_ratio)}",
            foreground="#1e3a8a")
        self._fill_warnings(ev.warnings + [
            f"电机：{ev.motor.model}（{ev.motor.kind}，额定 {_fmt(ev.motor.rated_power)} W / "
            f"{_fmt(ev.motor.rated_rpm)} rpm / {_fmt(ev.motor.rated_torque)} N·m）",
            f"减速机：{ev.gearbox.model if ev.gearbox else '无（直驱或通用速比）'}",
            "备注：" + (ev.motor.notes or "无"),
        ])

    # ==================================================================
    # 文件操作
    # ==================================================================
    def _default_report_name(self, ext: str) -> str:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = "".join(ch for ch in self.lc.name if ch not in '\\/:*?"<>|').strip() or "方案"
        return os.path.join(report_dir(), f"{name}_{stamp}.{ext}")

    def export_report(self) -> None:
        if not self._collect():
            return
        self.req = compute(self.lc)
        if not self.req.ok:
            messagebox.showwarning("无法导出", "输入有误：\n" + "\n".join(self.req.errors))
            return
        if not self.evaluations:
            self.run_selection(silent=True)
        path = filedialog.asksaveasfilename(
            title="导出计算书", defaultextension=".html",
            initialfile=os.path.basename(self._default_report_name("html")),
            initialdir=report_dir(), filetypes=[("网页计算书", "*.html")])
        if not path:
            return
        html_text = build_html(self.lc, self.req, self.evaluations, self.manual_ev,
                               title=f"电机选型计算书 — {self.lc.name}")
        write_html(path, html_text)
        self.var_status.set("计算书已导出：" + path)
        if messagebox.askyesno("导出成功", f"已生成：\n{path}\n\n现在用浏览器打开吗？"):
            try:
                os.startfile(path)                             # noqa: S606
            except Exception as exc:                           # noqa: BLE001
                messagebox.showinfo("提示", f"请手动打开：{path}\n({exc})")

    def export_csv(self) -> None:
        if not self.evaluations:
            self.run_selection(silent=True)
        if not self.evaluations:
            messagebox.showinfo("提示", "没有可导出的选型结果")
            return
        path = filedialog.asksaveasfilename(
            title="导出选型清单", defaultextension=".csv",
            initialfile=os.path.basename(self._default_report_name("csv")),
            initialdir=report_dir(), filetypes=[("CSV 表格", "*.csv")])
        if not path:
            return
        write_evals_csv(path, self.evaluations)
        self.var_status.set("选型清单已导出：" + path)

    def save_scheme(self) -> None:
        if not self._collect():
            return
        path = filedialog.asksaveasfilename(
            title="保存方案", defaultextension=".json",
            initialfile=f"{self.lc.name}.json", initialdir=scheme_dir(),
            filetypes=[("方案文件", "*.json")])
        if not path:
            return
        import json
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.lc.to_dict(), fh, ensure_ascii=False, indent=2)
        self.var_status.set("方案已保存：" + path)

    def open_scheme(self) -> None:
        path = filedialog.askopenfilename(title="打开方案", initialdir=scheme_dir(),
                                          filetypes=[("方案文件", "*.json"), ("全部", "*.*")])
        if not path:
            return
        import json
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            lc = LoadCase.from_dict(data)
        except Exception as exc:                               # noqa: BLE001
            messagebox.showerror("打开失败", f"{type(exc).__name__}: {exc}")
            return
        self.lc = lc
        self.var_name.set(lc.name)
        self.form.load_case(lc)
        self.manual_vars_sync(lc)
        self.evaluations = []
        self.tree_sel.delete(*self.tree_sel.get_children())
        self.recalculate()
        self.var_status.set("方案已载入：" + path)

    def manual_vars_sync(self, lc: LoadCase) -> None:
        for key, var in self.manual_vars.items():
            value = getattr(lc, key)
            var.set(value if isinstance(value, str) else fmt_input(value))

    def reset_case(self) -> None:
        if not messagebox.askyesno("恢复默认", "确定把所有参数恢复为默认值吗？"):
            return
        lc = LoadCase()
        self.lc = lc
        self.var_name.set(lc.name)
        self.form.load_case(lc)
        self.manual_vars_sync(lc)
        self.evaluations = []
        self.manual_ev = None
        self.tree_sel.delete(*self.tree_sel.get_children())
        self.tree_manual.delete(*self.tree_manual.get_children())
        self.recalculate()

    # ==================================================================
    # 工具窗口
    # ==================================================================
    def open_inertia_tool(self) -> None:
        win = tk.Toplevel(self)
        win.title("惯量计算器")
        win.transient(self)
        win.resizable(False, False)
        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)

        shapes = INERTIA_SHAPES
        var_shape = tk.StringVar(value=shapes[1][0])
        var_mass = tk.StringVar(value="10")
        var_r1 = tk.StringVar(value="0.05")
        var_r2 = tk.StringVar(value="0.1")
        var_a = tk.StringVar(value="0.2")
        var_b = tk.StringVar(value="0.2")
        var_l = tk.StringVar(value="0.5")
        var_out = tk.StringVar(value="")

        ttk.Label(box, text="形状", font=FONT_SM).grid(row=0, column=0, sticky="e", pady=4)
        ttk.Combobox(box, textvariable=var_shape, state="readonly", width=34,
                     values=[s[1] for s in shapes]).grid(row=0, column=1, columnspan=3,
                                                         sticky="w", pady=4)
        rows = [("质量 m (kg)", var_mass), ("内半径 r₁ (m)", var_r1), ("外半径 r₂ / r (m)", var_r2),
                ("边长 a (m)", var_a), ("边长 b (m)", var_b), ("长度 l (m)", var_l)]
        for idx, (label, var) in enumerate(rows, start=1):
            ttk.Label(box, text=label, font=FONT_SM).grid(row=idx, column=0, sticky="e", pady=3)
            ttk.Entry(box, textvariable=var, width=14, font=FONT_SM).grid(
                row=idx, column=1, sticky="w", pady=3)

        def current_mode() -> str:
            text = var_shape.get()
            for value, lab in shapes:
                if lab == text:
                    return value
            return "manual"

        def calc() -> float:
            j = inertia_of_shape(current_mode(), _parse_number(var_mass.get()),
                                 _parse_number(var_r1.get()), _parse_number(var_r2.get()),
                                 _parse_number(var_a.get()), _parse_number(var_b.get()),
                                 _parse_number(var_l.get()))
            var_out.set(f"{j:.6g} kg·m²")
            return j

        def fill() -> None:
            j = calc()
            self.lc.load_inertia = j
            self.lc.inertia_mode = "manual"
            self.form.load_case(self.lc)
            self.recalculate()
            self.var_status.set(f"已把 {j:.6g} kg·m² 填入负载惯量")

        ttk.Button(box, text="计算", command=calc).grid(row=7, column=0, pady=(10, 2))
        ttk.Button(box, text="填入负载惯量", command=fill).grid(row=7, column=1, pady=(10, 2))
        ttk.Label(box, textvariable=var_out, font=FONT_BOLD, foreground="#1e3a8a").grid(
            row=8, column=0, columnspan=4, sticky="w", pady=6)
        ttk.Label(box, text="注：长方体按绕垂直中心轴、细长杆按绕端部计算；实心圆柱按绕自身中心轴。",
                  font=FONT_SM, foreground="#666", wraplength=430, justify="left").grid(
            row=9, column=0, columnspan=4, sticky="w")
        calc()

    def open_library(self) -> None:
        win = tk.Toplevel(self)
        win.title("型号库")
        win.geometry("1080x620")
        win.transient(self)
        top = ttk.Frame(win, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        motors = all_motors()
        boxes = all_gearboxes()
        info = ttk.Label(top, font=FONT_BOLD, foreground="#1e3a8a",
                         text=f"电机 {len(motors)} 台（含用户库）｜ 减速机 {len(boxes)} 台　"
                              "内置数据为行业典型参数，正式选型请导入厂家样本")
        info.pack(side="left")

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        mtab = ttk.Frame(nb, padding=6)
        nb.add(mtab, text="电机库")
        cols = ("类型", "型号", "额定功率W", "额定转速rpm", "额定转矩N·m", "峰值/最大转矩N·m",
                "转子惯量kg·m²", "电压", "来源")
        tree = ttk.Treeview(mtab, columns=cols, show="headings")
        widths = (80, 220, 90, 96, 96, 120, 120, 110, 80)
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w", stretch=True)
        vs = ttk.Scrollbar(mtab, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        for m in motors:
            tree.insert("", "end", values=(m.kind, m.model, _fmt(m.rated_power), _fmt(m.rated_rpm),
                                           _fmt(m.rated_torque),
                                           _fmt(m.torque_at(m.rated_rpm) if m.kind != "直线电机"
                                                else m.peak_force),
                                           _fmt(m.inertia), m.voltage, m.source))

        gtab = ttk.Frame(nb, padding=6)
        nb.add(gtab, text="减速机库")
        gcols = ("类型", "型号", "减速比", "额定输出N·m", "峰值输出N·m", "效率", "背隙arcmin",
                 "允许输入rpm", "来源")
        gtree = ttk.Treeview(gtab, columns=gcols, show="headings")
        gwidths = (110, 200, 66, 96, 96, 60, 90, 100, 80)
        for c, w in zip(gcols, gwidths):
            gtree.heading(c, text=c)
            gtree.column(c, width=w, anchor="w", stretch=True)
        gvs = ttk.Scrollbar(gtab, orient="vertical", command=gtree.yview)
        gtree.configure(yscrollcommand=gvs.set)
        gvs.pack(side="right", fill="y")
        gtree.pack(side="left", fill="both", expand=True)
        for g in boxes:
            gtree.insert("", "end", values=(g.kind, g.model, _fmt(g.ratio), g.torque_text(),
                                            g.torque_text(peak=True), _fmt(g.efficiency),
                                            _fmt(g.backlash_arcmin), _fmt(g.max_input_rpm), g.source))

        btns = ttk.Frame(win, padding=(10, 0, 10, 2))
        btns.pack(fill="x")
        btns2 = ttk.Frame(win, padding=(10, 0, 10, 4))
        btns2.pack(fill="x")
        ttk.Label(btns2, font=FONT_SM, foreground="#666",
                  text="用户库文件：" + user_data_dir() +
                       "\\motors_user.csv（电机）、gearboxes_user.csv（减速机）；"
                       "导入是「追加」，同类型同型号自动去重").pack(side="left")

        def do_import(motors: bool) -> None:
            path = filedialog.askopenfilename(
                title="导入电机 CSV" if motors else "导入减速机 CSV",
                initialdir=user_data_dir(),
                filetypes=[("CSV", "*.csv"), ("全部", "*.*")])
            if not path:
                return
            try:
                count, errors = (import_user_motors(path) if motors
                                 else import_user_gearboxes(path))
            except Exception as exc:                           # noqa: BLE001
                messagebox.showerror("导入失败", f"{type(exc).__name__}: {exc}")
                return
            what = "电机" if motors else "减速机"
            messagebox.showinfo("导入完成", f"新增 {count} 台{what}到用户库" +
                                ("\n" + "\n".join(errors) if errors else ""))
            win.destroy()
            self.open_library()

        def do_template(motors: bool) -> None:
            name = "电机库模板.csv" if motors else "减速机库模板.csv"
            path = filedialog.asksaveasfilename(title="导出模板", defaultextension=".csv",
                                                initialfile=name, initialdir=user_data_dir(),
                                                filetypes=[("CSV", "*.csv")])
            if path:
                (export_motor_template if motors else export_gearbox_template)(path)
                messagebox.showinfo("已导出", "模板已生成：\n" + path +
                                    "\n\n用 Excel 打开、按行填参数，再点「导入」即可。")

        def do_export() -> None:
            path = filedialog.asksaveasfilename(title="导出当前电机库", defaultextension=".csv",
                                                initialfile="电机库导出.csv",
                                                initialdir=user_data_dir(),
                                                filetypes=[("CSV", "*.csv")])
            if path:
                save_motors_csv(path, motors)
                gpath = os.path.splitext(path)[0] + "_减速机.csv"
                save_gearboxes_csv(gpath, boxes)
                messagebox.showinfo("已导出", f"电机库：{path}\n减速机库：{gpath}")

        def do_clear() -> None:
            if messagebox.askyesno("清空用户库",
                                   "确定删除导入的用户型号库吗？\n（内置库不受影响，重新导入即可恢复）"):
                clear_user_motors()
                win.destroy()
                self.open_library()

        def do_open_dir() -> None:
            try:
                os.startfile(user_data_dir())                   # noqa: S606
            except Exception as exc:                            # noqa: BLE001
                messagebox.showinfo("提示", f"请手动打开：{user_data_dir()}\n({exc})")

        ttk.Button(btns, text="导入电机 CSV（追加到用户库）",
                   command=lambda: do_import(True)).pack(side="left")
        ttk.Button(btns, text="导入减速机 CSV（追加到用户库）",
                   command=lambda: do_import(False)).pack(side="left", padx=6)
        ttk.Button(btns, text="导出电机模板",
                   command=lambda: do_template(True)).pack(side="left", padx=(14, 6))
        ttk.Button(btns, text="导出减速机模板",
                   command=lambda: do_template(False)).pack(side="left")
        ttk.Button(btns, text="导出当前库", command=do_export).pack(side="left", padx=(14, 6))
        ttk.Button(btns, text="打开用户库文件夹", command=do_open_dir).pack(side="left")
        ttk.Button(btns, text="清空用户库", command=do_clear).pack(side="left", padx=6)
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="right")


# ==========================================================================
def main() -> None:
    enable_dpi_awareness()
    app = MotorSelectorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
