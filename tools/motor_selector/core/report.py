# -*- coding: utf-8 -*-
"""报告导出：HTML 计算书 / CSV 选型清单。"""
from __future__ import annotations

import csv
import datetime as _dt
import html
import os
from typing import Iterable, List, Optional, Sequence

from .entities import (
    CASES,
    CheckItem,
    Evaluation,
    LoadCase,
    MOTOR_KINDS,
    Requirement,
    TRANSMISSIONS,
    _fmt,
    fmt_input,
)
from .mechanics import load_inertia
from .selector import summarize

CASE_LABELS = dict(CASES)
TR_LABELS = dict(TRANSMISSIONS)

FIELD_LABELS = [
    ("工况", lambda lc: CASE_LABELS.get(lc.case, lc.case)),
    ("传动方式", lambda lc: TR_LABELS.get(lc.transmission, lc.transmission)),
    ("负载质量", lambda lc: f"{_fmt(lc.mass)} kg"),
    ("皮带/承载件质量", lambda lc: f"{_fmt(lc.belt_mass)} kg"),
    ("配重质量", lambda lc: f"{_fmt(lc.counterweight)} kg"),
    ("摩擦系数 μ", lambda lc: _fmt(lc.mu)),
    ("倾角", lambda lc: f"{_fmt(lc.incline_deg)} °"),
    ("恒定外力", lambda lc: f"{_fmt(lc.ext_force)} N"),
    ("外力矩", lambda lc: f"{_fmt(lc.ext_torque)} N·m"),
    ("轴承摩擦转矩", lambda lc: f"{_fmt(lc.friction_torque)} N·m"),
    ("不平衡重力矩", lambda lc: f"{_fmt(lc.unbalanced_torque)} N·m"),
    ("直线速度", lambda lc: f"{_fmt(lc.speed)} m/s"),
    ("负载转速", lambda lc: f"{_fmt(lc.load_rpm)} rpm"),
    ("加速时间", lambda lc: f"{_fmt(lc.accel_time)} s"),
    ("减速时间", lambda lc: f"{_fmt(lc.decel_time)} s"),
    ("匀速时间", lambda lc: f"{_fmt(lc.const_time)} s"),
    ("停留时间", lambda lc: f"{_fmt(lc.dwell_time)} s"),
    ("行程", lambda lc: f"{_fmt(lc.stroke)} m"),
    ("定位精度", lambda lc: f"{_fmt(lc.positioning_mm)} mm"),
    ("减速比 i", lambda lc: _fmt(lc.ratio)),
    ("传动效率 η", lambda lc: _fmt(lc.efficiency)),
    ("节圆直径", lambda lc: f"{_fmt(lc.pulley_dia)} m"),
    ("每转移动量", lambda lc: f"{_fmt(lc.per_rev_travel)} m/rev"),
    ("丝杆导程", lambda lc: f"{_fmt(lc.screw_lead)} m"),
    ("丝杆直径/长度", lambda lc: f"{_fmt(lc.screw_dia)} / {_fmt(lc.screw_len)} m"),
    ("丝杆效率", lambda lc: _fmt(lc.screw_efficiency)),
    ("负载惯量", lambda lc: f"{_fmt(load_inertia(lc))} kg·m²"),
    ("传动件惯量(负载侧)", lambda lc: f"{_fmt(lc.trans_inertia)} kg·m²"),
    ("联轴器惯量(电机侧)", lambda lc: f"{_fmt(lc.coupling_inertia)} kg·m²"),
    ("最小/最大卷径", lambda lc: f"{_fmt(lc.drum_dia0)} / {_fmt(lc.drum_dia1)} m"),
    ("张力", lambda lc: f"{_fmt(lc.tension)} N"),
    ("卷筒质量/惯量", lambda lc: f"{_fmt(lc.drum_mass)} kg / {_fmt(lc.drum_inertia)} kg·m²"),
    ("电机类型要求", lambda lc: lc.motor_kind_pref),
    ("允许加装减速机", lambda lc: "是" if lc.allow_gearbox else "否"),
    ("转矩安全系数", lambda lc: _fmt(lc.sf_torque)),
    ("功率安全系数", lambda lc: _fmt(lc.sf_power)),
    ("惯量比上限", lambda lc: _fmt(lc.max_inertia_ratio) if lc.max_inertia_ratio > 0 else "按类型默认"),
    ("供电条件", lambda lc: lc.voltage),
]

