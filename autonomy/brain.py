"""Calibration by active perception, heading filter, track-steered navigation, A -> B mission.

Hardware interface (dashboard Hub, or tests/simhw.SimHW):
  hw.pulse(actions, speed, seconds)       one command (spin, straight drive, arm...)
  hw.drive(a, b, seconds, back=False)     drive with explicit track speeds A, B
  hw.observe()                            fresh averaged RobotObs, or None

Heading is the hard part with one camera and no markers. Three sources, fused by
a small Kalman filter on the angle:
  - motion: where the robot actually went during a drive (strong, only after moving)
  - arm side: the arm sticks out the front, so the yellow blob is lopsided towards
    it (vision.RobotObs.front_deg / skew). Full 0-360, every frame, a bit noisy
  - long axis: precise but 180-ambiguous; resolved with the two above
The arm points where the turret points, so the filter also tracks the turret
offset (arm heading minus track heading), learned whenever the robot drives.
"""
import math

MIN_SPEED, MAX_SPEED = 15, 50


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


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class HeadingFilter:
    def __init__(self):
        self.h, self.P = 0.0, 180.0 ** 2     # deg, deg^2
        self.offset = 0.0                    # turret: arm heading - track heading
        self.arm_sign = 1                    # -1 if the lopsided end turns out to be the back
        self.disagree = 0
        self.arm_good = self.arm_bad = 0     # does the arm side agree with actual motion?

    def arm_trusted(self):
        return not (self.arm_bad >= 2 and (self.arm_good + 1) / (self.arm_good + self.arm_bad + 2) < 0.75)

    def predict(self, dh, extra_sd=0.0):
        self.h = (self.h + dh) % 360
        self.P += (0.25 * abs(dh) + extra_sd) ** 2 + 4

    def update(self, z, R):
        k = self.P / (self.P + R)
        self.h = (self.h + k * wrap180(z - self.h)) % 360
        self.P = max((1 - k) * self.P, 4.0)

    def arm_heading(self, o, skew_min):
        """Track heading suggested by the arm side, or None if the blob is too symmetric."""
        if o.skew < skew_min or not self.arm_trusted():
            return None
        f = o.front_deg if self.arm_sign > 0 else o.front_deg + 180
        return (f - self.offset) % 360

    def look_update(self, o, skew_min=0.08):
        """Fuse one observation's shape (arm side + long axis)."""
        arm = self.arm_heading(o, skew_min)
        sd = math.sqrt(self.P)
        if arm is not None and sd < 35 and abs(wrap180(arm - self.h)) > 100:
            # arm side disagrees with a confident estimate: probably one bad frame
            self.disagree += 1
            if self.disagree < 3:
                arm = None
        else:
            self.disagree = 0
        if o.elong > 1.3:
            ref = arm if arm is not None else (self.h if sd < 60 else None)
            if ref is not None:
                self.update(resolve(o.axis_deg - self.offset, ref), (10 if arm is not None else 16) ** 2)
        elif arm is not None:
            self.update(arm, 25 ** 2)

    def motion_update(self, o0, o1, back=False, dh_pred=0.0, min_cm=1.5, learn_offset=True, skew_min=0.08):
        """Heading from where the robot went. Returns the measured heading or None."""
        dx, dy = o1.center[0] - o0.center[0], o1.center[1] - o0.center[1]
        d = math.hypot(dx, dy)
        if d < min_cm:
            return None
        chord = math.degrees(math.atan2(dy, dx)) + (180 if back else 0)
        z = (chord + dh_pred / 2) % 360          # end heading of an arc
        R = math.degrees(math.atan2(1.0, d)) ** 2 + (0.3 * dh_pred) ** 2 + 9
        if o1.skew >= skew_min:
            f = o1.front_deg if self.arm_sign > 0 else o1.front_deg + 180
            off = wrap180(f - z)
            agree = abs(wrap180(off - self.offset))
            if agree < 45:
                self.arm_good += 1
            elif agree > 135:
                self.arm_bad += 1
            if learn_offset and abs(off) < 60:
                self.offset = wrap180(self.offset + 0.3 * wrap180(off - self.offset))
        self.update(z, R)
        return z


