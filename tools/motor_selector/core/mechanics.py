# -*- coding: utf-8 -*-
"""力学计算引擎：把工况参数换算成「电机轴上的需求」。

计算流程：
    1. 运动学   : 由速度/加速时间 -> 加速度 -> 负载侧角加速度 -> 电机侧角加速度
    2. 静力学   : 摩擦 + 重力分量 + 外力 -> 负载侧稳态阻力(矩)
    3. 动力学   : 惯量折算 + 角加速度 -> 加速转矩
    4. 折算     : 按减速比 i 与效率 η 折算到电机轴
    5. 时序     : 加速/匀速/减速/停留 -> 占空比、每小时启停次数、RMS 有效转矩
"""
from __future__ import annotations

import math
from typing import List, Tuple

from .entities import (
    G,
    LINEAR_CASES,
    ROTARY_CASES,
    LoadCase,
    Requirement,
    _fmt,
)

TWO_PI = 2.0 * math.pi


# --------------------------------------------------------------------------
# 惯量
# --------------------------------------------------------------------------
def inertia_of_shape(mode: str, mass: float, r1: float = 0.0, r2: float = 0.0,
                     a: float = 0.0, b: float = 0.0, length: float = 0.0) -> float:
    """按几何形状计算绕指定轴的转动惯量 (kg·m²)。"""
    m = max(float(mass), 0.0)
    if mode == "solid_cylinder":
        return 0.5 * m * r2 ** 2
    if mode == "ring":
        return 0.5 * m * (r1 ** 2 + r2 ** 2)
    if mode == "box":
        return m * (a ** 2 + b ** 2) / 12.0
    if mode == "rod_end":
        return m * length ** 2 / 3.0
    if mode == "sphere":
        return 0.4 * m * r2 ** 2
    return 0.0


def screw_inertia(dia: float, length: float, density: float = 7850.0) -> float:
    """实心钢轴（丝杆）绕自身轴的转动惯量 J = π·ρ·l·d⁴/32。"""
    d = max(float(dia), 0.0)
    l = max(float(length), 0.0)
    return math.pi * max(density, 0.0) * l * d ** 4 / 32.0


def load_inertia(lc: LoadCase) -> float:
    """旋转负载惯量（按形状自动计算或直接取输入值）。"""
    if lc.inertia_mode == "manual":
        return max(lc.load_inertia, 0.0)
    return inertia_of_shape(
        lc.inertia_mode, lc.in_mass, lc.in_r1, lc.in_r2, lc.in_a, lc.in_b, lc.in_l
    )


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------
def compute(lc: LoadCase) -> Requirement:
    """计算全部需求参数。任何异常都会被捕获并写进 errors，不会抛出。"""
    r = Requirement(case=lc.case, transmission=lc.transmission, is_linear=lc.is_linear)
    try:
        _validate(lc, r)
        if not r.ok:
            return r
        if lc.case in LINEAR_CASES:
            _linear(lc, r)
        elif lc.case in ROTARY_CASES:
            _rotary(lc, r)
        elif lc.case == "winding":
            _winding(lc, r)
        else:
            r.ok = False
            r.errors.append(f"未知工况：{lc.case}")
            return r
        _timing(lc, r)
        _sanity_warnings(lc, r)
    except Exception as exc:                                  # noqa: BLE001
        r.ok = False
        r.errors.append(f"计算异常：{type(exc).__name__}: {exc}")
    return r


