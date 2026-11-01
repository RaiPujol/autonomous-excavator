"""Simulator: a fake angled camera looking at a floor with pink/green tape and a
yellow excavator that obeys the same commands as the real one.

Deliberately imperfect (unknown speeds, slight curve, noise, tilted view) so the
calibration and controller get exercised for real.
"""
import math
import threading
import time

import cv2
import numpy as np

PX = 8                     # world raster px per cm
WORLD = 100                # cm


class SimRobot:
    def __init__(self, x=None, y=None, theta=None):
        rng0 = np.random.default_rng()
        self.x = x if x is not None else rng0.uniform(42, 58)   # cm, world frame, y down
        self.y = y if y is not None else rng0.uniform(42, 58)
        self.theta = theta if theta is not None else rng0.uniform(-180, 180)
        self.turret = 0.0
        self.boom = 0.0
        self.lock = threading.Lock()
        rng = np.random.default_rng()
        self.k_v = 0.28 * rng.uniform(0.8, 1.2)      # cm/s per throttle unit
        self.k_w = 4.0 * rng.uniform(0.8, 1.2)       # deg/s per throttle unit
        self.curve = rng.uniform(-6, 6)              # deg/s drift while driving

    def step(self, d, a, b, dt):
        with self.lock:
            spd = (a + b) / 2 if (a or b) else 30
            if d & 0x01 or d & 0x02:
                sgn = 1 if d & 0x01 else -1
                v = self.k_v * spd * sgn
                th = math.radians(self.theta)
                self.x += v * math.cos(th) * dt
                self.y += v * math.sin(th) * dt
                self.theta += (self.curve + (a - b) * 0.8) * dt * sgn
            elif d & 0x0C:
                sgn = -1 if d & 0x04 else 1               # left = counter-clockwise on screen
                self.theta += sgn * self.k_w * spd * dt
            if d & 0x40:
                self.turret = max(-135, self.turret - 70 * dt)
            if d & 0x80:
                self.turret = min(135, self.turret + 70 * dt)
            if d & 0x10:
                self.boom = min(1, self.boom + 1.2 * dt)
            if d & 0x20:
                self.boom = max(0, self.boom - 1.2 * dt)
            self.x = min(max(self.x, 5), WORLD - 5)
            self.y = min(max(self.y, 5), WORLD - 5)


def _rect(cx, cy, w, h, ang):
    return cv2.boxPoints(((cx * PX, cy * PX), (w * PX, h * PX), ang)).astype(np.int32)


class SimCamera:
    """Renders 1280x720 frames. `get_cmd()` returns (d, a, b) currently on air."""

    def __init__(self, get_cmd, square=(20, 20, 60), a_sq=(26, 56, 14), b_sq=(60, 26, 14)):
        self.robot = SimRobot()
        self.get_cmd = get_cmd
        self.last = time.time()
        world = np.full((WORLD * PX, WORLD * PX, 3), (120, 140, 160), np.uint8)   # beige floor
        noise = np.random.default_rng(1).integers(-12, 12, world.shape, dtype=np.int16)
        world = np.clip(world.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        x0, y0, s = square
        cv2.rectangle(world, (x0 * PX, y0 * PX), ((x0 + s) * PX, (y0 + s) * PX), (170, 60, 240), int(2.4 * PX))
        for (x, y, s2) in (a_sq, b_sq):
            cv2.rectangle(world, (x * PX, y * PX), ((x + s2) * PX, (y + s2) * PX), (70, 180, 60), int(1.8 * PX))
        self.world = world
        src = np.float32([[0, 0], [WORLD * PX, 0], [WORLD * PX, WORLD * PX], [0, WORLD * PX]])
        dst = np.float32([[400, 90], [930, 110], [1230, 715], [60, 690]])   # angled phone view
        self.Hc = cv2.getPerspectiveTransform(src, dst)

    def read(self):
        now = time.time()
        dt, self.last = min(now - self.last, 0.1), now
        d, a, b = self.get_cmd()
        self.robot.step(d, a, b, dt)
        w = self.world.copy()
        r = self.robot
        with r.lock:
            th = r.theta
            cv2.fillPoly(w, [_rect(r.x, r.y, 10.5, 5.2, th)], (40, 40, 45))          # tracks
            ta = th + r.turret
            cv2.fillPoly(w, [_rect(r.x, r.y, 5.5, 4.2, ta)], (20, 190, 245))        # cab
            ax = r.x + (4.5 + r.boom * 1.5) * math.cos(math.radians(ta))
            ay = r.y + (4.5 + r.boom * 1.5) * math.sin(math.radians(ta))
            cv2.fillPoly(w, [_rect(ax, ay, 5.0, 1.6, ta)], (20, 190, 245))           # boom
            bx = r.x + (7.5 + r.boom * 3) * math.cos(math.radians(ta))
            by = r.y + (7.5 + r.boom * 3) * math.sin(math.radians(ta))
            cv2.fillPoly(w, [_rect(bx, by, 1.8, 3.2, ta)], (60, 60, 70))             # bucket
        img = cv2.warpPerspective(w, self.Hc, (1280, 720), borderValue=(30, 30, 30))
        img = cv2.GaussianBlur(img, (3, 3), 0)
        time.sleep(1 / 30)
        return True, img

    def release(self):
        pass
