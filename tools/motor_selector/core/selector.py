# -*- coding: utf-8 -*-
"""校核与自动选型引擎。

同一个「需求」对每一种电机（可选配减速机）都要过一遍校核项，
再按余量合理程度打分排序，给出推荐清单。

校核项（因电机类型而异）：
    异步电机 : 转速 / 最大转矩(2.2×额定) / 连续转矩 / 功率
    步进电机 : 转速(矩频曲线覆盖) / 动态转矩 / 惯量比 / 步距分辨率 / 共振区提示
    伺服电机 : 最高转速 / 峰值转矩(过载倍数) / 连续有效转矩(RMS) / 惯量比 / 编码器分辨率
    直流无刷 : 转速 / 峰值转矩 / 连续转矩 / 功率
    直流有刷 : 转速 / 峰值转矩 / 连续转矩 / 功率
    直线电机 : 最高速度 / 峰值推力 / 连续推力 / 动子质量惯量比
    减速机   : 额定输出转矩 / 峰值输出转矩 / 允许输入转速 / 减速比范围 / 背隙定位误差
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .database import all_gearboxes, all_motors
from .entities import (
    GENERIC_RATIOS,
    CheckItem,
    Evaluation,
    Gearbox,
    LoadCase,
    Motor,
    Requirement,
    _fmt,
)


# --------------------------------------------------------------------------
# 从工况参数生成「手动输入」的电机
# --------------------------------------------------------------------------
def manual_motor(lc: LoadCase) -> Motor:
    return Motor(
        kind=lc.manual_kind,
        model="手动输入型号",
        rated_power=lc.manual_power,
        rated_rpm=lc.manual_rpm,
        max_rpm=lc.manual_max_rpm,
        rated_torque=lc.manual_torque,
        max_torque=lc.manual_peak_torque,
        peak_torque=lc.manual_peak_torque,
        inertia=lc.manual_inertia,
        voltage=lc.voltage if lc.voltage != "任意" else "任意",
        source="手动输入",
    )


# --------------------------------------------------------------------------
# 单次校核
# --------------------------------------------------------------------------
def evaluate(lc: LoadCase, req: Requirement, motor: Motor,
             gearbox: Optional[Gearbox] = None, ratio: float = 1.0) -> Evaluation:
    """把某台电机（可带减速机）拿去校核一个需求。"""
    i = max(float(ratio), 1e-6)
    if gearbox is not None:
        eta_gb = gearbox.efficiency
    else:
        # 没有指定具体减速机时，若速比不为 1 说明需要另配减速机，
        # 按通用行星减速机的典型效率保守计算（不能假装是无损传动）
        eta_gb = 1.0 if abs(i - 1.0) < 1e-9 else 0.94
    ev = Evaluation(motor=motor, gearbox=gearbox, ratio=i, efficiency=lc.efficiency * eta_gb)

    if motor.kind == "直线电机":
        _evaluate_linear_motor(lc, req, motor, ev)
    else:
        _evaluate_rotary_motor(lc, req, motor, ev, eta_gb)

    if gearbox is not None:
        _gearbox_checks(lc, req, gearbox, ev)
    elif abs(i - 1.0) > 1e-9:
        ev.warnings.append(
            f"该方案需要另配一台减速机（速比 i={_fmt(i)}，按典型效率 0.94 估算），"
            "减速机的额定/峰值输出转矩、允许输入转速与背隙需按实际样本另行校核"
        )

    ev.feasible = all(c.ok for c in ev.checks if c.mandatory)
    ev.score = _score(ev)
    return ev


def _rms(lc: LoadCase, t_load: float, t_acc: float) -> Tuple[float, float]:
    """由稳态转矩与加速转矩算 (工作段RMS, 整周期RMS)。"""
    t_a, t_c, t_d, t_w = lc.accel_time, lc.const_time, lc.decel_time, lc.dwell_time
    if t_a + t_c + t_d <= 0:
        return t_load, t_load
    t1 = t_load + t_acc
    t3 = abs(t_acc - t_load)
    num = t1 ** 2 * t_a + t_load ** 2 * t_c + t3 ** 2 * t_d
    t_work = t_a + t_c + t_d
    rms_work = math.sqrt(num / t_work)
    rms_cycle = math.sqrt(num / (t_work + t_w)) if t_w > 0 else rms_work
    return rms_work, rms_cycle


def _evaluate_rotary_motor(lc: LoadCase, req: Requirement, motor: Motor,
                           ev: Evaluation, eta_gb: float) -> None:
    i = ev.ratio
    n_motor = req.n_load * i
    alpha_motor = req.alpha_load * i
    j_ref = req.J_load_side / i ** 2
    j_coupling = lc.coupling_inertia + max(motor.inertia, 0.0)
    j_total = j_ref + j_coupling
    t_load = abs(req.T_load_side) / (i * eta_gb)
    t_acc = j_total * abs(alpha_motor)
    t_peak = t_load + t_acc
    rms_work, rms_cycle = _rms(lc, t_load, t_acc)
    t_rms = max(rms_work, rms_cycle) if lc.dwell_time <= 0 else rms_cycle
    p_steady = t_load * (2 * math.pi * n_motor / 60.0)
    p_peak = t_peak * (2 * math.pi * n_motor / 60.0)

    ev.n_motor, ev.T_load, ev.T_peak, ev.T_rms = n_motor, t_load, t_peak, t_rms
    ev.P_req = max(p_peak, p_steady * lc.sf_power)
    ev.J_reflected = j_ref
    ev.inertia_ratio = (j_ref / motor.inertia) if motor.inertia > 0 else 0.0

    # 卷绕的第二个工作点
    points = list(req.extra_points)

    sf = max(lc.sf_torque, 1.0)
    speed_limit = motor.speed_limit()
    t_avail = motor.torque_at(n_motor)
    t_cont = motor.continuous_torque()

    # 1) 转速
    ev.checks.append(CheckItem(
        "转速校核", n_motor, speed_limit, "rpm",
        ok=n_motor <= speed_limit + 1e-9,
        note=f"电机允许最高 {_fmt(speed_limit)} rpm；减速比 i={_fmt(i)}",
    ))
    if points:
        worst_n = max(p[1] for p in points)
        ev.checks.append(CheckItem(
            "卷绕最高转速校核", worst_n, speed_limit, "rpm",
            ok=worst_n <= speed_limit + 1e-9, note="小卷径时转速最高"
        ))
        for name, pn, pt in points:
            ev.checks.append(CheckItem(
                f"工作点校核·{name}", pt * sf, motor.torque_at(pn), "N·m",
                ok=pt * sf <= motor.torque_at(pn) + 1e-9,
                note=f"{_fmt(pn)} rpm 下的可用转矩",
            ))

    # 2) 峰值转矩
    ev.checks.append(CheckItem(
        "峰值转矩校核", t_peak * sf, t_avail, "N·m",
        ok=t_peak * sf <= t_avail + 1e-9,
        note=f"需求再乘安全系数 {_fmt(sf)}；电机过载倍数 {_fmt(motor.overload_factor())}×"
             + ("（步进按矩频曲线动态转矩）" if motor.kind == "步进电机" else ""),
    ))

    # 3) 连续 / 有效转矩
    ev.checks.append(CheckItem(
        "连续(有效)转矩校核", t_rms, t_cont, "N·m",
        ok=t_rms <= t_cont + 1e-9,
        note=f"一个周期 RMS 转矩 {_fmt(rms_cycle)} N·m，仅工作段 RMS {_fmt(rms_work)} N·m，"
             f"占空比 {_fmt(lc_duty(lc))}%",
    ))

    # 4) 功率
    if motor.rated_power > 0:
        p_need = max(p_steady, t_rms * (2 * math.pi * n_motor / 60.0)) * lc.sf_power
        ev.checks.append(CheckItem(
            "功率校核", p_need, motor.rated_power, "W",
            ok=p_need <= motor.rated_power + 1e-9,
            note=f"稳态功率 {_fmt(p_steady)} W，峰值功率 {_fmt(p_peak)} W",
        ))

    # 5) 惯量比
    _inertia_check(lc, motor, ev)

    # 6) 分辨率 / 定位
    _resolution_checks(lc, req, motor, ev)

    # 7) 伺服峰值转矩持续时间
    if motor.kind == "伺服电机" and lc.accel_time > 3.0:
        ev.warnings.append(
            f"加速时间 {_fmt(lc.accel_time)} s 超过伺服峰值转矩的常见允许时间（约 3 s），"
            "长时间过载会触发热保护，建议按额定转矩核算加速能力"
        )
    if motor.kind == "步进电机":
        if 100.0 <= n_motor <= 250.0:
            ev.warnings.append(
                f"工作转速 {_fmt(n_motor)} rpm 落在步进电机常见低频共振区（约 100~250 rpm），"
                "建议避开该区间、加细分或提高减速比"
            )
        ev.warnings.append("开环步进存在丢步风险，建议保留 30% 以上转矩余量并考虑闭环方案")
    if motor.kind == "异步电机":
        ev.warnings.append("异步电机需另配变频器；低速恒转矩运行时需强制风冷或降额使用")
    if t_peak > t_load * 3 and t_load > 1e-9:
        ev.warnings.append("加速转矩远大于稳态转矩（占比高），可考虑加大加速时间或降低惯量")


def _evaluate_linear_motor(lc: LoadCase, req: Requirement, motor: Motor, ev: Evaluation) -> None:
    """直线电机直驱：按推力校核。"""
    i = 1.0
    ev.ratio = 1.0
    v = req.v
    m_total = req.m_moving + motor.mover_mass
    f_acc = m_total * req.a
    f_resist = abs(req.F_resist)
    f_peak = f_resist + f_acc
    f_cont = f_resist + f_acc * (lc.accel_time / max(req.cycle_time, 1e-9)) ** 0.5

    ev.n_motor = 0.0
    ev.T_load = f_resist
    ev.T_peak = f_peak
    ev.T_rms = f_cont
    ev.P_req = f_peak * v
    ev.J_reflected = 0.0
    ev.inertia_ratio = (m_total / motor.mover_mass) if motor.mover_mass > 0 else 0.0

    sf = max(lc.sf_torque, 1.0)
    vmax = motor.max_speed or 1.0
    ev.checks.append(CheckItem("速度校核", v, vmax, "m/s", ok=v <= vmax + 1e-9,
                               note="直线电机最高速度限制"))
    ev.checks.append(CheckItem("峰值推力校核", f_peak * sf, motor.peak_force, "N",
                               ok=f_peak * sf <= motor.peak_force + 1e-9,
                               note=f"含动子质量 {_fmt(motor.mover_mass)} kg 的加速推力"))
    ev.checks.append(CheckItem("连续推力校核", f_cont, motor.cont_force, "N",
                               ok=f_cont <= motor.cont_force + 1e-9,
                               note="按占空比折算的连续推力（发热限制）"))
    ev.checks.append(CheckItem("动子质量比校核", m_total, motor.mover_mass * 30.0, "kg",
                               ok=m_total <= motor.mover_mass * 30.0, mandatory=False,
                               note="负载质量 / 动子质量过大会显著降低动态响应"))
    ev.checks.append(CheckItem("行程长度校核", lc.stroke * 1000, 6000.0, "mm",
                               ok=lc.stroke * 1000 <= 6000.0, mandatory=False,
                               note="长行程需按定子拼接段数与电缆拖链方案确认"))
    ev.notes.append("直线电机无减速环节，定位精度直接取决于光栅尺分辨率与导轨精度")


def _inertia_check(lc: LoadCase, motor: Motor, ev: Evaluation) -> None:
    limit = lc.max_inertia_ratio if lc.max_inertia_ratio > 0 else motor.inertia_ratio_limit()
    if motor.inertia <= 0:
        ev.checks.append(CheckItem("惯量比校核", 0.0, limit, "", ok=True, mandatory=False,
                                   note="电机转子惯量未提供，无法计算"))
        return
    ev.checks.append(CheckItem(
        "惯量比校核", ev.inertia_ratio, limit, "", ok=ev.inertia_ratio <= limit + 1e-9,
        mandatory=True,
        note=f"折算负载惯量 {_fmt(ev.J_reflected)} / 转子惯量 {_fmt(motor.inertia)} kg·m²；"
             f"{motor.kind}推荐上限 {_fmt(limit)}",
    ))
    if ev.inertia_ratio > limit:
        ev.warnings.append(
            f"惯量比 {_fmt(ev.inertia_ratio)} 超过 {motor.kind} 建议上限 {_fmt(limit)}，"
            "会出现整定困难、启停抖动，建议加大减速比或选大惯量电机"
        )


def _resolution_checks(lc: LoadCase, req: Requirement, motor: Motor, ev: Evaluation) -> None:
    if lc.positioning_mm <= 0 or req.travel_per_rev <= 0:
        return
    i = ev.ratio
    if motor.kind == "步进电机" and motor.step_angle > 0:
        per_step = motor.step_angle / 360.0 * req.travel_per_rev / i * 1000.0
        ev.checks.append(CheckItem(
            "步距分辨率校核", per_step, lc.positioning_mm, "mm",
            ok=per_step <= lc.positioning_mm + 1e-9, mandatory=False,
            note=f"整步位移 {_fmt(per_step)} mm；细分后按细分数等比例减小",
        ))
    if motor.encoder and "bit" in motor.encoder.lower():
        digits = "".join(ch for ch in motor.encoder if ch.isdigit())
        if digits:
            bits = int(digits[:2]) if len(digits) >= 2 else int(digits)
            if 8 <= bits <= 30:
                res = req.travel_per_rev / i / (2 ** bits) * 1e6   # μm
                ev.checks.append(CheckItem(
                    "编码器分辨率校核", res, lc.positioning_mm * 1000.0, "μm",
                    ok=res <= lc.positioning_mm * 1000.0 + 1e-9, mandatory=False,
                    note=f"{motor.encoder} 对应每脉冲位移",
                ))


def _gearbox_checks(lc: LoadCase, req: Requirement, gb: Gearbox, ev: Evaluation) -> None:
    t_cont_side = abs(req.T_load_side)
    t_peak_side = req.T_peak_side

    if gb.torque_unlimited:
        # 「通用减速机」只是速比占位，没有真实转矩数据，不做数值校核
        note = ("「通用减速机」只提供速比，程序不校核其转矩能力；"
                "确定速比后必须用实际减速机样本复核额定/峰值输出转矩")
        ev.checks.append(CheckItem(
            "减速机额定输出转矩", t_cont_side, 0.0, "N·m", ok=True, mandatory=False,
            capacity_text="不限（需按样本复核）", note=note))
        ev.checks.append(CheckItem(
            "减速机峰值输出转矩", t_peak_side, 0.0, "N·m", ok=True, mandatory=False,
            capacity_text="不限（需按样本复核）", note=note))
    else:
        ev.checks.append(CheckItem(
            "减速机额定输出转矩", t_cont_side, gb.rated_torque, "N·m",
            ok=t_cont_side <= gb.rated_torque + 1e-9,
            note=f"{gb.kind} {gb.model}",
        ))
        ev.checks.append(CheckItem(
            "减速机峰值输出转矩", t_peak_side, gb.peak_limit(), "N·m",
            ok=t_peak_side <= gb.peak_limit() + 1e-9,
            note="峰值按额定 2 倍计（如样本不同请以样本为准）",
        ))

    ev.checks.append(CheckItem(
        "减速机允许输入转速", ev.n_motor, gb.max_input_rpm, "rpm",
        ok=ev.n_motor <= gb.max_input_rpm + 1e-9,
        note="" if not gb.torque_unlimited else "通用减速机按 5000 rpm 占位，须按样本复核",
    ))
    if gb.ratio_min > 0 and gb.ratio_max > 0:
        in_range = gb.ratio_min - 1e-9 <= ev.ratio <= gb.ratio_max + 1e-9
        ev.checks.append(CheckItem(
            "减速机速比范围", ev.ratio, gb.ratio_max, "",
            ok=in_range, note=f"可用范围 {_fmt(gb.ratio_min)} ~ {_fmt(gb.ratio_max)}",
        ))
    if (not gb.torque_unlimited) and lc.positioning_mm > 0 and req.travel_per_rev > 0 \
            and gb.backlash_arcmin > 0:
        err_mm = gb.backlash_arcmin / 60.0 / 360.0 * req.travel_per_rev * 1000.0
        ev.checks.append(CheckItem(
            "背隙定位误差", err_mm, lc.positioning_mm, "mm",
            ok=err_mm <= lc.positioning_mm + 1e-9, mandatory=False,
            note=f"背隙 {_fmt(gb.backlash_arcmin)} arcmin 折算到负载侧；"
                 "如需更高精度需选低背隙/谐波减速机或单方向定位",
        ))
    if gb.torque_unlimited:
        ev.warnings.append("当前按「通用减速机」估算速比，实际减速机必须用样本额定转矩重新校核")


def lc_duty(lc: LoadCase) -> float:
    cycle = lc.accel_time + lc.const_time + lc.decel_time + lc.dwell_time
    if cycle <= 0:
        return 0.0
    return (lc.accel_time + lc.const_time + lc.decel_time) / cycle * 100.0


# --------------------------------------------------------------------------
# 打分
# --------------------------------------------------------------------------
def _margin_score(margin: float, ideal_lo: float, ideal_hi: float) -> float:
    """余量 -> 0~1 分。余量太小或太大都要扣分。"""
    if margin < 1.0:
        return 0.0
    if margin < ideal_lo:
        return (margin - 1.0) / max(ideal_lo - 1.0, 1e-9)
    if margin <= ideal_hi:
        return 1.0
    return max(0.0, 1.0 - (margin - ideal_hi) / max(ideal_hi * 2.0, 1e-9))


_WEIGHTS = {
    "峰值转矩校核": 0.32,
    "连续(有效)转矩校核": 0.16,
    "转速校核": 0.18,
    "惯量比校核": 0.18,
    "功率校核": 0.10,
    "峰值推力校核": 0.34,
    "连续推力校核": 0.20,
    "速度校核": 0.20,
}
_IDEAL = {
    "峰值转矩校核": (1.3, 2.5),
    "连续(有效)转矩校核": (1.05, 1.8),
    "转速校核": (1.15, 2.0),
    "功率校核": (1.05, 1.8),
    "峰值推力校核": (1.3, 2.5),
    "连续推力校核": (1.05, 1.8),
    "速度校核": (1.15, 2.0),
}


def _score(ev: Evaluation) -> float:
    if not ev.feasible:
        return 0.0
    total_w = 0.0
    acc = 0.0
    for check in ev.checks:
        if check.name == "惯量比校核":
            # 惯量比永远参与打分（即使对某些电机不作为否决项）
            if check.capacity <= 0:
                continue
            ratio = check.required / check.capacity
            sub = max(0.0, 1.0 - max(ratio - 0.5, 0.0) / 0.5)
            acc += _WEIGHTS["惯量比校核"] * sub
            total_w += _WEIGHTS["惯量比校核"]
            continue
        if not check.mandatory:
            continue
        w = _WEIGHTS.get(check.name)
        if w is None:
            continue
        lo, hi = _IDEAL.get(check.name, (1.2, 2.5))
        acc += w * _margin_score(check.margin, lo, hi)
        total_w += w
    # 减速机余量分（只有真实减速机型号才计入，占位条目不算）
    for check in ev.checks:
        if check.name == "减速机额定输出转矩":
            if check.capacity > 0 and check.capacity < 1.0e8:
                acc += 0.08 * _margin_score(check.margin, 1.2, 3.0)
                total_w += 0.08
            break
    if total_w <= 0:
        return 50.0
    return round(100.0 * acc / total_w, 1)


# --------------------------------------------------------------------------
# 自动选型
# --------------------------------------------------------------------------
def _voltage_ok(want: str, have: str) -> bool:
    if not want or want == "任意" or not have or have == "任意":
        return True
    return want.split()[0].strip().upper() == have.split()[0].strip().upper()


def _ratio_bounds(lc: LoadCase, req: Requirement, motor: Motor) -> Tuple[float, float]:
    """粗略的可用减速比区间 [i_min, i_max]。"""
    speed_limit = motor.speed_limit() if motor.kind != "直线电机" else 0.0
    if req.n_load <= 0 or speed_limit <= 0:
        i_max = 1e6
    else:
        i_max = speed_limit * 0.98 / req.n_load
    t_avail_max = motor.torque_at(0.0)
    t_need_side = abs(req.T_load_side) + req.J_load_side * abs(req.alpha_load)
    if t_avail_max <= 0:
        return 0.0, i_max
    i_min = t_need_side / (lc.efficiency * t_avail_max)
    return max(i_min, 1.0), i_max


def auto_select(lc: LoadCase, req: Requirement,
                motors: Optional[Sequence[Motor]] = None,
                gearboxes: Optional[Sequence[Gearbox]] = None,
                top_n: int = 40) -> List[Evaluation]:
    """在型号库中逐台校核，返回按匹配度排序的可行方案。"""
    if not req.ok:
        return []
    motors = list(motors) if motors is not None else all_motors()
    gearboxes = list(gearboxes) if gearboxes is not None else all_gearboxes()

    results: List[Evaluation] = []
    for motor in motors:
        if lc.motor_kind_pref not in ("任意", "") and motor.kind != lc.motor_kind_pref:
            continue
        if not _voltage_ok(lc.voltage, motor.voltage):
            continue
        if lc.max_motor_power > 0 and motor.rated_power > lc.max_motor_power * 1.001:
            continue

        if motor.kind == "直线电机":
            if not req.is_linear:
                continue
            ev = evaluate(lc, req, motor, None, 1.0)
            if ev.feasible:
                results.append(ev)
            continue

        i_min, i_max = _ratio_bounds(lc, req, motor)
        if i_min > i_max * 1.0001:
            continue

        combos: List[Tuple[float, Optional[Gearbox]]] = []
        if lc.allow_gearbox:
            for r in GENERIC_RATIOS:
                if i_min <= r <= i_max:
                    combos.append((r, None))
            for gb in gearboxes:
                if i_min <= gb.ratio <= i_max:
                    combos.append((gb.ratio, gb))
        else:
            combos.append((lc.ratio, None))

        best: Optional[Evaluation] = None
        for r, gb in combos:
            ev = evaluate(lc, req, motor, gb, r)
            if not ev.feasible:
                continue
            if best is None or ev.score > best.score:
                best = ev
        if best is not None:
            results.append(best)

    _apply_size_penalty(results)
    results.sort(key=lambda e: (-e.score, e.P_req, e.motor.rated_power))
    return results[:top_n]


def _apply_size_penalty(results: List[Evaluation]) -> None:
    """同分时优先「简单 + 小」的方案：
    * 功率量级越大扣分越多（能选小的不选大的）
    * 减速比越大扣分越多（减速机越贵、精度越差、效率越低）
    """
    if not results:
        return
    powers = [e.motor.rated_power for e in results if e.motor.rated_power > 0]
    p_min = min(powers) if powers else 0.0
    for e in results:
        p = e.motor.rated_power
        if p > 0 and p_min > 0:
            e.score = round(max(e.score - min(6.0, 6.0 * math.log10(p / p_min) / 1.5), 0.0), 1)
        if e.ratio > 1.0001:
            e.score = round(max(e.score - min(8.0, 3.0 * math.log10(e.ratio)), 0.0), 1)


def check_manual(lc: LoadCase, req: Requirement) -> Evaluation:
    """用界面上手填的电机参数做一次校核（等价于原来的 Excel 表格用法）。"""
    return evaluate(lc, req, manual_motor(lc), None, lc.ratio)


def summarize(ev: Evaluation) -> str:
    """一句话结论。"""
    if ev.feasible:
        fails = [c for c in ev.checks if c.mandatory and c.margin < 1.3]
        if fails:
            return "可行（余量偏紧：" + "、".join(c.name for c in fails) + "）"
        return "可行"
    names = ev.failed_names
    return "不通过：" + ("、".join(names) if names else "存在不满足项")