# --------------------------------------------------------------------------
# 输入校验
# --------------------------------------------------------------------------
def _validate(lc: LoadCase, r: Requirement) -> None:
    if lc.mass < 0:
        r.errors.append("负载质量不能为负")
    if lc.accel_time <= 0:
        r.errors.append("加速时间必须大于 0")
    if lc.decel_time <= 0:
        r.errors.append("减速时间必须大于 0")
    if lc.ratio <= 0:
        r.errors.append("减速比必须大于 0（不加装减速机时填 1）")
    if not (0 < lc.efficiency <= 1):
        r.errors.append("传动效率必须落在 0 ~ 1 之间")
    if lc.case in LINEAR_CASES:
        if lc.speed <= 0:
            r.errors.append("直线运动速度必须大于 0")
        L = lc.travel_per_rev()
        if L <= 0:
            r.errors.append("每转移动量（或带轮节圆直径 / 丝杆导程）必须大于 0")
        else:
            r.travel_per_rev = L
        if lc.transmission in ("screw_ball", "screw_trap"):
            if lc.screw_lead <= 0 and lc.per_rev_travel <= 0:
                r.errors.append("丝杆传动必须填写导程")
            if not (0 < lc.screw_efficiency <= 1):
                r.errors.append("丝杆效率必须落在 0 ~ 1 之间")
    if lc.case in ROTARY_CASES:
        if lc.load_rpm <= 0:
            r.errors.append("负载转速必须大于 0")
    if lc.case == "winding":
        if lc.speed <= 0:
            r.errors.append("线速度必须大于 0")
        if lc.drum_dia0 <= 0 or lc.drum_dia1 <= 0:
            r.errors.append("卷径必须大于 0")
        if lc.drum_dia1 < lc.drum_dia0:
            r.errors.append("最大卷径不能小于最小卷径")
    r.ok = not r.errors


# --------------------------------------------------------------------------
# 直线工况
# --------------------------------------------------------------------------
def _linear(lc: LoadCase, r: Requirement) -> None:
    L = lc.travel_per_rev()
    r.travel_per_rev = L
    g = G
    theta = math.radians(max(lc.incline_deg, 0.0)) if lc.case in ("incline", "conveyor") else 0.0

    m = lc.mass + (lc.belt_mass if lc.case == "conveyor" else 0.0)
    r.m_moving = m
    v = lc.speed
    a = v / lc.accel_time

    # ---- 力的组成（沿运动方向，正 = 阻碍运动） ----
    if lc.case == "horizontal":
        f_grav = 0.0
    elif lc.case in ("incline", "conveyor"):
        f_grav = m * g * math.sin(theta)
    elif lc.case == "vertical_lift":
        f_grav = m * g
    else:                                   # vertical_press
        f_grav = -m * g
    f_cw = lc.counterweight * g * math.cos(theta) if lc.case in ("incline", "conveyor") \
        else lc.counterweight * g
    f_grav_net = f_grav - f_cw
    f_fric = lc.mu * m * g * math.cos(theta)
    f_ext = lc.ext_force
    f_resist = f_fric + f_grav_net + f_ext
    f_accel = m * a
    f_peak = f_resist + f_accel

    r.v, r.a = v, a
    r.F_fric, r.F_grav, r.F_ext = f_fric, f_grav_net, f_ext
    r.F_resist, r.F_accel, r.F_peak = f_resist, f_accel, f_peak

    # ---- 负载侧转矩 ----
    t_load_side = f_resist * L / (TWO_PI * lc.efficiency)
    r.T_grav_side = f_grav_net * L / (TWO_PI * lc.efficiency)
    r.T_load_side = t_load_side

    # ---- 惯量 ----
    j_lin = m * (L / TWO_PI) ** 2
    j_trans = _transmission_inertia(lc, r)
    j_load_side = j_lin + j_trans
    r.J_linear, r.J_trans_side, r.J_load_side = j_lin, j_trans, j_load_side

    alpha_load = TWO_PI * a / L
    r.alpha_load = alpha_load
    r.T_peak_side = abs(t_load_side) + j_load_side * alpha_load

    # ---- 折算到电机轴 ----
    _reflect(lc, r, n_load=v / L * 60.0, alpha_load=alpha_load,
             t_load_side=t_load_side, j_load_side=j_load_side)

    r.add("每转移动量 L", f"{_fmt(L)} m",
          "传动方式决定的负载轴每转直线位移（丝杆=导程，带轮=π·节圆直径）")
    r.add("运动质量 m", f"{_fmt(m)} kg", "负载质量" + (" + 皮带/承载件质量" if lc.case == "conveyor" else ""))
    r.add("加速度 a", f"{_fmt(a)} m/s²", f"a = v / t_加 = {_fmt(v)} / {_fmt(lc.accel_time)}")
    r.add("摩擦力 F_f", f"{_fmt(f_fric)} N", f"F_f = μ·m·g·cosθ = {_fmt(lc.mu)}×{_fmt(m)}×9.8066×{_fmt(math.cos(theta))}")
    if lc.case != "horizontal":
        r.add("重力分量 F_g", f"{_fmt(f_grav_net)} N",
              f"F_g = m·g·sinθ - m_配重·g（θ={_fmt(lc.incline_deg)}°）")
    if f_ext:
        r.add("外力 F_e", f"{_fmt(f_ext)} N", "外部恒定阻力（切削力/张力/弹簧力等）")
    r.add("稳态总阻力 F", f"{_fmt(f_resist)} N", "F = F_f + F_g + F_e")
    r.add("加速力 F_a", f"{_fmt(f_accel)} N", "F_a = m·a")
    r.add("负载侧稳态转矩 T_L", f"{_fmt(t_load_side)} N·m", "T_L = F·L / (2π·η)")
    r.add("直线运动折算惯量 J_直", f"{_fmt(j_lin)} kg·m²", "J_直 = m·(L/2π)²")
    if j_trans:
        r.add("传动件惯量 J_传", f"{_fmt(j_trans)} kg·m²", "丝杆/带轮/齿轮自身惯量（负载侧）")


