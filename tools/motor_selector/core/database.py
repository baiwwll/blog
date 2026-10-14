# -*- coding: utf-8 -*-
"""电机 / 减速机型号库。

内置库全部是**按行业常见规格整理的典型参数**，用于选型演示与量级估算；
正式出图 / 下单前必须用厂家样本（或导入厂家 CSV）替换校核。

支持：
    * 内置典型库（按功率族自动生成，参数自洽）
    * CSV 导入 / 导出（用户库保存在 exe 同目录 userdata 下）
    * 表头中英文皆可识别
"""
from __future__ import annotations

import csv
import os
from typing import Dict, List, Optional, Tuple

from .entities import Gearbox, Motor
from .resources import user_data_dir

# --------------------------------------------------------------------------
# CSV 表头
# --------------------------------------------------------------------------
MOTOR_COLUMNS = [
    "kind", "model", "rated_power", "rated_rpm", "max_rpm", "rated_torque",
    "max_torque", "peak_torque", "inertia", "holding_torque", "step_angle",
    "torque_curve", "voltage", "encoder", "cont_force", "peak_force",
    "mover_mass", "max_speed", "weight", "efficiency", "notes",
]
MOTOR_HEADER_CN = {
    "kind": "类型", "model": "型号", "rated_power": "额定功率W", "rated_rpm": "额定转速rpm",
    "max_rpm": "最高转速rpm", "rated_torque": "额定转矩Nm", "max_torque": "最大转矩Nm",
    "peak_torque": "峰值转矩Nm", "inertia": "转子惯量kgm2", "holding_torque": "保持转矩Nm",
    "step_angle": "步距角deg", "torque_curve": "矩频曲线", "voltage": "电压",
    "encoder": "编码器", "cont_force": "连续推力N", "peak_force": "峰值推力N",
    "mover_mass": "动子质量kg", "max_speed": "最高速度ms", "weight": "重量kg",
    "efficiency": "效率", "notes": "备注",
}
GEARBOX_COLUMNS = [
    "kind", "model", "ratio", "rated_torque", "peak_torque", "efficiency",
    "backlash_arcmin", "max_input_rpm", "inertia", "weight", "notes",
]
GEARBOX_HEADER_CN = {
    "kind": "类型", "model": "型号", "ratio": "减速比", "rated_torque": "额定输出转矩Nm",
    "peak_torque": "峰值输出转矩Nm", "efficiency": "效率", "backlash_arcmin": "背隙arcmin",
    "max_input_rpm": "允许输入转速rpm", "inertia": "输入轴惯量kgm2", "weight": "重量kg",
    "notes": "备注",
}


# --------------------------------------------------------------------------
# 内置库构建
# --------------------------------------------------------------------------
def _stepper_curve(holding: float, closed_loop: bool = False) -> str:
    """按保持转矩生成典型矩频曲线（24V 驱动，半步/细分后折算到整步）。"""
    if closed_loop:
        profile = [(0, 1.00), (300, 0.98), (600, 0.92), (1200, 0.62), (1800, 0.38), (2400, 0.18)]
    else:
        profile = [(0, 1.00), (120, 0.95), (300, 0.80), (600, 0.52), (900, 0.30), (1200, 0.17), (1500, 0.09)]
    return ",".join(f"{rpm:g}:{holding * k:.3f}" for rpm, k in profile)


