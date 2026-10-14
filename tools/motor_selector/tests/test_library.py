# -*- coding: utf-8 -*-
"""型号库导入/导出自测：验证「加自己的电机、减速机数据」这条链路。

会临时备份并还原 userdata 里的用户库文件，不会弄丢你已导入的数据。

运行： python tests\test_library.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import LoadCase                                          # noqa: E402
from core.database import (                                        # noqa: E402
    all_gearboxes, all_motors, clear_user_motors, export_gearbox_template,
    export_motor_template, import_user_gearboxes, import_user_motors,
    load_gearboxes_csv, load_motors_csv, user_gearboxes_path, user_motors_path,
)
from core.mechanics import compute                                 # noqa: E402
from core.selector import auto_select                              # noqa: E402

FAILS = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'OK  ' if cond else 'FAIL'}] {name} {extra}")
    if not cond:
        FAILS.append(name)


def main() -> int:
    n_motor_before = len(all_motors())
    n_box_before = len(all_gearboxes())
    print(f"内置+用户库现状：电机 {n_motor_before} 台，减速机 {n_box_before} 台\n")

    # 备份已有用户库
    backup = {}
    for path in (user_motors_path(), user_gearboxes_path()):
        if os.path.isfile(path):
            dst = path + ".bak_test"
            shutil.copy2(path, dst)
            backup[path] = dst

    tmp = tempfile.mkdtemp(prefix="motorsel_")
    try:
        # ---- 1. 导出模板 ----
        m_tpl = os.path.join(tmp, "电机模板.csv")
        g_tpl = os.path.join(tmp, "减速机模板.csv")
        export_motor_template(m_tpl)
        export_gearbox_template(g_tpl)
        check("导出电机模板", os.path.getsize(m_tpl) > 100)
        check("导出减速机模板", os.path.getsize(g_tpl) > 100)

        # ---- 2. 模板能被自己读回来（中英文表头都认） ----
        tpl_motors = load_motors_csv(m_tpl)
        tpl_boxes = load_gearboxes_csv(g_tpl)
        check("模板可回读·电机", len(tpl_motors) == 3, f"{len(tpl_motors)} 条")
        check("模板可回读·减速机", len(tpl_boxes) == 2, f"{len(tpl_boxes)} 条")
        check("模板字段正确·伺服峰值转矩", abs(tpl_motors[0].peak_torque - 7.16) < 1e-9)
        check("模板字段正确·矩频曲线", ":" in tpl_motors[1].torque_curve)

        # ---- 3. 模拟用户自带的一台电机 + 一台减速机（英文表头） ----
        my_motor = os.path.join(tmp, "my_motor.csv")
        with open(my_motor, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("kind,model,rated_power,rated_rpm,rated_torque,peak_torque,inertia,"
                     "voltage,encoder,notes\n")
            fh.write("伺服电机,MDMF302L1H8-我的电机,3000,3000,9.55,28.65,5.9e-4,"
                     "AC220V 三相,23bit,测试用\n")
        my_box = os.path.join(tmp, "my_box.csv")
        with open(my_box, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("类型,型号,减速比,额定输出转矩Nm,峰值输出转矩Nm,效率,背隙arcmin,"
                     "允许输入转速rpm,输入轴惯量kgm2,重量kg,备注\n")
            fh.write("行星减速机,我的减速机 i=25,25,120,240,0.94,8,4000,2.2e-4,7.5,测试用\n")

        added_m, err_m = import_user_motors(my_motor)
        added_g, err_g = import_user_gearboxes(my_box)
        check("导入用户电机", added_m == 1, f"新增 {added_m} 条 {err_m}")
        check("导入用户减速机", added_g == 1, f"新增 {added_g} 条 {err_g}")

        # ---- 4. 重复导入应去重 ----
        again_m, _ = import_user_motors(my_motor)
        again_g, _ = import_user_gearboxes(my_box)
        check("重复导入自动去重·电机", again_m == 0)
        check("重复导入自动去重·减速机", again_g == 0)

        # ---- 5. 合并后的库能被选型引擎用到 ----
        motors = all_motors()
        boxes = all_gearboxes()
        check("总电机数 +1", len(motors) == n_motor_before + 1,
              f"{n_motor_before} -> {len(motors)}")
        check("总减速机数 +1", len(boxes) == n_box_before + 1,
              f"{n_box_before} -> {len(boxes)}")
        my_kind = [m for m in motors if m.model == "MDMF302L1H8-我的电机"]
        check("用户电机在库中且来源标记为「用户导入」",
              bool(my_kind) and my_kind[0].source == "用户导入")
        my_g = [g for g in boxes if g.model == "我的减速机 i=25"]
        check("用户减速机在库中", bool(my_g), f"i={my_g[0].ratio:g}" if my_g else "")

        # ---- 6. 端到端：把导入的电机 / 减速机真正拿去校核与选型 ----
        from core.selector import evaluate
        user_motor = my_kind[0] if my_kind else None
        user_box = my_g[0] if my_g else None

        # 6a. 直接用「导入的电机 + 导入的减速机」做一次校核
        lc_dir = LoadCase(case="rotary_table", load_rpm=60.0, accel_time=0.3,
                          inertia_mode="solid_cylinder", in_mass=6.25, in_r2=0.4,
                          friction_torque=0.5, transmission="gearbox",
                          motor_kind_pref="伺服电机", allow_gearbox=True)
        req_dir = compute(lc_dir)
        ev = evaluate(lc_dir, req_dir, user_motor, user_box, 25.0)
        check("导入的电机+减速机 (i=25) 校核可行", ev.feasible,
              "未通过：" + "、".join(ev.failed_names))
        check("校核用到了导入减速机的额定转矩",
              any(c.name == "减速机额定输出转矩" and abs(c.capacity - 120.0) < 1e-9
                  for c in ev.checks))
        print(f"      i=25：电机侧峰值 {ev.T_peak:.3f} N·m，惯量比 {ev.inertia_ratio:.2f}，"
              f"匹配度 {ev.score}")

        # 6b. 自动选型结果里应当能出现导入的电机
        lc = LoadCase(case="rotary_table", load_rpm=60.0, accel_time=0.3,
                      inertia_mode="solid_cylinder", in_mass=6.25, in_r2=0.4,
                      friction_torque=0.5, motor_kind_pref="伺服电机", allow_gearbox=True)
        req = compute(lc)
        check("工况计算正常", req.ok, str(req.errors))
        results = auto_select(lc, req, motors, boxes, top_n=200)
        check("选型结果里出现了导入的电机",
              any(r.motor.model == "MDMF302L1H8-我的电机" for r in results),
              f"共 {len(results)} 个方案")
        if results:
            top = results[0]
            print(f"      首选：{top.motor.kind} {top.train_label}  i={top.ratio:g}  "
                  f"匹配度={top.score}")

        # ---- 7. 参数校验：坏数据不应该污染库 ----
        bad = os.path.join(tmp, "bad.csv")
        with open(bad, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("型号\n")           # 只有型号、没有类型/参数
        n_bad, errs = import_user_motors(bad)
        check("空数据文件被拒绝", n_bad == 0, str(errs[:1]))

    finally:
        # 还原用户库
        clear_user_motors()
        for path, dst in backup.items():
            shutil.copy2(dst, path)
            os.remove(dst)
        shutil.rmtree(tmp, ignore_errors=True)

    check("测试后用户库已还原",
          os.path.isfile(user_motors_path()) == (user_motors_path() in backup))

    print("\n" + "=" * 60)
    if FAILS:
        print(f"未通过 {len(FAILS)} 项：{FAILS}")
        return 1
    print("型号库链路测试全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
