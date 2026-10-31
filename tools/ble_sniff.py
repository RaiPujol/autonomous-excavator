#!/usr/bin/env python3
"""Laptop BLE advertisement sniffer (macOS / Windows / Linux).

Run it while the phone app (RCCar) is open and you press buttons.
It prints every advertisement whose content changed, and on Ctrl+C ranks devices
by how many distinct payloads they sent. The phone running the app should be #1.

  pip install bleak
  python3 ble_sniff.py                 # everything stronger than -60 dBm
  python3 ble_sniff.py --rssi -45      # phone held right next to the laptop
  python3 ble_sniff.py --addr <id>     # only one device once you know it
  python3 ble_sniff.py --log s01.jsonl # also save to file

Type a label + Enter while it runs (e.g. "forward") to drop a marker in the output/log.
"""
import argparse
import asyncio
import json
import os
import sys
import threading
import time
from collections import defaultdict

from bleak import BleakScanner


def fmt(adv):
    parts = []
    if adv.local_name:
        parts.append(f"name={adv.local_name}")
    for cid, data in adv.manufacturer_data.items():
        parts.append(f"mfg[{cid:#06x}]={data.hex(' ')}")
    for uuid, data in adv.service_data.items():
        parts.append(f"svcdata[{uuid}]={data.hex(' ')}")
    if adv.service_uuids:
        parts.append("uuids=" + ",".join(adv.service_uuids))
    return " | ".join(parts) or "(empty)"


async def main(a):
    last = {}
    distinct = defaultdict(set)
    t0 = time.time()
    if a.log:
        os.makedirs(os.path.dirname(os.path.abspath(a.log)), exist_ok=True)
    logf = open(a.log, "a") if a.log else None

    def mark(label):
        line = f"{time.time() - t0:8.3f}  ===== {label} ====="
        print(line, flush=True)
        if logf:
            logf.write(json.dumps({"t": time.time() - t0, "marker": label}) + "\n")
            logf.flush()

    def stdin_reader():
        for line in sys.stdin:
            if line.strip():
                mark(line.strip())

    threading.Thread(target=stdin_reader, daemon=True).start()

    def cb(dev, adv):
        if adv.rssi < a.rssi or adv.rssi == 127:  # 127 = macOS "unknown", not strong
            return
        if a.addr and dev.address.lower() != a.addr.lower():
            return
        s = fmt(adv)
        if last.get(dev.address) == s:
            return
        last[dev.address] = s
        distinct[dev.address].add(s)
        t = time.time() - t0
        print(f"{t:8.3f}  {dev.address}  {adv.rssi:4d}  {s}", flush=True)
        if logf:
            logf.write(json.dumps({
                "t": t, "addr": dev.address, "rssi": adv.rssi, "name": adv.local_name,
                "mfg": {str(k): v.hex() for k, v in adv.manufacturer_data.items()},
                "svcdata": {k: v.hex() for k, v in adv.service_data.items()},
                "uuids": adv.service_uuids,
            }) + "\n")
            logf.flush()

    async with BleakScanner(cb):
        print(f"scanning (rssi >= {a.rssi}). Type a label + Enter to mark. Ctrl+C to stop.", flush=True)
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    print("\nDevices ranked by distinct payloads (app broadcaster should be on top):")
    for addr, s in sorted(distinct.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"  {len(s):5d}  {addr}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rssi", type=int, default=-60)
    ap.add_argument("--addr")
    ap.add_argument("--log")
    try:
        asyncio.run(main(ap.parse_args()))
    except KeyboardInterrupt:
        pass
