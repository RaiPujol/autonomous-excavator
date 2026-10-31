#!/usr/bin/env python3
"""Parse an Android btsnoop_hci.log and print what the phone sends to the toy.

Shows:
  - ATT writes (GATT connection mode): handle + value
  - ATT notifications (toy -> phone)
  - LE advertising data changes (advertising broadcast mode)
  - Other ACL traffic (e.g. classic SPP/RFCOMM) as raw hex

Usage:
  python3 parse_btsnoop.py btsnoop_hci.log
  python3 parse_btsnoop.py btsnoop_hci.log --csv out.csv --handle 0x000e
  python3 parse_btsnoop.py btsnoop_hci.log --adv-only --dedupe
"""
import argparse
import csv
import struct
import sys

EPOCH_DELTA_US = 0x00DCDDB30F2F8000  # btsnoop epoch (year 0) -> unix epoch

ATT_OPS = {
    0x12: "WRITE_REQ",
    0x52: "WRITE_CMD",
    0x1B: "NOTIFY",
    0x1D: "INDICATE",
    0x0B: "READ_RSP",
}
ADV_OPCODES = {
    0x2008: "LE_SET_ADV_DATA",
    0x2009: "LE_SET_SCAN_RSP",
    0x2037: "LE_SET_EXT_ADV_DATA",
}


def records(path):
    with open(path, "rb") as f:
        hdr = f.read(16)
        if hdr[:8] != b"btsnoop\x00":
            sys.exit("not a btsnoop file")
        _ver, datalink = struct.unpack(">II", hdr[8:16])
        if datalink != 1002:
            print(f"warning: datalink {datalink}, expected 1002 (H4)", file=sys.stderr)
        while True:
            rh = f.read(24)
            if len(rh) < 24:
                return
            _orig, incl, flags, _drops, ts = struct.unpack(">IIIIq", rh)
            data = f.read(incl)
            sent = (flags & 1) == 0  # 0 = host -> controller
            yield (ts - EPOCH_DELTA_US) / 1e6, sent, data


def parse(path):
    for t, sent, d in records(path):
        if not d:
            continue
        ptype = d[0]
        if ptype == 0x01 and len(d) >= 4:  # HCI command
            opcode = struct.unpack("<H", d[1:3])[0]
            if opcode not in ADV_OPCODES:
                continue
            p = d[4:]
            if opcode == 0x2037:
                if len(p) < 4:
                    continue
                payload = p[4 : 4 + p[3]]
            else:
                if len(p) < 1:
                    continue
                payload = p[1 : 1 + p[0]]
            yield t, "TX" if sent else "RX", ADV_OPCODES[opcode], None, payload
        elif ptype == 0x02 and len(d) >= 9:  # ACL
            _hf, _alen, l2len, cid = struct.unpack("<HHHH", d[1:9])
            p = d[9 : 9 + l2len]
            if cid == 0x0004 and p:
                op = p[0]
                name = ATT_OPS.get(op)
                if not name:
                    continue
                if op == 0x0B:
                    yield t, "TX" if sent else "RX", name, None, p[1:]
                elif len(p) >= 3:
                    handle = struct.unpack("<H", p[1:3])[0]
                    yield t, "TX" if sent else "RX", name, handle, p[3:]
            elif cid not in (0x0004, 0x0005, 0x0006):
                yield t, "TX" if sent else "RX", f"ACL_CID_{cid:#06x}", None, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--csv")
    ap.add_argument("--handle", type=lambda s: int(s, 0), help="only this ATT handle")
    ap.add_argument("--adv-only", action="store_true")
    ap.add_argument("--att-only", action="store_true")
    ap.add_argument("--dedupe", action="store_true", help="hide frames identical to the previous one of the same kind")
    a = ap.parse_args()

    rows, last, t0 = [], {}, None
    for t, direction, kind, handle, payload in parse(a.log):
        is_adv = kind.startswith("LE_SET")
        if a.adv_only and not is_adv:
            continue
        if a.att_only and is_adv:
            continue
        if a.handle is not None and handle != a.handle:
            continue
        key = (kind, handle)
        if a.dedupe and last.get(key) == payload:
            continue
        last[key] = payload
        t0 = t if t0 is None else t0
        h = f"{handle:#06x}" if handle is not None else "-"
        rows.append((f"{t - t0:9.3f}", direction, kind, h, payload.hex(" ")))

    for r in rows:
        print("  ".join(r))
    print(f"\n{len(rows)} frames", file=sys.stderr)
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "dir", "kind", "handle", "hex"])
            w.writerows(rows)


if __name__ == "__main__":
    main()
