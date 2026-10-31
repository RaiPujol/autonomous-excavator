#!/usr/bin/env python3
"""Decode RCCar app frames from a ble_sniff.py .jsonl log.

The iPhone app encodes each command in a 128-bit service UUID it advertises.
Picks the device with the most distinct payloads (the phone) unless --addr is given.

  python3 tools/decode_rccar.py captures/session-01.jsonl
"""
import argparse
import json
from collections import Counter


def fields(uuid):
    b = bytes.fromhex(uuid.replace("-", ""))
    chk_ok = b[0] == (b[1] ^ b[4] ^ b[5] ^ b[6] ^ b[7] ^ 0x08)
    return b, chk_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--addr")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.log) if l.strip()]
    addr = a.addr
    if not addr:
        c = Counter(r["addr"] for r in rows if "addr" in r)
        addr = c.most_common(1)[0][0]
    print(f"device {addr}\n")
    print(f"{'t':>8}  chk ctr | b4 b5 b6 b7 | id (bytes 8-15)     ok")
    for r in rows:
        if "marker" in r:
            print(f"{r['t']:8.2f}  ===== {r['marker']} =====")
            continue
        if not r["addr"].lower().startswith(addr.lower()):
            continue
        for u in r.get("uuids") or []:
            b, ok = fields(u)
            print(f"{r['t']:8.2f}  {b[0]:02x}  {b[1]:02x}  | {b[4]:02x} {b[5]:02x} {b[6]:02x} {b[7]:02x} | {b[8:].hex()}  {'ok' if ok else 'BAD'}")


if __name__ == "__main__":
    main()