class Brain:
    def __init__(self, hw, cfg, log):
        self.hw, self.cfg, self.log = hw, cfg, log
        self.pose = None          # (x, y, heading_deg) in map cm
        self.model = None
        self.hf = HeadingFilter()
        self.target = None
        self.trail = []
        self.status = "idle"

    # ---------- sensing ----------
    def look(self):
        o = self.hw.observe()
        if o is None:
            raise Abort("robot not visible")
        return o

    def _set_pose(self, o):
        self.pose = (o.center[0], o.center[1], self.hf.h)
        self.trail.append((round(o.center[0], 1), round(o.center[1], 1)))
        self.trail = self.trail[-400:]

    def _skew_min(self):
        return self.cfg.get("skew_min", 0.08)

    def _spin(self, action, secs):
        self.hw.pulse([action], self.cfg["turn_speed"], secs)

    def _turned(self, o0, o1):
        """Heading change between two looks (assumes < 90 deg), or None."""
        if min(o0.elong, o1.elong) > 1.3:
            return axis_diff(o1.axis_deg, o0.axis_deg)
        a0, a1 = self._shape_heading(o0), self._shape_heading(o1)
        return None if a0 is None or a1 is None else wrap180(a1 - a0)

    def _shape_heading(self, o):
        """Best single-look heading guess (arm side + axis), or None."""
        arm = self.hf.arm_heading(o, self._skew_min())
        if arm is None:
            return None
        return resolve(o.axis_deg - self.hf.offset, arm) if o.elong > 1.3 else arm

    # ---------- calibration ----------
    def calibrate(self):
        c = self.cfg
        hf = self.hf = HeadingFilter()
        self.status = "calibrating"
        self.log("Calibration: put the arm low and stretched out, turret centred")
        o0 = self.look()
        if o0.elong < 1.4 and o0.skew < 0.15:
            self.log("  WARNING: robot looks round from here (arm tucked in?). Stretch the arm out low "
                     "and forward, or heading will be unreliable")

        # 1. straight forward: speed, true heading, which end the arm is on
        T = c["calib_drive_s"]
        self.hw.pulse(["forward"], c["drive_speed"], T)
        o1 = self.look()
        dx, dy = o1.center[0] - o0.center[0], o1.center[1] - o0.center[1]
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            raise Abort(f"robot only moved {dist:.1f} cm; raise drive_speed or calib_drive_s")
        z = math.degrees(math.atan2(dy, dx)) % 360
        fwd = dist / T
        f1 = o1.front_deg if o1.skew >= self._skew_min() else None
        if f1 is not None:
            if abs(wrap180(f1 - z)) > 90:
                hf.arm_sign = -1
                self.log("  arm looks like it is at the back (folded?); using the other end as front")
                f1 += 180
            if abs(wrap180(f1 - z)) < c.get("arm_offset_max_deg", 20):
                hf.offset, hf.arm_good = wrap180(f1 - z), 1
            else:   # turret is centred, so a big offset means the arm reading is unreliable
                hf.arm_bad = 2
                self.log("  arm direction unclear (off by %.0f deg); heading from motion + long axis"
                         % abs(wrap180(f1 - z)))
        else:
            self.log("  robot shape too symmetric to see the arm; heading from motion only")
        hf.h, hf.P = z, 12 ** 2
        hf.look_update(o1, self._skew_min())
        drift = (self._turned(o0, o1) or 0.0) / T
        self.log(f"  forward {fwd:.1f} cm/s, heading {z:.0f} deg, arm offset {hf.offset:.0f} deg")

        # 2. back to the start
        self.hw.pulse(["back"], c["drive_speed"], T)
        o2 = self.look()
        back = math.hypot(o2.center[0] - o1.center[0], o2.center[1] - o1.center[1]) / T
        hf.predict(-drift * T)
        hf.motion_update(o1, o2, back=True, skew_min=self._skew_min())
        hf.look_update(o2, self._skew_min())

        # 3. spins: two pulse lengths each way -> rate and motor dead time.
        #    Short enough to stay under 90 deg even for a fast toy.
        t1, t2 = c.get("calib_turn_s1", 0.15), c.get("calib_turn_s2", 0.30)
        meas = {}
        o_prev = o2
        for action, t in (("left", t1), ("right", t1), ("left", t2), ("right", t2)):
            self._spin(action, t)
            o = self.look()
            a_prev, a_now = self._shape_heading(o_prev), self._shape_heading(o)
            if min(o.elong, o_prev.elong) > 1.3 or a_prev is None or a_now is None:
                dth = axis_diff(o.axis_deg, o_prev.axis_deg)       # pulses kept short: < 90 deg
            else:
                dth = wrap180(a_now - a_prev)
            meas[(action, t)] = dth
            o_prev = o
        A1 = (abs(meas[("left", t1)]) + abs(meas[("right", t1)])) / 2
        A2 = (abs(meas[("left", t2)]) + abs(meas[("right", t2)])) / 2
        if A2 < 6:
            raise Abort(f"spin too small ({A2:.0f} deg in {t2:.2f}s); raise turn_speed or calib_turn_s2")
        lsum = meas[("left", t1)] + meas[("left", t2)]
        left_sign = 1 if lsum > 0 else -1
        if A1 >= 3 and A2 > A1 * 1.2:
            rate = (A2 - A1) / (t2 - t1)
            dead = clamp(t1 - A1 / rate, 0.0, t1 * 0.9)
        else:
            dead = t1 * 0.8 if A1 < 3 else 0.0
            rate = A2 / (t2 - dead)
        # the four spins cancel out (left t1 + right t1 + left t2 + right t2)
        hf.predict(0.0, extra_sd=10)
        hf.look_update(o_prev, self._skew_min())

        # 4. track steering: forward with uneven tracks, then back the same way
        s, dlt = c.get("arc_speed", 30), c.get("calib_track_diff", 12)
        a_, b_ = s + dlt / 2, s - dlt / 2
        self.hw.drive(a_, b_, T)
        o5 = self.look()
        turned = self._turned(o_prev, o5)
        curv = 0.0
        if turned is not None:
            curv = (turned - drift * T) / max(T - dead * 0.5, 0.1) / (a_ - b_)
            hf.predict(turned)
            hf.motion_update(o_prev, o5, dh_pred=turned, skew_min=self._skew_min())
        hf.look_update(o5, self._skew_min())
        self.hw.drive(a_, b_, T, back=True)
        o6 = self.look()
        hf.predict(-(curv * (a_ - b_) * T + drift * T))
        hf.motion_update(o5, o6, back=True, dh_pred=-(curv * (a_ - b_) * T), skew_min=self._skew_min())
        hf.look_update(o6, self._skew_min())
        if not hf.arm_trusted():
            self.log("  arm side does not match the motion: ignoring it (heading from motion + long axis)")
        steer_ok = abs(curv * (a_ - b_)) * T > 5
        if not steer_ok:
            self.log("  uneven tracks barely steer: falling back to spin-then-drive")

        self.model = {"fwd_cm_s": round(fwd, 2), "back_cm_s": round(back, 2),
                      "turn_deg_s": round(rate, 1), "turn_dead_s": round(dead, 3),
                      "left_sign": left_sign, "curv": round(curv, 3) if steer_ok else 0.0,
                      "drift_deg_s": round(drift, 1), "arm_sign": hf.arm_sign,
                      "arm_offset": round(hf.offset, 1), "arm_trusted": hf.arm_trusted()}
        self._set_pose(o6)
        self.log(f"Calibration done: {fwd:.1f} cm/s, spin {rate:.0f} deg/s (dead {dead*1000:.0f} ms), "
                 f"left turns {'+' if left_sign > 0 else '-'}, "
                 f"track steer {curv:+.2f} deg/s per unit{'' if steer_ok else ' (unused)'}")
        self.status = "idle"

    def relocalize(self):
        """Short drive forward and back: re-learn heading and turret offset (e.g. after the turret moved)."""
        c = self.cfg
        o0 = self.look()
        self.hw.pulse(["forward"], c["drive_speed"], 0.35)
        o1 = self.look()
        self.hf.P = max(self.hf.P, 30 ** 2)
        self.hf.motion_update(o0, o1, skew_min=self._skew_min())
        self.hw.pulse(["back"], c["drive_speed"], 0.35)
        o2 = self.look()
        self.hf.motion_update(o1, o2, back=True, skew_min=self._skew_min())
        self.hf.look_update(o2, self._skew_min())
        self._set_pose(o2)

    # ---------- navigation ----------
    def _spin_towards(self, err, m, o0):
        """Spin pulse towards the target. Aims a bit short (fast toy, overshoot is worse
        than undershoot), then measures the real turn and adapts the rate model."""
        c = self.cfg
        want_positive = err > 0
        action = "left" if (m["left_sign"] > 0) == want_positive else "right"
        aim = min(abs(err) * c.get("spin_aim", 0.8), c.get("max_spin_deg", 60))
        dur = m["turn_dead_s"] + aim / m["turn_deg_s"]
        dur = clamp(dur, c.get("min_turn_pulse_s", 0.08), c["max_turn_pulse_s"])
        self._spin(action, dur)
        turned = m["turn_deg_s"] * max(0.0, dur - m["turn_dead_s"])
        o1 = self.look()
        actual = self._turned(o0, o1)
        if actual is not None:
            # the long axis can't tell +a from a-180: take the reading closest to the commanded turn
            sgn = math.copysign(turned, err)
            actual = min((actual, actual + 180, actual - 180), key=lambda v: abs(v - sgn))
        if actual is not None and abs(actual) < 120:
            if abs(actual) > 6 and dur - m["turn_dead_s"] > 0.02:     # online system identification
                eff = abs(actual) / (dur - m["turn_dead_s"])
                m["turn_deg_s"] = round(clamp(0.6 * m["turn_deg_s"] + 0.4 * eff, 20, 1000), 1)
            self.hf.predict(actual, extra_sd=5)
        else:
            self.hf.predict(math.copysign(turned, err), extra_sd=10)
        self.hf.look_update(o1, self._skew_min())
        return o1

    def _arc(self, err, dist, m):
        """Drive forward, steering with uneven track speeds towards the target."""
        c = self.cfg
        s = c.get("arc_speed", 30)
        w_max = c.get("arc_max_turn_deg_s", 60)
        w = clamp(c.get("arc_gain", 1.5) * err, -w_max, w_max)       # deg/s wanted
        diff = clamp(w / m["curv"], -(MAX_SPEED - MIN_SPEED), MAX_SPEED - MIN_SPEED)
        a, b = s + diff / 2, s - diff / 2
        lo = min(a, b)
        if lo < MIN_SPEED:            # keep both tracks above stall
            a, b = a + MIN_SPEED - lo, b + MIN_SPEED - lo
        hi = max(a, b)
        if hi > MAX_SPEED:
            a, b = a - (hi - MAX_SPEED), b - (hi - MAX_SPEED)
        a, b = round(a), round(b)
        v = m["fwd_cm_s"] * (a + b) / 2 / c["drive_speed"]
        dur = clamp(dist / max(v, 1.0), c.get("min_drive_pulse_s", 0.1), c["max_drive_pulse_s"])
        o0 = self.look()
        self.hw.drive(a, b, dur)
        dh = m["curv"] * (a - b) * dur + m["drift_deg_s"] * dur
        self.hf.predict(dh, extra_sd=4)
        o1 = self.look()
        self.hf.motion_update(o0, o1, dh_pred=dh, skew_min=self._skew_min())
        self.hf.look_update(o1, self._skew_min())
        return o1

    def _straight(self, dist, m, back=False):
        c = self.cfg
        v = m["back_cm_s"] if back else m["fwd_cm_s"]
        dur = clamp(dist / max(v, 1.0), c.get("min_drive_pulse_s", 0.1), c["max_drive_pulse_s"])
        o0 = self.look()
        self.hw.pulse(["back" if back else "forward"], c["drive_speed"], dur)
        self.hf.predict(m["drift_deg_s"] * dur * (-1 if back else 1), extra_sd=3)
        o1 = self.look()
        self.hf.motion_update(o0, o1, back=back, skew_min=self._skew_min())
        self.hf.look_update(o1, self._skew_min())
        return o1

    def go_to(self, target, tol=None, max_steps=None):
        c = self.cfg
        tol = tol or c["goal_tol_cm"]
        max_steps = max_steps or c.get("max_steps", 60)
        if self.model is None:
            self.calibrate()
        m = self.model
        self.target = target
        self.status = f"going to ({target[0]:.0f}, {target[1]:.0f})"
        o = self.look()
        self.hf.look_update(o, self._skew_min())
        self._set_pose(o)
        steer = m.get("curv", 0) != 0
        spin_tol = c.get("spin_tol_deg", 60) if steer else c["heading_tol_deg"]
        for _ in range(max_steps):
            x, y, h = self.pose
            bo = c["bucket_offset_cm"]
            fx, fy = x + bo * math.cos(math.radians(h)), y + bo * math.sin(math.radians(h))
            dist_c = math.hypot(target[0] - x, target[1] - y)
            dist_f = math.hypot(target[0] - fx, target[1] - fy)
            if dist_f < tol or dist_c < tol * 0.6:
                self.log(f"Arrived ({dist_f:.1f} cm from target)")
                self.target = None
                self.status = "idle"
                return True
            err = wrap180(math.degrees(math.atan2(target[1] - y, target[0] - x)) - h)
            near = dist_f < c.get("near_cm", 12)      # inside the turning circle: spin, don't orbit
            if math.sqrt(self.hf.P) > c.get("probe_sd_deg", 25):
                # heading too uncertain (round-looking blob after a spin): move a bit and look
                o = self._straight(2.5, m)
                self.log("  heading unsure: probe drive")
            elif dist_c < bo + tol and abs(err) > 60:
                o = self._straight(3.0, m, back=True)       # target under/behind the bucket
            elif abs(err) > (c["heading_tol_deg"] if near else spin_tol):
                o = self._spin_towards(err, m, o)
            elif steer and not near:
                o = self._arc(err, dist_f, m)
            else:
                o = self._straight(dist_f, m)
            self._set_pose(o)
        raise Abort("gave up: too many steps")

    # ---------- actions ----------
    def sequence(self, name):
        self.status = name
        self.log(f"{name.capitalize()}")
        for action, secs in self.cfg[name]:
            speed = self.cfg["drive_speed"] if action in ("forward", "back") else self.cfg["turn_speed"]
            self.hw.pulse([action], speed, float(secs))
        if any(a.startswith("turret") for a, _ in self.cfg[name]):
            self.relocalize()   # turret moved, arm direction changed: re-learn the offset

    def mission(self, scene, repeats=1):
        if not ("A" in scene.targets and "B" in scene.targets):
            raise Abort("need both targets A and B")
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