def builtin_motors() -> List[Motor]:
    """构建内置典型电机库。"""
    out: List[Motor] = []

    # ---- 通用异步电机（4 极 1450 rpm / AC380V，Y 系列量级） ----
    for p_kw in (0.12, 0.18, 0.25, 0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3.0,
                 4.0, 5.5, 7.5, 11.0, 15.0, 18.5, 22.0):
        n = 1450.0
        tn = 9550.0 * p_kw / n
        out.append(Motor(
            kind="异步电机", model=f"Y{p_kw:g}kW-4极", rated_power=p_kw * 1000.0,
            rated_rpm=n, max_rpm=n, rated_torque=tn, max_torque=tn * 2.2,
            inertia=0.0015 * p_kw ** 0.95, voltage="AC380V 三相",
            efficiency=0.72 + 0.02 * min(p_kw, 5.0), weight=8.0 + 6.0 * p_kw,
            source="内置典型",
            notes="通用异步电机典型值：最大转矩 2.2×额定，转子惯量为估算值，订货以厂家样本为准",
        ))
    for p_kw in (0.55, 0.75, 1.1, 1.5, 2.2, 3.0, 4.0, 5.5, 7.5, 11.0):
        n = 960.0
        tn = 9550.0 * p_kw / n
        out.append(Motor(
            kind="异步电机", model=f"Y{p_kw:g}kW-6极", rated_power=p_kw * 1000.0,
            rated_rpm=n, max_rpm=n, rated_torque=tn, max_torque=tn * 2.0,
            inertia=0.0018 * p_kw ** 0.95, voltage="AC380V 三相",
            efficiency=0.70 + 0.02 * min(p_kw, 5.0), weight=9.0 + 6.5 * p_kw,
            source="内置典型", notes="6 极异步电机典型值",
        ))

    # ---- 交流伺服电机（AC220V，3000 rpm，峰值 3×额定） ----
    for p_w, j in ((100, 4.0e-6), (200, 9.0e-6), (400, 2.6e-5), (750, 8.7e-5),
                   (1000, 1.1e-4), (1500, 1.9e-4), (2000, 2.6e-4), (3000, 5.9e-4),
                   (5000, 9.0e-4), (7500, 1.5e-3)):
        n = 3000.0
        tn = 9550.0 * (p_w / 1000.0) / n
        out.append(Motor(
            kind="伺服电机", model=f"伺服 {p_w}W/3000rpm", rated_power=p_w,
            rated_rpm=n, max_rpm=6000.0 if p_w <= 1000 else 5000.0,
            rated_torque=tn, peak_torque=tn * 3.0, inertia=j,
            voltage="AC220V 单相", encoder="23bit 绝对值编码器",
            efficiency=0.90, weight=0.6 + p_w / 1000.0 * 1.6, source="内置典型",
            notes="通用小惯量伺服典型值：峰值 3×额定，惯量为量级参考值",
        ))
    # 大惯量（带制动/大转动惯量）伺服，惯量比普通型大 3~5 倍
    for p_w, j in ((400, 1.1e-4), (750, 3.5e-4), (1500, 8.0e-4), (2000, 1.1e-3)):
        n = 2000.0
        tn = 9550.0 * (p_w / 1000.0) / n
        out.append(Motor(
            kind="伺服电机", model=f"伺服 {p_w}W/2000rpm 大惯量", rated_power=p_w,
            rated_rpm=n, max_rpm=3000.0, rated_torque=tn, peak_torque=tn * 3.0,
            inertia=j, voltage="AC220V 三相", encoder="23bit 绝对值编码器",
            efficiency=0.90, weight=2.0 + p_w / 1000.0 * 2.5, source="内置典型",
            notes="大惯量伺服，适合大惯量负载直驱",
        ))

    # ---- 两相混合式步进电机（NEMA 规格，1.8°） ----
    steppers = [
        ("42-40mm", 0.40, 5.4e-6, 0.35, False), ("42-48mm", 0.65, 8.2e-6, 0.45, False),
        ("57-56mm", 1.20, 3.0e-5, 0.75, False), ("57-76mm", 1.90, 4.8e-5, 1.05, False),
        ("57-100mm", 2.80, 8.2e-5, 1.40, False), ("57-112mm 闭环", 3.00, 8.5e-5, 1.50, True),
        ("86-98mm", 4.50, 1.4e-4, 2.40, False), ("86-118mm", 6.00, 1.9e-4, 3.20, False),
        ("86-156mm", 8.50, 2.7e-4, 4.50, False), ("86-156mm 闭环", 12.00, 2.8e-4, 4.80, True),
        ("110-150mm", 12.00, 6.0e-4, 6.80, False), ("110-200mm", 18.00, 9.5e-4, 9.50, False),
        ("130-200mm", 20.00, 1.4e-3, 12.0, False), ("130-250mm", 28.00, 2.1e-3, 16.0, False),
    ]
    for model, hold, j, w, cl in steppers:
        out.append(Motor(
            kind="步进电机", model=f"两相步进 {model}" + ("（闭环）" if cl else ""),
            rated_power=0.0, rated_rpm=600.0,
            max_rpm=2400.0 if cl else 1500.0,
            rated_torque=hold, holding_torque=hold, max_torque=hold,
            inertia=j, step_angle=1.8, torque_curve=_stepper_curve(hold, cl),
            voltage="DC24V" if not cl else "DC48V",
            encoder="1000线增量编码器" if cl else "",
            efficiency=0.60 if not cl else 0.75, weight=w, source="内置典型",
            notes="保持转矩与矩频曲线为 24V/48V 典型值；开环步进务必留 30%~50% 转矩余量",
        ))

    # ---- 直流无刷 / 有刷 ----
    for p_w, n in ((60, 3000), (100, 3000), (200, 3000), (400, 3000), (750, 3000), (1200, 3000)):
        tn = 9550.0 * (p_w / 1000.0) / n
        out.append(Motor(
            kind="直流无刷", model=f"BLDC {p_w}W/{n}rpm", rated_power=p_w, rated_rpm=n,
            max_rpm=n * 1.5, rated_torque=tn, peak_torque=tn * 2.5,
            inertia=1.5e-6 * (p_w / 100.0) ** 0.9, voltage="DC48V",
            encoder="霍尔 + 增量编码器", efficiency=0.85,
            weight=0.3 + p_w / 1000.0 * 1.2, source="内置典型",
            notes="无刷直流典型值：峰值 2.5×额定，需配驱动器",
        ))
    for p_w, n in ((30, 3000), (60, 3000), (100, 3000), (150, 3000), (250, 3000)):
        tn = 9550.0 * (p_w / 1000.0) / n
        out.append(Motor(
            kind="直流有刷", model=f"有刷 DC{p_w}W/{n}rpm", rated_power=p_w, rated_rpm=n,
            max_rpm=n * 1.5, rated_torque=tn, peak_torque=tn * 3.0,
            inertia=1.0e-6 * (p_w / 50.0) ** 0.9, voltage="DC24V",
            encoder="增量编码器（可选）", efficiency=0.70,
            weight=0.25 + p_w / 1000.0 * 1.0, source="内置典型",
            notes="有刷直流典型值，注意电刷寿命",
        ))

    # ---- 直线电机（无铁芯 / 有铁芯） ----
    linear = [
        ("无铁芯 30N", 30.0, 90.0, 0.55, 3.0, 0.9),
        ("无铁芯 60N", 60.0, 180.0, 0.95, 3.0, 1.6),
        ("无铁芯 120N", 120.0, 360.0, 1.8, 3.0, 3.0),
        ("有铁芯 200N", 200.0, 600.0, 4.5, 2.5, 5.5),
        ("有铁芯 500N", 500.0, 1500.0, 9.0, 2.0, 13.0),
        ("有铁芯 1000N", 1000.0, 3000.0, 16.0, 1.5, 25.0),
        ("有铁芯 2000N", 2000.0, 6000.0, 28.0, 1.2, 48.0),
    ]
    for name, fc, fp, mover, vmax, w in linear:
        out.append(Motor(
            kind="直线电机", model=f"直线电机 {name}", rated_power=fc * 1.0,
            rated_rpm=0.0, max_rpm=0.0, rated_torque=0.0, cont_force=fc, peak_force=fp,
            mover_mass=mover, max_speed=vmax, inertia=0.0, voltage="AC220V 三相",
            encoder="光栅尺（0.1μm 级）", efficiency=0.85, weight=w, source="内置典型",
            notes="连续/峰值推力为典型值；额定功率按 1 m/s 参考速度折算，实际随速度变化",
        ))
    return out


