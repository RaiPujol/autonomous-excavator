"""Headless stand-in for the dashboard Hub: same pulse/drive/observe interface the
Brain uses, but on the simulator with a virtual clock (runs much faster than real time)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from autonomy import vision  # noqa: E402
from autonomy.sim import SimWorld  # noqa: E402
from excavator.protocol import bits_from_names, frame_uuid  # noqa: E402

DT = 1 / 30


class SimHW:
    def __init__(self, cfg, world=None, seed=None):
        self.cfg, self.t = cfg, 0.0
        self.world = world or SimWorld(seed=seed)
        self.scene = vision.detect_scene(self.world.render(), cfg)
        if not self.scene.ok:
            raise RuntimeError("sim scene not detected: " + self.scene.msg)
        self.motor_s = 0.0          # total motor-on time
        self.starts = 0             # number of motor starts

    def _run(self, d, a, b, secs):
        n = max(1, round(secs / DT))
        for _ in range(n):
            self.world.robot.step(d, a, b, DT)
            self.t += DT
        if d:
            self.motor_s += secs
            self.starts += 1

    def pulse(self, actions, speed, secs):
        d = bits_from_names(actions)
        u = frame_uuid(0, speed, False, d)
        self._run(d, int(u[9:11], 16), int(u[11:13], 16), secs)
        self._run(0, 0, 0, self.cfg["settle_s"])

    def drive(self, a, b, secs, back=False):
        self._run(0x02 if back else 0x01, int(a), int(b), secs)
        self._run(0, 0, 0, self.cfg["settle_s"])

    def observe(self, n=3):
        got = []
        for _ in range(n):
            self._run(0, 0, 0, DT)
            o = vision.detect_robot(self.world.render(), self.scene, self.cfg, self.t)
            if o is not None:
                got.append(o)
        return vision.average_obs(got)

    def world_to_map(self, pts_cm):
        """World cm (simulator ground truth) -> the scene's map frame."""
        import numpy as np
        P = np.asarray(pts_cm, np.float64) * 8
        ph = np.c_[P, np.ones(len(P))] @ self.world.Hc.T
        img = (ph[:, :2] / ph[:, 2:]).astype(np.float32)
        return vision.to_map(self.scene.H, img)

    def true_pose_map(self):
        """Ground truth: robot centre, heading and bucket point in the map frame."""
        import math
        r = self.world.robot
        th = math.radians(r.theta)
        m = self.world_to_map([[r.x, r.y], [r.x + math.cos(th), r.y + math.sin(th)]])
        d = m[1] - m[0]
        return float(m[0][0]), float(m[0][1]), math.degrees(math.atan2(d[1], d[0])) % 360