def _transmission_inertia(lc: LoadCase, r: Requirement) -> float:
    """传动件自身惯量（负载侧）：用户优先，丝杆可自动估算。"""
    if lc.trans_inertia > 0:
        return lc.trans_inertia
    if lc.transmission in ("screw_ball", "screw_trap") and lc.screw_dia > 0:
        j = screw_inertia(lc.screw_dia, lc.screw_len, lc.screw_density)
        r.warnings.append(
            "丝杆自身惯量已按实心钢轴自动估算（可在「传动件惯量」中填实测值覆盖）"
        )
        return j
    return 0.0


# --------------------------------------------------------------------------
# 旋转工况（水平轴 / 分度盘）
# --------------------------------------------------------------------------
def _rotary(lc: LoadCase, r: Requirement) -> None:
    n_load = lc.load_rpm
    alpha_load = TWO_PI * (n_load / 60.0) / lc.accel_time
    j_load = load_inertia(lc)
    j_trans = _transmission_inertia(lc, r)
    j_load_side = j_load + j_trans

    t_load_side = lc.friction_torque + lc.ext_torque + lc.unbalanced_torque

    r.v = 0.0
    r.a = 0.0
    r.J_load_side = j_load_side
    r.J_trans_side = j_trans
    r.T_load_side = t_load_side
    r.T_grav_side = lc.unbalanced_torque
    r.alpha_load = alpha_load
    r.T_peak_side = abs(t_load_side) + j_load_side * alpha_load

    _reflect(lc, r, n_load=n_load, alpha_load=alpha_load,
             t_load_side=t_load_side, j_load_side=j_load_side)

    r.add("负载转速 n", f"{_fmt(n_load)} rpm", "旋转工况输入")
    r.add("负载角加速度 α", f"{_fmt(alpha_load)} rad/s²", "α = 2π·(n/60) / t_加")
    r.add("负载惯量 J", f"{_fmt(j_load)} kg·m²",
          "按 " + ("直接输入" if lc.inertia_mode == "manual" else lc.inertia_mode) + " 得到")
    r.add("负载侧摩擦/外力矩 T_L", f"{_fmt(t_load_side)} N·m",
          "T_L = 轴承摩擦 + 外力矩 + 不平衡重力矩")
    if j_trans:
        r.add("传动件惯量 J_传", f"{_fmt(j_trans)} kg·m²", "负载侧传动件惯量")


