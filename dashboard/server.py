#!/usr/bin/env python3
"""Autonomy dashboard: camera + perception + brain + Bluetooth, one web page.

  python3 dashboard/server.py --cam 1     # real excavator, iPhone camera index 1
  python3 dashboard/server.py --sim       # simulator, no hardware needed

Then open http://localhost:8000
"""
import argparse
import collections
import json
import math
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from autonomy import config as cfgmod  # noqa: E402
from autonomy import vision  # noqa: E402
from autonomy.brain import Abort, Brain  # noqa: E402
from autonomy.vision import RobotObs  # noqa: E402
from excavator.protocol import bits_from_names, frame_uuid, pulse_turn, track_speeds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEADMAN_S = 0.4


class Hub:
    def __init__(self, cfg, mode):
        self.cfg = cfg
        self.mode = mode
        self.lock = threading.RLock()
        # manual control (from page)
        self.m_actions, self.m_speed, self.lights, self.trim = [], 25, False, 0
        self.turn_mode, self.m_last = "throttle", 0.0
        # autonomous command
        self.auto = None            # (bits, speed, until)
        self.abort = threading.Event()
        # radio output
        self.out = (0, 0, 0)        # d, a, b actually on air
        self.uuid, self.ctr, self.frames = "", 0, 0
        # perception
        self.frame, self.frame_t, self.fps = None, 0.0, 0.0
        self.scene = vision.Scene()
        self.pending_corners = []
        self.last_plan = None
        self.swap = False
        self.obs = None
        self.obs_buf = collections.deque(maxlen=30)
        self.redetect = True
        # brain
        self.logs = collections.deque(maxlen=200)
        self.brain = Brain(self, cfg, self.log)
        self.job = None

    def log(self, msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        self.logs.append(line)

    # ---------- interface used by Brain ----------
    def _check(self):
        if self.abort.is_set():
            raise Abort("stopped by user")

    def pulse(self, actions, speed, secs):
        self._check()
        with self.lock:
            self.auto = (bits_from_names(actions), speed, time.time() + secs)
        end = time.time() + secs
        while time.time() < end:
            self._check()
            time.sleep(0.01)
        with self.lock:
            self.auto = None
        end = time.time() + self.cfg["settle_s"]
        while time.time() < end:
            self._check()
            time.sleep(0.01)

    def observe(self, n=3, timeout=1.5):
        t0 = time.time()
        got, last_t = [], t0 + 0.03
        while time.time() - t0 < timeout and len(got) < n:
            self._check()
            with self.lock:
                fresh = [o for o in self.obs_buf if o.t > last_t]
            if fresh:
                got.extend(fresh[: n - len(got)])
                last_t = got[-1].t
            time.sleep(0.02)
        if len(got) < 2:
            return None
        cx = sum(o.center[0] for o in got) / len(got)
        cy = sum(o.center[1] for o in got) / len(got)
        s = sum(math.sin(math.radians(2 * o.axis_deg)) for o in got)
        c = sum(math.cos(math.radians(2 * o.axis_deg)) for o in got)
        axis = (math.degrees(math.atan2(s, c)) / 2) % 180
        return RobotObs(t=got[-1].t, center=(cx, cy), axis_deg=axis,
                        elong=sum(o.elong for o in got) / len(got),
                        area_cm2=got[-1].area_cm2, contour_img=got[-1].contour_img)

    # ---------- jobs ----------
    def start_job(self, name, fn):
        if self.job and self.job.is_alive():
            return False
        self.abort.clear()

        def run():
            try:
                fn()
            except Abort as e:
                self.log(f"{name} stopped: {e}")
            except Exception as e:  # keep the server alive
                self.log(f"{name} error: {e!r}")
            finally:
                with self.lock:
                    self.auto = None
                self.brain.status = "idle"
                self.brain.target = None

        self.job = threading.Thread(target=run, daemon=True)
        self.job.start()
        return True

    def apply_manual_targets(self, sc):
        for name, c in (self.cfg.get("manual_targets") or {}).items():
            sc.targets[name] = vision.square_target(c, 10.0)

    def set_target(self, name, x, y):
        mt = dict(self.cfg.get("manual_targets") or {})
        mt[name] = [round(x, 2), round(y, 2)]
        self.cfg["manual_targets"] = mt
        self.scene.targets[name] = vision.square_target((x, y), 10.0)
        self.log(f"Target {name} set at ({x:.1f}, {y:.1f})")

    def click_to_map(self, view, u, v):
        with self.lock:
            frame = self.frame
        sc = self.scene
        if frame is None or not sc.ok:
            return None
        if view == "map":
            return u, v
        if view == "topdown" and sc.metric:
            return u * sc.w_cm, v * sc.h_cm
        fh, fw = frame.shape[:2]
        x, y = vision.to_map(sc.H, [(u * fw, v * fh)])[0]
        return float(x), float(y)

    def run_plan(self, text):
        import autonomy.vlm as vlm
        with self.lock:
            frame, obs = self.frame, self.obs
        self.log(f'Command: "{text}"')
        self.brain.status = "thinking"
        p = vlm.plan(frame, self.scene, obs, self.brain.pose, self.scene.targets, text, self.cfg)
        self.last_plan = p
        self.log(f"Plan: {p['say']}")
        for st in p["steps"]:
            self.log("  - " + json.dumps(st))
        b = self.brain
        for st in p["steps"]:
            self._check()
            d = st["do"]
            if d == "goto":
                b.go_to((st["x"], st["y"]))
            elif d == "goto_target":
                t = self.scene.targets.get(st["name"])
                if t is None:
                    raise Abort(f"no target {st['name']}")
                b.go_to(t["center"])
            elif d == "set_target":
                self.set_target(st["name"], st["x"], st["y"])
            elif d in ("dig", "dump"):
                b.sequence(d)
            elif d == "lights":
                self.lights = bool(st.get("on", True))
            elif d == "wait":
                end = time.time() + min(10.0, float(st.get("seconds", 1)))
                while time.time() < end:
                    self._check()
                    time.sleep(0.05)
        self.log("Command done")

    def busy(self):
        return bool(self.job and self.job.is_alive())

    def stop(self):
        self.abort.set()
        with self.lock:
            self.auto = None
            self.m_actions = []
        self.log("STOP")

    # ---------- radio tick ----------
    def tick(self):
        with self.lock:
            now = time.time()
            if self.auto and now < self.auto[2]:
                d, speed = self.auto[0], self.auto[1]
            elif not self.busy() and now - self.m_last < DEADMAN_S:
                d, speed = bits_from_names(self.m_actions), self.m_speed
            else:
                d, speed = 0, self.m_speed
            if self.turn_mode == "pulse":
                d = pulse_turn(d, speed, self.frames)
            self.uuid = frame_uuid(self.ctr, speed, self.lights, d, self.trim,
                                   turn_bytes=self.turn_mode == "throttle")
            a, b = (int(self.uuid[9:11], 16), int(self.uuid[11:13], 16))
            self.out = (d, a, b)
            self.ctr = (self.ctr + 1) & 0xFF
            self.frames += 1
            return self.uuid


# ---------- camera / perception thread ----------
def vision_loop(hub, cam):
    n, t0, last_try = 0, time.time(), 0.0
    while True:
        ok, frame = cam.read()
        if not ok or frame is None:
            time.sleep(0.05)
            continue
        t = time.time()
        if hub.redetect or (not hub.scene.ok and t - last_try > 2):
            last_try = t
            sc = vision.detect_scene(frame, hub.cfg, hub.swap)
            if sc.ok:
                hub.apply_manual_targets(sc)
            if sc.ok or hub.redetect:
                hub.log(f"Scene: {sc.msg}")
            hub.scene = sc
            hub.redetect = False
        elif hub.scene.ok and not hub.scene.metric and "put the robot" in hub.scene.msg \
                and t - last_try > 2 and not hub.busy():
            last_try = t
            hub.redetect = True     # robot may be in view now: recompute the scale
        obs = vision.detect_robot(frame, hub.scene, hub.cfg, t)
        with hub.lock:
            hub.frame, hub.frame_t, hub.obs = frame, t, obs
            if obs is not None:
                hub.obs_buf.append(obs)
        n += 1
        if t - t0 >= 1:
            hub.fps, n, t0 = n / (t - t0), 0, t


def render(hub, view):
    with hub.lock:
        frame, obs = hub.frame, hub.obs
    if frame is None:
        img = np.full((360, 640, 3), 20, np.uint8)
        cv2.putText(img, "waiting for camera...", (150, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
        return img
    b = hub.brain
    if view == "mask":
        return vision.mask_view(frame, hub.cfg)
    img = vision.draw_overlay(frame, hub.scene, obs, b.pose, b.target, b.trail[-150:] or None)
    if view == "topdown" and hub.scene.ok:
        img = vision.topdown_view(img, hub.scene)
    return img


# ---------- web ----------
HUB = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        h = HUB
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/stream.mjpg"):
            view = "camera"
            if "view=" in self.path:
                view = self.path.split("view=")[1].split("&")[0]
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    img = render(h, view)
                    if img.shape[1] > 1000:
                        s = 1000 / img.shape[1]
                        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg.tobytes() + b"\r\n")
                    time.sleep(0.08)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == "/api/state":
            b = h.brain
            o = h.obs
            with h.lock:
                st = {
                    "mode": h.mode, "fps": round(h.fps, 1), "camera": h.frame is not None,
                    "scene": h.scene.to_json(), "swap": h.swap,
                    "robot": None if o is None else {"center": [round(v, 2) for v in o.center],
                                                     "axis": round(o.axis_deg, 1), "elong": round(o.elong, 2)},
                    "pose": None if b.pose is None else [round(v, 2) for v in b.pose],
                    "model": b.model, "target": b.target, "trail": b.trail[-200:],
                    "status": b.status, "busy": h.busy(), "logs": list(h.logs)[-60:],
                    "pending_corners": len(h.pending_corners), "plan": h.last_plan,
                    "vlm_ready": bool(os.environ.get("ANTHROPIC_API_KEY")),
                    "uuid": h.uuid, "out": h.out, "frames": h.frames,
                    "manual": {"speed": h.m_speed, "lights": h.lights, "trim": h.trim, "turn_mode": h.turn_mode},
                    "cfg": h.cfg,
                }
            self._json(st)
        else:
            self.send_error(404)

    def do_POST(self):
        h, b = HUB, HUB.brain
        msg = self._body()
        p = self.path
        if p == "/api/manual":
            with h.lock:
                h.m_actions = msg.get("actions", [])
                h.m_speed = int(msg.get("speed", h.m_speed))
                h.lights = bool(msg.get("lights", h.lights))
                h.trim = max(-30, min(30, int(msg.get("trim", h.trim))))
                if msg.get("turn_mode") in ("throttle", "pulse"):
                    h.turn_mode = msg["turn_mode"]
                h.m_last = time.time()
            return self._json({"ok": True, "uuid": h.uuid, "busy": h.busy()})
        if p == "/api/stop":
            h.stop()
            return self._json({"ok": True})
        if p == "/api/scene/detect":
            h.redetect = True
            return self._json({"ok": True})
        if p == "/api/scene/swap":
            h.swap = not h.swap
            h.redetect = True
            return self._json({"ok": True})
        if p == "/api/calibrate":
            return self._json({"ok": h.start_job("Calibration", b.calibrate)})
        if p == "/api/goto":
            t = (float(msg["x"]), float(msg["y"]))
            h.log(f"Go to ({t[0]:.1f}, {t[1]:.1f}) cm")
            return self._json({"ok": h.start_job("Go-to", lambda: b.go_to(t))})
        if p == "/api/goto_square":
            name = msg.get("name", "A")
            if name not in h.scene.targets:
                return self._json({"ok": False, "error": f"no square {name}"})
            c = h.scene.targets[name]["center"]
            h.log(f"Go to square {name}")
            return self._json({"ok": h.start_job("Go-to", lambda: b.go_to(c))})
        if p == "/api/action":
            name = msg.get("name")
            if name not in ("dig", "dump"):
                return self._json({"ok": False})
            return self._json({"ok": h.start_job(name, lambda: b.sequence(name))})
        if p == "/api/mission":
            reps = max(1, min(20, int(msg.get("repeats", 1))))
            h.log(f"Mission start x{reps}")
            return self._json({"ok": h.start_job("Mission", lambda: b.mission(h.scene, reps))})
        if p == "/api/click":
            mode, view = msg.get("mode", "goto"), msg.get("view", "camera")
            u, v = float(msg["u"]), float(msg["v"])
            if mode == "corners":
                h.pending_corners.append([round(u, 4), round(v, 4)])
                n = len(h.pending_corners)
                h.log(f"Corner {n}/4")
                if n == 4:
                    h.cfg["arena_corners"] = h.pending_corners
                    h.cfg["arena_mode"] = "corners"
                    h.pending_corners = []
                    h.redetect = True
                    b.model, b.pose = None, None
                return self._json({"ok": True, "corners": n})
            pt = h.click_to_map(view, u, v)
            if pt is None:
                return self._json({"ok": False, "error": "no work area yet"})
            if mode in ("A", "B"):
                h.set_target(mode, *pt)
                return self._json({"ok": True})
            h.log(f"Go to ({pt[0]:.1f}, {pt[1]:.1f})")
            return self._json({"ok": h.start_job("Go-to", lambda: b.go_to(pt))})
        if p == "/api/arena":
            mode = msg.get("mode")
            if mode in ("auto", "corners", "pink"):
                h.cfg["arena_mode"] = mode
            for k in ("arena_w_cm", "arena_h_cm", "square_cm"):
                if k in msg:
                    h.cfg[k] = float(msg[k])
            if mode == "corners" and msg.get("restart"):
                h.pending_corners = []
                h.log("Click the 4 corners of the work area on the camera image")
                return self._json({"ok": True})
            h.redetect = True
            b.model, b.pose, b.trail = None, None, []
            return self._json({"ok": True})
        if p == "/api/targets/clear":
            h.cfg["manual_targets"] = {}
            h.redetect = True
            h.log("Targets cleared")
            return self._json({"ok": True})
        if p == "/api/command":
            text = str(msg.get("text", "")).strip()[:300]
            if not text:
                return self._json({"ok": False})
            return self._json({"ok": h.start_job("Command", lambda: h.run_plan(text))})
        if p == "/api/reset_model":
            b.model, b.pose, b.trail = None, None, []
            h.log("Calibration cleared")
            return self._json({"ok": True})
        if p == "/api/config":
            upd = msg.get("set", {})
            for k, v in upd.items():
                if k in h.cfg:
                    h.cfg[k] = v
            if any(k in upd for k in ("hsv", "square_cm", "arena_w_cm", "arena_h_cm", "arena_tol", "robot_len_cm")):
                h.redetect = True
            if msg.get("save"):
                cfgmod.save(h.cfg)
                h.log("Settings saved")
            return self._json({"ok": True})
        self.send_error(404)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def main():
    global HUB
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=None, help="camera index (see tools/camera_check.py --list)")
    ap.add_argument("--sim", action="store_true", help="simulated camera + excavator, no hardware")
    ap.add_argument("--dry-run", action="store_true", help="real camera, no Bluetooth")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    cfg = cfgmod.load()
    if a.cam is not None:
        cfg["camera_index"] = a.cam
    HUB = Hub(cfg, "sim" if a.sim else ("dry-run" if a.dry_run else "live"))

    if a.sim or a.dry_run:
        from excavator.mac_ble import DryRunBroadcaster
        tx = DryRunBroadcaster()
    else:
        from excavator.mac_ble import MacBroadcaster
        tx = MacBroadcaster()

    if a.sim:
        from autonomy.sim import SimCamera
        cam = SimCamera(lambda: HUB.out)
        HUB.log("Simulator running")
    else:
        cam = cv2.VideoCapture(cfg["camera_index"])
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not cam.isOpened():
            raise SystemExit(f"camera {cfg['camera_index']} did not open. Try tools/camera_check.py --list")
        HUB.log(f"Camera {cfg['camera_index']} open")
    threading.Thread(target=vision_loop, args=(HUB, cam), daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Dashboard: http://localhost:{a.port}")
    ip = lan_ip()
    if ip:
        print(f"From another device on the same Wi-Fi: http://{ip}:{a.port}")
    frame_s = 0.05 if a.sim or a.dry_run else 0.1
    try:
        while True:
            tx.send(HUB.tick())
            tx.pump(frame_s)   # BLE run loop lives on the main thread
    except KeyboardInterrupt:
        pass
    finally:
        HUB.stop()
        tx.stop()
        srv.shutdown()
        print("stopped")


if __name__ == "__main__":
    main()
