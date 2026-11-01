# Protocol findings

**Summary.** The RCCar app never connects to the toy. It broadcasts each command as a 128-bit service UUID in its BLE advertisement; the toy's 2.4 GHz receiver listens to those broadcasts. Frame (UUID string order):

```
chk ctr 00 14 - A B - C D - 34 30 34 b7 06 7f 07 0c
chk = ctr ^ A ^ B ^ C ^ D ^ 0x08
A, B = track speeds 0-50 (forward/back only), C = flags (0x04 lights), D = action bits
D: 01 fwd, 02 back, 04 left, 08 right, 10 boom up, 20 boom down, 40 cab left, 80 cab right
```

Below: how each piece was found, session by session.

## Session 01 (2026-10-31, iPhone + MacBook, `ble_sniff.py`)

- The iPhone running RCCar (local name `FF04`) is the broadcaster: 55 distinct payloads vs 1-2 for every other device nearby. The excavator moved during the capture.
- No connection: the app **encodes each command in a 128-bit service UUID** it advertises. Manufacturer data and service data are empty (iOS doesn't allow them).
- No labels were recorded in this session, so which button maps to which value is still unconfirmed.

### Frame layout (bytes as shown in the UUID string)

```
 b0  b1  b2  b3 - b4  b5 - b6  b7 - b8 .. b15
chk ctr  00  14   A   B    C   D   34 30 34 b7 06 7f 07 0c
```

| Byte | Meaning | Evidence |
|---|---|---|
| b0 | **Checksum**: `b1 ^ b4 ^ b5 ^ b6 ^ b7 ^ 0x08` | Matches 55/55 frames |
| b1 | **Rolling counter**, +1 per frame | 0e, 0f, 11, 12 ... 6d |
| b2 b3 | Constant `00 14` | Probably frame type or length |
| b4 (A) | **Drive speed**, 0-50 (0x32 = max) | Session 03: 50, 49, 41, 34 while driving. Only nonzero with forward/back |
| b5 (B) | **Second track speed.** The app always sent `max(0, A - 16)`, which made the toy curve; we send B = A (+ trim) | Session 03 pattern, then confirmed by driving straight with A = B |
| b6 (C) | **Flags**. `0x04` = **lights on** (latched: sent in every frame while on) | Session 02: toggled lights only, C followed it exactly. Session 01 started with lights on |
| b7 (D) | **Action bitmask**, see table below | Session 03 |
| b8-b15 | Constant `34 30 34 b7 06 7f 07 0c` | Probably pairing/bind ID. Check whether it changes after re-pairing or on a different phone |

Idle frame: `A=00 B=00 C=00 D=00`.

### D bitmask (session 03)

| Bit | Action | Confidence |
|---|---|---|
| 0x01 | Forward (with speed A) | Confirmed |
| 0x02 | Back (with speed A) | Confirmed |
| 0x04 | Left (A = 0) | Confirmed |
| 0x08 | Right (A = 0) | Confirmed |
| 0x10 | Bucket/arm up | Confirmed |
| 0x20 | Bucket/arm down | **Inferred** from the pattern, frame missed in capture |
| 0x40 | Turret rotate left | Confirmed |
| 0x80 | Turret rotate right | Confirmed |


### Caveats

- macOS only reports an advert every ~0.3 s, so we see a subsample. Fine for decoding, not for measuring the app's real send rate.
- The bytes are in UUID-string order. Over the air, 128-bit UUIDs are little-endian (reversed). This matters when replaying from the ESP32: pass the UUID string to the BLE library and let it handle ordering.

### Open questions (status)

1. ~~Which D bit is forward / back / left / right?~~ Answered in session 03.
2. ~~Is A speed?~~ Yes. A and B are the two track speeds (see "Curve on forward").
3. Other C bits (sound, speed gear): not captured yet.
4. Does the ID (b8-b15) change per phone or per pairing? Unknown; the Mac reuses the iPhone's ID and the toy accepts it.
5. Bucket down = 0x20: inferred, not captured.

## Session 02 (lights only)

Started off, toggled several times, ended off. C went `00 -> 04 -> 00 -> 04 -> 00 -> 04 -> 00`, nothing else changed. Checksum still matches every frame. **C bit 0x04 = lights, confirmed.**

Tool fix: macOS reports RSSI 127 for "unknown", which slipped past the `--rssi` filter. Now excluded.

## Session 03 (all buttons, labelled)

130 frames, checksum 130/130. Labels were sometimes typed just after the action instead of before, so mapping used the nearest action burst. Bucket down produced no captured frame (macOS samples only every ~0.3 s), 0x20 assumed.

Next: confirm 0x20, and capture the iPhone's **raw** advert bytes with the ESP32 scanner so the ESP32 replay can copy the exact over-the-air layout.

## Replay result (2026-10-31)

`tools/mac_rccar_tx.py` (CoreBluetooth, service-UUID advert, new frame every 100 ms, ID copied from the iPhone) drove the excavator on the first try. No re-pairing needed. Protocol is solved for control purposes.

## Curve on forward (2026-10-31)

Driving forward from the control panel made the excavator go in circles. New hypothesis: **A and B are the two track speeds**, not speed + derived value. The app always sent B = A - 16 (so one track slower, and B = 0 for A <= 16). Changed default to A = B, plus a trim slider (`[` `]`). Trim -16 at speed 50 reproduces the app's frame exactly, for comparison. To verify: which track does A drive?
