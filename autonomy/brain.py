"""Calibration by active perception, move-stop-look navigation, and the A -> B mission.

All motion goes through `hw.pulse(actions, speed, seconds)`; all sensing through
`hw.observe()` which returns a fresh averaged RobotObs (or None).
"""
import math
import time


class Abort(Exception):
    pass


def wrap180(a):
    return (a + 180) % 360 - 180


def axis_diff(a, b):
    """Smallest signed difference between two axes (mod 180), in [-90, 90)."""
    return (a - b + 90) % 180 - 90


def resolve(axis_deg, predicted_heading):
    """Pick axis or axis+180, whichever is closer to the predicted heading."""
    c1, c2 = axis_deg % 360, (axis_deg + 180) % 360
    return c1 if abs(wrap180(c1 - predicted_heading)) <= abs(wrap180(c2 - predicted_heading)) else c2


class Brain:
    def __init__(self, hw, cfg, log):
        self.hw, self.cfg, self.log = hw, cfg, log
        self.pose = None          # (x, y, heading_deg) in map cm
        self.model = None         # {"fwd_cm_s", "back_cm_s", "turn_deg_s", "left_sign"}
        self.target = None
        self.trail = []
        self.status = "idle"

    # ---------- sensing ----------
    def look(self):
        o = self.hw.observe()
        if o is None:
            raise Abort("robot not visible")
        return o

    def _set_pose(self, x, y, h):
        self.pose = (x, y, h % 360)
        self.trail.append((round(x, 1), round(y, 1)))
        self.trail = self.trail[-400:]

    # ---------- calibration ----------
    def calibrate(self):
        c = self.cfg
        self.status = "calibrating"
        self.log("Calibration: looking for the robot")
        o0 = self.look()
        T = c["calib_drive_s"]
        self.log(f"Calibration: forward {T:.2f}s")
        self.hw.pulse(["forward"], c["drive_speed"], T)
        o1 = self.look()
        dx, dy = o1.center[0] - o0.center[0], o1.center[1] - o0.center[1]
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            raise Abort(f"robot only moved {dist:.1f} cm; raise drive_speed or calib_drive_s")
        heading = math.degrees(math.atan2(dy, dx))
        fwd = dist / T
        self.log(f"  moved {dist:.1f} cm -> {fwd:.1f} cm/s, heading {heading:.0f} deg")
        self.hw.pulse(["back"], c["drive_speed"], T)
        o2 = self.look()
        back = math.hypot(o2.center[0] - o1.center[0], o2.center[1] - o1.center[1]) / T
        heading = resolve(o2.axis_deg, heading)

        Tt = c["calib_turn_s"]
        self.hw.pulse(["left"], c["turn_speed"], Tt)
        o3 = self.look()
        dl = axis_diff(o3.axis_deg, o2.axis_deg)
        self.hw.pulse(["right"], c["turn_speed"], Tt)
        o4 = self.look()
        dr = axis_diff(o4.axis_deg, o3.axis_deg)
        if abs(dl) < 4 or abs(dr) < 4:
            raise Abort(f"spin too small (left {dl:.0f}, right {dr:.0f} deg); raise turn_speed or calib_turn_s")
        left_sign = 1 if dl > 0 else -1
        rate = (abs(dl) + abs(dr)) / 2 / Tt
        heading = resolve(o4.axis_deg, heading + dl + dr)
        self.model = {"fwd_cm_s": round(fwd, 2), "back_cm_s": round(back, 2),
                      "turn_deg_s": round(rate, 1), "left_sign": left_sign}
        self._set_pose(*o4.center, heading)
        self.log(f"Calibration done: {fwd:.1f} cm/s, {rate:.0f} deg/s, left turns {'+' if left_sign > 0 else '-'}")
        self.status = "idle"

    def relocalize(self):
        """Nudge forward/back to recover heading (e.g. after turret moves)."""
        o0 = self.look()
        self.hw.pulse(["forward"], self.cfg["drive_speed"], 0.35)
        o1 = self.look()
        dx, dy = o1.center[0] - o0.center[0], o1.center[1] - o0.center[1]
        h = math.degrees(math.atan2(dy, dx)) if math.hypot(dx, dy) > 0.8 else self.pose[2]
        self.hw.pulse(["back"], self.cfg["drive_speed"], 0.35)
        o2 = self.look()
        self._set_pose(*o2.center, resolve(o2.axis_deg, h))

    # ---------- navigation ----------
    def go_to(self, target, tol=None, max_steps=80):
        c = self.cfg
        tol = tol or c["goal_tol_cm"]
        if self.model is None:
            self.calibrate()
        m = self.model
        self.target = target
        self.status = f"going to ({target[0]:.0f}, {target[1]:.0f})"
        o = self.look()
        self._set_pose(*o.center, resolve(o.axis_deg, self.pose[2]) if o.elong > 1.3 else self.pose[2])
        for _ in range(max_steps):
            x, y, h = self.pose
            # aim the bucket (front of the robot) at the target, not the blob centre
            bo = c["bucket_offset_cm"]
            fx, fy = x + bo * math.cos(math.radians(h)), y + bo * math.sin(math.radians(h))
            dist_c = math.hypot(target[0] - x, target[1] - y)
            dist_f = math.hypot(target[0] - fx, target[1] - fy)
            if dist_f < tol or dist_c < tol * 0.6:
                self.log(f"Arrived ({dist_f:.1f} cm from target)")
                self.target = None
                self.status = "idle"
                return True
            bearing = math.degrees(math.atan2(target[1] - y, target[0] - x))
            err = wrap180(bearing - h)
            if dist_c < bo + tol and abs(err) > 60:
                # target is under/behind the bucket: back up a little first
                self.hw.pulse(["back"], c["drive_speed"], 0.3)
                o = self.look()
                self._set_pose(*o.center, resolve(o.axis_deg, h) if o.elong > 1.3 else h)
                continue
            if abs(err) > c["heading_tol_deg"]:
                dur = min(abs(err) / m["turn_deg_s"], c["max_turn_pulse_s"])
                dur = max(dur, 0.08)
                want_positive = err > 0
                action = "left" if (m["left_sign"] > 0) == want_positive else "right"
                self.hw.pulse([action], c["turn_speed"], dur)
                predicted = h + math.copysign(m["turn_deg_s"] * dur, err)
                o = self.look()
                nh = resolve(o.axis_deg, predicted) if o.elong > 1.3 else predicted
                self._set_pose(*o.center, nh)
            else:
                dur = min(dist_f / m["fwd_cm_s"], c["max_drive_pulse_s"])
                dur = max(dur, 0.1)
                self.hw.pulse(["forward"], c["drive_speed"], dur)
                o = self.look()
                dx, dy = o.center[0] - x, o.center[1] - y
                if math.hypot(dx, dy) > 1.2:   # trust actual motion for heading
                    nh = math.degrees(math.atan2(dy, dx))
                    nh = resolve(o.axis_deg, nh) if o.elong > 1.3 else nh
                else:
                    nh = resolve(o.axis_deg, h) if o.elong > 1.3 else h
                self._set_pose(*o.center, nh)
        raise Abort("gave up: too many steps")

    # ---------- actions ----------
    def sequence(self, name):
        self.status = name
        self.log(f"{name.capitalize()}")
        for action, secs in self.cfg[name]:
            speed = self.cfg["drive_speed"] if action in ("forward", "back") else self.cfg["turn_speed"]
            self.hw.pulse([action], speed, float(secs))
        if any(a.startswith("turret") for a, _ in self.cfg[name]):
            self.relocalize()   # turret moved, blob shape changed: re-check heading

    def mission(self, scene, repeats=1):
        if not ("A" in scene.targets and "B" in scene.targets):
            raise Abort("need both green squares A and B")
        if self.model is None:
            self.calibrate()
        for i in range(repeats):
            self.log(f"Mission run {i + 1}/{repeats}: to A")
            self.go_to(scene.targets["A"]["center"])
            self.sequence("dig")
            self.log("To B")
            self.go_to(scene.targets["B"]["center"])
            self.sequence("dump")
        self.status = "idle"
        self.log("Mission complete")