_CSS = """
body{font-family:"Microsoft YaHei UI","Microsoft YaHei",-apple-system,Segoe UI,sans-serif;
     margin:24px auto;max-width:1180px;color:#1a1a1a;line-height:1.55;padding:0 16px 60px}
h1{font-size:22px;border-bottom:3px solid #2563eb;padding-bottom:8px;margin-bottom:4px}
h2{font-size:16px;margin-top:26px;padding-left:9px;border-left:4px solid #2563eb;color:#1e3a8a}
.sub{color:#666;font-size:13px;margin-bottom:18px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
th,td{border:1px solid #d7dbe2;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#eef2f8;font-weight:600;white-space:nowrap}
tr:nth-child(even) td{background:#fafbfd}
.ok{color:#15803d;font-weight:700}
.bad{color:#b91c1c;font-weight:700}
.warn{color:#b45309;font-weight:700}
.tip{background:#fffbeb;border:1px solid #fcd34d;padding:10px 12px;border-radius:6px;font-size:13px;margin:10px 0}
.err{background:#fef2f2;border:1px solid #fca5a5;padding:10px 12px;border-radius:6px;font-size:13px;margin:10px 0}
.small{font-size:12px;color:#666}
.num{text-align:right;font-variant-numeric:tabular-nums}
"""


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _check_row(c: CheckItem) -> str:
    if not c.mandatory:
        cls, tag = "warn", "提示"
    else:
        cls, tag = ("ok", "通过") if c.ok else ("bad", "不通过")
    margin = "-" if c.required <= 0 else f"{c.margin:.2f}×"
    return (f"<tr><td>{_esc(c.name)}</td>"
            f"<td class='num'>{_esc(c.text_required)}</td>"
            f"<td class='num'>{_esc(c.text_capacity)}</td>"
            f"<td class='num'>{margin}</td>"
            f"<td class='{cls}'>{tag}</td>"
            f"<td class='small'>{_esc(c.note)}</td></tr>")


def _checks_table(checks: Sequence[CheckItem]) -> str:
    if not checks:
        return "<p class='small'>（无校核项）</p>"
    rows = "".join(_check_row(c) for c in checks)
    return ("<table><tr><th>校核项</th><th>需求值</th><th>电机/减速机能力</th>"
            "<th>余量</th><th>结论</th><th>说明</th></tr>" + rows + "</table>")


def _steps_table(steps: Sequence) -> str:
    if not steps:
        return "<p class='small'>（无）</p>"
    rows = "".join(
        f"<tr><td>{_esc(a)}</td><td class='num'>{_esc(b)}</td><td class='small'>{_esc(c)}</td></tr>"
        for a, b, c in steps)
    return "<table><tr><th>项目</th><th>数值</th><th>公式 / 说明</th></tr>" + rows + "</table>"


def _inputs_table(lc: LoadCase) -> str:
    rows = []
    for label, getter in FIELD_LABELS:
        try:
            value = getter(lc)
        except Exception:                                        # noqa: BLE001
            value = "-"
        rows.append(f"<tr><td>{_esc(label)}</td><td>{_esc(value)}</td></tr>")
    body = "".join(rows)
    return "<table><tr><th style='width:230px'>输入参数</th><th>取值</th></tr>" + body + "</table>"


def _evals_table(evals: Sequence[Evaluation], limit: Optional[int] = None) -> str:
    if not evals:
        return "<p class='small'>（没有满足全部校核项的方案，可放宽安全系数、允许加减速机或更换电机类型）</p>"
    rows = []
    for idx, ev in enumerate(evals[:limit] if limit else evals, start=1):
        cls = "ok" if ev.feasible else "bad"
        rows.append(
            f"<tr><td class='num'>{idx}</td><td>{_esc(ev.motor.kind)}</td>"
            f"<td>{_esc(ev.train_label)}</td>"
            f"<td class='num'>{_fmt(ev.ratio)}</td>"
            f"<td class='num'>{_fmt(ev.n_motor)}</td>"
            f"<td class='num'>{_fmt(ev.T_peak)}</td>"
            f"<td class='num'>{_fmt(ev.T_rms)}</td>"
            f"<td class='num'>{_fmt(ev.P_req)}</td>"
            f"<td class='num'>{_fmt(ev.inertia_ratio)}</td>"
            f"<td class='num'>{_fmt(ev.score)}</td>"
            f"<td class='{cls}'>{_esc(summarize(ev))}</td></tr>"
        )
    return ("<table><tr><th>#</th><th>类型</th><th>电机 + 减速机</th><th>减速比 i</th>"
            "<th>转速 rpm</th><th>峰值转矩 N·m</th><th>有效转矩 N·m</th><th>需求功率 W</th>"
            "<th>惯量比</th><th>匹配度</th><th>结论</th></tr>" + "".join(rows) + "</table>")