def builtin_gearboxes() -> List[Gearbox]:
    """构建内置典型减速机库（每个速比一条记录，便于直接比对）。"""
    out: List[Gearbox] = []

    def add(kind, model, ratio, t_rated, eta, backlash, max_in, j, w, notes=""):
        out.append(Gearbox(kind=kind, model=model, ratio=ratio, ratio_min=ratio, ratio_max=ratio,
                           rated_torque=t_rated, peak_torque=t_rated * 2.0, efficiency=eta,
                           backlash_arcmin=backlash, max_input_rpm=max_in, inertia=j,
                           weight=w, source="内置典型", notes=notes))

    # 行星减速机（单级 / 两级），按常用机座号
    planetary = [
        ("行星 60 单级", [3, 4, 5, 7, 10], 22.0, 0.96, 15.0, 5000.0, 1.3e-5, 1.1),
        ("行星 60 两级", [12, 16, 20, 25, 28, 35, 40, 50, 70, 100], 28.0, 0.92, 22.0, 5000.0, 1.0e-5, 1.2),
        ("行星 90 单级", [3, 4, 5, 7, 10], 60.0, 0.96, 15.0, 5000.0, 5.0e-5, 2.6),
        ("行星 90 两级", [12, 16, 20, 25, 28, 35, 40, 50, 70, 100], 75.0, 0.92, 22.0, 5000.0, 3.5e-5, 2.9),
        ("行星 120 单级", [3, 4, 5, 7, 10], 150.0, 0.96, 15.0, 4000.0, 1.6e-4, 5.6),
        ("行星 120 两级", [12, 16, 20, 25, 28, 35, 40, 50, 70, 100], 190.0, 0.92, 22.0, 4000.0, 1.2e-4, 6.2),
        ("行星 160 单级", [3, 4, 5, 7, 10], 350.0, 0.96, 15.0, 3500.0, 4.5e-4, 12.0),
        ("行星 160 两级", [12, 16, 20, 25, 35, 50, 70, 100], 450.0, 0.92, 22.0, 3500.0, 3.2e-4, 13.5),
    ]
    for model, ratios, tr, eta, bl, nmax, j, w in planetary:
        for rt in ratios:
            add("行星减速机", f"{model} i={rt}", float(rt), tr, eta, bl, nmax, j, w)

    # 谐波减速机（高精度、高减速比、低背隙）
    for rt, tr, j, w in ((50, 30.0, 3.2e-5, 1.4), (80, 45.0, 3.0e-5, 1.5),
                         (100, 55.0, 2.8e-5, 1.6), (120, 60.0, 2.6e-5, 1.7),
                         (160, 75.0, 2.4e-5, 1.8)):
        add("谐波减速机", f"谐波 CSF-20 i={rt}", float(rt), tr, 0.78, 3.0, 6500.0, j, w,
            "高精度分度 / 机器人关节常用")

    # 蜗轮蜗杆（可自锁、低效率、中等背隙）
    for rt in (7.5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100):
        tr = 25.0 if rt <= 20 else 35.0
        add("蜗轮蜗杆减速机", f"NMRV-63 i={rt:g}", float(rt), tr, 0.72, 30.0, 1500.0, 2.0e-5, 4.0,
            "自锁性好、效率低，适合垂直提升保位")

    # 摆线针轮（重载、抗冲击）
    for rt in (11, 17, 23, 29, 35, 43, 59, 87, 121):
        add("摆线针轮减速机", f"RV-40 i={rt}", float(rt), 200.0, 0.85, 1.0, 3000.0, 1.5e-4, 9.0,
            "重载、抗冲击、低背隙")

    # 通用减速机（仅按速比计算，供「不限品牌」时估算）
    for rt in (2, 3, 4, 5, 8, 10, 15, 20, 30, 40, 60, 100):
        add("通用减速机", f"通用减速机 i={rt}", float(rt), 1.0e9, 0.94, 20.0, 5000.0, 0.0, 0.0,
            "仅用于估算：额定转矩按不限处理，选定速比后必须用实际减速机样本复核")
    return out