# --------------------------------------------------------------------------
# 卷绕 / 放卷
# --------------------------------------------------------------------------
def _winding(lc: LoadCase, r: Requirement) -> None:
    d0, d1 = lc.drum_dia0, lc.drum_dia1
    v = lc.speed
    eta = lc.efficiency
    i = lc.ratio

    n_load_d1 = v / (math.pi * d1) * 60.0        # 大卷径 -> 低转速
    n_load_d0 = v / (math.pi * d0) * 60.0        # 小卷径 -> 高转速
    t_side_d1 = lc.tension * d1 / 2.0            # 大卷径 -> 大转矩
    t_side_d0 = lc.tension * d0 / 2.0

    j_drum = lc.drum_inertia if lc.drum_inertia > 0 else 0.5 * lc.drum_mass * (d1 / 2.0) ** 2
    j_load_side = j_drum + lc.trans_inertia
    j_ref = j_load_side / i ** 2
    j_coupling = lc.coupling_inertia

    # 两个工作点各自的角加速度与电机侧转矩
    alpha_load_d1 = TWO_PI * (n_load_d1 / 60.0) / lc.accel_time
    alpha_load_d0 = TWO_PI * (n_load_d0 / 60.0) / lc.accel_time
    t_motor_d1 = t_side_d1 / (i * eta) + (j_ref + j_coupling) * alpha_load_d1 * i
    t_motor_d0 = t_side_d0 / (i * eta) + (j_ref + j_coupling) * alpha_load_d0 * i
    n_motor_d1, n_motor_d0 = n_load_d1 * i, n_load_d0 * i

    r.extra_points = [
        (f"大卷径 D1 = {_fmt(d1)} m（转矩工况）", n_motor_d1, t_motor_d1),
        (f"小卷径 D0 = {_fmt(d0)} m（转速工况）", n_motor_d0, t_motor_d0),
    ]

    alpha_load = max(alpha_load_d0, alpha_load_d1)
    r.n_load = max(n_load_d0, n_load_d1)
    r.alpha_load = alpha_load
    r.J_load_side = j_load_side
    r.T_load_side = max(abs(t_side_d1), abs(t_side_d0))
    r.T_peak_side = max(abs(t_side_d1) + j_load_side * alpha_load_d1,
                        abs(t_side_d0) + j_load_side * alpha_load_d0)

    n_motor = max(n_motor_d0, n_motor_d1)
    t_load_motor = max(abs(t_side_d1 / (i * eta)), abs(t_side_d0 / (i * eta)))
    alpha_motor = alpha_load * i
    t_acc_motor = (j_ref + j_coupling) * alpha_motor

    r.ratio = i
    r.n_motor = n_motor
    r.alpha_motor = alpha_motor
    r.omega_motor = TWO_PI * n_motor / 60.0
    r.J_reflected = j_ref
    r.J_coupling = j_coupling
    r.T_load_motor = t_load_motor
    r.T_accel_motor = t_acc_motor
    r.T_peak_motor = max(t_motor_d1, t_motor_d0)
    r.T_dec_motor = max(t_acc_motor - t_load_motor, 0.0)

    r.P_steady = t_load_motor * r.omega_motor
    r.P_peak = r.T_peak_motor * r.omega_motor
    r.P_req = max(r.P_peak, r.P_steady * lc.sf_power)

    r.add("大卷径转速 n(D1)", f"{_fmt(n_load_d1)} rpm", "n = v / (π·D1) × 60")
    r.add("小卷径转速 n(D0)", f"{_fmt(n_load_d0)} rpm", "n = v / (π·D0) × 60")
    r.add("大卷径转矩 T(D1)", f"{_fmt(t_side_d1)} N·m", "T = F_张力 · D1 / 2（负载侧）")
    r.add("小卷径转矩 T(D0)", f"{_fmt(t_side_d0)} N·m", "T = F_张力 · D0 / 2（负载侧）")
    r.add("卷筒惯量 J", f"{_fmt(j_drum)} kg·m²", "按实心圆柱 m·r²/2 估算或用户输入")
    r.add("电机侧折算惯量 J'", f"{_fmt(j_ref)} kg·m²", "J' = J_负载侧 / i²")
    r.add("电机侧转速(最恶劣)", f"{_fmt(n_motor)} rpm", "取小卷径高转速点")
    r.add("电机侧峰值转矩(最恶劣)", f"{_fmt(r.T_peak_motor)} N·m", "两个工作点取大值")


