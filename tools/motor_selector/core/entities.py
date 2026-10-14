# -*- coding: utf-8 -*-
"""数据实体与常量定义。

单位约定（全部 SI，角度用度、转速用 rpm 的地方会显式标注）：
    质量 kg        长度 m        时间 s        力 N
    转矩 N·m       功率 W        角速度 rad/s  角加速度 rad/s^2
    惯量 kg·m^2    转速 rpm      角度 °
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

G = 9.80665  # 标准重力加速度 m/s^2

# --------------------------------------------------------------------------
# 枚举 / 标签
# --------------------------------------------------------------------------
# 工况（运动形式 + 受力形式）
CASES: List[Tuple[str, str]] = [
    ("horizontal", "水平直线运动（滑台/小车/齿条）"),
    ("incline", "倾斜面运动（可设倾角）"),
    ("vertical_lift", "垂直提升 / 升降"),
    ("vertical_press", "垂直下压 / 压装 / 压制"),
    ("conveyor", "皮带 / 链板输送机"),
    ("rotary_shaft", "旋转轴（水平轴 / 辊筒 / 主轴）"),
    ("rotary_table", "分度盘 / 转台（垂直轴）"),
    ("winding", "卷绕 / 放卷（卷径变化）"),
]
CASE_LABELS = dict(CASES)

# 运动形式
LINEAR_CASES = {"horizontal", "incline", "vertical_lift", "vertical_press", "conveyor"}
ROTARY_CASES = {"rotary_shaft", "rotary_table"}

# 传动形式
TRANSMISSIONS: List[Tuple[str, str]] = [
    ("direct", "直接驱动（联轴器直连）"),
    ("gearbox", "减速机输出轴直连"),
    ("belt", "同步带 / 皮带轮"),
    ("chain", "链轮 / 链条"),
    ("rack", "齿轮齿条"),
    ("screw_ball", "滚珠丝杆"),
    ("screw_trap", "梯形丝杆（滑动丝杆）"),
    ("drum", "卷筒 / 钢丝绳卷扬"),
]
TRANSMISSION_LABELS = dict(TRANSMISSIONS)
LINEAR_TRANSMISSIONS = {"belt", "chain", "rack", "screw_ball", "screw_trap", "drum"}

# 传动效率建议值（仅用于界面提示）
EFFICIENCY_HINT = {
    "direct": "0.98 ~ 0.99",
    "gearbox": "0.90 ~ 0.97（见减速机参数）",
    "belt": "0.92 ~ 0.98",
    "chain": "0.85 ~ 0.95",
    "rack": "0.90 ~ 0.95",
    "screw_ball": "0.85 ~ 0.95",
    "screw_trap": "0.30 ~ 0.50",
    "drum": "0.94 ~ 0.98",
}

# 电机类型
MOTOR_KINDS: List[str] = [
    "异步电机",
    "步进电机",
    "伺服电机",
    "直流无刷",
    "直流有刷",
    "直线电机",
]

# 供电 / 电压
VOLTAGES: List[str] = [
    "任意",
    "AC380V 三相",
    "AC220V 单相",
    "AC220V 三相",
    "DC48V",
    "DC24V",
    "DC12V",
]

# 惯量计算形状
INERTIA_SHAPES: List[Tuple[str, str]] = [
    ("manual", "直接输入惯量值"),
    ("solid_cylinder", "实心圆柱（绕中心轴）J = m·r²/2"),
    ("ring", "空心圆柱 / 圆环（绕中心轴）J = m(r₁²+r₂²)/2"),
    ("box", "长方体（绕垂直中心轴）J = m(a²+b²)/12"),
    ("rod_end", "细长杆（绕端部）J = m·l²/3"),
    ("sphere", "实心球（绕直径）J = 2m·r²/5"),
]

# 自动选型用的备选减速比（通用减速机速比序列）
GENERIC_RATIOS: List[float] = [
    1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
    12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 80.0, 100.0,
]

# 电机类型 -> 默认惯量比上限（折算到电机轴的负载惯量 / 电机转子惯量）
DEFAULT_INERTIA_RATIO_LIMIT = {
    "伺服电机": 10.0,
    "步进电机": 5.0,
    "直流无刷": 10.0,
    "直流有刷": 20.0,
    "异步电机": 100.0,
    "直线电机": 30.0,
}

# 电机类型 -> 默认过载（峰值/额定）倍数
DEFAULT_OVERLOAD = {
    "伺服电机": 3.0,
    "步进电机": 1.0,   # 步进的"峰值"即矩频曲线上的动态转矩
    "异步电机": 2.2,   # 最大转矩倍数
    "直流无刷": 2.5,
    "直流有刷": 3.0,
    "直线电机": 3.0,
}


# --------------------------------------------------------------------------
# 输入：工况参数
# --------------------------------------------------------------------------
@dataclass
class LoadCase:
    """一次选型计算的全部输入参数。"""

    name: str = "方案1"

    # ---- 工况与负载 ----
    case: str = "horizontal"           # 见 CASES
    mass: float = 50.0                 # kg   负载（运动）质量，直线工况
    belt_mass: float = 0.0             # kg   皮带 / 链条 / 承载件质量（输送机用）
    counterweight: float = 0.0         # kg   配重质量（垂直提升用）
    mu: float = 0.10                   # -    导轨/支撑摩擦系数
    incline_deg: float = 0.0           # °    倾角
    ext_force: float = 0.0             # N    恒定的外部阻力（切削力、张力、弹簧力等）
    ext_torque: float = 0.0            # N·m  外部阻力矩（旋转工况）
    friction_torque: float = 0.0       # N·m  轴承/密封摩擦转矩（旋转工况）
    unbalanced_torque: float = 0.0     # N·m  不平衡重力矩（偏心转台）

    # ---- 运动与时间 ----
    speed: float = 0.5                 # m/s  直线运动速度
    load_rpm: float = 60.0             # rpm  旋转工况的负载转速
    accel_time: float = 0.10           # s    加速时间
    decel_time: float = 0.10           # s    减速时间
    const_time: float = 0.50           # s    匀速运行时间
    dwell_time: float = 0.50           # s    停留（停止）时间
    stroke: float = 0.50               # m    单程行程（用于计算行程时间与校核）
    positioning_mm: float = 0.05       # mm   定位精度要求
    starts_per_hour: float = 0.0       # 次/h 频繁启停次数；0 = 按时序自动推算

    # ---- 传动 ----
    transmission: str = "belt"         # 见 TRANSMISSIONS
    ratio: float = 1.0                 # -    减速比 i = 电机转速 / 负载转速
    efficiency: float = 0.80           # -    传动机构（不含减速机）效率
    pulley_dia: float = 0.0            # m    带轮/齿轮/链轮 节圆直径；0 = 使用每转移动量
    per_rev_travel: float = 0.05       # m/rev 负载轴每转的直线移动量
    screw_lead: float = 0.010          # m    丝杆导程
    screw_dia: float = 0.016           # m    丝杆公称直径（算丝杆自身惯量用）
    screw_len: float = 0.500           # m    丝杆长度
    screw_efficiency: float = 0.90     # -    丝杆效率
    screw_density: float = 7850.0      # kg/m^3 丝杆材料密度（钢）
    trans_inertia: float = 0.0         # kg·m² 负载侧传动件惯量（带轮/齿轮/丝杆），0=自动估算
    coupling_inertia: float = 0.0      # kg·m² 电机侧惯量（联轴器/制动器）

    # ---- 旋转负载惯量 ----
    inertia_mode: str = "manual"       # 见 INERTIA_SHAPES
    load_inertia: float = 0.0          # kg·m² 负载惯量（manual 模式直接使用）
    in_mass: float = 0.0               # kg    惯量计算用质量
    in_r1: float = 0.0                 # m     内半径
    in_r2: float = 0.0                 # m     外半径
    in_a: float = 0.0                  # m     边长 a
    in_b: float = 0.0                  # m     边长 b
    in_l: float = 0.0                  # m     长度

    # ---- 卷绕 / 放卷 ----
    drum_dia0: float = 0.10            # m   最小卷径（芯轴直径）
    drum_dia1: float = 0.40            # m   最大卷径
    tension: float = 50.0              # N   张力
    drum_mass: float = 5.0             # kg  卷筒质量
    drum_inertia: float = 0.0          # kg·m² 卷筒自身惯量（0=按实心圆柱估算）

    # ---- 选型要求 ----
    motor_kind_pref: str = "任意"       # 见 MOTOR_KINDS，或 "任意"
    allow_gearbox: bool = True         # 是否允许加装减速机
    sf_torque: float = 1.50            # 转矩安全系数（校核时对需求转矩放大）
    sf_power: float = 1.20             # 功率安全系数
    max_inertia_ratio: float = 0.0     # 惯量比上限；0 = 按电机类型默认值
    voltage: str = "任意"              # 供电条件
    max_motor_power: float = 0.0       # W  允许的最大电机功率（0=不限）
    max_motor_frame: str = ""          # 机座号限制（备注用）

    # ---- 手动校核（复刻 Excel 表格的用法） ----
    manual_kind: str = "异步电机"
    manual_power: float = 750.0        # W
    manual_rpm: float = 1450.0         # rpm
    manual_torque: float = 3.0         # N·m  额定转矩
    manual_peak_torque: float = 0.0    # N·m  峰值/最大转矩（0 = 按类型默认倍数）
    manual_inertia: float = 0.0005     # kg·m² 转子惯量
    manual_max_rpm: float = 0.0        # rpm  最高转速（0 = 默认）

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoadCase":
        valid = {f.name for f in fields(cls)}
        clean: Dict[str, Any] = {}
        for k, v in (data or {}).items():
            if k not in valid:
                continue
            ref = getattr(cls(), k)
            try:
                if isinstance(ref, bool):
                    clean[k] = bool(v)
                elif isinstance(ref, float) and not isinstance(ref, bool):
                    clean[k] = float(v)
                elif isinstance(ref, int) and not isinstance(ref, bool):
                    clean[k] = int(float(v))
                else:
                    clean[k] = str(v)
            except (TypeError, ValueError):
                continue
        return cls(**clean)

    def copy(self) -> "LoadCase":
        return LoadCase.from_dict(self.to_dict())

    # ---- 便捷属性 ----
    @property
    def is_linear(self) -> bool:
        return self.case in LINEAR_CASES

    @property
    def is_rotary(self) -> bool:
        return self.case in ROTARY_CASES

    @property
    def case_label(self) -> str:
        return CASE_LABELS.get(self.case, self.case)

    @property
    def transmission_label(self) -> str:
        return TRANSMISSION_LABELS.get(self.transmission, self.transmission)

    def travel_per_rev(self) -> float:
        """负载轴每转对应的直线移动量 L (m/rev)。"""
        t = self.transmission
        if t in ("screw_ball", "screw_trap"):
            return self.screw_lead if self.screw_lead > 0 else self.per_rev_travel
        if t in ("belt", "chain", "rack", "drum"):
            if self.pulley_dia > 0:
                return math.pi * self.pulley_dia
            if t == "drum" and self.drum_dia0 > 0:
                return math.pi * self.drum_dia0
            return self.per_rev_travel
        return self.per_rev_travel


# --------------------------------------------------------------------------
# 电机 / 减速机
# --------------------------------------------------------------------------
@dataclass
class Motor:
    """电机型号参数（库中一条记录，或用户手动输入的一条）。"""

    kind: str = "异步电机"
    model: str = "手动输入"
    rated_power: float = 750.0          # W      额定功率
    rated_rpm: float = 1450.0           # rpm    额定转速
    max_rpm: float = 0.0                # rpm    最高转速（0=按类型默认）
    rated_torque: float = 3.0           # N·m    额定（连续）转矩
    max_torque: float = 0.0             # N·m    最大转矩（异步）/ 峰值转矩（伺服）
    peak_torque: float = 0.0            # N·m    峰值转矩（可与 max_torque 二选一）
    inertia: float = 0.0005             # kg·m²  转子惯量
    holding_torque: float = 0.0         # N·m    步进保持转矩
    step_angle: float = 0.0             # °      步距角
    torque_curve: str = ""              # 步进矩频曲线 "rpm:torque,rpm:torque"
    voltage: str = "任意"
    encoder: str = ""                   # 编码器分辨率/类型
    cont_force: float = 0.0             # N      直线电机连续推力
    peak_force: float = 0.0             # N      直线电机峰值推力
    mover_mass: float = 0.0             # kg     直线电机动子质量
    max_speed: float = 0.0              # m/s    直线电机最大速度
    weight: float = 0.0                 # kg     重量
    efficiency: float = 0.0             # -      电机效率（异步/直流）
    source: str = "内置库"
    notes: str = ""

    # ------------------------------------------------------------------
    @property
    def kind_label(self) -> str:
        return self.kind

    @property
    def display(self) -> str:
        return f"[{self.kind}] {self.model}"

    def torque_at(self, rpm: float) -> float:
        """该转速下电机可持续输出的最大转矩（已计入过载能力）。

        异步/直流：最大转矩（或额定×过载倍数）
        伺服：峰值转矩
        步进：矩频曲线插值（曲线即动态可用转矩）
        直线电机：不适用，返回 0
        """
        rpm = abs(float(rpm))
        if self.kind == "直线电机":
            return 0.0
        if self.kind == "步进电机" and self.torque_curve.strip():
            return _interp_curve(self.torque_curve, rpm)
        if self.kind == "伺服电机":
            t = self.peak_torque or self.max_torque
            if t <= 0:
                t = self.rated_torque * DEFAULT_OVERLOAD["伺服电机"]
            return t
        if self.kind == "异步电机":
            return self.max_torque or self.rated_torque * DEFAULT_OVERLOAD["异步电机"]
        t = self.peak_torque or self.max_torque
        return t if t > 0 else self.rated_torque * DEFAULT_OVERLOAD.get(self.kind, 2.0)

    def speed_limit(self) -> float:
        """允许的最高工作转速 (rpm)。"""
        if self.max_rpm > 0:
            return self.max_rpm
        if self.kind == "伺服电机":
            return max(self.rated_rpm * 1.5, 3000.0)
        if self.kind == "步进电机":
            pts = _parse_curve(self.torque_curve)
            if pts:
                return pts[-1][0]
            return self.rated_rpm
        if self.kind == "异步电机":
            return self.rated_rpm  # 额定转速以上为恒功率区，按额定点设计
        return self.rated_rpm

    def continuous_torque(self) -> float:
        """连续（长期允许）输出转矩。"""
        if self.kind == "步进电机":
            return self.holding_torque or self.rated_torque
        return self.rated_torque

    def overload_factor(self) -> float:
        if self.kind == "步进电机":
            return 1.0
        cap = self.peak_torque or self.max_torque
        if cap > 0 and self.rated_torque > 0:
            return cap / self.rated_torque
        return DEFAULT_OVERLOAD.get(self.kind, 2.0)

    def inertia_ratio_limit(self) -> float:
        return DEFAULT_INERTIA_RATIO_LIMIT.get(self.kind, 10.0)


@dataclass
class Gearbox:
    """减速机型号参数。"""

    kind: str = "行星减速机"
    model: str = "手动输入"
    ratio: float = 10.0                 # 标称减速比
    ratio_min: float = 0.0
    ratio_max: float = 0.0
    rated_torque: float = 25.0          # N·m 额定输出转矩
    peak_torque: float = 0.0            # N·m 峰值输出转矩（0=2×额定）
    efficiency: float = 0.94
    backlash_arcmin: float = 15.0       # arcmin 背隙
    max_input_rpm: float = 5000.0
    inertia: float = 0.000013           # kg·m² 折算到输入轴的惯量
    weight: float = 1.2
    source: str = "内置库"
    notes: str = ""

    @property
    def display(self) -> str:
        return f"{self.model} (i={self.ratio:g})"

    @property
    def torque_unlimited(self) -> bool:
        """是否为「通用减速机」这类只做速比占位、不校核转矩的条目。"""
        return self.rated_torque >= 1.0e8

    def torque_text(self, peak: bool = False) -> str:
        """转矩显示文本：占位条目显示「不限」，避免出现 1e+09。"""
        if self.torque_unlimited:
            return "不限"
        value = self.peak_limit() if peak else self.rated_torque
        return _fmt(value)

    def peak_limit(self) -> float:
        return self.peak_torque if self.peak_torque > 0 else self.rated_torque * 2.0


# --------------------------------------------------------------------------
# 计算结果
# --------------------------------------------------------------------------
@dataclass
class Requirement:
    """由工况参数算出的「需求」（尚未针对具体电机）。"""

    case: str = ""
    transmission: str = ""
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    steps: List[Tuple[str, str, str]] = field(default_factory=list)  # (项目, 数值, 公式/说明)

    is_linear: bool = True
    travel_per_rev: float = 0.0      # m/rev

    # 运动学（负载侧）
    v: float = 0.0                   # m/s
    a: float = 0.0                   # m/s^2
    n_load: float = 0.0              # rpm
    alpha_load: float = 0.0          # rad/s^2
    ratio: float = 1.0
    n_motor: float = 0.0             # rpm
    alpha_motor: float = 0.0         # rad/s^2
    omega_motor: float = 0.0         # rad/s

    # 力（直线工况，负载侧）
    F_fric: float = 0.0
    F_grav: float = 0.0
    F_ext: float = 0.0
    F_resist: float = 0.0            # 稳态阻力（沿运动方向为正 = 阻力）
    F_accel: float = 0.0
    F_peak: float = 0.0

    # 转矩（负载侧）
    T_load_side: float = 0.0         # 稳态负载转矩
    T_peak_side: float = 0.0         # 峰值负载转矩（含加速）
    T_grav_side: float = 0.0         # 重力分量折算转矩

    # 惯量
    J_linear: float = 0.0            # 直线运动质量折算惯量（负载侧）
    J_load_side: float = 0.0         # 负载侧总惯量
    J_trans_side: float = 0.0        # 传动件惯量（负载侧）
    J_reflected: float = 0.0         # 折算到电机轴（不含电机自身）
    J_coupling: float = 0.0          # 电机侧附加惯量
    m_moving: float = 0.0            # 直线运动总质量（含动子）

    # 折算到电机轴
    T_load_motor: float = 0.0
    T_accel_motor: float = 0.0
    T_peak_motor: float = 0.0
    T_dec_motor: float = 0.0

    # 功率
    P_steady: float = 0.0            # W
    P_peak: float = 0.0              # W
    P_req: float = 0.0               # W 含安全系数

    # 时序
    t_accel: float = 0.0
    t_const: float = 0.0
    t_decel: float = 0.0
    t_dwell: float = 0.0
    cycle_time: float = 0.0
    starts_per_hour: float = 0.0
    duty: float = 0.0                # % 运行占空比

    # 卷绕双工况：(说明, 电机转速rpm, 电机侧转矩N·m)
    extra_points: List[Tuple[str, float, float]] = field(default_factory=list)

    def add(self, name: str, value: Any, formula: str = "") -> None:
        self.steps.append((name, _fmt(value), formula))

    def limits(self) -> Tuple[float, float, float]:
        """返回选型/校核用：(需求转速 rpm, 需求峰值转矩 N·m(电机侧), 有效转矩 N·m(电机侧))"""
        return self.n_motor, self.T_peak_motor, self.T_rms_motor()

    def T_rms_motor(self, J_motor: float = 0.0) -> float:
        """含电机转子惯量后的一个周期有效值（RMS）转矩（电机侧）。

        按「加速段 / 匀速段 / 减速段 / 停留段」四段工时加权，停留段转矩为 0，
        即断续工作制（S3）下的等效发热转矩 —— 这是伺服 / 步进热校核的标准做法。
        """
        return self.T_rms_detail(J_motor)[1]

    def T_rms_detail(self, J_motor: float = 0.0) -> Tuple[float, float]:
        """返回 (仅工作段 RMS, 含停留段整周期 RMS)。"""
        alpha = self.alpha_motor
        J_ref = self.J_reflected + self.J_coupling + max(J_motor, 0.0)
        T_load = abs(self.T_load_motor)
        T_acc = J_ref * abs(alpha)
        t_a, t_c, t_d, t_w = self.t_accel, self.t_const, self.t_decel, self.t_dwell
        if t_a + t_c + t_d <= 0:
            return T_load, T_load
        T1 = T_load + T_acc
        T2 = T_load
        T3 = abs(T_acc - T_load)
        num = T1 ** 2 * t_a + T2 ** 2 * t_c + T3 ** 2 * t_d
        t_work = t_a + t_c + t_d
        rms_work = math.sqrt(num / t_work)
        rms_cycle = math.sqrt(num / (t_work + t_w)) if t_w > 0 else rms_work
        return rms_work, rms_cycle


@dataclass
class CheckItem:
    """一条校核项。"""

    name: str
    required: float
    capacity: float
    unit: str = ""
    ok: bool = True
    note: str = ""
    mandatory: bool = True     # False = 提示性校核（不影响可行性）
    capacity_text: str = ""    # 非空时用它替代能力值的显示（例如「不限」）

    @property
    def margin(self) -> float:
        if self.required <= 0:
            return float("inf") if self.capacity > 0 else 0.0
        return self.capacity / self.required

    @property
    def text_required(self) -> str:
        return f"{_fmt(self.required)} {self.unit}".strip()

    @property
    def text_capacity(self) -> str:
        if self.capacity_text:
            return self.capacity_text
        return f"{_fmt(self.capacity)} {self.unit}".strip()

    @property
    def text_result(self) -> str:
        if not self.mandatory:
            return "提示"
        return "通过" if self.ok else "不通过"


@dataclass
class Evaluation:
    """某个电机（可含减速机）针对某需求的完整校核结果。"""

    motor: Motor
    gearbox: Optional[Gearbox] = None
    ratio: float = 1.0
    efficiency: float = 0.8
    feasible: bool = False
    score: float = 0.0
    n_motor: float = 0.0            # rpm
    T_load: float = 0.0             # N·m
    T_peak: float = 0.0             # N·m
    T_rms: float = 0.0              # N·m
    P_req: float = 0.0              # W
    J_reflected: float = 0.0        # kg·m²
    inertia_ratio: float = 0.0
    checks: List[CheckItem] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def train_label(self) -> str:
        if self.gearbox is not None:
            return f"{self.motor.model} + {self.gearbox.model}"
        if abs(self.ratio - 1.0) > 1e-9:
            return f"{self.motor.model} + 通用减速机 i={self.ratio:g}"
        return f"{self.motor.model}（直驱）"

    @property
    def failed_names(self) -> List[str]:
        return [c.name for c in self.checks if c.mandatory and not c.ok]


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def _strip(text: str) -> str:
    """去掉小数末尾多余的 0 与小数点。"""
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fmt(value: Any, nd: int = 4) -> str:
    """数值美化输出（给表格、计算书看）。

    原则：**不出现科学计数法**，除非数量级确实极端（≥1e12 或 <1e-7）。
    注意：这个函数会加千分位逗号，**界面输入框回填请用 fmt_input()**，
    否则 "1,450" 被读回时会解析失败。
    """
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v != v or v in (float("inf"), float("-inf")):   # NaN / inf
        return "-"
    av = abs(v)
    if av == 0:
        return "0"
    if av >= 1e12 or av < 1e-7:
        return f"{v:.4e}"
    if av >= 1e6:
        return f"{v:,.0f}"
    if av >= 1000:
        return _strip(f"{v:,.2f}")
    if av >= 100:
        return _strip(f"{v:.2f}")
    if av >= 1:
        return _strip(f"{v:.{max(nd, 1)}f}")
    digits = min(12, max(6, int(-math.log10(av)) + 4))
    return _strip(f"{v:.{digits}f}")


def fmt_input(value: Any) -> str:
    """输入框回填用：无千分位、无科学计数法，能被 float() 原样读回。"""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        return value
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if v != v:
        return "0"
    if abs(v - round(v)) < 1e-12 and abs(v) < 1e15:
        return str(int(round(v)))
    if abs(v) >= 1:
        return _strip(f"{v:.6f}")
    return _strip(f"{v:.10f}")


def _parse_curve(text: str) -> List[Tuple[float, float]]:
    """解析矩频曲线 "0:1.8,300:1.2,600:0.6" -> [(0,1.8),(300,1.2),(600,0.6)]"""
    pts: List[Tuple[float, float]] = []
    if not text:
        return pts
    for chunk in str(text).replace("；", ",").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        for sep in (":", "："):
            if sep in chunk:
                a, _, b = chunk.partition(sep)
                try:
                    pts.append((float(a), float(b)))
                except ValueError:
                    pass
                break
    pts.sort(key=lambda p: p[0])
    return pts


def _interp_curve(text: str, rpm: float) -> float:
    """矩频曲线线性插值。"""
    pts = _parse_curve(text)
    if not pts:
        return 0.0
    if rpm <= pts[0][0]:
        return pts[0][1]
    if rpm >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= rpm <= x1:
            if x1 - x0 < 1e-9:
                return min(y0, y1)
            k = (rpm - x0) / (x1 - x0)
            return y0 + (y1 - y0) * k
    return pts[-1][1]