# --------------------------------------------------------------------------
# 用户库（CSV）
# --------------------------------------------------------------------------
def user_motors_path() -> str:
    return os.path.join(user_data_dir(), "motors_user.csv")


def user_gearboxes_path() -> str:
    return os.path.join(user_data_dir(), "gearboxes_user.csv")


def all_motors() -> List[Motor]:
    motors = builtin_motors()
    motors.extend(load_motors_csv(user_motors_path(), quiet=True))
    return motors


def all_gearboxes() -> List[Gearbox]:
    boxes = builtin_gearboxes()
    boxes.extend(load_gearboxes_csv(user_gearboxes_path(), quiet=True))
    return boxes


def _norm_header(name: str) -> str:
    """把中文表头还原成内部字段名；已经是英文列名则原样返回。

    注意：电机表与减速机表存在同名字段但中文表头不同（例如 rated_torque
    在电机里叫「额定转矩Nm」、在减速机里叫「额定输出转矩Nm」），
    所以两张映射表必须**分别**查找，绝不能合并成一个 dict，
    否则同名键会互相覆盖，导致导入时那几列全部读成 0。
    """
    name = (name or "").strip().lstrip("\ufeff")
    if not name:
        return name
    for table in (MOTOR_HEADER_CN, GEARBOX_HEADER_CN):
        for key, cn in table.items():
            if name == cn:
                return key
    return name


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def load_motors_csv(path: str, quiet: bool = False) -> List[Motor]:
    """从 CSV 读取电机。表头支持英文列名或中文列名。"""
    motors: List[Motor] = []
    if not path or not os.path.isfile(path):
        if not quiet:
            raise FileNotFoundError(f"文件不存在：{path}")
        return motors
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            data: Dict[str, object] = {}
            for k, v in row.items():
                if k is None:
                    continue
                data[_norm_header(k)] = v
            if not str(data.get("model", "")).strip() and not str(data.get("kind", "")).strip():
                continue
            m = Motor(
                kind=str(data.get("kind", "异步电机")).strip() or "异步电机",
                model=str(data.get("model", "")).strip() or "未命名",
                rated_power=_to_float(data.get("rated_power")),
                rated_rpm=_to_float(data.get("rated_rpm")),
                max_rpm=_to_float(data.get("max_rpm")),
                rated_torque=_to_float(data.get("rated_torque")),
                max_torque=_to_float(data.get("max_torque")),
                peak_torque=_to_float(data.get("peak_torque")),
                inertia=_to_float(data.get("inertia")),
                holding_torque=_to_float(data.get("holding_torque")),
                step_angle=_to_float(data.get("step_angle")),
                torque_curve=str(data.get("torque_curve", "") or "").strip(),
                voltage=str(data.get("voltage", "任意") or "任意").strip(),
                encoder=str(data.get("encoder", "") or "").strip(),
                cont_force=_to_float(data.get("cont_force")),
                peak_force=_to_float(data.get("peak_force")),
                mover_mass=_to_float(data.get("mover_mass")),
                max_speed=_to_float(data.get("max_speed")),
                weight=_to_float(data.get("weight")),
                efficiency=_to_float(data.get("efficiency")),
                source="用户导入",
                notes=str(data.get("notes", "") or "").strip(),
            )
            if m.kind not in ("异步电机", "步进电机", "伺服电机", "直流无刷", "直流有刷", "直线电机"):
                m.notes = (m.notes + " ").strip() + f"（原类型={m.kind}，已按异步电机处理）"
                m.kind = "异步电机"
            motors.append(m)
    return motors


