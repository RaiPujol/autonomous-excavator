"""Simulator: a fake angled camera looking at a floor with pink/green tape and a
yellow excavator that obeys the same radio frames as the real one.

Deliberately nasty, to match what the real toy does (2026-11-01):
  - spins at its own fast speed whatever throttle is sent (120-260 deg/s)
  - motors have a dead time at each start (60-120 ms of nothing)
  - A and B drive the two tracks; which one is left is random; < 15 stalls
  - slight drift when driving straight
  - dark engine deck at the back and dark cab window, like the real toy
Unknowns are randomised per robot so calibration has to find them.

`SimCamera.read()` runs in wall-clock time (dashboard). `SimWorld` steps
physics on a virtual clock, for fast headless tests (tests/sim_missions.py).
"""
import math
import threading
import time

import cv2
import numpy as np

PX = 8                     # world raster px per cm
WORLD = 100                # cm
MIN_SPEED = 15
TRACK_W = 5.5              # cm between track centres


class SimRobot:
    def __init__(self, x=None, y=None, theta=None, rng=None, easy=False):
        rng = rng or np.random.default_rng()
        self.x = x if x is not None else rng.uniform(40, 60)   # cm, world frame, y down
        self.y = y if y is not None else rng.uniform(40, 60)
        self.theta = theta if theta is not None else rng.uniform(-180, 180)
        self.turret = 0.0
        self.boom = 0.0
        self.lock = threading.Lock()
        self.k_v = 0.28 * rng.uniform(0.8, 1.2)       # cm/s per throttle unit
        self.curve = rng.uniform(-5, 5)               # deg/s drift while driving
        self.a_is_left = bool(rng.integers(2))        # which track A drives
        if easy:   # the old, friendly simulator
            self.spin = None
            self.dead = 0.0
        else:
            self.spin = rng.uniform(120, 260)         # deg/s, throttle-independent
            self.dead = rng.uniform(0.06, 0.12)       # s of nothing after a motor start
        self.k_w = 4.0 * rng.uniform(0.8, 1.2)        # easy mode: deg/s per throttle unit
        self._last_d = 0
        self._on_t = 0.0

    def step(self, d, a, b, dt):
        with self.lock:
            moving = d & 0x0F
            if moving != self._last_d & 0x0F:
                self._on_t = 0.0
            self._last_d = d
            self._on_t += dt
            live = self._on_t > self.dead
            if live and d & 0x03:
                sgn = 1 if d & 0x01 else -1
                va = self.k_v * a if a >= MIN_SPEED else 0.0
                vb = self.k_v * b if b >= MIN_SPEED else 0.0
                vl, vr = (va, vb) if self.a_is_left else (vb, va)
                v = (vl + vr) / 2 * sgn
                # y points down, so positive theta is clockwise on screen:
                # left track faster -> turns right (clockwise)
                w = math.degrees((vl - vr) / TRACK_W) * sgn
                th = math.radians(self.theta)
                self.x += v * math.cos(th) * dt
                self.y += v * math.sin(th) * dt
                self.theta += (w + self.curve * sgn * (v != 0)) * dt
            elif live and d & 0x0C:
                sgn = -1 if d & 0x04 else 1               # left = counter-clockwise on screen
                rate = self.spin if self.spin else self.k_w * max(a, 30)
                self.theta += sgn * rate * dt
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


def _off(x, y, ang, d):
    return x + d * math.cos(math.radians(ang)), y + d * math.sin(math.radians(ang))


class SimWorld:
    """Floor + robot + angled camera. `render()` gives a 1280x720 BGR frame."""

    def __init__(self, robot=None, square=(20, 20, 60), a_sq=(26, 56, 14), b_sq=(60, 26, 14),
                 floor=(120, 140, 160), seed=None):
        self.rng = np.random.default_rng(seed)
        self.robot = robot or SimRobot(rng=self.rng)
        world = np.full((WORLD * PX, WORLD * PX, 3), floor, np.uint8)
        noise = np.random.default_rng(1).integers(-12, 12, world.shape, dtype=np.int16)
        world = np.clip(world.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        if square:
            x0, y0, s = square
            cv2.rectangle(world, (x0 * PX, y0 * PX), ((x0 + s) * PX, (y0 + s) * PX), (170, 60, 240), int(2.4 * PX))
        for sq in (a_sq, b_sq):
            if sq:
                x, y, s2 = sq
                cv2.rectangle(world, (x * PX, y * PX), ((x + s2) * PX, (y + s2) * PX), (70, 180, 60), int(1.8 * PX))
        self.world = world
        self.obstacles = []      # list of (x, y, w, h) cm, drawn as grey boxes
        src = np.float32([[0, 0], [WORLD * PX, 0], [WORLD * PX, WORLD * PX], [0, WORLD * PX]])
        dst = np.float32([[400, 90], [930, 110], [1230, 715], [60, 690]])   # angled phone view
        self.Hc = cv2.getPerspectiveTransform(src, dst)

    def render(self):
        w = self.world.copy()
        for (ox, oy, ow, oh) in self.obstacles:
            cv2.rectangle(w, (int(ox * PX), int(oy * PX)), (int((ox + ow) * PX), int((oy + oh) * PX)),
                          (90, 90, 95), -1)
        r = self.robot
        with r.lock:
            th = r.theta
            cv2.fillPoly(w, [_rect(r.x, r.y, 10.5, 5.6, th)], (40, 40, 45))           # tracks
            ta = th + r.turret
            cv2.fillPoly(w, [_rect(r.x, r.y, 6.5, 4.6, ta)], (20, 190, 245))         # turret
            ex, ey = _off(r.x, r.y, ta, -2.2)
            cv2.fillPoly(w, [_rect(ex, ey, 1.8, 3.6, ta)], (70, 70, 75))             # engine deck (dark)
            cx, cy = _off(r.x, r.y, ta, 1.6)
            cx, cy = _off(cx, cy, ta - 90, 1.3)
            cv2.fillPoly(w, [_rect(cx, cy, 2.2, 1.6, ta)], (25, 25, 30))             # cab window (dark)
            ax, ay = _off(r.x, r.y, ta, 5.0 + r.boom * 1.5)
            cv2.fillPoly(w, [_rect(ax, ay, 5.5, 1.5, ta)], (20, 190, 245))           # boom + stick
            bx, by = _off(r.x, r.y, ta, 8.4 + r.boom * 3)
            cv2.fillPoly(w, [_rect(bx, by, 1.8, 3.0, ta)], (60, 60, 70))             # bucket
        img = cv2.warpPerspective(w, self.Hc, (1280, 720), borderValue=(30, 30, 30))
        img = cv2.GaussianBlur(img, (3, 3), 0)
        n = self.rng.integers(-6, 7, img.shape, dtype=np.int16)      # sensor noise, per frame
        return np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)


class SimCamera:
    """Wall-clock simulator for the dashboard. `get_cmd()` returns (d, a, b) on air."""

    def __init__(self, get_cmd, **kw):
        self.sim = SimWorld(**kw)
        self.robot = self.sim.robot
        self.get_cmd = get_cmd
        self.last = time.time()

    def read(self):
        now = time.time()
        dt, self.last = min(now - self.last, 0.1), now
        d, a, b = self.get_cmd()
        self.robot.step(d, a, b, dt)
        img = self.sim.render()
        time.sleep(1 / 30)
        return True, img

    def release(self):
        pass
