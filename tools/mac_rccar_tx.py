#!/usr/bin/env python3
"""Drive the excavator from a Mac: broadcasts the same frames as the RCCar app.

Close the RCCar app on the phone first, otherwise both fight.
Needs pyobjc-framework-CoreBluetooth (installed together with bleak).

  python3 tools/mac_rccar_tx.py

Commands (type + Enter):
  f [speed] [ms]   forward (speed 0-50, default 50; ms default 1000)
  b [speed] [ms]   back
  l / r [ms]       left / right
  u / d [ms]       bucket up / down
  tl / tr [ms]     turret left / right
  light            toggle lights
  s                stop
  q                quit
Every command returns to idle after [ms] (safety).
"""
import threading
import time

from CoreBluetooth import (
    CBAdvertisementDataLocalNameKey,
    CBAdvertisementDataServiceUUIDsKey,
    CBPeripheralManager,
    CBUUID,
)
from Foundation import NSDate, NSObject, NSRunLoop

ID = "3430-34b7067f070c"   # constant tail seen from Rai's iPhone (pairing ID?)
NAME = "FF04"              # local name the iPhone app advertises
FRAME_S = 0.1              # new frame (counter + 1) every 100 ms
POWERED_ON = 5

BITS = {"f": 0x01, "b": 0x02, "l": 0x04, "r": 0x08,
        "u": 0x10, "d": 0x20, "tl": 0x40, "tr": 0x80}


class Delegate(NSObject):
    def peripheralManagerDidUpdateState_(self, pm):
        pass

    def peripheralManagerDidStartAdvertising_error_(self, pm, err):
        if err:
            print("advertising error:", err)


class State:
    ctr = 0
    A = 0      # speed 0-50
    C = 0      # flags, 0x04 = lights
    D = 0      # action bits
    stop_at = 0.0
    quit = False
    lock = threading.Lock()


def frame_uuid(s):
    B = max(0, s.A - 16)
    chk = s.ctr ^ s.A ^ B ^ s.C ^ s.D ^ 0x08
    return f"{chk:02x}{s.ctr:02x}0014-{s.A:02x}{B:02x}-{s.C:02x}{s.D:02x}-{ID}"


def set_cmd(s, a, d, ms):
    with s.lock:
        s.A, s.D = a, d
        s.stop_at = time.time() + ms / 1000 if ms else 0
    print(f"  A={a} C={s.C:02x} D={d:02x} for {ms} ms")


def reader(s):
    while not s.quit:
        try:
            parts = input("> ").split()
        except EOFError:
            s.quit = True
            return
        if not parts:
            continue
        c, args = parts[0], [int(x) for x in parts[1:] if x.lstrip("-").isdigit()]
        if c == "q":
            s.quit = True
        elif c == "s":
            set_cmd(s, 0, 0, 0)
        elif c == "light":
            with s.lock:
                s.C ^= 0x04
            print("  lights", "on" if s.C else "off")
        elif c in ("f", "b"):
            speed = max(0, min(50, args[0])) if args else 50
            ms = args[1] if len(args) > 1 else 1000
            set_cmd(s, speed, BITS[c], ms)
        elif c in BITS:
            set_cmd(s, 0, BITS[c], args[0] if args else 1000)
        else:
            print("  ? f b l r u d tl tr light s q")


def pump(sec):
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(sec))


def main():
    s = State()
    delegate = Delegate.alloc().init()
    pm = CBPeripheralManager.alloc().initWithDelegate_queue_(delegate, None)

    t0 = time.time()
    while pm.state() != POWERED_ON:
        pump(0.1)
        if time.time() - t0 > 5:
            print("Bluetooth not ready. Is it on, and is Terminal allowed in "
                  "System Settings > Privacy & Security > Bluetooth?")
            return

    print("broadcasting. Close the RCCar app on the phone. Commands: f b l r u d tl tr light s q")
    threading.Thread(target=reader, args=(s,), daemon=True).start()

    try:
        while not s.quit:
            with s.lock:
                if s.stop_at and time.time() >= s.stop_at:
                    s.A, s.D, s.stop_at = 0, 0, 0
                    print("  idle")
                u = frame_uuid(s)
                s.ctr = (s.ctr + 1) & 0xFF
            pm.stopAdvertising()
            pm.startAdvertising_({
                CBAdvertisementDataServiceUUIDsKey: [CBUUID.UUIDWithString_(u)],
                CBAdvertisementDataLocalNameKey: NAME,
            })
            pump(FRAME_S)
    except KeyboardInterrupt:
        pass
    finally:
        pm.stopAdvertising()
        print("stopped")


if __name__ == "__main__":
    main()