def load_gearboxes_csv(path: str, quiet: bool = False) -> List[Gearbox]:
    boxes: List[Gearbox] = []
    if not path or not os.path.isfile(path):
        if not quiet:
            raise FileNotFoundError(f"文件不存在：{path}")
        return boxes
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            data: Dict[str, object] = {}
            for k, v in row.items():
                if k is None:
                    continue
                data[_norm_header(k)] = v
            ratio = _to_float(data.get("ratio"))
            if ratio <= 0:
                continue
            boxes.append(Gearbox(
                kind=str(data.get("kind", "行星减速机")).strip() or "行星减速机",
                model=str(data.get("model", "")).strip() or f"减速机 i={ratio:g}",
                ratio=ratio,
                ratio_min=_to_float(data.get("ratio_min"), ratio),
                ratio_max=_to_float(data.get("ratio_max"), ratio),
                rated_torque=_to_float(data.get("rated_torque")),
                peak_torque=_to_float(data.get("peak_torque")),
                efficiency=_to_float(data.get("efficiency"), 0.94),
                backlash_arcmin=_to_float(data.get("backlash_arcmin")),
                max_input_rpm=_to_float(data.get("max_input_rpm"), 5000.0),
                inertia=_to_float(data.get("inertia")),
                weight=_to_float(data.get("weight")),
                source="用户导入",
                notes=str(data.get("notes", "") or "").strip(),
            ))
    return boxes


