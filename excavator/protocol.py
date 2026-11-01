"""RCCar / Trasped HG4 excavator frame format (see docs/02-protocol-findings.md).

Frame = one 128-bit service UUID, string order:
    chk ctr 00 14 - A B - C D - ID(8)
    chk = ctr ^ A ^ B ^ C ^ D ^ 0x08,  B = max(0, A - 16)
"""

ID = "3430-34b7067f070c"   # pairing ID copied from Rai's iPhone
NAME = "FF04"              # local name the app advertises
MAX_SPEED = 50

BITS = {
    "forward": 0x01,
    "back": 0x02,
    "left": 0x04,
    "right": 0x08,
    "bucket_up": 0x10,
    "bucket_down": 0x20,
    "turret_left": 0x40,
    "turret_right": 0x80,
}
OPPOSITES = [("forward", "back"), ("left", "right"),
             ("bucket_up", "bucket_down"), ("turret_left", "turret_right")]
LIGHTS = 0x04


def bits_from_names(names):
    names = set(n for n in names if n in BITS)
    for a, b in OPPOSITES:  # pressing both = neither
        if a in names and b in names:
            names -= {a, b}
    d = 0
    for n in names:
        d |= BITS[n]
    return d


def frame_uuid(ctr, speed, lights, d):
    a = max(0, min(MAX_SPEED, int(speed))) if d & 0x03 else 0
    b = max(0, a - 16)
    c = LIGHTS if lights else 0
    chk = ctr ^ a ^ b ^ c ^ d ^ 0x08
    return f"{chk:02x}{ctr & 0xFF:02x}0014-{a:02x}{b:02x}-{c:02x}{d:02x}-{ID}"
