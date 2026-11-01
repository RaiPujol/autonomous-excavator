"""RCCar / Trasped HG4 excavator frame format (see docs/02-protocol-findings.md).

Frame = one 128-bit service UUID, string order:
    chk ctr 00 14 - A B - C D - ID(8)
    chk = ctr ^ A ^ B ^ C ^ D ^ 0x08

A and B look like the two track speeds (0-50). The iPhone app sent B = A - 16,
which makes the toy curve; we send A = B by default and expose a trim.
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


def track_speeds(speed, trim=0):
    """trim > 0 slows track A, trim < 0 slows track B."""
    s = max(0, min(MAX_SPEED, int(speed)))
    t = int(trim)
    a = s - t if t > 0 else s
    b = s + t if t < 0 else s
    return max(0, min(MAX_SPEED, a)), max(0, min(MAX_SPEED, b))


def frame_uuid(ctr, speed, lights, d, trim=0):
    a, b = track_speeds(speed, trim) if d & 0x03 else (0, 0)
    c = LIGHTS if lights else 0
    chk = ctr ^ a ^ b ^ c ^ d ^ 0x08
    return f"{chk:02x}{ctr & 0xFF:02x}0014-{a:02x}{b:02x}-{c:02x}{d:02x}-{ID}"