def save_motors_csv(path: str, motors: List[Motor]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([MOTOR_HEADER_CN[c] for c in MOTOR_COLUMNS])
        for m in motors:
            writer.writerow([getattr(m, c) for c in MOTOR_COLUMNS])


def save_gearboxes_csv(path: str, boxes: List[Gearbox]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([GEARBOX_HEADER_CN[c] for c in GEARBOX_COLUMNS])
        for g in boxes:
            writer.writerow([getattr(g, c) for c in GEARBOX_COLUMNS])


def export_motor_template(path: str) -> None:
    """导出一份带示例行的电机 CSV 模板。"""
    sample = [
        Motor(kind="伺服电机", model="示例-伺服750W", rated_power=750, rated_rpm=3000,
              max_rpm=6000, rated_torque=2.39, peak_torque=7.16, inertia=8.7e-5,
              voltage="AC220V 单相", encoder="23bit 绝对值", weight=2.0,
              notes="把这一行换成你实际选用的型号参数"),
        Motor(kind="步进电机", model="示例-步进57", rated_power=0, rated_rpm=600,
              max_rpm=1500, rated_torque=1.9, holding_torque=1.9, step_angle=1.8,
              torque_curve="0:1.9,300:1.5,600:1.0,900:0.55,1200:0.3",
              inertia=4.8e-5, voltage="DC24V", weight=1.05,
              notes="矩频曲线格式 转速:转矩，逗号分隔"),
        Motor(kind="直线电机", model="示例-直线电机200N", rated_power=200,
              cont_force=200, peak_force=600, mover_mass=4.5, max_speed=2.5,
              voltage="AC220V 三相", encoder="光栅尺", weight=5.5,
              notes="直线电机只填 连续推力N / 峰值推力N / 动子质量kg / 最高速度ms"),
    ]
    save_motors_csv(path, sample)


def export_gearbox_template(path: str) -> None:
    """导出一份带示例行的减速机 CSV 模板。"""
    sample = [
        Gearbox(kind="行星减速机", model="示例-行星60 i=10", ratio=10, rated_torque=22,
                peak_torque=44, efficiency=0.96, backlash_arcmin=15,
                max_input_rpm=5000, inertia=1.3e-5, weight=1.1,
                notes="把这一行换成你实际选用的减速机参数；每个速比写一行"),
        Gearbox(kind="蜗轮蜗杆减速机", model="示例-NMRV63 i=30", ratio=30, rated_torque=35,
                peak_torque=70, efficiency=0.72, backlash_arcmin=30,
                max_input_rpm=1500, inertia=2.0e-5, weight=4.0,
                notes="效率低的减速机自锁性好，适合垂直提升保位"),
    ]
    save_gearboxes_csv(path, sample)


def import_user_motors(path: str) -> Tuple[int, List[str]]:
    """把 CSV 里的电机追加进用户库，返回 (条数, 错误信息)。"""
    motors = load_motors_csv(path)
    if not motors:
        return 0, ["文件中没有解析到任何电机记录（检查表头与「型号」列是否为空）"]
    existing = load_motors_csv(user_motors_path(), quiet=True)
    known = {(m.kind, m.model) for m in existing}
    added = [m for m in motors if (m.kind, m.model) not in known]
    merged = existing + added
    save_motors_csv(user_motors_path(), merged)
    return len(added), []


def import_user_gearboxes(path: str) -> Tuple[int, List[str]]:
    """把 CSV 里的减速机追加进用户库，返回 (条数, 错误信息)。"""
    boxes = load_gearboxes_csv(path)
    if not boxes:
        return 0, ["文件中没有解析到任何减速机记录（检查表头与「减速比」列是否为空）"]
    existing = load_gearboxes_csv(user_gearboxes_path(), quiet=True)
    known = {(g.kind, g.model) for g in existing}
    added = [g for g in boxes if (g.kind, g.model) not in known]
    merged = existing + added
    save_gearboxes_csv(user_gearboxes_path(), merged)
    return len(added), []


def clear_user_motors() -> None:
    for p in (user_motors_path(), user_gearboxes_path()):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
