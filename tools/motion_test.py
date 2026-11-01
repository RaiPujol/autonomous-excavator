#!/usr/bin/env python3
"""Replay the autonomy motion pattern with NO camera and NO dashboard.

Purpose: find out whether the excavator switching off is caused by the
motion itself (power / battery / motor starts) or by the dashboard software.

  python3 tools/motion_test.py calib          # exact calibration sequence
  python3 tools/motion_test.py goto           # typical go-to: short turn + drive pulses
  python3 tools/motion_test.py goto --gentle  # same, fewer and longer pulses
  python3 tools/motion_test.py goto --app-turns   # send speed 0 on turns, like the RCCar app
  add --dry-run to test without Bluetooth

Close the RCCar app first. Watch the toy and note the step number where it dies.
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from excavator.protocol import bits_from_names, frame_uuid  # noqa: E402


def calib_seq(a):
    return [(["forward"], a.speed, 0.6), (["back"], a.speed, 0.6),
            (["left"], a.turn_speed, 0.45), (["right"], a.turn_speed, 0.45)]


def goto_seq(a):
    tp, dp = (0.25, 0.3) if a.gentle else (0.08, 0.1)
    seq = []
    for i in range(8):
        seq.append((["left" if i % 2 else "right"], a.turn_speed, max(tp, 0.15)))
        seq.append((["forward"], a.speed, max(dp, 0.25)))
        seq.append((["right" if i % 2 else "left"], a.turn_speed, tp))
        seq.append((["forward"], a.speed, 0.7))
    return seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pattern", choices=["calib", "goto"])
    ap.add_argument("--speed", type=int, default=22, help="drive throttle (dashboard default 22)")
    ap.add_argument("--turn-speed", type=int, default=18, help="turn throttle (dashboard default 18)")
    ap.add_argument("--settle", type=float, default=0.35, help="pause after each pulse (s)")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--gentle", action="store_true", help="min pulses 0.3 drive / 0.25 turn")
    ap.add_argument("--app-turns", action="store_true", help="speed bytes 0 on turns, like the app")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.dry_run:
        from excavator.mac_ble import DryRunBroadcaster
        tx = DryRunBroadcaster()
    else:
        from excavator.mac_ble import MacBroadcaster
        tx = MacBroadcaster()

    seq = (calib_seq(a) if a.pattern == "calib" else goto_seq(a)) * a.repeat
    cur = {"d": 0, "speed": a.speed}
    done = threading.Event()
    t0 = time.time()

    def runner():
        time.sleep(1.0)
        for i, (acts, spd, dur) in enumerate(seq, 1):
            print(f"[{time.time() - t0:6.2f}s] step {i:3d}/{len(seq)}  {acts[0]:8s} speed {spd}  {dur:.2f}s", flush=True)
            cur["d"], cur["speed"] = bits_from_names(acts), spd
            time.sleep(dur)
            cur["d"] = 0
            time.sleep(a.settle)
        done.set()

    threading.Thread(target=runner, daemon=True).start()
    ctr, last, worst = 0, time.time(), 0.0
    try:
        while not done.is_set():
            tx.send(frame_uuid(ctr, cur["speed"], False, cur["d"], 0, turn_bytes=not a.app_turns))
            ctr = (ctr + 1) & 0xFF
            tx.pump(0.1)
            now = time.time()
            worst, last = max(worst, now - last), now
    except KeyboardInterrupt:
        pass
    finally:
        for _ in range(5):
            tx.send(frame_uuid(ctr, 0, False, 0))
            ctr = (ctr + 1) & 0xFF
            tx.pump(0.1)
        tx.stop()
    print(f"Done. Slowest radio frame gap: {worst * 1000:.0f} ms (should be ~100)")
    print("Did the toy switch off? Note the step number.")


if __name__ == "__main__":
    main()