# --------------------------------------------------------------------------
# 统一折算到电机轴
# --------------------------------------------------------------------------
def _reflect(lc: LoadCase, r: Requirement, n_load: float, alpha_load: float,
             t_load_side: float, j_load_side: float) -> None:
    i = lc.ratio
    r.ratio = i
    r.n_load = n_load
    r.alpha_load = alpha_load
    r.n_motor = n_load * i
    r.alpha_motor = alpha_load * i
    r.omega_motor = TWO_PI * r.n_motor / 60.0
    r.J_load_side = j_load_side
    r.J_reflected = j_load_side / i ** 2
    r.J_coupling = lc.coupling_inertia
    r.T_load_motor = t_load_side / i
    r.T_accel_motor = r.J_reflected * r.alpha_motor
    r.T_peak_motor = abs(r.T_load_motor) + r.T_accel_motor
    r.T_dec_motor = max(r.T_accel_motor - abs(r.T_load_motor), 0.0)

    r.P_steady = abs(r.T_load_motor) * r.omega_motor
    r.P_peak = r.T_peak_motor * r.omega_motor
    r.P_req = max(r.P_peak, r.P_steady * lc.sf_power)

    r.add("负载侧转速 n_负载", f"{_fmt(n_load)} rpm", "由运动速度换算")
    r.add("减速比 i", f"{_fmt(i)}", "i = 电机转速 / 负载转速（直驱填 1）")
    r.add("电机转速 n_电机", f"{_fmt(r.n_motor)} rpm", "n_电机 = n_负载 × i")
    r.add("折算惯量 J_折算", f"{_fmt(r.J_reflected)} kg·m²", "J_折算 = J_负载侧 / i²")
    r.add("电机侧稳态转矩 T_L'", f"{_fmt(r.T_load_motor)} N·m", "T_L' = T_L / i")
    r.add("电机侧加速转矩 T_a", f"{_fmt(r.T_accel_motor)} N·m", "T_a = J_折算 · α_电机（尚未含电机转子惯量）")
    r.add("电机侧峰值转矩 T_峰", f"{_fmt(r.T_peak_motor)} N·m", "T_峰 = |T_L'| + T_a")
    r.add("稳态功率 P_稳", f"{_fmt(r.P_steady)} W", "P = T_L' · ω_电机")
    r.add("峰值功率 P_峰", f"{_fmt(r.P_peak)} W", "P = T_峰 · ω_电机")


# --------------------------------------------------------------------------
# 时序 / 占空比
# --------------------------------------------------------------------------
def _timing(lc: LoadCase, r: Requirement) -> None:
    r.t_accel, r.t_const = lc.accel_time, lc.const_time
    r.t_decel, r.t_dwell = lc.decel_time, lc.dwell_time
    r.cycle_time = r.t_accel + r.t_const + r.t_decel + r.t_dwell
    work = r.t_accel + r.t_const + r.t_decel
    r.duty = work / r.cycle_time * 100.0 if r.cycle_time > 0 else 0.0
    r.starts_per_hour = lc.starts_per_hour if lc.starts_per_hour > 0 else (
        3600.0 / r.cycle_time if r.cycle_time > 0 else 0.0
    )
    r.add("单周期时间", f"{_fmt(r.cycle_time)} s", "t_加 + t_匀 + t_减 + t_停")
    r.add("运行占空比", f"{_fmt(r.duty)} %", "((t_加+t_匀+t_减) / 周期) × 100%")
    r.add("每小时启停次数", f"{_fmt(r.starts_per_hour)} 次/h",
          "用户指定" if lc.starts_per_hour > 0 else "3600 / 周期时间")

    if lc.case in LINEAR_CASES and lc.stroke > 0 and lc.speed > 0:
        d_acc = lc.speed * lc.accel_time / 2.0
        d_dec = lc.speed * lc.decel_time / 2.0
        d_need = d_acc + d_dec
        if d_need > lc.stroke:
            r.warnings.append(
                f"行程不足：加/减速本身就需要 {d_need * 1000:.1f} mm，超过给定行程 "
                f"{lc.stroke * 1000:.1f} mm，无法达到设定速度（需降低速度、加大加速度或加长行程）"
            )
        else:
            r.add("匀速段距离", f"{_fmt(lc.stroke - d_need)} m", f"行程 {_fmt(lc.stroke)} m - 加速/减速距离")
            v_max_possible = math.sqrt(2 * (lc.speed / lc.accel_time) * lc.stroke * 0.9)
            if v_max_possible > 0:
                r.add("行程内可达最高速度(估算)", f"{_fmt(v_max_possible)} m/s", "三角速度曲线估算，仅供校核")


