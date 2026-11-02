#!/usr/bin/env python3
"""Regression test: calibrate + go-to on many randomised simulated robots.

  python3 tests/sim_missions.py            # 20 robots, the realistic (nasty) simulator
  python3 tests/sim_missions.py --easy     # the old friendly simulator
  python3 tests/sim_missions.py -n 50 --brain path/to/other_brain.py

Success = the brain says "arrived" AND the true bucket position (simulator
ground truth) is within 2x the goal tolerance of the target.
"""
import argparse
import copy
import importlib.util
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
from autonomy.config import DEFAULTS  # noqa: E402
from autonomy.sim import SimRobot, SimWorld  # noqa: E402
from simhw import SimHW  # noqa: E402


def load_brain(path):
    if not path:
        from autonomy import brain
        return brain
    spec = importlib.util.spec_from_file_location("brain_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_one(seed, mod, easy, goals=3, verbose=False):
    rng = np.random.default_rng(seed)
    cfg = copy.deepcopy(DEFAULTS)
    world = SimWorld(robot=SimRobot(rng=rng, easy=easy), seed=seed)
    hw = SimHW(cfg, world)
    logs = []
    b = mod.Brain(hw, cfg, logs.append)
    res = {"seed": seed, "ok": 0, "goals": goals, "err": [], "steps_s": 0.0, "fail": ""}
    try:
        b.calibrate()
    except mod.Abort as e:
        res["fail"] = f"calib: {e}"
        return res, logs
    tol = cfg["goal_tol_cm"]
    for g in range(goals):
        wt = rng.uniform(25, 75, 2)
        tgt = [float(v) for v in hw.world_to_map([wt])[0]]
        t0 = hw.t
        try:
            b.go_to(tgt)
        except mod.Abort as e:
            res["fail"] = f"goal {g}: {e}"
            break
        x, y, h = hw.true_pose_map()
        bo = cfg["bucket_offset_cm"]
        fx, fy = x + bo * math.cos(math.radians(h)), y + bo * math.sin(math.radians(h))
        e = min(math.hypot(tgt[0] - fx, tgt[1] - fy), math.hypot(tgt[0] - x, tgt[1] - y) / 0.6)
        res["err"].append(round(e, 1))
        res["steps_s"] += hw.t - t0
        if e < 2 * tol:
            res["ok"] += 1
        else:
            res["fail"] = f"goal {g}: claimed arrival but {e:.1f} cm off"
            break
    res["model"] = b.model
    return res, logs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--easy", action="store_true")
    ap.add_argument("--brain", default=None)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    mod = load_brain(a.brain)
    tot_ok = tot = 0
    times = []
    for s in range(a.seed0, a.seed0 + a.n):
        res, logs = run_one(s, mod, a.easy)
        tot_ok += res["ok"]
        tot += res["goals"]
        if res["ok"]:
            times.append(res["steps_s"] / res["ok"])
        if a.v or res["fail"]:
            print(f"seed {s:3d}: {res['ok']}/{res['goals']}  err {res['err']}  {res['fail']}")
            if a.v:
                print("   ", res.get("model"))
    print(f"\nTOTAL {tot_ok}/{tot} goals reached"
          + (f", median {sorted(times)[len(times)//2]:.1f} s per goal" if times else ""))
    return 0 if tot_ok == tot else 1


if __name__ == "__main__":
    sys.exit(main())
