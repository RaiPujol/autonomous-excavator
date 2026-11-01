#!/usr/bin/env python3
"""Excavator control panel: web UI + Bluetooth broadcaster. No extra installs.

  python3 ui/server.py            # then open http://localhost:8000
  python3 ui/server.py --dry-run  # UI only, no Bluetooth (testing)

Close the RCCar app on the phone first. The page also works from your iPhone's
browser on the same Wi-Fi (URL printed at start).

Safety: if the page stops sending for 0.4 s (tab closed, Wi-Fi drop), the
excavator goes idle.
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from excavator.protocol import bits_from_names, frame_uuid, pulse_turn  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEADMAN_S = 0.4
FRAME_S = 0.1


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.speed = 30
        self.d = 0
        self.lights = False
        self.trim = 0
        self.turn_mode = "throttle"  # or "pulse"
        self.last_update = 0.0
        self.ctr = 0
        self.uuid = frame_uuid(0, 0, False, 0)
        self.frames = 0
        self.mode = "ble"

    def snapshot(self):
        return {"uuid": self.uuid, "ctr": self.ctr, "frames": self.frames,
                "d": self.d, "speed": self.speed, "lights": self.lights, "trim": self.trim, "turn_mode": self.turn_mode,
                "mode": self.mode}


S = State()


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

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            with S.lock:
                self._json(S.snapshot())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/state":
            return self.send_error(404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            msg = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "bad json"}, 400)
        with S.lock:
            S.speed = int(msg.get("speed", S.speed))
            S.d = bits_from_names(msg.get("actions", []))
            S.lights = bool(msg.get("lights", S.lights))
            S.trim = max(-30, min(30, int(msg.get("trim", S.trim))))
            if msg.get("turn_mode") in ("throttle", "pulse"):
                S.turn_mode = msg["turn_mode"]
            S.last_update = time.time()
            self._json(S.snapshot())


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.dry_run:
        from excavator.mac_ble import DryRunBroadcaster
        tx = DryRunBroadcaster()
        S.mode = "dry-run"
    else:
        from excavator.mac_ble import MacBroadcaster
        tx = MacBroadcaster()

    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Control panel:  http://localhost:{a.port}")
    ip = lan_ip()
    if ip:
        print(f"From your phone (same Wi-Fi): http://{ip}:{a.port}")
    print("Mode:", S.mode, "| Ctrl+C to quit")

    try:
        while True:
            with S.lock:
                if S.d and time.time() - S.last_update > DEADMAN_S:
                    S.d = 0  # deadman: page went quiet
                d = S.d
                if S.turn_mode == "pulse":
                    d = pulse_turn(d, S.speed, S.frames)
                S.uuid = frame_uuid(S.ctr, S.speed, S.lights, d, S.trim,
                                    turn_bytes=S.turn_mode == "throttle")
                S.ctr = (S.ctr + 1) & 0xFF
                S.frames += 1
                uuid = S.uuid
            tx.send(uuid)
            tx.pump(FRAME_S)  # BLE run loop must live on the main thread
    except KeyboardInterrupt:
        pass
    finally:
        tx.stop()
        srv.shutdown()
        print("stopped")


if __name__ == "__main__":
    main()