# --------------------------------------------------------------------------
# 工程性提示
# --------------------------------------------------------------------------
def _sanity_warnings(lc: LoadCase, r: Requirement) -> None:
    # 1. 加速度过大
    if r.a > 5 * G:
        r.warnings.append(f"加速度 {r.a:.2f} m/s² 已超过 5g，请确认机械结构与工艺允许")

    # 2. 梯形丝杆自锁 / 效率
    if lc.transmission == "screw_trap":
        if lc.screw_efficiency > 0.6:
            r.warnings.append("梯形（滑动）丝杆效率一般在 0.30 ~ 0.50，当前值偏高，请复核")
        lead = lc.screw_lead if lc.screw_lead > 0 else lc.per_rev_travel
        d2 = max(lc.screw_dia * 0.92, 1e-6)
        lam = math.atan(lead / (math.pi * d2))
        if math.tan(lam) >= 0.1:
            r.warnings.append(
                f"丝杆螺旋升角 {math.degrees(lam):.2f}° 偏大，垂直工况可能无法自锁，"
                "需配置制动器或平衡配重"
            )

    # 3. 丝杆细长比
    if lc.transmission in ("screw_ball", "screw_trap") and lc.screw_dia > 0:
        sl = lc.screw_len / lc.screw_dia
        if sl > 40:
            r.warnings.append(
                f"丝杆长径比 {sl:.1f} 偏大（>40），需校核临界转速与压杆稳定性，"
                "必要时加大直径或改用两端固定支撑"
            )

    # 4. 垂直工况制动
    if lc.case in ("vertical_lift", "vertical_press", "incline") and lc.counterweight <= 0:
        if lc.case != "incline" or lc.incline_deg > 30:
            r.warnings.append("垂直/大倾角工况重力持续作用，停机后需电磁制动器或自锁机构保持位置")

    # 5. 无传动件惯量提示
    if (lc.trans_inertia <= 0 and lc.transmission in ("belt", "chain", "rack", "gearbox", "drum")
            and lc.coupling_inertia <= 0):
        r.warnings.append("未计入带轮/齿轮/联轴器惯量，若其折算惯量占比较大请填入「传动件惯量」")

    # 6. 卷绕张力控制
    if lc.case == "winding":
        r.warnings.append("卷绕/放卷为变卷径恒张力工况，需锥度张力控制；选型时需同时满足最大卷径转矩与最小卷径转速")

    # 7. 效率与传动不匹配
    hint = {
        "direct": (0.90, 1.00), "belt": (0.88, 0.99), "chain": (0.80, 0.96),
        "rack": (0.85, 0.97), "screw_ball": (0.80, 0.96), "screw_trap": (0.25, 0.55),
        "drum": (0.90, 0.99), "gearbox": (0.50, 0.99),
    }.get(lc.transmission)
    if hint and not (hint[0] <= lc.efficiency <= hint[1]):
        r.warnings.append(
            f"当前传动效率 {lc.efficiency:.2f} 超出「{lc.transmission_label}」的常见范围 "
            f"{hint[0]:.2f} ~ {hint[1]:.2f}，请复核"
        )

    # 8. 旋转工况缺少惯量 / 负载转矩
    if lc.case in ROTARY_CASES:
        if load_inertia(lc) <= 0:
            r.warnings.append("负载惯量填的是 0：加速转矩与惯量比都会被低估，请用「惯量计算器」补齐")
        if abs(r.T_load_side) <= 1e-9:
            r.warnings.append("负载侧摩擦转矩/外力矩为 0：请确认是否忽略轴承摩擦、切削力或不平衡重力矩")

    # 9. 直线工况缺负载
    if r.is_linear and lc.mass <= 0 and lc.ext_force <= 0:
        r.warnings.append("负载质量与外力都为 0，计算结果没有意义，请检查输入")
