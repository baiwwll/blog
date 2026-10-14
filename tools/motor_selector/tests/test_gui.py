# -*- coding: utf-8 -*-
"""界面冒烟测试：不进入消息循环，直接构造窗口并模拟操作。

运行： python tests\test_gui.py
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as app_mod                                          # noqa: E402
from core.entities import CASES, INERTIA_SHAPES, TRANSMISSIONS   # noqa: E402
from core.mechanics import compute                               # noqa: E402
from core.report import build_html                               # noqa: E402

FAILS = []


def step(name: str, fn) -> None:
    try:
        fn()
        print(f"[OK  ] {name}")
    except Exception as exc:                                    # noqa: BLE001
        FAILS.append(name)
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()


def main() -> int:
    app_mod.enable_dpi_awareness()
    app = app_mod.MotorSelectorApp()
    app.withdraw()

    step("窗口构造", lambda: app.update())

    # 遍历全部工况 + 全部传动 + 全部惯量模式，检查界面不报错
    def sweep_cases() -> None:
        for value, label in CASES:
            app.form.vars["case"].set(label)
            app.form._changed("case")
            app.update()
            app.recalculate()
            app.run_selection(silent=True)
            assert app.req is not None
            print(f"      工况 {label:24s} 需求n={app.req.n_motor:9.1f}rpm "
                  f"T峰={app.req.T_peak_motor:8.3f}N·m  方案数={len(app.evaluations)}")
    step("全部工况遍历（含自动选型）", sweep_cases)

    def sweep_transmissions() -> None:
        app.form.vars["case"].set(dict(CASES)["horizontal"])
        app.form._changed("case")
        for value, label in TRANSMISSIONS:
            app.form.vars["transmission"].set(label)
            app.form._changed("transmission")
            app.update()
            app.recalculate()
            assert app.req is not None and app.req.ok, app.req.errors
    step("全部传动形式遍历", sweep_transmissions)

    def sweep_inertia() -> None:
        app.form.vars["case"].set(dict(CASES)["rotary_table"])
        app.form._changed("case")
        for value, label in INERTIA_SHAPES:
            app.form.vars["inertia_mode"].set(label)
            app.form._changed("inertia_mode")
            app.update()
            app.recalculate()
            assert app.req is not None and app.req.ok, app.req.errors
    step("全部惯量形状遍历", sweep_inertia)

    def manual_check() -> None:
        # 还原成图片里那张 Excel 表的输入
        app.form.vars["case"].set(dict(CASES)["horizontal"])
        app.form._changed("case")
        app.form.vars["transmission"].set(dict(TRANSMISSIONS)["rack"])
        app.form._changed("transmission")
        app.form.vars["per_rev_travel"].set("0.05")
        app.form.vars["pulley_dia"].set("0")
        app.form.vars["mass"].set("50")
        app.form.vars["mu"].set("0.1")
        app.form.vars["speed"].set("0.5")
        app.form.vars["accel_time"].set("0.1")
        app.form.vars["ratio"].set("1")
        app.form.vars["efficiency"].set("0.8")
        app.form.vars["inertia_mode"].set(dict(INERTIA_SHAPES)["manual"])
        app.recalculate()
        app.manual_vars["manual_kind"].set("异步电机")
        app.manual_vars["manual_power"].set("750")
        app.manual_vars["manual_rpm"].set("1450")
        app.manual_vars["manual_max_rpm"].set("0")
        app.manual_vars["manual_torque"].set("3")
        app.manual_vars["manual_peak_torque"].set("0")
        app.manual_vars["manual_inertia"].set("0.0005")
        app.run_manual_check()
        assert app.manual_ev is not None
        print(f"      手填校核结论：{'通过' if app.manual_ev.feasible else '不通过'} "
              f"匹配度={app.manual_ev.score} 校核项={len(app.manual_ev.checks)} "
              f"惯量比={app.manual_ev.inertia_ratio:.2f}")
        assert app.manual_ev.feasible, app.manual_ev.failed_names
    step("手填电机校核（复刻 Excel 表格）", manual_check)

    def fill_from_top() -> None:
        app.run_selection(silent=True)
        app.fill_manual_from_top()
        assert app.manual_vars["manual_power"].get()
    step("把推荐第一名填入手填区", fill_from_top)

    def detail_view() -> None:
        app.run_selection(silent=True)
        first = app.tree_sel.get_children()[0]
        app.tree_sel.selection_set(first)
        app.show_selected_detail()
        assert len(app.tree_checks.get_children()) > 0
    step("查看选中方案校核明细", detail_view)

    def tools() -> None:
        app.open_inertia_tool()
        app.update()
        app.open_library()
        app.update()
        for child in app.winfo_children():
            if child.winfo_class() == "Toplevel":
                child.destroy()
    step("工具窗口（惯量计算器 / 型号库）", tools)

    def report() -> None:
        app.recalculate()
        app.run_selection(silent=True)
        html = build_html(app.lc, app.req, app.evaluations, app.manual_ev, title="界面冒烟测试")
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_smoke_report.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        assert os.path.getsize(out) > 4000, "报告内容过少"
        print(f"      报告已写出 {os.path.getsize(out)} 字节 -> {out}")
    step("生成计算书 HTML", report)

    def scheme_roundtrip() -> None:
        import json
        from core.entities import LoadCase
        data = app.form.sync_to_case().to_dict()
        text = json.dumps(data, ensure_ascii=False)
        back = LoadCase.from_dict(json.loads(text))
        assert back.to_dict() == data, "方案序列化不一致"
    step("方案 JSON 往返", scheme_roundtrip)

    def number_parsing() -> None:
        """回归：输入框回填的数值必须能被正确读回（曾经被千分位逗号坑过）。"""
        cases = [("1450", 1450.0), ("1,450", 1450.0), ("1,450.5", 1450.5),
                 ("1,234,567", 1234567.0), ("7850", 7850.0),
                 ("0.0005", 0.0005), ("0.05", 0.05), ("", 0.0),
                 ("1450.0", 1450.0), ("2.39", 2.39)]
        bad = []
        for text, want in cases:
            got = app_mod._parse_number(text)
            if abs(got - want) > 1e-9:
                bad.append(f"{text!r} -> {got} 应为 {want}")
        assert not bad, bad
        # 「0,5」这种小数点写法不应该被当成千分位乱解析
        assert app_mod._parse_number("0,5") == 0.0
        print("      千分位/小数解析全部正确")

    step("数字解析（含千分位逗号）", number_parsing)

    def entry_roundtrip() -> None:
        """回归：界面默认值回填后再读出来，必须和原值一致。"""
        lc = app_mod.LoadCase()
        app.form.load_case(lc)
        app.manual_vars_sync(lc)
        app.recalculate()
        got = app.form.sync_to_case()
        diffs = []
        for key in ("manual_rpm", "screw_density", "mass", "speed", "accel_time",
                    "per_rev_travel", "ratio", "efficiency", "mu", "stroke"):
            a, b = getattr(lc, key), getattr(got, key)
            if abs(float(a) - float(b)) > 1e-9:
                diffs.append(f"{key}: {a} -> {b}")
        assert not diffs, diffs
        text = app.manual_vars["manual_rpm"].get()
        assert "," not in text, f"输入框不该出现千分位：{text!r}"
        assert abs(app_mod._parse_number(text) - 1450.0) < 1e-9, text
        print(f"      手动校核转速回填 = {text!r}，原样读回 OK；"
              f"丝杆长度 = {app.form.vars['screw_len'].get()!r}，"
              f"每转移动量 = {app.form.vars['per_rev_travel'].get()!r}")

    step("界面输入框数值往返", entry_roundtrip)

    def gearbox_display() -> None:
        """回归：通用减速机的转矩列不能出现 1e+09 这种科学计数法。"""
        from core.database import all_gearboxes
        bad = []
        for g in all_gearboxes():
            for text in (g.torque_text(), g.torque_text(peak=True)):
                if "e+" in text.lower() or "e-" in text.lower():
                    bad.append(f"{g.model}: {text}")
        assert not bad, bad[:5]
        generic = [g for g in all_gearboxes() if g.torque_unlimited]
        assert generic and generic[0].torque_text() == "不限"
        print(f"      通用减速机 {len(generic)} 条，转矩显示：{generic[0].torque_text()}")

    step("减速机库转矩显示（无科学计数法）", gearbox_display)

    app.destroy()
    print("\n" + "=" * 60)
    if FAILS:
        print(f"界面测试未通过 {len(FAILS)} 项：{FAILS}")
        return 1
    print("界面冒烟测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
