# Protocol findings

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
| b4 (A) | **Magnitude**, 0-9 seen | Ramped 04, 08, 09 and held 09 for ~3 s |
| b5 (B) | Always 00 so far | |
| b6 (C) | 04 for the first ~10 s, then 00 | Possibly a mode/speed/light flag |
| b7 (D) | **Direction bitmask**: 01, 02, 08 seen | One bit per direction, so 04 is probably the fourth |
| b8-b15 | Constant `34 30 34 b7 06 7f 07 0c` | Probably pairing/bind ID. Check whether it changes after re-pairing or on a different phone |

Idle frame: `A=00 B=00 C=00 D=00`.

### Caveats

- macOS only reports an advert every ~0.3 s, so we see a subsample. Fine for decoding, not for measuring the app's real send rate.
- The bytes are in UUID-string order. Over the air, 128-bit UUIDs are little-endian (reversed). This matters when replaying from the ESP32: pass the UUID string to the BLE library and let it handle ordering.

### Open questions (session 02)

1. Which D bit is forward / back / left / right?
2. Is A really speed (proportional joystick) or the gear?
3. What are C and B: arm channels, lights, sound, speed?
4. Does the ID (b8-b15) change per phone or per pairing?
