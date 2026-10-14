# -*- coding: utf-8 -*-
"""引擎自测：用手算 / 原 Excel 表格的数据回归校核计算结果。

直接运行： python tests\test_engine.py
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import LoadCase                                        # noqa: E402
from core.database import all_gearboxes, all_motors              # noqa: E402
from core.entities import _fmt                                   # noqa: E402
from core.mechanics import compute, screw_inertia                # noqa: E402
from core.selector import auto_select, check_manual              # noqa: E402

FAILS = []


def near(name: str, got: float, want: float, tol: float = 0.02) -> None:
    ok = abs(got - want) <= abs(want) * tol + 1e-9
    flag = "OK  " if ok else "FAIL"
    if not ok:
        FAILS.append(f"{name}: got={got!r} want={want!r}")
    print(f"[{flag}] {name}: got={got:.6g}  want≈{want:.6g}")


def check(name: str, cond: bool, extra: str = "") -> None:
    flag = "OK  " if cond else "FAIL"
    if not cond:
        FAILS.append(f"{name} {extra}")
    print(f"[{flag}] {name} {extra}")


# --------------------------------------------------------------------------
# 1. 复刻图片里那张 Excel 表（水平滑台，负载 50kg）
# --------------------------------------------------------------------------
def test_excel_case() -> None:
    print("\n=== 1. 复刻 Excel 表格（水平直线，50kg） ===")
    lc = LoadCase(
        name="Excel 复刻",
        case="horizontal",
        mass=50.0,
        mu=0.10,
        speed=0.5,
        accel_time=0.1,
        transmission="rack",       # 齿轮齿条 / 每转移动量 0.05 m
        per_rev_travel=0.05,
        pulley_dia=0.0,
        ratio=1.0,
        efficiency=0.80,
        ext_force=0.0,
        const_time=0.5,
        dwell_time=0.5,
    )
    req = compute(lc)
    check("需求计算无错误", req.ok, str(req.errors))

    near("直线运动折算惯量 J_直 (Excel 0.0031695)", req.J_linear, 0.0031695)
    near("摩擦力 F_f (Excel 50 N)", req.F_fric, 49.03, 0.01)
    near("加速力 F_a (Excel 250 N)", req.F_accel, 250.0, 0.001)
    near("负载侧稳态转矩 (Excel 0.5 N·m)", req.T_load_side, 0.4974, 0.02)
    near("负载侧转速 (Excel 600 rpm)", req.n_load, 600.0, 0.001)
    near("电机侧稳态转矩", req.T_load_motor, 0.4974, 0.02)
    near("电机侧角加速度 α=2πa/L", req.alpha_motor, 2 * math.pi * 5.0 / 0.05, 0.001)
    near("电机侧加速转矩 T_a = J·α", req.T_accel_motor, 0.0031695 * 628.318, 0.02)
    near("电机侧峰值转矩", req.T_peak_motor,
         req.T_load_motor + req.T_accel_motor, 1e-6)
    check("减速比 1 时电机转速 = 负载转速", abs(req.n_motor - req.n_load) < 1e-9,
          f"{req.n_motor:.3f} rpm")

    # 手填电机：1450rpm / 3N·m / 0.0005 kg·m²（Excel 输入的电机）
    ev = check_manual(lc, req)
    check("手填电机（1450rpm,3N·m）转矩+转速校核通过", ev.feasible,
          "未通过项=" + ",".join(ev.failed_names))
    near("惯量比 ≈ 6.34", ev.inertia_ratio, 0.0031695 / 0.0005, 0.02)


# --------------------------------------------------------------------------
# 2. 垂直提升
# --------------------------------------------------------------------------
def test_lift() -> None:
    print("\n=== 2. 垂直提升（丝杆）===")
    lc = LoadCase(
        case="vertical_lift", mass=80.0, counterweight=0.0, mu=0.02,
        speed=0.2, accel_time=0.2, transmission="screw_ball",
        screw_lead=0.01, screw_dia=0.02, screw_len=0.6, screw_efficiency=0.9,
        efficiency=0.9, ratio=1.0, const_time=0.5, dwell_time=0.5,
    )
    req = compute(lc)
    check("计算无错误", req.ok, str(req.errors))
    near("重力 = m·g", req.F_grav, 80 * 9.80665, 0.001)
    near("负载转速 = v/L·60", req.n_load, 0.2 / 0.01 * 60, 0.001)
    near("丝杆惯量自动估算", req.J_trans_side,
         screw_inertia(0.02, 0.6), 1e-6)
    j_need = 0.6 ** 2 * (0.5 * 7850 * math.pi * 0.02 ** 2)
    check("丝杆惯量量级合理 (<1e-4)", req.J_trans_side < 1e-4,
          f"{req.J_trans_side:.3e} kg·m²")
    check("存在垂直工况制动提示",
          any("制动" in w for w in req.warnings), str(req.warnings[:1]))

    results = auto_select(lc, req, top_n=5)
    check("自动选型有结果", len(results) > 0, f"{len(results)} 条")
    if results:
        print("  推荐 TOP3：")
        for ev in results[:3]:
            print(f"    {ev.motor.kind:6s} {ev.train_label:38s} "
                  f"i={ev.ratio:<5g} n={ev.n_motor:8.1f}rpm T峰={ev.T_peak:7.3f}N·m "
                  f"惯量比={ev.inertia_ratio:6.2f} 匹配度={ev.score}")


# --------------------------------------------------------------------------
# 3. 分度盘
# --------------------------------------------------------------------------
def test_rotary() -> None:
    print("\n=== 3. 分度盘（伺服 + 减速机）===")
    lc = LoadCase(
        case="rotary_table", load_rpm=60.0, accel_time=0.2,
        inertia_mode="solid_cylinder", in_mass=30.0, in_r2=0.25,
        friction_torque=1.0, ratio=1.0, efficiency=0.95,
        transmission="gearbox", allow_gearbox=True,
        positioning_mm=0.05, dwell_time=0.8, const_time=0.5,
    )
    req = compute(lc)
    check("计算无错误", req.ok, str(req.errors))
    near("圆柱惯量 m·r²/2", req.J_load_side, 0.5 * 30 * 0.25 ** 2, 1e-6)
    near("负载角加速度", req.alpha_load, 2 * math.pi * 1.0 / 0.2, 0.001)
    results = auto_select(lc, req, top_n=5)
    check("自动选型有结果", len(results) > 0, f"{len(results)} 条")
    if results:
        top = results[0]
        check("推荐方案可行", top.feasible)
        check("推荐方案惯量比合理", top.inertia_ratio <= 30,
              f"{top.inertia_ratio:.2f}")
        print(f"  最优：{top.train_label}  i={top.ratio:g}  匹配度={top.score}")


# --------------------------------------------------------------------------
# 4. 卷绕
# --------------------------------------------------------------------------
def test_winding() -> None:
    print("\n=== 4. 卷绕（变卷径）===")
    lc = LoadCase(
        case="winding", speed=1.0, accel_time=0.5, tension=40.0,
        drum_dia0=0.10, drum_dia1=0.35, drum_mass=6.0, ratio=1.0,
        efficiency=0.95, transmission="drum", per_rev_travel=0.0,
    )
    req = compute(lc)
    check("计算无错误", req.ok, str(req.errors))
    near("大卷径转速", req.extra_points[0][1], 1.0 / (math.pi * 0.35) * 60, 0.001)
    near("小卷径转速", req.extra_points[1][1], 1.0 / (math.pi * 0.10) * 60, 0.001)
    check("存在张力控制提示", any("张力" in w for w in req.warnings))


# --------------------------------------------------------------------------
# 5. 参数校验与全工况遍历
# --------------------------------------------------------------------------
def test_validation_and_sweep() -> None:
    print("\n=== 5. 参数校验 & 全工况遍历 ===")
    bad = compute(LoadCase(accel_time=0.0))
    check("加速时间为 0 时报错", not bad.ok, str(bad.errors[:1]))

    motors = all_motors()
    boxes = all_gearboxes()
    print(f"  内置电机 {len(motors)} 台，减速机 {len(boxes)} 台")
    check("内置电机数量 >= 60", len(motors) >= 60, str(len(motors)))
    check("内置减速机数量 >= 50", len(boxes) >= 50, str(len(boxes)))

    import time
    cases = ["horizontal", "incline", "vertical_lift", "vertical_press",
             "conveyor", "rotary_shaft", "rotary_table", "winding"]
    t0 = time.time()
    for case in cases:
        lc = LoadCase(case=case, allow_gearbox=True, motor_kind_pref="任意")
        req = compute(lc)
        if not req.ok:
            FAILS.append(f"工况 {case} 默认参数计算失败: {req.errors}")
            print(f"[FAIL] {case}: {req.errors}")
            continue
        res = auto_select(lc, req, motors, boxes, top_n=3)
        top = res[0].train_label if res else "无可行方案"
        print(f"[OK  ] {case:15s} 需求 n={req.n_motor:8.1f}rpm "
              f"T峰={req.T_peak_motor:8.3f}N·m  J={req.J_reflected:.3e}kg·m²  -> {top}")
    print(f"  8 个工况全部选型耗时 {time.time() - t0:.2f} s")


# --------------------------------------------------------------------------
# 6. 数值格式化 / 输入回填（回归：科学计数法与千分位逗号问题）
# --------------------------------------------------------------------------
def test_formatting() -> None:
    print("\n=== 6. 数值格式化 / 输入回填 ===")
    import dataclasses
    from core.database import builtin_gearboxes
    from core.entities import CheckItem, fmt_input
    from core.selector import evaluate

    # 6.1 显示值不再出现科学计数法
    for value in (1.0e9, 2.0e9, 4.0e-6, 8.7e-5, 5.4e-6, 1.5e6):
        text = _fmt(value)
        check(f"_fmt({value:g}) 不用科学计数法", "e" not in text.lower(), f"-> {text}")
    check("_fmt(1e9) = 1,000,000,000", _fmt(1.0e9) == "1,000,000,000", _fmt(1.0e9))
    check("_fmt(4e-6) = 0.000004", _fmt(4.0e-6) == "0.000004", _fmt(4.0e-6))

    # 6.2 通用减速机显示「不限」
    generic = [g for g in builtin_gearboxes() if g.torque_unlimited]
    check("内置库存在「通用减速机」占位条目", len(generic) > 0, f"{len(generic)} 条")
    check("通用减速机额定转矩显示「不限」",
          all(g.torque_text() == "不限" for g in generic),
          generic[0].torque_text() if generic else "")
    check("通用减速机峰值转矩显示「不限」",
          all(g.torque_text(peak=True) == "不限" for g in generic))

    # 6.3 校核项可以自定义能力显示文本
    ci = CheckItem("减速机额定输出转矩", 10.0, 0.0, "N·m",
                   capacity_text="不限（需按样本复核）")
    check("CheckItem 支持自定义能力文本",
          ci.text_capacity == "不限（需按样本复核）", ci.text_capacity)

    # 6.4 真的跑一次「电机 + 通用减速机」校核，确认界面/计算书里不出现 e+09
    lc = LoadCase(case="horizontal", mass=50.0, speed=0.5, accel_time=0.1,
                  transmission="rack", per_rev_travel=0.05, ratio=10.0,
                  efficiency=0.8, allow_gearbox=True)
    req = compute(lc)
    motor = [m for m in all_motors() if m.kind == "伺服电机"][0]
    ev = evaluate(lc, req, motor, generic[0], 10.0)
    texts = [c.text_capacity for c in ev.checks] + [c.text_required for c in ev.checks]
    check("校核文本里没有科学计数法",
          not any(("e+" in t) or ("e-" in t) for t in texts),
          str([t for t in texts if "e+" in t or "e-" in t][:3]))
    check("通用减速机的转矩校核标记为「提示」不影响可行性",
          all(c.mandatory is False for c in ev.checks
              if c.name.startswith("减速机") and "转矩" in c.name))

    # 6.5 fmt_input 必须能被 float() 原样读回，且不带千分位（输入框靠它回填）
    values = []
    for f in dataclasses.fields(LoadCase):
        ref = getattr(LoadCase(), f.name)
        if isinstance(ref, float):
            values.append(ref)
    for m in all_motors():
        values += [m.rated_power, m.rated_rpm, m.max_rpm, m.rated_torque, m.max_torque,
                   m.peak_torque, m.inertia, m.holding_torque, m.step_angle,
                   m.cont_force, m.peak_force, m.mover_mass, m.max_speed, m.weight]
    for g in all_gearboxes():
        values += [g.ratio, g.rated_torque, g.peak_torque, g.efficiency,
                   g.backlash_arcmin, g.max_input_rpm, g.inertia, g.weight]
    problems = []
    for v in values:
        if v == 0:
            continue
        s = fmt_input(v)
        if "," in s:
            problems.append(f"{v!r} -> {s}（含千分位）")
            continue
        try:
            back = float(s)
        except ValueError:
            problems.append(f"{v!r} -> {s}（无法解析）")
            continue
        if abs(back - v) > 1e-6 + abs(v) * 1e-9:
            problems.append(f"{v!r} -> {s} -> {back!r}")
    check(f"fmt_input 全部可原样读回（共 {len(values)} 个值）", not problems,
          str(problems[:3]))


if __name__ == "__main__":
    test_excel_case()
    test_lift()
    test_rotary()
    test_winding()
    test_validation_and_sweep()
    test_formatting()
    print("\n" + "=" * 64)
    if FAILS:
        print(f"共 {len(FAILS)} 项未通过：")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("全部测试通过 ✔")