def build_html(lc: LoadCase, req: Requirement,
               evaluations: Sequence[Evaluation] = (),
               manual_ev: Optional[Evaluation] = None,
               title: str = "电机选型计算书") -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts: List[str] = []
    parts.append(f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
                 f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>")
    parts.append(f"<h1>{_esc(title)}</h1>")
    parts.append(f"<div class='sub'>方案：{_esc(lc.name)} ｜ 生成时间：{now} ｜ "
                 f"工况：{_esc(lc.case_label)} ｜ 传动：{_esc(lc.transmission_label)}</div>")

    if req.errors:
        parts.append("<div class='err'><b>输入有误，无法计算：</b><br>"
                     + "<br>".join(_esc(e) for e in req.errors) + "</div>")

    parts.append("<h2>一、输入参数</h2>")
    parts.append(_inputs_table(lc))

    parts.append("<h2>二、需求计算过程</h2>")
    parts.append(_steps_table(req.steps))

    if req.warnings:
        parts.append("<div class='tip'><b>工程提示：</b><br>"
                     + "<br>".join("· " + _esc(w) for w in req.warnings) + "</div>")

    parts.append("<h2>三、需求汇总（电机轴）</h2>")
    parts.append(
        "<table><tr><th>项目</th><th>数值</th></tr>"
        f"<tr><td>需求转速</td><td class='num'>{_fmt(req.n_motor)} rpm</td></tr>"
        f"<tr><td>需求峰值转矩</td><td class='num'>{_fmt(req.T_peak_motor)} N·m</td></tr>"
        f"<tr><td>需求有效(RMS)转矩</td><td class='num'>{_fmt(req.T_rms_motor())} N·m</td></tr>"
        f"<tr><td>折算负载惯量</td><td class='num'>{_fmt(req.J_reflected)} kg·m²</td></tr>"
        f"<tr><td>峰值功率</td><td class='num'>{_fmt(req.P_peak)} W</td></tr>"
        f"<tr><td>建议功率(含安全系数)</td><td class='num'>{_fmt(req.P_req)} W</td></tr>"
        "</table>")

    if manual_ev is not None:
        parts.append("<h2>四、手动输入电机校核</h2>")
        m = manual_ev.motor
        parts.append(
            "<table><tr><th>项目</th><th>取值</th></tr>"
            f"<tr><td>类型</td><td>{_esc(m.kind)}</td></tr>"
            f"<tr><td>额定功率</td><td class='num'>{_fmt(m.rated_power)} W</td></tr>"
            f"<tr><td>额定转速</td><td class='num'>{_fmt(m.rated_rpm)} rpm</td></tr>"
            f"<tr><td>额定转矩</td><td class='num'>{_fmt(m.rated_torque)} N·m</td></tr>"
            f"<tr><td>峰值/最大转矩</td><td class='num'>{_fmt(m.torque_at(manual_ev.n_motor))} N·m</td></tr>"
            f"<tr><td>转子惯量</td><td class='num'>{_fmt(m.inertia)} kg·m²</td></tr>"
            "</table>")
        parts.append(_checks_table(manual_ev.checks))
        if manual_ev.warnings:
            parts.append("<div class='tip'><b>提示：</b><br>"
                         + "<br>".join("· " + _esc(w) for w in manual_ev.warnings) + "</div>")

    parts.append("<h2>五、自动选型推荐</h2>")
    parts.append(_evals_table(evaluations))
    if evaluations:
        parts.append("<h2>六、推荐方案校核明细（第 1 名）</h2>")
        parts.append(_checks_table(evaluations[0].checks))
        if evaluations[0].warnings:
            parts.append("<div class='tip'><b>提示：</b><br>"
                         + "<br>".join("· " + _esc(w) for w in evaluations[0].warnings) + "</div>")
        parts.append("<h2>七、备选方案校核明细（第 2~3 名）</h2>")
        for ev in evaluations[1:3]:
            parts.append(f"<h3 style='font-size:14px;margin:16px 0 4px'>{_esc(ev.train_label)}"
                         f"　（匹配度 {_fmt(ev.score)}）</h3>")
            parts.append(_checks_table(ev.checks))

    parts.append(
        "<div class='tip'><b>免责说明：</b>内置型号库为按行业常见规格整理的<strong>典型参数</strong>，"
        "仅用于方案阶段估算与量级校核；正式设计、下单前请导入厂家样本数据（CSV）复核，"
        "并确认电机的过载能力、散热条件、驱动电压、安装尺寸与成本。<br>"
        "关键校核项：峰值转矩 / 有效(RMS)转矩 / 最高转速 / 惯量比 / 功率 / 减速机输出转矩。</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_html(path: str, html_text: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    return path


def write_evals_csv(path: str, evaluations: Iterable[Evaluation]) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["排名", "电机类型", "电机型号", "减速机", "减速比", "需求转速rpm",
                         "峰值转矩Nm", "有效转矩Nm", "需求功率W", "惯量比", "匹配度", "结论",
                         "未通过项", "备注"])
        for idx, ev in enumerate(evaluations, start=1):
            writer.writerow([
                idx, ev.motor.kind, ev.motor.model,
                ev.gearbox.model if ev.gearbox else ("通用减速机" if ev.ratio != 1 else "直驱"),
                fmt_input(ev.ratio), fmt_input(ev.n_motor), fmt_input(ev.T_peak),
                fmt_input(ev.T_rms), fmt_input(ev.P_req), fmt_input(ev.inertia_ratio),
                fmt_input(ev.score),
                summarize(ev), "、".join(ev.failed_names),
                " / ".join(ev.warnings[:2]),
            ])
    return path
